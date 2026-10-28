"""Normalised trip domain objects.

The Splitwise payload is wide and stringly-typed. Everything downstream works
on these dataclasses instead, so analytics never has to think about
`owed_share` being the string "4.50".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .classify import Bucket, Mode, classify

ZERO = Decimal("0")


def to_decimal(value: object) -> Decimal:
    """Parse Splitwise's string money fields without ever raising."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


def to_date(value: object) -> date | None:
    """Parse an ISO 8601 timestamp (Splitwise uses trailing 'Z')."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


@dataclass(slots=True)
class Person:
    id: int
    name: str
    first_name: str = ""
    avatar: str | None = None
    initials: str = ""

    @classmethod
    def from_name(cls, user_id: int, name: str) -> "Person":
        """Build a person from a display name alone.

        The CSV export and the settle-up fallback path only know a name, so
        first name and initials are derived here rather than in each caller.
        """
        clean = name.strip() or f"User {user_id}"
        parts = clean.split()
        first = parts[0] if parts else clean
        last = parts[-1] if len(parts) > 1 else ""
        return cls(
            id=user_id,
            name=clean,
            first_name=first,
            initials=(first[:1] + last[:1]).upper(),
        )

    @classmethod
    def from_api(cls, raw: dict) -> "Person":
        first = (raw.get("first_name") or "").strip()
        last = (raw.get("last_name") or "").strip()
        name = " ".join(p for p in (first, last) if p) or f"User {raw.get('id')}"
        picture = raw.get("picture") or {}
        avatar = picture.get("medium") or picture.get("small") or picture.get("large")
        # Splitwise serves a generic grey silhouette for users with no photo;
        # our own initials bubble looks better than that.
        if avatar and "default" in avatar:
            avatar = None
        initials = (first[:1] + (last[:1] if last else "")).upper() or name[:1].upper()
        return cls(
            id=int(raw.get("id", 0)),
            name=name,
            first_name=first or name.split()[0],
            avatar=avatar,
            initials=initials,
        )


@dataclass(slots=True)
class Share:
    """One person's involvement in one expense."""

    user_id: int
    name: str
    paid: Decimal = ZERO
    owed: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        """Positive when this person is owed money for this expense."""
        return self.paid - self.owed


@dataclass(slots=True)
class Expense:
    id: int
    description: str
    cost: Decimal
    currency: str
    date: date | None
    category: str = ""
    details: str = ""
    is_payment: bool = False
    shares: list[Share] = field(default_factory=list)
    mode: Mode = Mode.NONE
    bucket: Bucket = Bucket.MISC
    confidence: float = 0.0
    reason: str = ""
    #: Cost converted into the home currency; filled in by the FX layer.
    home_cost: Decimal = ZERO

    @classmethod
    def from_api(cls, raw: dict) -> "Expense":
        category = ((raw.get("category") or {}).get("name") or "").strip()
        description = (raw.get("description") or "").strip()
        details = (raw.get("details") or "") or ""
        verdict = classify(description, category, details)

        shares: list[Share] = []
        for entry in raw.get("users") or []:
            user = entry.get("user") or {}
            person = Person.from_api(user) if user else None
            uid = int(entry.get("user_id") or user.get("id") or 0)
            shares.append(
                Share(
                    user_id=uid,
                    name=person.name if person else f"User {uid}",
                    paid=to_decimal(entry.get("paid_share")),
                    owed=to_decimal(entry.get("owed_share")),
                )
            )

        return cls(
            id=int(raw.get("id", 0)),
            description=description or "(no description)",
            cost=to_decimal(raw.get("cost")),
            currency=(raw.get("currency_code") or "THB").upper(),
            date=to_date(raw.get("date")),
            category=category,
            details=details.strip(),
            is_payment=bool(raw.get("payment")),
            shares=shares,
            mode=verdict.mode,
            bucket=verdict.bucket,
            confidence=verdict.confidence,
            reason=verdict.reason,
        )

    @property
    def payer_names(self) -> list[str]:
        return [s.name for s in self.shares if s.paid > 0]

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "details": self.details,
            "cost": float(self.cost),
            "currency": self.currency,
            "home_cost": float(self.home_cost),
            "date": self.date.isoformat() if self.date else None,
            "category": self.category,
            "mode": str(self.mode),
            "bucket": str(self.bucket),
            "confidence": self.confidence,
            "reason": self.reason,
            "is_payment": self.is_payment,
            "payers": self.payer_names,
            "shares": [
                {
                    "user_id": s.user_id,
                    "name": s.name,
                    "paid": float(s.paid),
                    "owed": float(s.owed),
                }
                for s in self.shares
            ],
        }


@dataclass(slots=True)
class TripData:
    """Everything we pulled from Splitwise for one trip group."""

    group_id: int | None
    group_name: str
    people: list[Person]
    expenses: list[Expense]
    source: str = "live"          # "live" | "demo" | "cache"
    warning: str | None = None
    fetched_at: datetime | None = None

    def person(self, user_id: int) -> Person | None:
        return next((p for p in self.people if p.id == user_id), None)
