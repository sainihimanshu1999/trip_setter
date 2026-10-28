"""Turn a list of expenses into everything the dashboard draws.

All money is converted to the home currency first, so a THB ferry ticket and an
INR flight booking can sit in the same bar chart.

Vocabulary used throughout:

* **paid** - money that actually left this person's pocket.
* **owed** - this person's share of the group's spending (their fair share).
* **net** - paid minus owed. Positive means the group owes them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote

from .classify import Bucket, Mode, bucket_style, mode_style
from .domain import ZERO, Expense, Person, TripData
from .fx import FxConverter

CENTS = Decimal("0.01")

# Distinct, accessible colours assigned to people in order. Chosen for contrast
# against white backgrounds and each other, and tested for colour-blind safety.
PERSON_COLOURS = [
    "#e63946",  # red
    "#2563eb",  # blue
    "#059669",  # emerald
    "#d97706",  # amber
    "#7c3aed",  # violet
    "#db2777",  # pink
    "#0d9488",  # teal
    "#ea580c",  # orange
    "#4f46e5",  # indigo
    "#65a30d",  # lime
]

# DiceBear avatar styles that look like fun 3D characters.
# The URL is deterministic from the person's name, so the same person always
# gets the same face. No API key required, no files stored.
_AVATAR_STYLE = "adventurer"
_AVATAR_BASE = f"https://api.dicebear.com/9.x/{_AVATAR_STYLE}/svg"


def person_avatar_url(name: str) -> str:
    """Stable, fun 3D-ish avatar from DiceBear for a person's name."""
    return f"{_AVATAR_BASE}?seed={quote(name)}&radius=50&size=80"


def person_colour(index: int) -> str:
    """Return a colour from the palette, cycling if needed."""
    return PERSON_COLOURS[index % len(PERSON_COLOURS)]


@dataclass(slots=True)
class PersonTotals:
    person: Person
    paid: Decimal = ZERO
    owed: Decimal = ZERO
    expense_count: int = 0
    #: Settle-up money received from / sent to others.
    settled_in: Decimal = ZERO
    settled_out: Decimal = ZERO
    by_bucket: dict[str, Decimal] = field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        """Fronted minus fair share, ignoring settle-ups.

        Answers "did this person carry the group?" rather than "what do they
        owe right now".
        """
        return (self.paid - self.owed).quantize(CENTS)

    @property
    def balance(self) -> Decimal:
        """What this person is actually up or down once settle-ups count.

        Positive means the group still owes them.
        """
        return (self.paid - self.owed + self.settled_out - self.settled_in).quantize(CENTS)

    def as_json(self, max_paid: Decimal, index: int = 0) -> dict:
        # Bar length is relative to the biggest spender so the chart always
        # fills its width regardless of trip size.
        share = float(self.paid / max_paid) if max_paid > 0 else 0.0
        return {
            "id": self.person.id,
            "name": self.person.name,
            "first_name": self.person.first_name,
            "initials": self.person.initials,
            "avatar": self.person.avatar,
            "avatar_3d": person_avatar_url(self.person.name),
            "color": person_colour(index),
            "paid": float(self.paid.quantize(CENTS)),
            "owed": float(self.owed.quantize(CENTS)),
            "net": float(self.net),
            "balance": float(self.balance),
            "settled_in": float(self.settled_in.quantize(CENTS)),
            "settled_out": float(self.settled_out.quantize(CENTS)),
            "expense_count": self.expense_count,
            "bar_ratio": round(share, 4),
            "by_bucket": {k: float(v.quantize(CENTS)) for k, v in self.by_bucket.items()},
        }


@dataclass(slots=True)
class Settlement:
    """One transfer that moves the group towards settled."""

    from_id: int
    from_name: str
    to_id: int
    to_name: str
    amount: Decimal

    def as_json(self) -> dict:
        return {
            "from_id": self.from_id,
            "from_name": self.from_name,
            "to_id": self.to_id,
            "to_name": self.to_name,
            "amount": float(self.amount),
        }


def settle(nets: dict[int, Decimal], names: dict[int, str],
           epsilon: Decimal = Decimal("0.5")) -> list[Settlement]:
    """Minimise the number of transfers that clear everyone's balance.

    Greedy largest-creditor/largest-debtor matching. This is the same idea as
    Splitwise's "simplify debts" and gives at most n-1 transfers, which is the
    best possible in the general case.

    `epsilon` ignores sub-currency-unit dust left by rounding.
    """
    creditors = sorted(
        ((uid, amt) for uid, amt in nets.items() if amt > epsilon),
        key=lambda kv: kv[1], reverse=True,
    )
    debtors = sorted(
        ((uid, -amt) for uid, amt in nets.items() if amt < -epsilon),
        key=lambda kv: kv[1], reverse=True,
    )

    transfers: list[Settlement] = []
    ci = di = 0
    credit = list(creditors)
    debit = list(debtors)

    while ci < len(credit) and di < len(debit):
        cred_id, cred_amt = credit[ci]
        debt_id, debt_amt = debit[di]
        amount = min(cred_amt, debt_amt)
        if amount > epsilon:
            transfers.append(Settlement(
                from_id=debt_id, from_name=names.get(debt_id, f"User {debt_id}"),
                to_id=cred_id, to_name=names.get(cred_id, f"User {cred_id}"),
                amount=amount.quantize(CENTS),
            ))
        credit[ci] = (cred_id, cred_amt - amount)
        debit[di] = (debt_id, debt_amt - amount)
        if credit[ci][1] <= epsilon:
            ci += 1
        if debit[di][1] <= epsilon:
            di += 1

    return transfers


