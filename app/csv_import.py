"""Import expenses from a Splitwise CSV export.

Splitwise lets you export any group or friendship as a spreadsheet from the web
UI, which needs neither an API key nor a Pro subscription:

    Group page -> settings gear -> "Export as spreadsheet"

The file has five fixed columns followed by one column per group member:

    Date, Description, Category, Cost, Currency, <Person 1>, <Person 2>, ...

Each person column holds that person's **net** impact for the row: positive
means they are owed money, negative means they owe it. The API reports `paid`
and `owed` separately, so `_build_shares` reconstructs them.

The result is a :class:`TripData` identical in shape to what the API client
returns, so analytics, FX, classification and the journey map are unchanged.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .classify import classify
from .domain import ZERO, Expense, Person, Share, TripData

log = logging.getLogger("trip.csv_import")

CENTS = Decimal("0.01")

#: The columns every export starts with. Anything else is a person.
FIXED_COLUMNS = ("date", "description", "category", "cost", "currency")

#: Synthetic user ids. The export has no ids, so people are numbered from here
#: in column order, which keeps them stable across reloads of the same file.
FIRST_USER_ID = 1001

#: Expense ids are synthetic too, offset by the CSV row number.
EXPENSE_ID_BASE = 500_000

#: Descriptions Splitwise uses for its trailing summary row.
SUMMARY_PREFIX = "total balance"

#: Words that mark a row as a settle-up rather than group spending. These
#: mirror the API's `payment` flag, which the export does not include.
PAYMENT_KEYWORDS = ("payment", "settle up", "settled up", "settle all", "repayment")

_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y")


def _safe_decimal(value: str) -> Decimal:
    """Parse a money cell, tolerating blanks, thousands separators and junk."""
    cleaned = (value or "").strip().replace(",", "")
    if not cleaned:
        return ZERO
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        log.warning("Cannot parse amount %r, treating as zero", value)
        return ZERO


def _parse_date(value: str) -> date | None:
    """Parse a date cell. Exports vary by locale, so several formats are tried."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        log.warning("Cannot parse date %r", value)
        return None


def _detect_person_columns(header: list[str]) -> list[str]:
    """Return the person columns, in the order the export lists them."""
    return [col.strip() for col in header if col.strip().lower() not in FIXED_COLUMNS]


def _assign_ids(names: list[str]) -> dict[str, int]:
    """Number the people in column order."""
    return {name: FIRST_USER_ID + i for i, name in enumerate(names)}


def _is_payment_row(description: str, category: str) -> bool:
    """Is this row a settle-up rather than group spending?"""
    haystack = f"{description} {category}".lower()
    return any(word in haystack for word in PAYMENT_KEYWORDS)


def _build_shares(
    person_columns: list[str],
    id_map: dict[str, int],
    row: dict[str, str],
    cost: Decimal,
) -> list[Share]:
    """Rebuild per-person paid and owed figures from the export's net balances.

    The decomposition that reproduces what the API would have returned:

    * **net < 0** - they paid nothing and owe exactly `-net`.
    * **net > 0** - they fronted money. What the payers owe between them is
      `cost` minus what the debtors owe, divided across the payers in
      proportion to their net. Their paid share is then `net + owed`.
    * **net == 0** - they are not in this expense. Someone who paid exactly
      their own share looks identical in the export, but splitting the cost
      with them anyway would invent money the `Cost` column does not account
      for, and would credit people who were not there.

    Because a row's nets sum to zero, this keeps both `sum(paid) == cost` and
    `sum(owed) == cost`.
    """
    nets = {name: _safe_decimal(row.get(name, "")) for name in person_columns}
    owed_by_debtors = sum((-net for net in nets.values() if net < ZERO), ZERO)
    fronted = sum((net for net in nets.values() if net > ZERO), ZERO)
    owed_by_payers = cost - owed_by_debtors

    shares: list[Share] = []
    for name, net in nets.items():
        user_id = id_map[name]
        if net < ZERO:
            shares.append(Share(user_id=user_id, name=name, paid=ZERO, owed=-net))
        elif net > ZERO:
            # fronted > 0 whenever any net > 0, so this cannot divide by zero.
            owed = (owed_by_payers * net / fronted).quantize(CENTS)
            shares.append(Share(user_id=user_id, name=name, paid=net + owed, owed=owed))
        else:
            shares.append(Share(user_id=user_id, name=name, paid=ZERO, owed=ZERO))
    return shares


def load_csv(path: Path | str) -> TripData:
    """Read a Splitwise CSV export.

    Raises `FileNotFoundError` if the file is missing, and `ValueError` if it
    has no header, is missing a fixed column, or names no people.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    # utf-8-sig drops the byte order mark Excel writes on Windows.
    reader = csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines())
    if reader.fieldnames is None:
        raise ValueError(f"CSV file is empty or has no header: {path}")

    header = [col.strip() for col in reader.fieldnames]
    missing = [col for col in FIXED_COLUMNS if col not in {h.lower() for h in header}]
    if missing:
        raise ValueError(
            f"CSV is missing required columns: {', '.join(missing)}. "
            f"Found: {', '.join(header)}"
        )

    person_columns = _detect_person_columns(header)
    if not person_columns:
        raise ValueError(
            "CSV has no person columns after "
            f"{'/'.join(c.title() for c in FIXED_COLUMNS)}. "
            "A Splitwise export has one column per group member."
        )

    id_map = _assign_ids(person_columns)
    people = [Person.from_name(id_map[name], name) for name in person_columns]

    expenses: list[Expense] = []
    for row_number, raw_row in enumerate(reader, start=2):
        # DictReader keeps the header's casing, and files a short row's missing
        # values as None. Normalise both, and drop the overflow column a
        # trailing comma produces (its key is None).
        row = {key.strip(): (value or "") for key, value in raw_row.items() if key}
        fields = {key.lower(): value.strip() for key, value in row.items()}

        description = fields.get("description", "")
        category = fields.get("category", "")
        cost = _safe_decimal(fields.get("cost", ""))

        if not description and cost == ZERO:
            continue
        if description.lower().startswith(SUMMARY_PREFIX):
            continue

        verdict = classify(description, category, "")
        expenses.append(Expense(
            id=EXPENSE_ID_BASE + row_number,
            description=description or "(no description)",
            cost=cost,
            currency=fields.get("currency", "").upper() or "THB",
            date=_parse_date(fields.get("date", "")),
            category=category,
            is_payment=_is_payment_row(description, category),
            shares=_build_shares(person_columns, id_map, row, cost),
            mode=verdict.mode,
            bucket=verdict.bucket,
            confidence=verdict.confidence,
            reason=verdict.reason,
        ))

    expenses.sort(key=lambda e: (e.date or date.min, e.id))
    log.info(
        "CSV import: %d expenses and %d people (%s) from %s",
        len(expenses), len(people), ", ".join(person_columns), path.name,
    )

    return TripData(
        group_id=None,
        group_name=_group_name_from(path),
        people=sorted(people, key=lambda p: p.name.lower()),
        expenses=expenses,
        source="csv",
        fetched_at=datetime.now(timezone.utc),
    )


def _group_name_from(path: Path) -> str:
    """Best guess at the group name, since the export does not carry one."""
    stem = re.sub(r"[_-]?export", "", path.stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)          # "Trip (1)" -> "Trip"
    stem = stem.replace("_", " ").replace("-", " ").strip()
    if not stem or stem.startswith("."):
        return "Splitwise import"
    return stem.title()
