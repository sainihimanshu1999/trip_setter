"""SQLite models for the itinerary and bookings.

Splitwise knows what the trip cost. It has no idea where you are going, what
you booked, or which link the confirmation email came from. That lives here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BookingKind(StrEnum):
    FLIGHT = "flight"
    STAY = "stay"
    TOUR = "tour"
    TRANSFER = "transfer"
    TRAIN = "train"
    FERRY = "ferry"
    VISA = "visa"
    OTHER = "other"


#: Presentation metadata for booking kinds, mirrored in the frontend.
#: Kept in step with app.classify.MODE_STYLE so a flight booking and a flight
#: line on the map are the same colour.
BOOKING_KIND_STYLE: dict[str, dict[str, str]] = {
    BookingKind.FLIGHT: {"label": "Flight", "colour": "#2563eb", "glyph": "plane"},
    BookingKind.STAY: {"label": "Stay", "colour": "#7c3aed", "glyph": "bed"},
    BookingKind.TOUR: {"label": "Tour", "colour": "#0d9488", "glyph": "ticket"},
    BookingKind.TRANSFER: {"label": "Transfer", "colour": "#d97706", "glyph": "car"},
    BookingKind.TRAIN: {"label": "Train", "colour": "#7c3aed", "glyph": "train"},
    BookingKind.FERRY: {"label": "Ferry", "colour": "#0d9488", "glyph": "boat"},
    BookingKind.VISA: {"label": "Visa & docs", "colour": "#ca8a04", "glyph": "stamp"},
    BookingKind.OTHER: {"label": "Other", "colour": "#717171", "glyph": "dot"},
}


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    PENDING = "pending"
    CANCELLED = "cancelled"
    IDEA = "idea"


class Place(Base):
    """A stop on the trip. Coordinates drive the journey map layout."""

    __tablename__ = "places"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(120), default="")
    country: Mapped[str] = mapped_column(String(80), default="Thailand")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    arrive_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    depart_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    nights: Mapped[int] = mapped_column(Integer, default=0)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    blurb: Mapped[str] = mapped_column(Text, default="")
    #: Keywords that tie Splitwise expenses to this place.
    match_terms: Mapped[str] = mapped_column(Text, default="")

    bookings: Mapped[list["Booking"]] = relationship(
        back_populates="place", cascade="all, delete-orphan",
    )

    def terms(self) -> list[str]:
        base = [self.name.lower(), self.slug.lower()]
        extra = [t.strip().lower() for t in (self.match_terms or "").split(",") if t.strip()]
        return [t for t in base + extra if t]

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "region": self.region,
            "country": self.country,
            "lat": self.lat,
            "lon": self.lon,
            "arrive_on": self.arrive_on.isoformat() if self.arrive_on else None,
            "depart_on": self.depart_on.isoformat() if self.depart_on else None,
            "nights": self.nights,
            "order_index": self.order_index,
            "blurb": self.blurb,
        }


class Leg(Base):
    """A planned hop between two places, with the mode drawn on the map."""

    __tablename__ = "legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_slug: Mapped[str] = mapped_column(String(64), index=True)
    to_slug: Mapped[str] = mapped_column(String(64), index=True)
    #: One of app.classify.Mode
    mode: Mapped[str] = mapped_column(String(16), default="plane")
    operator: Mapped[str] = mapped_column(String(120), default="")
    reference: Mapped[str] = mapped_column(String(80), default="")
    depart_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrive_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    booking_url: Mapped[str] = mapped_column(Text, default="")

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "from": self.from_slug,
            "to": self.to_slug,
            "mode": self.mode,
            "operator": self.operator,
            "reference": self.reference,
            "depart_at": self.depart_at.isoformat() if self.depart_at else None,
            "arrive_at": self.arrive_at.isoformat() if self.arrive_at else None,
            "duration_minutes": self.duration_minutes,
            "order_index": self.order_index,
            "notes": self.notes,
            "booking_url": self.booking_url,
        }


class Booking(Base):
    """Anything reserved in advance: flights, hotels, tours, transfers."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), default=BookingKind.OTHER, index=True)
    title: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    place_id: Mapped[int | None] = mapped_column(
        ForeignKey("places.id", ondelete="SET NULL"), nullable=True,
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="THB")
    confirmation: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default=BookingStatus.CONFIRMED)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    place: Mapped["Place | None"] = relationship(back_populates="bookings")

    def as_json(self) -> dict:
        style = BOOKING_KIND_STYLE.get(self.kind, BOOKING_KIND_STYLE[BookingKind.OTHER])
        return {
            "id": self.id,
            "kind": self.kind,
            "kind_label": style["label"],
            "colour": style["colour"],
            "glyph": style["glyph"],
            "title": self.title,
            "provider": self.provider,
            "url": self.url,
            "description": self.description,
            "place_id": self.place_id,
            "place": self.place.name if self.place else None,
            "place_slug": self.place.slug if self.place else None,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "cost": self.cost,
            "currency": self.currency,
            "confirmation": self.confirmation,
            "status": self.status,
            "notes": self.notes,
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