@dataclass(slots=True)
class Analytics:
    """Computed view over a trip. Built once per request, cheap to rebuild."""

    trip: TripData
    fx: FxConverter
    people: list[PersonTotals] = field(default_factory=list)
    by_bucket: dict[str, Decimal] = field(default_factory=dict)
    by_mode: dict[str, Decimal] = field(default_factory=dict)
    by_day: dict[date, Decimal] = field(default_factory=dict)
    settlements: list[Settlement] = field(default_factory=list)
    total_spend: Decimal = ZERO
    total_settled: Decimal = ZERO
    currencies: dict[str, Decimal] = field(default_factory=dict)
    #: Spending dated before the trip window, e.g. flights booked months out.
    prebooked: Decimal = ZERO
    window: tuple[date, date] | None = None

    @property
    def currency(self) -> str:
        return self.fx.home

    @property
    def head_count(self) -> int:
        return len([p for p in self.people if p.owed > 0 or p.paid > 0])

    @property
    def per_head(self) -> Decimal:
        n = self.head_count
        return (self.total_spend / n).quantize(CENTS) if n else ZERO

    @property
    def biggest_day(self) -> tuple[date | None, Decimal]:
        """Heaviest spending day inside the trip window.

        Pre-trip bookings are excluded: a flight bought in December would
        otherwise always win, and it already has its own `prebooked` figure.
        """
        candidates = self.by_day
        if self.window:
            start, end = self.window
            in_window = {d: v for d, v in self.by_day.items() if start <= d <= end}
            candidates = in_window or self.by_day
        if not candidates:
            return None, ZERO
        day, amount = max(candidates.items(), key=lambda kv: kv[1])
        return day, amount


def build_analytics(
    trip: TripData,
    fx: FxConverter,
    window: tuple[date, date] | None = None,
) -> Analytics:
    """Fold every expense into per-person, per-bucket and per-day totals."""
    out = Analytics(trip=trip, fx=fx, window=window)

    totals: dict[int, PersonTotals] = {
        p.id: PersonTotals(person=p, by_bucket={}) for p in trip.people
    }
    nets: dict[int, Decimal] = defaultdict(lambda: ZERO)
    names: dict[int, str] = {p.id: p.name for p in trip.people}

    bucket_sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    mode_sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    day_sums: dict[date, Decimal] = defaultdict(lambda: ZERO)
    currency_sums: dict[str, Decimal] = defaultdict(lambda: ZERO)

    for expense in trip.expenses:
        home_cost = fx.convert(expense.cost, expense.currency)
        expense.home_cost = home_cost

        # A settle-up moves money without being group spending.
        if expense.is_payment:
            out.total_settled += home_cost
        else:
            out.total_spend += home_cost
            bucket_sums[str(expense.bucket)] += home_cost
            mode_sums[str(expense.mode)] += home_cost
            currency_sums[expense.currency] += expense.cost
            if expense.date:
                day_sums[expense.date] += home_cost
                if window and expense.date < window[0]:
                    out.prebooked += home_cost

        for share in expense.shares:
            paid_home = fx.convert(share.paid, expense.currency)
            owed_home = fx.convert(share.owed, expense.currency)

            if share.user_id not in totals:
                totals[share.user_id] = PersonTotals(
                    person=Person.from_name(share.user_id, share.name),
                    by_bucket={},
                )
                names.setdefault(share.user_id, share.name)

            entry = totals[share.user_id]
            if expense.is_payment:
                # Settle-ups affect who owes whom, never how much was spent.
                entry.settled_out += paid_home
                entry.settled_in += owed_home
            else:
                entry.paid += paid_home
                entry.owed += owed_home
                if paid_home > 0:
                    entry.expense_count += 1
                if owed_home > 0:
                    key = str(expense.bucket)
                    entry.by_bucket[key] = entry.by_bucket.get(key, ZERO) + owed_home

            nets[share.user_id] += paid_home - owed_home

    out.people = sorted(totals.values(), key=lambda t: t.paid, reverse=True)
    out.by_bucket = dict(sorted(bucket_sums.items(), key=lambda kv: kv[1], reverse=True))
    out.by_mode = dict(sorted(mode_sums.items(), key=lambda kv: kv[1], reverse=True))
    out.by_day = dict(sorted(day_sums.items()))
    out.currencies = dict(sorted(currency_sums.items(), key=lambda kv: kv[1], reverse=True))
    out.settlements = settle({k: v for k, v in nets.items()}, names)
    return out


