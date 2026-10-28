"""Server-rendered pages.

Each page ships its shell and first-paint data from the server, then the
frontend JS animates in the charts. That way the dashboard shows real numbers
before any JavaScript runs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import buckets_payload, overview_payload, timeline_payload
from ..config import BASE_DIR
from ..db import get_db
from ..deps import AnalyticsDep, SettingsDep
from ..journey import build_journey
from ..models import BOOKING_KIND_STYLE, Booking, Place

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

DbDep = Annotated[Session, Depends(get_db)]


def _money(value: float | int, currency: str = "INR") -> str:
    """Compact money for KPI tiles: 1.2L, 43.6k, 940."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "-"
    symbol = {"INR": "\u20b9", "THB": "\u0e3f", "USD": "$", "EUR": "\u20ac"}.get(
        currency.upper(), ""
    )
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if currency.upper() == "INR" and amount >= 100_000:
        return f"{sign}{symbol}{amount / 100_000:.2f}L"
    if amount >= 1_000_000:
        return f"{sign}{symbol}{amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sign}{symbol}{amount / 1_000:.1f}k"
    return f"{sign}{symbol}{amount:,.0f}"


templates.env.filters["money"] = _money


def _prettydate(value: object) -> str:
    """ISO date string or date -> '14 Jan'."""
    if not value:
        return "\u2014"
    if isinstance(value, (date, datetime)):
        return value.strftime("%d %b")
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b")
    except ValueError:
        return str(value)


templates.env.filters["prettydate"] = _prettydate


def _base_context(request: Request, settings, active: str) -> dict:
    return {
        "request": request,
        "active": active,
        "trip_title": settings.trip_title,
        "trip_subtitle": settings.trip_subtitle,
        "trip_start": settings.trip_start,
        "trip_end": settings.trip_end,
        "demo_mode": settings.demo_mode,
        "csv_mode": settings.csv_mode,
        "home_currency": settings.home_currency,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    analytics: AnalyticsDep,
    settings: SettingsDep,
    db: DbDep,
) -> HTMLResponse:
    context = _base_context(request, settings, "dashboard")
    context.update({
        "overview": overview_payload(analytics),
        "buckets": buckets_payload(analytics),
        "timeline": timeline_payload(analytics),
        "journey": build_journey(db, analytics),
    })
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/journey", response_class=HTMLResponse)
async def journey_page(
    request: Request,
    analytics: AnalyticsDep,
    settings: SettingsDep,
    db: DbDep,
) -> HTMLResponse:
    context = _base_context(request, settings, "journey")
    graph = build_journey(db, analytics)
    bookings = db.scalars(select(Booking)).all()
    by_place: dict[str, list[dict]] = {}
    for booking in bookings:
        if booking.place and booking.place.slug:
            by_place.setdefault(booking.place.slug, []).append(booking.as_json())
    context.update({
        "journey": graph,
        "overview": overview_payload(analytics),
        "bookings_by_place": by_place,
    })
    return templates.TemplateResponse(request, "journey.html", context)


@router.get("/bookings", response_class=HTMLResponse)
async def bookings_page(
    request: Request,
    settings: SettingsDep,
    db: DbDep,
) -> HTMLResponse:
    rows = db.scalars(select(Booking)).all()
    rows = sorted(rows, key=lambda b: (b.starts_at is None, b.starts_at or ""))
    places = db.scalars(select(Place).order_by(Place.order_index)).all()

    totals: dict[str, float] = {}
    for booking in rows:
        if booking.status != "cancelled":
            totals[booking.currency] = totals.get(booking.currency, 0.0) + booking.cost

    context = _base_context(request, settings, "bookings")
    context.update({
        "bookings": [b.as_json() for b in rows],
        "places": [p.as_json() for p in places],
        "kinds": {str(k): dict(v) for k, v in BOOKING_KIND_STYLE.items()},
        "totals_by_currency": {k: round(v, 2) for k, v in totals.items()},
        "confirmed_count": len([b for b in rows if b.status == "confirmed"]),
        "idea_count": len([b for b in rows if b.status == "idea"]),
    })
    return templates.TemplateResponse(request, "bookings.html", context)
