"""Import expenses from a Splitwise CSV export.

Splitwise lets you export any group or friendship as a spreadsheet from the web
UI, which needs neither an API key nor a Pro subscription:

    Group page -> settings gear -> "Export as spreadsheet"

The file has five fixed fields followed by one column per group member:

    Date, Description, Category, Cost, Currency, <Person 1>, <Person 2>, ...

Nothing below depends on where a column *sits*. The header is read once into a
:class:`ColumnMap` -- a dictionary from canonical field name to the spelling
this particular file uses -- and every row is then addressed through that map.
That matters because an export is not a fixed document: it grows every time an
expense is added, and Splitwise does not promise a stable column order between
exports. The two exports of this trip in `data/` list their six members in
different orders.

Each person column holds that person's **net** impact for the row: positive
means they are owed money, negative means they owe it. The API reports `paid`
and `owed` separately, so :func:`_build_shares` reconstructs them.

Identities are derived from content rather than file position, so the same
person and the same expense keep the same id as the file grows:

* a person's id is a hash of their name, not their column index
* an expense's id is a hash of its date, description, cost and currency

Every import also produces an :class:`IngestReport` recording what the header
was understood to mean, which rows were skipped and why, and which rows look
internally inconsistent. A total that looks wrong can then be explained from
the report instead of guessed at.

The result is a :class:`TripData` identical in shape to what the API client
returns, so analytics, FX, classification and the journey map are unchanged.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .classify import classify
from .domain import ZERO, Expense, Person, Share, TripData

log = logging.getLogger("trip.csv_import")

CENTS = Decimal("0.01")

#: Canonical field -> the header spellings accepted for it, as produced by
#: :func:`_norm`. Splitwise's own export uses the first spelling in each tuple;
#: the rest cover hand-edited files and other exporters.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "expense date", "transaction date", "day"),
    "description": ("description", "desc", "item", "name", "expense", "title"),
    "category": ("category", "expense category", "type"),
    "cost": ("cost", "amount", "total", "total cost", "price", "value"),
    "currency": ("currency", "currency code", "ccy", "curr"),
}

#: Fields a row cannot be read without.
REQUIRED_FIELDS: tuple[str, ...] = tuple(COLUMN_ALIASES)

#: Headers that are neither a known field nor a group member. Without this
#: list, any column Splitwise adds later would be read as a person whose "net"
#: is whatever that column happens to hold, inventing a member and corrupting
#: every share on every row.
NON_PERSON_HEADERS: frozenset[str] = frozenset({
    "",
    "balance", "total balance", "running balance",
    "comment", "comments", "memo", "note", "notes", "details",
    "created at", "created by", "updated at", "updated by",
    "deleted", "deleted at", "is deleted",
    "expense id", "id", "group", "group id", "group name",
    "image", "receipt", "receipt url",
    "is payment", "payment", "owed", "paid",
    "repeat", "repeats", "repeat interval",
    "unnamed", "column",
})

#: Description Splitwise uses for its trailing summary row, after normalising.
SUMMARY_PREFIX = "total balance"

#: Words that mark a row as a settle-up rather than group spending. These
#: mirror the API's `payment` flag, which the export does not include.
PAYMENT_KEYWORDS = ("payment", "settle up", "settled up", "settle all", "repayment")

#: Spans the synthetic ids live in. The export carries none, so people and
#: expenses get content-derived ids inside these ranges. The spans are wide
#: enough that a collision is remote, and :func:`_allocate` probes
#: deterministically if one happens anyway.
PERSON_ID_BASE = 1_000_000
PERSON_ID_SPAN = 8_999_999
EXPENSE_ID_BASE = 500_000_000
EXPENSE_ID_SPAN = 8_999_999_999

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %B %Y",
)

_PUNCT = re.compile(r"[^\w\s/]+", re.UNICODE)
_SEPARATORS = re.compile(r"[_\-.]+")


# ------------------------------------------------------------------ parsing


def _norm(text: str | None) -> str:
    """Fold a header or label to a comparable key.

    Lowercases, drops a byte order mark, turns separators into spaces, strips
    punctuation and collapses whitespace, so "Currency_Code", "currency code"
    and " Currency Code " all land on the same key.
    """
    if not text:
        return ""
    cleaned = text.replace("\ufeff", "").strip().strip("\"'")
    cleaned = _SEPARATORS.sub(" ", cleaned)
    cleaned = _PUNCT.sub(" ", cleaned)
    return " ".join(cleaned.lower().split())


def _safe_decimal(value: str) -> Decimal:
    """Parse a money cell, tolerating blanks, separators and junk.

    Grouping is ambiguous across locales and the export does not say which one
    it used, so the separator nearest the end decides. "1,200.50" and
    "1.200,50" both read as 1200.50, and a bare "18899,20" is read as a decimal
    comma rather than a thousands separator -- taking it as grouping would
    yield 1889920 and inflate the row a hundredfold with nothing looking wrong
    downstream.

    A comma-only value is grouped if its last group is three digits, which
    covers Western "12,345,678" and Indian "1,23,456" alike. Home currency
    here is INR, so lakh grouping is the likelier of the two.
    """
    cleaned = (value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not cleaned:
        return ZERO

    has_comma, has_dot = "," in cleaned, "." in cleaned
    if has_comma and has_dot:
        # Whichever appears last is the decimal separator.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif has_comma:
        head, _, tail = cleaned.rpartition(",")
        if len(tail) == 3:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = f"{head.replace(',', '')}.{tail}"

    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        log.warning("Cannot parse amount %r, treating as zero", value)
        return ZERO

    if not parsed.is_finite():
        # Decimal accepts "NaN", "Infinity" and "sNaN" as literals. Either one
        # would spread through every total silently -- NaN compares False
        # against everything, so no threshold check catches it -- and then
        # serialise as a bare NaN token that breaks JSON.parse in the browser.
        log.warning("Non-finite amount %r, treating as zero", value)
        return ZERO
    return parsed


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


def _is_payment_row(description: str, category: str) -> bool:
    """Is this row a settle-up rather than group spending?"""
    haystack = f"{description} {category}".lower()
    return any(word in haystack for word in PAYMENT_KEYWORDS)


# ------------------------------------------------------------ column mapping


#: Reverse index of COLUMN_ALIASES, built once: spelling -> canonical field.
_ALIAS_INDEX: dict[str, str] = {
    alias: canonical
    for canonical, aliases in COLUMN_ALIASES.items()
    for alias in aliases
}


@dataclass(frozen=True, slots=True)
class ColumnMap:
    """What one file's header means, learned once and reused for every row.

    `fields` maps a canonical field name to the header spelling this file uses,
    so row access never depends on column position.
    """

    fields: dict[str, str]
    people: tuple[str, ...]
    ignored: tuple[str, ...]
    header: tuple[str, ...]

    def get(self, row: dict[str, str], canonical: str) -> str:
        """Read one canonical field out of a row."""
        column = self.fields.get(canonical)
        if column is None:
            return ""
        return (row.get(column) or "").strip()

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(f for f in REQUIRED_FIELDS if f not in self.fields)

    def as_json(self) -> dict:
        return {
            "fields": dict(self.fields),
            "people": list(self.people),
            "ignored": list(self.ignored),
            "header": list(self.header),
        }


def learn_columns(header: list[str]) -> ColumnMap:
    """Read a header row into a field dictionary plus the person columns.

    Each column is resolved in this order:

    1. an exact match against :data:`COLUMN_ALIASES` -> that canonical field
    2. a known non-person header -> ignored
    3. anything else -> a group member

    A canonical field already claimed by an earlier column is not claimed
    twice, so a stray second "Cost" column is ignored rather than silently
    overriding the real one.

    Does not raise: a header with no people or a missing field still produces
    a map, and :func:`load_csv` decides whether that is fatal. That keeps this
    usable for inspecting a header on its own.
    """
    fields: dict[str, str] = {}
    people: list[str] = []
    ignored: list[str] = []

    for raw in header:
        column = (raw or "").strip()
        key = _norm(column)
        canonical = _ALIAS_INDEX.get(key)

        if canonical and canonical not in fields:
            fields[canonical] = column
        elif canonical or key in NON_PERSON_HEADERS:
            ignored.append(column)
        else:
            people.append(column)

    return ColumnMap(
        fields=fields,
        people=tuple(people),
        ignored=tuple(ignored),
        header=tuple((h or "").strip() for h in header),
    )


def _detect_person_columns(header: list[str]) -> list[str]:
    """Person columns, in the order the export lists them."""
    return list(learn_columns(header).people)


# --------------------------------------------------------------- identities


def _digest(text: str, base: int, span: int) -> int:
    return base + int.from_bytes(
        hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big"
    ) % span


def _allocate(text: str, taken: set[int], base: int, span: int) -> int:
    """Content-derived id, probed forward until free.

    Probing keeps the result deterministic for a given set of inputs: the same
    file always yields the same ids, and a hash collision displaces only the
    later of the two colliding entries.
    """
    candidate = _digest(text, base, span)
    while candidate in taken:
        candidate = base + ((candidate - base) + 1) % span
    taken.add(candidate)
    return candidate


def _assign_ids(names: list[str] | tuple[str, ...]) -> dict[str, int]:
    """Map each person column to a stable id derived from the name.

    Derived from the name and not the column index, because Splitwise does not
    guarantee column order across exports -- the 2026-11-14 export of this trip
    lists its members in a different order to the 2026-10-27 one. A positional
    id silently reassigns everyone's identity on re-export, so a person's
    history would follow whoever later occupied their column.

    Allocation walks the names in sorted order, so the result depends only on
    the set of names present and not on where they sit in the header.
    """
    taken: set[int] = set()
    ids: dict[str, int] = {}
    for name in sorted({n for n in names}, key=_norm):
        ids[name] = _allocate(_norm(name), taken, PERSON_ID_BASE, PERSON_ID_SPAN)
    return {name: ids[name] for name in names}


def _fingerprint(when: date | None, description: str, cost: Decimal,
                 currency: str) -> str:
    """Content key for one expense, stable as the file grows.

    Deliberately excludes the row number. This export gained three rows between
    2026-10-27 and 2026-11-14 and will keep gaining more, and a row is not
    promised to keep its position. Keying on content means an expense holds its
    id across exports, so anything pointing at an id keeps pointing at the same
    expense.
    """
    return "|".join((
        when.isoformat() if when else "-",
        _norm(description),
        str(cost.quantize(CENTS)),
        currency.upper(),
    ))


# ------------------------------------------------------------------- report


@dataclass(slots=True)
class IngestReport:
    """What one import actually did, so a surprising total can be explained."""

    source: str = ""
    columns: ColumnMap | None = None
    rows_read: int = 0
    rows_imported: int = 0
    payments: int = 0
    skipped: list[dict] = field(default_factory=list)
    anomalies: list[dict] = field(default_factory=list)
    currencies: dict[str, int] = field(default_factory=dict)

    def skip(self, row: int, reason: str, description: str = "") -> None:
        self.skipped.append({"row": row, "reason": reason, "description": description})

    def flag(self, row: int, issue: str, detail: str) -> None:
        self.anomalies.append({"row": row, "issue": issue, "detail": detail})
        log.warning("Row %d: %s (%s)", row, issue, detail)

    @property
    def spend_rows(self) -> int:
        return self.rows_imported - self.payments

    def as_json(self) -> dict:
        return {
            "source": self.source,
            "columns": self.columns.as_json() if self.columns else None,
            "rows_read": self.rows_read,
            "rows_imported": self.rows_imported,
            "spend_rows": self.spend_rows,
            "payments": self.payments,
            "skipped": list(self.skipped),
            "anomalies": list(self.anomalies),
            "currencies": dict(self.currencies),
        }


# -------------------------------------------------------------------- shares


def _build_shares(
    columns: ColumnMap,
    id_map: dict[str, int],
    row: dict[str, str],
    cost: Decimal,
    report: IngestReport | None = None,
    row_number: int = 0,
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

    When a row's nets sum to zero and at least one person fronted money, this
    keeps both `sum(paid) == cost` and `sum(owed) == cost`. Rows that break
    either precondition are reconstructed as best they can be and recorded on
    the report rather than silently producing nonsense.
    """
    nets: dict[int, Decimal] = {}
    names: dict[int, str] = {}
    for column in columns.people:
        user_id = id_map[column]
        nets[user_id] = nets.get(user_id, ZERO) + _safe_decimal(row.get(column, ""))
        names.setdefault(user_id, column)

    owed_by_debtors = sum((-net for net in nets.values() if net < ZERO), ZERO)
    fronted = sum((net for net in nets.values() if net > ZERO), ZERO)
    owed_by_payers = cost - owed_by_debtors

    if owed_by_payers < ZERO:
        # The debtor columns already account for more than Cost, so the row is
        # internally inconsistent: a hand-edited file, a truncated export, or a
        # Cost recorded in a different currency to the splits. Charging the
        # payer a negative share would credit them money nobody spent and push
        # a negative amount into the category totals, so clamp and record it.
        if report is not None:
            report.flag(
                row_number, "cost_below_splits",
                f"debtor shares total {owed_by_debtors} but Cost is {cost}",
            )
        owed_by_payers = ZERO

    if fronted == ZERO and cost != ZERO and report is not None:
        # No column has a positive net, so no share carries this row's cost.
        # The row still counts towards trip spend, so per-person totals will
        # not add up to the trip total and that needs to be visible.
        report.flag(
            row_number, "no_payer",
            f"no column has a positive net, so {cost} is unattributed",
        )

    shares: list[Share] = []
    for user_id, net in nets.items():
        name = names[user_id]
        if net < ZERO:
            shares.append(Share(user_id=user_id, name=name, paid=ZERO, owed=-net))
        elif net > ZERO:
            # fronted > 0 whenever any net > 0, so this cannot divide by zero.
            owed = (owed_by_payers * net / fronted).quantize(CENTS)
            shares.append(Share(user_id=user_id, name=name, paid=net + owed, owed=owed))
        else:
            shares.append(Share(user_id=user_id, name=name, paid=ZERO, owed=ZERO))
    return shares