# ------------------------------------------------------------------ payloads


def overview_payload(a: Analytics) -> dict:
    big_day, big_amount = a.biggest_day
    max_paid = max((p.paid for p in a.people), default=ZERO)
    return {
        "currency": a.currency,
        "group_name": a.trip.group_name,
        "source": a.trip.source,
        "warning": a.trip.warning,
        "fetched_at": a.trip.fetched_at.isoformat() if a.trip.fetched_at else None,
        "total_spend": float(a.total_spend.quantize(CENTS)),
        "total_settled": float(a.total_settled.quantize(CENTS)),
        "prebooked": float(a.prebooked.quantize(CENTS)),
        "per_head": float(a.per_head),
        "head_count": a.head_count,
        "expense_count": len([e for e in a.trip.expenses if not e.is_payment]),
        "transport_spend": float(sum(
            (v for k, v in a.by_mode.items() if k != str(Mode.NONE)), ZERO
        ).quantize(CENTS)),
        "biggest_day": {
            "date": big_day.isoformat() if big_day else None,
            "amount": float(big_amount.quantize(CENTS)),
        },
        "currencies": {k: float(v.quantize(CENTS)) for k, v in a.currencies.items()},
        "fx": a.fx.as_json(),
        "people": [p.as_json(max_paid, i) for i, p in enumerate(a.people)],
        "settlements": [s.as_json() for s in a.settlements],
    }


def buckets_payload(a: Analytics) -> dict:
    total = a.total_spend or Decimal("1")
    rows = []
    for key, amount in a.by_bucket.items():
        style = bucket_style(key)
        rows.append({
            "key": key,
            "label": style["label"],
            "colour": style["colour"],
            "icon": style["icon"],
            "amount": float(amount.quantize(CENTS)),
            "share": round(float(amount / total), 4),
        })
    return {
        "currency": a.currency,
        "total": float(a.total_spend.quantize(CENTS)),
        "buckets": rows,
    }


def modes_payload(a: Analytics) -> dict:
    rows = []
    for key, amount in a.by_mode.items():
        if key == str(Mode.NONE):
            continue
        style = mode_style(key)
        rows.append({
            "key": key,
            "label": style["label"],
            "colour": style["colour"],
            "glyph": style["glyph"],
            "amount": float(amount.quantize(CENTS)),
            "count": len([
                e for e in a.trip.expenses
                if str(e.mode) == key and not e.is_payment
            ]),
        })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return {"currency": a.currency, "modes": rows}


def timeline_payload(a: Analytics) -> dict:
    """Daily spend across the trip window, gap-filled so no days are missing.

    Spending dated before the window (flights booked months ahead) would
    otherwise stretch the axis across empty weeks, so it is reported as a
    single `prebooked` figure instead.
    """
    if not a.by_day:
        return {
            "currency": a.currency, "days": [], "max": 0.0,
            "prebooked": 0.0, "window": None,
        }

    if a.window:
        start, end = a.window
        # Let real spending extend the window if the trip ran long.
        dated = [d for d in a.by_day if start <= d <= end]
        if dated:
            end = max(end, max(dated))
    else:
        start, end = min(a.by_day), max(a.by_day)

    prebooked = sum((amt for day, amt in a.by_day.items() if day < start), ZERO)
    after = sum((amt for day, amt in a.by_day.items() if day > end), ZERO)

    by_day_expenses: dict[date, list] = defaultdict(list)
    for expense in a.trip.expenses:
        if expense.date and not expense.is_payment:
            by_day_expenses[expense.date].append(expense)

    days = []
    cursor = start
    while cursor <= end:
        todays = by_day_expenses.get(cursor, [])
        top = max(todays, key=lambda e: e.home_cost, default=None)
        days.append({
            "date": cursor.isoformat(),
            "label": cursor.strftime("%d %b"),
            "weekday": cursor.strftime("%a"),
            "amount": float(a.by_day.get(cursor, ZERO).quantize(CENTS)),
            "count": len(todays),
            "modes": sorted({str(e.mode) for e in todays if e.mode != Mode.NONE}),
            "top": top.description if top else "",
        })
        cursor += timedelta(days=1)

    peak = max((d["amount"] for d in days), default=0.0)
    return {
        "currency": a.currency,
        "days": days,
        "max": peak,
        "prebooked": float(prebooked.quantize(CENTS)),
        "after": float(after.quantize(CENTS)),
        "window": [start.isoformat(), end.isoformat()],
    }


def expenses_payload(a: Analytics, limit: int | None = None) -> dict:
    rows = [e.as_json() for e in reversed(a.trip.expenses)]
    if limit:
        rows = rows[:limit]
    return {"currency": a.currency, "expenses": rows}
