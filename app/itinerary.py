"""Committed snapshot of the itinerary: every place and leg.

`data/trip.db` is gitignored, so a stop or leg added through the website
exists only on the machine that added it until something commits it. This is
that something: `data/itinerary.json`, rewritten wholesale after every
itinerary change, the same way `data/docs/manifest.json` tracks documents.

Unlike the document manifest, this file is treated as the full, authoritative
list rather than an add-only record: `sync_itinerary_to_db()` makes the
database match it exactly, including removing a place or leg that used to be
listed and no longer is. A delete made through the website should stay
deleted after a fresh seed, not come back because `app/seed.py`'s baseline
still mentions it.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import DATA_DIR
from .models import Leg, Place

log = logging.getLogger("trip.itinerary")

ITINERARY_FILE = DATA_DIR / "itinerary.json"


def _place_row(place: Place) -> dict:
    return {
        "slug": place.slug,
        "name": place.name,
        "region": place.region,
        "country": place.country,
        "lat": place.lat,
        "lon": place.lon,
        "arrive_on": place.arrive_on.isoformat() if place.arrive_on else None,
        "depart_on": place.depart_on.isoformat() if place.depart_on else None,
        "nights": place.nights,
        "order_index": place.order_index,
        "blurb": place.blurb,
        "match_terms": place.match_terms,
    }


def _leg_row(leg: Leg) -> dict:
    return {
        "from_slug": leg.from_slug,
        "to_slug": leg.to_slug,
        "mode": leg.mode,
        "operator": leg.operator,
        "reference": leg.reference,
        "depart_at": leg.depart_at.isoformat() if leg.depart_at else None,
        "arrive_at": leg.arrive_at.isoformat() if leg.arrive_at else None,
        "duration_minutes": leg.duration_minutes,
        "order_index": leg.order_index,
        "notes": leg.notes,
        "booking_url": leg.booking_url,
    }


def read_itinerary() -> dict[str, list[dict]]:
    """Load the committed snapshot. A missing or broken file is not fatal."""
    if not ITINERARY_FILE.is_file():
        return {}
    try:
        payload = json.loads(ITINERARY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Ignoring unreadable %s: %s", ITINERARY_FILE.name, exc)
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def write_itinerary(session: Session) -> None:
    """Replace the snapshot with the database's current places and legs."""
    places = session.scalars(select(Place).order_by(Place.order_index)).all()
    legs = session.scalars(select(Leg).order_by(Leg.order_index)).all()
    body = {
        "_comment": (
            "Current itinerary, written by the app after every add, edit or "
            "delete. Committed so a fresh database -- the static build, a "
            "new clone -- ends up with the same stops and legs instead of "
            "just the baseline in app/seed.py."
        ),
        "places": [_place_row(p) for p in places],
        "legs": [_leg_row(leg) for leg in legs],
    }
    ITINERARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    ITINERARY_FILE.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )


def sync_itinerary_to_db(session: Session) -> int:
    """Reconcile places and legs to match the committed snapshot exactly.

    Called on every boot, after seeding. A missing file means nobody has
    published an itinerary change yet, so the seeded baseline is left alone.
    Once the file exists, it wins: upserts everything it lists, by slug for a
    place and by (from, to, order) for a leg, and removes anything in the
    database that is no longer listed.
    """
    payload = read_itinerary()
    if not payload:
        return 0
    changed = 0

    want_places = {
        row["slug"]: row for row in payload.get("places", []) if row.get("slug")
    }
    have_places = {p.slug: p for p in session.scalars(select(Place)).all()}
    for slug, row in want_places.items():
        place = have_places.get(slug)
        if place is None:
            place = Place(slug=slug)
            session.add(place)
            changed += 1
        place.name = row.get("name") or slug
        place.region = row.get("region") or ""
        place.country = row.get("country") or ""
        place.lat = float(row.get("lat") or 0.0)
        place.lon = float(row.get("lon") or 0.0)
        place.arrive_on = date.fromisoformat(row["arrive_on"]) if row.get("arrive_on") else None
        place.depart_on = date.fromisoformat(row["depart_on"]) if row.get("depart_on") else None
        place.nights = int(row.get("nights") or 0)
        place.order_index = int(row.get("order_index") or 0)
        place.blurb = row.get("blurb") or ""
        place.match_terms = row.get("match_terms") or ""
    session.flush()
    for slug, place in have_places.items():
        if slug not in want_places:
            session.delete(place)
            changed += 1

    want_legs = {
        (row["from_slug"], row["to_slug"], int(row.get("order_index") or 0)): row
        for row in payload.get("legs", [])
        if row.get("from_slug") and row.get("to_slug")
    }
    have_legs = {
        (leg.from_slug, leg.to_slug, leg.order_index): leg
        for leg in session.scalars(select(Leg)).all()
    }
    for key, row in want_legs.items():
        leg = have_legs.get(key)
        if leg is None:
            leg = Leg(from_slug=key[0], to_slug=key[1], order_index=key[2])
            session.add(leg)
            changed += 1
        leg.mode = row.get("mode") or "plane"
        leg.operator = row.get("operator") or ""
        leg.reference = row.get("reference") or ""
        leg.depart_at = datetime.fromisoformat(row["depart_at"]) if row.get("depart_at") else None
        leg.arrive_at = datetime.fromisoformat(row["arrive_at"]) if row.get("arrive_at") else None
        leg.duration_minutes = int(row.get("duration_minutes") or 0)
        leg.notes = row.get("notes") or ""
        leg.booking_url = row.get("booking_url") or ""
    for key, leg in have_legs.items():
        if key not in want_legs:
            session.delete(leg)
            changed += 1

    if changed:
        log.info("Reconciled %d place/leg row(s) from the itinerary snapshot", changed)
    return changed
