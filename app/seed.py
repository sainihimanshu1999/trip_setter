"""Seed the trip itinerary.

Coordinates are real so the journey map is geographically honest. The route and
dates line up with the CSV expense data, which is what lets the map match a
"Bkk to surat thani train" expense to the Bangkok -> Koh Samui leg.

Route: Delhi -> Bangkok -> Koh Samui -> Phuket -> Delhi / Bangalore
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select

from .db import session_scope
from .models import Booking, BookingKind, BookingStatus, Leg, Place


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


# slug, name, region, lat, lon, arrive, depart, nights, order, blurb, match terms
PLACES: list[tuple] = [
    (
        "delhi", "Delhi", "India", 28.6139, 77.2090,
        None, date(2026, 10, 5), 0, 0,
        "Where it starts. Red-eye out of Terminal 3.",
        "del,indira gandhi,home,delhi",
    ),
    (
        "bangkok", "Bangkok", "Central Thailand", 13.7563, 100.5018,
        date(2026, 10, 5), date(2026, 10, 8), 3, 1,
        "Temples at sunrise, Chinatown at midnight, and the best pad thai "
        "on the planet at Thipsamai. Base for the first three nights.",
        "bkk,dmk,suvarnabhumi,don mueang,chatuchak,wat pho,grand palace,"
        "khao san,sukhumvit,silom,thipsamai,rajadamnern,chao phraya,phaya thai,"
        "bangkok stay",
    ),
    (
        "koh-samui", "Koh Samui", "Gulf Coast", 9.5120, 100.0067,
        date(2026, 10, 8), date(2026, 10, 14), 6, 2,
        "Island vibes, golden beaches, and a BnB with the crew. "
        "Train from Bangkok to Surat Thani, then ferry across.",
        "koh samui,samui,surat thani,nathon,chaweng,lamai,bophut,fisherman village,"
        "koh samui bnb",
    ),
    (
        "phuket", "Phuket", "Andaman Coast", 7.8906, 98.2969,
        date(2026, 10, 14), date(2026, 10, 17), 3, 3,
        "Last stop. Patong nightlife, Kata beach, and the flights home.",
        "hkt,patong,rassada,kalim,kata,karon,phuket,flight hkt",
    ),
    (
        "bangalore", "Bangalore", "India", 12.9716, 77.5946,
        date(2026, 10, 17), None, 0, 4,
        "Home for Riya, Ayushi and Shruti. Direct Phuket–Bangalore flight.",
        "blr,bangalore,bengaluru,kempegowda",
    ),
]

# from, to, mode, operator, ref, depart, arrive, minutes, order, notes, url
LEGS: list[tuple] = [
    (
        "delhi", "bangkok", "plane", "IndiGo", "6E 1051",
        "2026-10-05T04:15:00", "2026-10-05T11:05:00", 255, 0,
        "Delhi to Bangkok. Lands at Suvarnabhumi.",
        "https://www.goindigo.in/",
    ),
    (
        "bangkok", "koh-samui", "train", "", "",
        "2026-10-08T17:00:00", "2026-10-09T08:00:00", 900, 1,
        "Overnight train Bangkok to Surat Thani, then ferry to Koh Samui.",
        "",
    ),
    (
        "koh-samui", "phuket", "plane", "", "",
        "2026-10-14T10:00:00", "2026-10-14T11:10:00", 70, 2,
        "Short hop from Samui to Phuket.",
        "",
    ),
    (
        "phuket", "delhi", "plane", "", "",
        "2026-10-17T13:55:00", "2026-10-17T17:20:00", 265, 3,
        "Phuket to Delhi. Himanshu and Lakshay fly home.",
        "https://www.goindigo.in/",
    ),
    (
        "phuket", "bangalore", "plane", "", "",
        "2026-10-17T12:00:00", "2026-10-17T14:30:00", 210, 4,
        "Phuket to Bangalore. Riya, Ayushi and Shruti fly home.",
        "",
    ),
]

# kind, title, provider, url, description, place slug, start, end, cost, ccy,
# confirmation, status, notes
BOOKINGS: list[tuple] = [
    (
        BookingKind.FLIGHT, "Delhi to Bangkok", "IndiGo",
        "https://www.goindigo.in/",
        "All six seats booked together.",
        "delhi", "2026-10-05T04:15:00", "2026-10-05T11:05:00",
        94496, "INR", "", BookingStatus.CONFIRMED,
        "Pranjal paid for the group.",
    ),
    (
        BookingKind.STAY, "Bangkok stay", "",
        "",
        "Bangkok accommodation for the crew.",
        "bangkok", "2026-10-05T14:00:00", "2026-10-08T12:00:00",
        32546, "INR", "", BookingStatus.CONFIRMED,
        "Ayushi booked this one.",
    ),
    (
        BookingKind.TRAIN, "Bangkok to Surat Thani train", "",
        "",
        "Overnight train from Bangkok, then ferry to Koh Samui.",
        "bangkok", "2026-10-08T17:00:00", "2026-10-09T08:00:00",
        19147, "INR", "", BookingStatus.CONFIRMED,
        "Himanshu covered the tickets.",
    ),
    (
        BookingKind.STAY, "Koh Samui BnB", "",
        "",
        "BnB on Koh Samui for the whole group.",
        "koh-samui", "2026-10-09T14:00:00", "2026-10-14T11:00:00",
        27511, "INR", "", BookingStatus.CONFIRMED,
        "Pranjal booked the BnB.",
    ),
    (
        BookingKind.FLIGHT, "Phuket to Bangalore", "",
        "",
        "Riya, Ayushi, and Shruti fly home to Bangalore.",
        "phuket", "2026-10-17T12:00:00", "2026-10-17T14:30:00",
        68157, "INR", "", BookingStatus.CONFIRMED,
        "Riya booked this flight.",
    ),
    (
        BookingKind.FLIGHT, "Phuket to Delhi", "",
        "",
        "Himanshu and Lakshay fly home to Delhi.",
        "phuket", "2026-10-17T13:55:00", "2026-10-17T17:20:00",
        51658, "INR", "", BookingStatus.CONFIRMED,
        "Himanshu booked this flight.",
    ),
]


def seed_itinerary(*, wipe: bool = False) -> dict[str, int]:
    """Insert the itinerary. Idempotent on `slug` and booking title."""
    counts = {"places": 0, "legs": 0, "bookings": 0}

    with session_scope() as session:
        if wipe:
            session.query(Booking).delete()
            session.query(Leg).delete()
            session.query(Place).delete()
            session.flush()

        by_slug: dict[str, Place] = {
            p.slug: p for p in session.scalars(select(Place)).all()
        }

        for (slug, name, region, lat, lon, arrive, depart, nights,
             order, blurb, terms) in PLACES:
            if slug in by_slug:
                continue
            place = Place(
                slug=slug, name=name, region=region, lat=lat, lon=lon,
                arrive_on=arrive, depart_on=depart, nights=nights,
                order_index=order, blurb=blurb, match_terms=terms,
                country="India" if slug in ("delhi", "bangalore") else "Thailand",
            )
            session.add(place)
            by_slug[slug] = place
            counts["places"] += 1
        session.flush()

        existing_legs = {
            (leg.from_slug, leg.to_slug, leg.order_index)
            for leg in session.scalars(select(Leg)).all()
        }
        for (frm, to, mode, operator, ref, dep, arr, mins,
             order, notes, url) in LEGS:
            if (frm, to, order) in existing_legs:
                continue
            session.add(Leg(
                from_slug=frm, to_slug=to, mode=mode, operator=operator,
                reference=ref, depart_at=_dt(dep), arrive_at=_dt(arr),
                duration_minutes=mins, order_index=order, notes=notes,
                booking_url=url,
            ))
            counts["legs"] += 1

        existing_titles = {
            b.title for b in session.scalars(select(Booking)).all()
        }
        for (kind, title, provider, url, description, place_slug, start, end,
             cost, ccy, confirmation, status, notes) in BOOKINGS:
            if title in existing_titles:
                continue
            place = by_slug.get(place_slug) if place_slug else None
            session.add(Booking(
                kind=str(kind), title=title, provider=provider, url=url,
                description=description,
                place_id=place.id if place else None,
                starts_at=_dt(start) if start else None,
                ends_at=_dt(end) if end else None,
                cost=float(cost), currency=ccy, confirmation=confirmation,
                status=str(status), notes=notes,
            ))
            counts["bookings"] += 1

    return counts


if __name__ == "__main__":
    from .db import init_db

    init_db(seed_if_empty=False)
    result = seed_itinerary()
    print(f"seeded: {result}")
