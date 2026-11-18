"""Request/response schemas for the booking and itinerary CRUD endpoints."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .classify import Mode
from .models import BookingKind, BookingStatus

ALLOWED_SCHEMES = ("http://", "https://")


def _safe_url_or_raise(v: str) -> str:
    """Shared by every optional link field: only http(s), never javascript:."""
    if not v:
        return ""
    if not v.lower().startswith(ALLOWED_SCHEMES):
        raise ValueError("url must start with http:// or https://")
    return v


class BookingIn(BaseModel):
    """Payload for creating a booking."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: BookingKind = BookingKind.OTHER
    title: str = Field(min_length=1, max_length=200)
    provider: str = Field(default="", max_length=120)
    url: str = ""
    description: str = ""
    place_id: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    cost: float = Field(default=0.0, ge=0)
    currency: str = Field(default="THB", min_length=3, max_length=8)
    confirmation: str = Field(default="", max_length=120)
    status: BookingStatus = BookingStatus.CONFIRMED
    notes: str = ""

    @field_validator("url", mode="after")
    @classmethod
    def _safe_url(cls, v: str) -> str:
        """Only allow http(s). Blocks javascript: and data: URLs, which would
        otherwise execute when the card link is clicked."""
        if not v:
            return ""
        if not v.lower().startswith(ALLOWED_SCHEMES):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("currency", mode="after")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("ends_at", mode="after")
    @classmethod
    def _end_after_start(cls, v: datetime | None, info) -> datetime | None:  # noqa: ANN001
        start = info.data.get("starts_at")
        if v and start and v < start:
            raise ValueError("ends_at cannot be before starts_at")
        return v


class BookingPatch(BaseModel):
    """Partial update. Every field optional; omitted fields stay as they are."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: BookingKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    provider: str | None = None
    url: str | None = None
    description: str | None = None
    place_id: int | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    confirmation: str | None = None
    status: BookingStatus | None = None
    notes: str | None = None

    @field_validator("url", mode="after")
    @classmethod
    def _safe_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if not v.lower().startswith(ALLOWED_SCHEMES):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("currency", mode="after")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


# ------------------------------------------------------------------ itinerary


class PlaceIn(BaseModel):
    """Payload for adding a stop to the itinerary."""

    model_config = ConfigDict(str_strip_whitespace=True)

    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    region: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    arrive_on: date | None = None
    depart_on: date | None = None
    nights: int = Field(default=0, ge=0)
    order_index: int = 0
    blurb: str = ""
    #: Comma-separated keywords that tie a Splitwise expense to this place.
    match_terms: str = Field(default="", max_length=2000)

    @field_validator("depart_on", mode="after")
    @classmethod
    def _depart_after_arrive(cls, v: date | None, info) -> date | None:  # noqa: ANN001
        arrive = info.data.get("arrive_on")
        if v and arrive and v < arrive:
            raise ValueError("depart_on cannot be before arrive_on")
        return v


class PlacePatch(BaseModel):
    """Partial update. Every field optional; omitted fields stay as they are."""

    model_config = ConfigDict(str_strip_whitespace=True)

    slug: str | None = Field(default=None, min_length=1, max_length=64,
                              pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    region: str | None = None
    country: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    arrive_on: date | None = None
    depart_on: date | None = None
    nights: int | None = Field(default=None, ge=0)
    order_index: int | None = None
    blurb: str | None = None
    match_terms: str | None = Field(default=None, max_length=2000)


class LegIn(BaseModel):
    """Payload for adding a leg between two places."""

    model_config = ConfigDict(str_strip_whitespace=True)

    from_slug: str = Field(min_length=1, max_length=64)
    to_slug: str = Field(min_length=1, max_length=64)
    mode: Mode = Mode.PLANE
    operator: str = Field(default="", max_length=120)
    reference: str = Field(default="", max_length=80)
    depart_at: datetime | None = None
    arrive_at: datetime | None = None
    duration_minutes: int = Field(default=0, ge=0)
    order_index: int = 0
    notes: str = ""
    booking_url: str = ""

    @field_validator("booking_url", mode="after")
    @classmethod
    def _safe_url(cls, v: str) -> str:
        return _safe_url_or_raise(v)

    @field_validator("arrive_at", mode="after")
    @classmethod
    def _arrive_after_depart(cls, v: datetime | None, info) -> datetime | None:  # noqa: ANN001
        depart = info.data.get("depart_at")
        if v and depart and v < depart:
            raise ValueError("arrive_at cannot be before depart_at")
        return v

    @field_validator("to_slug", mode="after")
    @classmethod
    def _not_a_loop(cls, v: str, info) -> str:  # noqa: ANN001
        if v and v == info.data.get("from_slug"):
            raise ValueError("a leg needs two different places")
        return v


class LegPatch(BaseModel):
    """Partial update. Every field optional; omitted fields stay as they are."""

    model_config = ConfigDict(str_strip_whitespace=True)

    from_slug: str | None = Field(default=None, min_length=1, max_length=64)
    to_slug: str | None = Field(default=None, min_length=1, max_length=64)
    mode: Mode | None = None
    operator: str | None = None
    reference: str | None = None
    depart_at: datetime | None = None
    arrive_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0)
    order_index: int | None = None
    notes: str | None = None
    booking_url: str | None = None

    @field_validator("booking_url", mode="after")
    @classmethod
    def _safe_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _safe_url_or_raise(v)
