"""Seed the trip itinerary.

Coordinates are real so the journey map is geographically honest. Dates,
operators and confirmation numbers come from the actual booking documents
(see `data/docs/`), not from the CSV: a Splitwise expense is dated whenever it
was *entered*, which is routinely months before departure, so the CSV's own
dates were never a reliable source for when the trip happens.

Route: Delhi -> Bangkok -> Koh Samui -> Phuket -> Delhi / Bangalore

Koh Samui's and Phuket's exact arrive/depart dates are estimates: no document
confirms them yet (both marked in their `notes`). Everything else here is
taken directly from a ticket, voucher or policy.
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
        None, date(2026, 11, 20), 0, 0,
        "Where it starts. Red-eye out of Terminal 3.",
        "del,indira gandhi,home,delhi",
    ),
    (
        "bangkok", "Bangkok", "Central Thailand", 13.7563, 100.5018,
        date(2026, 11, 20), date(2026, 11, 22), 2, 1,
        "Temples at sunrise, Chinatown at midnight, and the best pad thai "
        "on the planet at Thipsamai. Base for the first two nights.",
        "bkk,dmk,suvarnabhumi,don mueang,chatuchak,wat pho,grand palace,"
        "khao san,sukhumvit,silom,thipsamai,rajadamnern,chao phraya,phaya thai,"
        "bangkok stay",
    ),
    (
        "koh-samui", "Koh Samui", "Gulf Coast", 9.5120, 100.0067,
        date(2026, 11, 23), date(2026, 11, 28), 5, 2,
        "Island vibes, golden beaches, and a BnB with the crew. "
        "Train from Bangkok to Surat Thani, then ferry across. "
        "Dates are an estimate -- no confirmation document for this stay yet.",
        "koh samui,samui,surat thani,nathon,chaweng,lamai,bophut,fisherman village,"
        "koh samui bnb",
    ),
    (
        "phuket", "Phuket", "Andaman Coast", 7.8906, 98.2969,
        date(2026, 11, 28), date(2026, 11, 29), 1, 3,
        "Last stop. Patong nightlife, Kata beach, and the flights home. "
        "Dates are an estimate -- no confirmation document for this stay yet.",
        "hkt,patong,rassada,kalim,kata,karon,phuket,flight hkt,airbnb phuket",
    ),
    (
        "bangalore", "Bangalore", "India", 12.9716, 77.5946,
        date(2026, 11, 29), None, 0, 4,
        "Home for Riya, Ayushi and Shruti. Direct Phuket–Bangalore flight.",
        "blr,bangalore,bengaluru,kempegowda",
    ),
]

# from, to, mode, operator, ref, depart, arrive, minutes, order, notes, url
LEGS: list[tuple] = [
    (
        "delhi", "bangkok", "plane", "Thai Airways", "TG 332",
        "2026-11-20T03:30:00", "2026-11-20T09:00:00", 240, 0,
        "Delhi to Bangkok. Lands at Suvarnabhumi. PNR 897AUL.",
        "https://www.thaiairways.com/",
    ),
    (
        "bangkok", "koh-samui", "train", "Thai Railways", "167",
        "2026-11-22T20:30:00", "2026-11-23T07:16:00", 646, 1,
        "Overnight sleeper, Krung Thep Aphiwat Central to Surat Thani "
        "(booking 12GO33371718), then ferry to Koh Samui.",
        "",
    ),
    (
        "koh-samui", "phuket", "plane", "", "",
        "2026-11-28T10:00:00", "2026-11-28T11:10:00", 70, 2,
        "Short hop from Samui to Phuket. Date estimated -- no confirmation yet.",
        "",
    ),
    (
        "phuket", "delhi", "plane", "IndiGo", "6E 1082",
        "2026-11-29T22:40:00", "2026-11-30T02:00:00", 290, 3,
        "Phuket to Delhi. Himanshu and Lakshay fly home. PNR TGDG5X.",
        "https://www.goindigo.in/",
    ),
    (
        "phuket", "bangalore", "plane", "Akasa Air", "QP 624",
        "2026-11-29T17:00:00", "2026-11-29T19:20:00", 140, 4,
        "Phuket to Bangalore. Riya, Ayushi and Shruti fly home. PNR KB9GYQ.",
        "https://www.akasaair.com/",
    ),
]

# kind, title, provider, url, description, place slug, start, end, cost, ccy,
# confirmation, status, notes
BOOKINGS: list[tuple] = [
    (
        BookingKind.FLIGHT, "Delhi to Bangkok", "Thai Airways",
        "https://www.thaiairways.com/",
        "Riya, Ayushi, Pranjal, Himanshu and Shruti on this ticket; "
        "Lakshay travelled separately.",
        "delhi", "2026-11-20T03:30:00", "2026-11-20T09:00:00",
        94496, "INR", "897AUL", BookingStatus.CONFIRMED,
        "Pranjal paid for the group.",
    ),
    (
        BookingKind.STAY, "Bangkok stay", "lyf Sukhumvit 8 Bangkok",
        "",
        "3 rooms at lyf Sukhumvit 8, near BTS Nana.",
        "bangkok", "2026-11-20T14:00:00", "2026-11-22T12:00:00",
        32546, "INR", "6081.740.924", BookingStatus.CONFIRMED,
        "Ayushi booked this one. PIN 2060 for check-in.",
    ),
    (
        BookingKind.TRAIN, "Bangkok to Surat Thani train",
        "Thai Railways (via 12Go)",
        "",
        "Krung Thep Aphiwat Central to Surat Thani, 2nd class sleeper AC, "
        "then ferry to Koh Samui.",
        "bangkok", "2026-11-22T20:30:00", "2026-11-23T07:16:00",
        19147, "INR", "12GO33371718", BookingStatus.CONFIRMED,
        "Himanshu covered the tickets.",
    ),
    (
        BookingKind.STAY, "Koh Samui BnB", "",
        "",
        "BnB on Koh Samui for the whole group.",
        "koh-samui", "2026-11-23T14:00:00", "2026-11-28T11:00:00",
        27511, "INR", "", BookingStatus.CONFIRMED,
        "Pranjal booked the BnB. Dates are an estimate -- no confirmation "
        "document yet; edit once you have one.",
    ),
    (
        BookingKind.FLIGHT, "Phuket to Bangalore", "Akasa Air",
        "https://www.akasaair.com/",
        "Riya, Ayushi, and Shruti fly home to Bangalore.",
        "phuket", "2026-11-29T17:00:00", "2026-11-29T19:20:00",
        68157, "INR", "KB9GYQ", BookingStatus.CONFIRMED,
        "Riya booked this flight.",
    ),
    (
        BookingKind.FLIGHT, "Phuket to Delhi", "IndiGo",
        "https://www.goindigo.in/",
        "Himanshu and Lakshay fly home to Delhi.",
        "phuket", "2026-11-29T22:40:00", "2026-11-30T02:00:00",
        51658, "INR", "TGDG5X", BookingStatus.CONFIRMED,
        "Himanshu booked this flight.",
    ),
    (
        BookingKind.STAY, "Airbnb Phuket", "Airbnb",
        "",
        "Phuket accommodation for the last stop.",
        "phuket", "2026-11-28T14:00:00", "2026-11-29T11:00:00",
        51856, "INR", "", BookingStatus.CONFIRMED,
        "Dates are an estimate -- no confirmation document yet; edit once "
        "you have one.",
    ),
    (
        BookingKind.VISA, "Travel insurance", "Go Digit General Insurance",
        "https://www.godigit.com/",
        "Digit \"On-the-Move\" group policy covering the trip.",
        "", "2026-11-20T00:00:00", "2026-11-30T23:59:00",
        3365.60, "INR", "D309476821", BookingStatus.CONFIRMED,
        "Covers Ayushi, Himanshu, Shruti and Riya. Pranjal and Lakshay are "
        "not on this policy -- worth checking if they need their own cover.",
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
