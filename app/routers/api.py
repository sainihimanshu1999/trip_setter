"""JSON API. Everything the frontend fetches lives here."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import (
    CENTS,
    buckets_payload,
    expenses_payload,
    modes_payload,
    overview_payload,
    person_avatar_url,
    person_colour,
    timeline_payload,
)
from ..classify import BUCKET_STYLE, MODE_STYLE
from ..csv_import import load_csv
from ..db import get_db
from ..deps import AnalyticsDep, ServiceDep, SettingsDep
from ..domain import ZERO
from ..journey import build_journey
from ..models import BOOKING_KIND_STYLE, Booking, Leg, Place
from ..schemas import BookingIn, BookingPatch
from ..splitwise import SplitwiseError

log = logging.getLogger("trip.api")

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
    # Same scale the dashboard uses: the largest total handed over.
    max_paid = max((p.paid_total for p in analytics.people), default=ZERO)
    return {
        "currency": analytics.currency,
        "total": float(analytics.total_spend),
        "total_moved": float(analytics.total_moved),
        "per_head": float(analytics.per_head),
        # The index is the colour: without it every person came back as
        # person_colour(0), so this endpoint painted the whole group red while
        # /api/overview gave each one a distinct colour.
        "people": [p.as_json(max_paid, i) for i, p in enumerate(analytics.people)],
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


@router.get("/ingest")
async def ingest(analytics: AnalyticsDep) -> dict:
    """How the current data was parsed, and whether the totals reconcile.

    Exists so a total that looks wrong can be explained rather than guessed
    at: which header column was read as which field, which columns were
    ignored, which rows were skipped and why, and whether per-person shares
    still add up to the trip total.
    """
    a = analytics
    report = a.trip.ingest
    paid = sum((p.paid for p in a.people), ZERO)
    owed = sum((p.owed for p in a.people), ZERO)
    balances = sum((p.balance for p in a.people), ZERO)

    timeline = timeline_payload(a)
    charted = Decimal(str(sum(d["amount"] for d in timeline["days"])))

    return {
        "source": a.trip.source,
        "group_name": a.trip.group_name,
        "fetched_at": a.trip.fetched_at.isoformat() if a.trip.fetched_at else None,
        "warning": a.trip.warning,
        "currency": a.currency,
        "report": report.as_json() if report else None,
        # Each check states what it compares, so a failure names its own cause.
        "reconciliation": {
            "total_spend": float(a.total_spend.quantize(CENTS)),
            "sum_person_paid": float(paid.quantize(CENTS)),
            "sum_person_owed": float(owed.quantize(CENTS)),
            "paid_matches_total": abs(paid - a.total_spend) < Decimal("1"),
            "owed_matches_total": abs(owed - a.total_spend) < Decimal("1"),
            "balances_sum_to_zero": abs(balances) < Decimal("1"),
            "charted": float(charted),
            "chart_matches_total": abs(charted - a.total_spend) < Decimal("1"),
            "undated_spend": float(sum(
                (e.home_cost for e in a.trip.expenses
                 if not e.is_payment and e.date is None), ZERO
            ).quantize(CENTS)),
        },
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
    """Drop the cache and re-pull from Splitwise, plus fresh FX rates.

    Re-reads whatever is already on disk. It cannot see a newer export that
    was published to GitHub -- use `POST /api/pull` for that.
    """
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


@router.post("/pull")
async def pull(service: ServiceDep, settings: SettingsDep) -> dict:
    """Fetch the published export from GitHub and replace the local copy.

    The upload panel pushes a CSV up to the repository, where Actions rebuilds
    the static site. Nothing brought it back down again, so a local checkout
    kept serving whatever it last had on disk while the published site moved
    on. This closes that loop.

    The download is parsed before it is allowed to replace anything, so a
    truncated response or an HTML error page cannot destroy a working file.
    """
    repo = settings.resolved_github_repo
    if not repo:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No GitHub repo configured and none found in .git/config. "
            "Set GITHUB_REPO=owner/name in .env.",
        )

    target = settings.canonical_csv_path
    before = await service.analytics()
    url = f"https://api.github.com/repos/{repo}/contents/{settings.github_csv_path}"
    headers = {
        # Asks the contents API for the file itself rather than a JSON
        # envelope. Works anonymously for a public repo.
        "Accept": "application/vnd.github.raw",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token.strip():
        headers["Authorization"] = f"Bearer {settings.github_token.strip()}"

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(
                url, params={"ref": settings.github_branch}, headers=headers
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Could not reach GitHub: {exc}"
        ) from exc

    if response.status_code == 404:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"{repo} has no {settings.github_csv_path} on branch "
            f"{settings.github_branch}.",
        )
    if response.status_code in (401, 403):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "GitHub refused the request. A private repo needs GITHUB_TOKEN "
            "in .env with repo read access.",
        )
    if response.status_code != 200:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"GitHub returned {response.status_code}: {response.text[:200]}",
        )

    incoming = response.text
    if target.is_file() and target.read_text(encoding="utf-8-sig") == incoming:
        return {
            "pulled": False,
            "reason": "already up to date",
            "repo": repo,
            "path": str(target),
            "total_spend": float(before.total_spend.quantize(CENTS)),
            "currency": before.currency,
        }

    # Parse it somewhere harmless first. An export that does not load is a
    # failed pull, not a reason to lose the file that was working.
    staging = target.with_name(f".{target.name}.incoming")
    staging.write_text(incoming, encoding="utf-8")
    try:
        candidate = load_csv(staging, default_currency=settings.trip_currency)
    except (ValueError, OSError) as exc:
        staging.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Downloaded file is not a usable Splitwise export: {exc}",
        ) from exc

    # Keep the replaced file. A pull that turns out to be the wrong export
    # should be recoverable without reaching for git.
    backup = None
    if target.is_file():
        archive = target.parent / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = archive / f"{target.stem}-{stamp}{target.suffix}"
        shutil.copy2(target, backup)

    staging.replace(target)          # atomic on the same filesystem

    service.client.invalidate()
    await service.fx.refresh()
    after = await service.analytics()

    log.info(
        "Pulled %s from %s@%s: %d expenses, total %s -> %s",
        settings.github_csv_path, repo, settings.github_branch,
        len(candidate.expenses), before.total_spend, after.total_spend,
    )

    return {
        "pulled": True,
        "repo": repo,
        "branch": settings.github_branch,
        "path": str(target),
        "backup": str(backup) if backup else None,
        "currency": after.currency,
        "expense_count": len([e for e in after.trip.expenses if not e.is_payment]),
        "before": {
            "total_spend": float(before.total_spend.quantize(CENTS)),
            "expense_count": len([e for e in before.trip.expenses if not e.is_payment]),
        },
        "after": {
            "total_spend": float(after.total_spend.quantize(CENTS)),
            "expense_count": len([e for e in after.trip.expenses if not e.is_payment]),
        },
        "changed": float((after.total_spend - before.total_spend).quantize(CENTS)),
        "ingest": after.trip.ingest.as_json() if after.trip.ingest else None,
    }
