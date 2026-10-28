"""JSON API. Everything the frontend fetches lives here."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import (
    buckets_payload,
    expenses_payload,
    modes_payload,
    overview_payload,
    person_avatar_url,
    person_colour,
    timeline_payload,
)
from ..classify import BUCKET_STYLE, MODE_STYLE
from ..db import get_db
from ..deps import AnalyticsDep, ServiceDep, SettingsDep
from ..domain import ZERO
from ..journey import build_journey
from ..models import BOOKING_KIND_STYLE, Booking, Leg, Place
from ..schemas import BookingIn, BookingPatch
from ..splitwise import SplitwiseError

router = APIRouter(prefix="/api", tags=["api"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("/health")
async def health(settings: SettingsDep) -> dict:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "home_currency": settings.home_currency,
        "trip": [settings.trip_start.isoformat(), settings.trip_end.isoformat()],
    }


@router.get("/overview")
async def overview(analytics: AnalyticsDep) -> dict:
    return overview_payload(analytics)


@router.get("/people")
async def people(analytics: AnalyticsDep) -> dict:
    """Per-person spend, the data behind the expenditure bars."""
    max_paid = max((p.paid for p in analytics.people), default=ZERO)
    return {
        "currency": analytics.currency,
        "total": float(analytics.total_spend),
        "per_head": float(analytics.per_head),
        "people": [p.as_json(max_paid) for p in analytics.people],
    }


@router.get("/categories")
async def categories(analytics: AnalyticsDep) -> dict:
    return buckets_payload(analytics)


@router.get("/modes")
async def modes(analytics: AnalyticsDep) -> dict:
    return modes_payload(analytics)


@router.get("/timeline")
async def timeline(analytics: AnalyticsDep) -> dict:
    return timeline_payload(analytics)


@router.get("/settlements")
async def settlements(analytics: AnalyticsDep) -> dict:
    return {
        "currency": analytics.currency,
        "settlements": [s.as_json() for s in analytics.settlements],
        "balances": [
            {
                "id": p.person.id,
                "name": p.person.name,
                "first_name": p.person.first_name,
                "initials": p.person.initials,
                "color": person_colour(i),
                "avatar_3d": person_avatar_url(p.person.name),
                "balance": float(p.balance),
            }
            for i, p in enumerate(analytics.people)
        ],
    }


@router.get("/expenses")
async def expenses(
    analytics: AnalyticsDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    mode: str | None = None,
    bucket: str | None = None,
    include_payments: bool = False,
) -> dict:
    """Expenses, newest first.

    Settle-up payments are excluded by default: they move money between people
    rather than being trip spending, and the settlements view already covers
    them.
    """
    payload = expenses_payload(analytics)
    rows = payload["expenses"]
    if not include_payments:
        rows = [r for r in rows if not r["is_payment"]]
    if mode:
        rows = [r for r in rows if r["mode"] == mode]
    if bucket:
        rows = [r for r in rows if r["bucket"] == bucket]
    payload["expenses"] = rows[:limit]
    payload["total_matched"] = len(rows)
    return payload


@router.get("/journey")
async def journey(analytics: AnalyticsDep, db: DbDep) -> dict:
    """Nodes and edges for the animated map."""
    return build_journey(db, analytics)


@router.get("/places")
async def places(db: DbDep) -> dict:
    rows = db.scalars(select(Place).order_by(Place.order_index)).all()
    return {"places": [p.as_json() for p in rows]}


@router.get("/legs")
async def legs(db: DbDep) -> dict:
    rows = db.scalars(select(Leg).order_by(Leg.order_index)).all()
    return {"legs": [leg.as_json() for leg in rows]}


@router.get("/meta")
async def meta() -> dict:
    """Style tokens, so the frontend never hardcodes a colour the backend owns."""
    return {
        "modes": {
            str(k): {kk: vv for kk, vv in v.items()}
            for k, v in MODE_STYLE.items()
        },
        "buckets": {str(k): dict(v) for k, v in BUCKET_STYLE.items()},
        "booking_kinds": {str(k): dict(v) for k, v in BOOKING_KIND_STYLE.items()},
    }


# --------------------------------------------------------------- bookings


@router.get("/bookings")
async def list_bookings(
    db: DbDep,
    kind: str | None = None,
    place_id: int | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict:
    stmt = select(Booking)
    if kind:
        stmt = stmt.where(Booking.kind == kind)
    if place_id:
        stmt = stmt.where(Booking.place_id == place_id)
    if status_filter:
        stmt = stmt.where(Booking.status == status_filter)

    rows = db.scalars(stmt).all()
    # Undated bookings sort last rather than crashing the comparison.
    rows = sorted(rows, key=lambda b: (b.starts_at is None, b.starts_at or ""))

    totals: dict[str, float] = {}
    for booking in rows:
        totals[booking.currency] = totals.get(booking.currency, 0.0) + booking.cost

    return {
        "bookings": [b.as_json() for b in rows],
        "count": len(rows),
        "totals_by_currency": {k: round(v, 2) for k, v in totals.items()},
    }


@router.get("/bookings/{booking_id}")
async def get_booking(booking_id: int, db: DbDep) -> dict:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such booking")
    return booking.as_json()


@router.post("/bookings", status_code=status.HTTP_201_CREATED)
async def create_booking(payload: BookingIn, db: DbDep) -> dict:
    if payload.place_id is not None and db.get(Place, payload.place_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No such place")

    booking = Booking(**payload.model_dump())
    booking.kind = str(payload.kind)
    booking.status = str(payload.status)
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking.as_json()


@router.patch("/bookings/{booking_id}")
async def update_booking(booking_id: int, payload: BookingPatch, db: DbDep) -> dict:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such booking")

    changes = payload.model_dump(exclude_unset=True)
    if "place_id" in changes and changes["place_id"] is not None:
        if db.get(Place, changes["place_id"]) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No such place")

    for key, value in changes.items():
        setattr(booking, key, str(value) if key in ("kind", "status") else value)

    db.commit()
    db.refresh(booking)
    return booking.as_json()


@router.delete("/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_booking(booking_id: int, db: DbDep) -> Response:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such booking")
    db.delete(booking)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------- splitwise ops


@router.get("/groups")
async def groups(service: ServiceDep, settings: SettingsDep) -> dict:
    """List your Splitwise groups, so you can find the id for .env."""
    if settings.demo_mode:
        return {
            "demo_mode": True,
            "groups": [],
            "hint": "Set SPLITWISE_API_KEY in .env to list your real groups.",
        }
    try:
        raw = await service.client.get_groups()
    except SplitwiseError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {
        "demo_mode": False,
        "groups": [
            {
                "id": g.get("id"),
                "name": g.get("name"),
                "group_type": g.get("group_type"),
                "members": len(g.get("members") or []),
            }
            for g in raw
        ],
    }


@router.post("/refresh")
async def refresh(service: ServiceDep) -> dict:
    """Drop the cache and re-pull from Splitwise, plus fresh FX rates."""
    service.client.invalidate()
    await service.fx.refresh()
    analytics = await service.analytics()
    return {
        "refreshed": True,
        "source": analytics.trip.source,
        "expense_count": len(analytics.trip.expenses),
        "total_spend": float(analytics.total_spend),
        "currency": analytics.currency,
        "fx": analytics.fx.as_json(),
    }
