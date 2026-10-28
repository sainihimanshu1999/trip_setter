"""Request/response schemas for the booking CRUD endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import BookingKind, BookingStatus

ALLOWED_SCHEMES = ("http://", "https://")


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