# --------------------------------------------------------------------- load


def load_csv(path: Path | str, default_currency: str = "THB") -> TripData:
    """Read a Splitwise CSV export.

    `default_currency` is used only for rows whose Currency cell is blank; each
    such row is recorded on the report, because guessing wrong here scales the
    row by the whole FX rate.

    Raises `FileNotFoundError` if the file is missing, and `ValueError` if it
    has no header, is missing a required field, or names no people.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    # utf-8-sig drops the byte order mark Excel writes on Windows.
    reader = csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines())
    if reader.fieldnames is None:
        raise ValueError(f"CSV file is empty or has no header: {path}")

    columns = learn_columns(list(reader.fieldnames))
    if columns.missing:
        raise ValueError(
            f"CSV is missing required columns: {', '.join(columns.missing)}. "
            f"Found: {', '.join(columns.header)}"
        )
    if not columns.people:
        raise ValueError(
            "CSV has no person columns after "
            f"{'/'.join(c.title() for c in REQUIRED_FIELDS)}. "
            "A Splitwise export has one column per group member."
        )

    report = IngestReport(source=path.name, columns=columns)
    fallback = (default_currency or "THB").upper()

    id_map = _assign_ids(columns.people)
    people = [Person.from_name(id_map[name], name) for name in columns.people]

    expense_ids: set[int] = set()
    occurrences: dict[str, int] = {}
    expenses: list[Expense] = []

    for row_number, raw_row in enumerate(reader, start=2):
        # DictReader keeps the header's casing, and files a short row's missing
        # values as None. Normalise both, and drop the overflow column a
        # trailing comma produces (its key is None).
        row = {key.strip(): (value or "") for key, value in raw_row.items() if key}
        report.rows_read += 1

        description = columns.get(row, "description")
        category = columns.get(row, "category")
        cost = _safe_decimal(columns.get(row, "cost"))

        if not description and cost == ZERO:
            report.skip(row_number, "blank row")
            continue
        if _norm(description).startswith(SUMMARY_PREFIX):
            report.skip(row_number, "summary row", description)
            continue

        date_cell = columns.get(row, "date")
        when = _parse_date(date_cell)
        if date_cell and when is None:
            report.flag(row_number, "unparsed_date", date_cell)

        currency = columns.get(row, "currency").upper()
        if not currency:
            currency = fallback
            report.flag(row_number, "missing_currency", f"defaulted to {fallback}")
        report.currencies[currency] = report.currencies.get(currency, 0) + 1

        fingerprint = _fingerprint(when, description, cost, currency)
        seen = occurrences.get(fingerprint, 0)
        occurrences[fingerprint] = seen + 1

        is_payment = _is_payment_row(description, category)
        verdict = classify(description, category, "")

        expenses.append(Expense(
            id=_allocate(
                f"{fingerprint}#{seen}", expense_ids, EXPENSE_ID_BASE, EXPENSE_ID_SPAN
            ),
            description=description or "(no description)",
            cost=cost,
            currency=currency,
            date=when,
            category=category,
            is_payment=is_payment,
            shares=_build_shares(columns, id_map, row, cost, report, row_number),
            mode=verdict.mode,
            bucket=verdict.bucket,
            confidence=verdict.confidence,
            reason=verdict.reason,
        ))
        report.rows_imported += 1
        report.payments += int(is_payment)

    # Stable sort, so rows sharing a date keep the order the file listed them.
    expenses.sort(key=lambda e: e.date or date.min)

    log.info(
        "CSV import: %d/%d rows from %s - %d expenses, %d settle-ups, "
        "%d people (%s)%s",
        report.rows_imported, report.rows_read, path.name,
        report.spend_rows, report.payments, len(people), ", ".join(columns.people),
        f", ignored columns: {', '.join(columns.ignored)}" if columns.ignored else "",
    )

    return TripData(
        group_id=None,
        group_name=_group_name_from(path),
        people=sorted(people, key=lambda p: p.name.lower()),
        expenses=expenses,
        source="csv",
        fetched_at=datetime.now(timezone.utc),
        ingest=report,
    )


def _group_name_from(path: Path) -> str:
    """Best guess at the group name, since the export does not carry one."""
    stem = re.sub(r"[_-]?export", "", path.stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)          # "Trip (1)" -> "Trip"
    # Splitwise names an export after the day it was made; the date is noise.
    stem = re.sub(r"[_-]?\d{4}-\d{2}-\d{2}", "", stem)
    stem = stem.replace("_", " ").replace("-", " ").strip()
    if not stem or stem.startswith("."):
        return "Splitwise import"
    return stem.title()
