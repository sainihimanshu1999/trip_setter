"""Tests for app/csv_import.py — Splitwise CSV export parser."""

from __future__ import annotations

import textwrap
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.csv_import import (
    _build_shares,
    _detect_person_columns,
    _group_name_from,
    _is_payment_row,
    _parse_date,
    _safe_decimal,
    load_csv,
)
from app.domain import TripData


# ----------------------------------------------------------------- fixtures


@pytest.fixture
def csv_dir(tmp_path: Path) -> Path:
    """Return a temp directory for CSV test files."""
    return tmp_path


def _write_csv(directory: Path, name: str, content: str) -> Path:
    """Write a CSV file and return its path."""
    path = directory / name
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return path


# ---------------------------------------------------- unit: _safe_decimal


class TestSafeDecimal:
    def test_normal(self):
        assert _safe_decimal("25.50") == Decimal("25.50")

    def test_negative(self):
        assert _safe_decimal("-12.00") == Decimal("-12.00")

    def test_comma_thousands(self):
        assert _safe_decimal("1,200.50") == Decimal("1200.50")

    def test_empty(self):
        assert _safe_decimal("") == Decimal("0")

    def test_whitespace(self):
        assert _safe_decimal("  ") == Decimal("0")

    def test_garbage(self):
        assert _safe_decimal("abc") == Decimal("0")


# ---------------------------------------------------- unit: _parse_date


class TestParseDate:
    def test_iso(self):
        assert _parse_date("2026-01-15") == date(2026, 1, 15)

    def test_iso_with_time(self):
        assert _parse_date("2026-01-15T09:00:00Z") == date(2026, 1, 15)

    def test_us_format(self):
        assert _parse_date("01/15/2026") == date(2026, 1, 15)

    def test_empty(self):
        assert _parse_date("") is None

    def test_garbage(self):
        assert _parse_date("not-a-date") is None

    def test_iso_no_tz(self):
        assert _parse_date("2026-01-15T09:00:00") == date(2026, 1, 15)


# ------------------------------------------------ unit: _detect_person_columns


class TestDetectPersonColumns:
    def test_typical_header(self):
        header = ["Date", "Description", "Category", "Cost", "Currency", "Alice", "Bob"]
        assert _detect_person_columns(header) == ["Alice", "Bob"]

    def test_case_insensitive_fixed(self):
        header = ["date", "description", "category", "cost", "currency", "Charlie"]
        assert _detect_person_columns(header) == ["Charlie"]

    def test_no_people(self):
        header = ["Date", "Description", "Category", "Cost", "Currency"]
        assert _detect_person_columns(header) == []


# ------------------------------------------------ unit: _is_payment_row


class TestIsPaymentRow:
    def test_settle_up(self):
        assert _is_payment_row("Settle up", "Payment") is True

    def test_payment_keyword(self):
        assert _is_payment_row("Payment", "General") is True

    def test_normal_expense(self):
        assert _is_payment_row("Dinner at Blue Elephant", "Food & Drink") is False


# ------------------------------------------------ unit: _guess_group_name


class TestGuessGroupName:
    def test_simple(self):
        assert _group_name_from(Path("data/Thailand_2026.csv")) == "Thailand 2026"

    def test_removes_export_suffix(self):
        assert _group_name_from(Path("my_trip_export.csv")) == "My Trip"

    def test_removes_duplicate_number(self):
        assert _group_name_from(Path("Trip (1).csv")) == "Trip"

    def test_empty_stem(self):
        assert _group_name_from(Path(".csv")) == "Splitwise import"


# ------------------------------------------------ integration: load_csv


class TestLoadCsv:
    def test_basic_trip(self, csv_dir: Path):
        """Parse a minimal 2-person, 3-expense CSV."""
        path = _write_csv(csv_dir, "basic.csv", """\
            Date,Description,Category,Cost,Currency,Himanshu Saini,Aarav Mehta
            2026-01-11,Pad Thai dinner,Food & Drink,600.00,THB,300.00,-300.00
            2026-01-12,Tuk tuk to temple,Transportation,200.00,THB,100.00,-100.00
            2026-01-13,Settle up,Payment,300.00,THB,-300.00,300.00
        """)

        trip = load_csv(path)
        assert isinstance(trip, TripData)
        assert trip.source == "csv"
        assert trip.warning is None
        assert len(trip.people) == 2
        assert len(trip.expenses) == 3

        # Check group name derived from filename
        assert trip.group_name == "Basic"

        # People
        names = {p.name for p in trip.people}
        assert names == {"Himanshu Saini", "Aarav Mehta"}

        # First expense — Pad Thai
        pad_thai = trip.expenses[0]
        assert pad_thai.description == "Pad Thai dinner"
        assert pad_thai.cost == Decimal("600.00")
        assert pad_thai.currency == "THB"
        assert pad_thai.date == date(2026, 1, 11)
        assert pad_thai.category == "Food & Drink"
        assert not pad_thai.is_payment

        # Shares: Himanshu paid 600, each owes 300
        h_share = next(s for s in pad_thai.shares if s.name == "Himanshu Saini")
        a_share = next(s for s in pad_thai.shares if s.name == "Aarav Mehta")
        assert h_share.paid == Decimal("600.00")
        assert h_share.owed == Decimal("300.00")
        assert a_share.paid == Decimal("0")
        assert a_share.owed == Decimal("300.00")

        # Settlement row
        settle = trip.expenses[2]
        assert settle.is_payment is True

    def test_three_way_split(self, csv_dir: Path):
        """One payer, two debtors, unequal split."""
        path = _write_csv(csv_dir, "three.csv", """\
            Date,Description,Category,Cost,Currency,Alice,Bob,Charlie
            2026-02-01,Hotel,Accommodation,3000.00,THB,2000.00,-500.00,-1500.00
        """)

        trip = load_csv(path)
        assert len(trip.people) == 3
        assert len(trip.expenses) == 1

        exp = trip.expenses[0]
        assert exp.cost == Decimal("3000.00")

        alice = next(s for s in exp.shares if s.name == "Alice")
        bob = next(s for s in exp.shares if s.name == "Bob")
        charlie = next(s for s in exp.shares if s.name == "Charlie")

        # Alice paid, net is +2000, so she paid 3000 and owes 1000
        assert alice.paid == Decimal("3000.00")
        assert alice.owed == Decimal("1000.00")
        # Bob owes 500
        assert bob.paid == Decimal("0")
        assert bob.owed == Decimal("500.00")
        # Charlie owes 1500
        assert charlie.paid == Decimal("0")
        assert charlie.owed == Decimal("1500.00")

    def test_multiple_currencies(self, csv_dir: Path):
        """Expenses in different currencies."""
        path = _write_csv(csv_dir, "multi.csv", """\
            Date,Description,Category,Cost,Currency,A,B
            2026-01-10,Flight,Transportation,71600.00,INR,35800.00,-35800.00
            2026-01-12,Dinner,Food & Drink,800.00,THB,400.00,-400.00
        """)

        trip = load_csv(path)
        assert trip.expenses[0].currency == "INR"
        assert trip.expenses[1].currency == "THB"

    def test_sorted_by_date(self, csv_dir: Path):
        """Expenses come back sorted by date regardless of CSV order."""
        path = _write_csv(csv_dir, "unsorted.csv", """\
            Date,Description,Category,Cost,Currency,A,B
            2026-01-15,Later,General,100.00,THB,50.00,-50.00
            2026-01-10,Earlier,General,200.00,THB,100.00,-100.00
        """)

        trip = load_csv(path)
        assert trip.expenses[0].description == "Earlier"
        assert trip.expenses[1].description == "Later"

    def test_blank_rows_skipped(self, csv_dir: Path):
        """Empty rows are ignored."""
        path = _write_csv(csv_dir, "blanks.csv", """\
            Date,Description,Category,Cost,Currency,A,B
            2026-01-10,Real expense,General,100.00,THB,50.00,-50.00
            ,,,,,,
            2026-01-11,Another one,General,200.00,THB,100.00,-100.00
        """)

        trip = load_csv(path)
        assert len(trip.expenses) == 2

    def test_classification_runs(self, csv_dir: Path):
        """Expenses get classified (mode/bucket) just like API ones."""
        path = _write_csv(csv_dir, "classified.csv", """\
            Date,Description,Category,Cost,Currency,A,B
            2026-01-12,Grab to airport,Taxi,500.00,THB,250.00,-250.00
        """)

        trip = load_csv(path)
        exp = trip.expenses[0]
        # The classifier should pick up "Grab" and "Taxi"
        assert exp.mode.value != "none" or exp.bucket.value != "misc"

    def test_person_ids_stable(self, csv_dir: Path):
        """Each person gets a consistent synthetic ID."""
        path = _write_csv(csv_dir, "ids.csv", """\
            Date,Description,Category,Cost,Currency,Zara,Yuki
            2026-01-10,Test,General,100.00,THB,50.00,-50.00
        """)

        trip = load_csv(path)
        ids = {p.name: p.id for p in trip.people}
        # Consistent with assignment order in the CSV header
        assert ids["Zara"] == 1001
        assert ids["Yuki"] == 1002

    def test_initials(self, csv_dir: Path):
        """Initials come from the first and last name, as they do for API users."""
        path = _write_csv(csv_dir, "initials.csv", """\
            Date,Description,Category,Cost,Currency,Himanshu Saini,Aarav
            2026-01-10,Test,General,100.00,THB,50.00,-50.00
        """)

        trip = load_csv(path)
        by_name = {p.name: p for p in trip.people}
        assert by_name["Himanshu Saini"].initials == "HS"
        assert by_name["Aarav"].initials == "A"


# ------------------------------------------------ error cases


class TestLoadCsvErrors:
    def test_file_not_found(self, csv_dir: Path):
        with pytest.raises(FileNotFoundError):
            load_csv(csv_dir / "nonexistent.csv")

    def test_empty_file(self, csv_dir: Path):
        path = csv_dir / "empty.csv"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty or has no header"):
            load_csv(path)

    def test_missing_columns(self, csv_dir: Path):
        path = _write_csv(csv_dir, "missing.csv", """\
            Date,Description,Category
            2026-01-10,Test,General
        """)
        with pytest.raises(ValueError, match="missing required columns"):
            load_csv(path)

    def test_no_person_columns(self, csv_dir: Path):
        path = _write_csv(csv_dir, "nopeople.csv", """\
            Date,Description,Category,Cost,Currency
            2026-01-10,Test,General,100.00,THB
        """)
        with pytest.raises(ValueError, match="no person columns"):
            load_csv(path)

    def test_bom_handled(self, csv_dir: Path):
        """UTF-8 BOM from Excel exports is stripped."""
        path = csv_dir / "bom.csv"
        content = "Date,Description,Category,Cost,Currency,Alice\n2026-01-10,Test,General,100.00,THB,100.00\n"
        # Write with BOM encoding (Excel does this on Windows)
        path.write_text(content, encoding="utf-8-sig")

        trip = load_csv(path)
        assert len(trip.expenses) == 1
        assert trip.people[0].name == "Alice"


# ------------------------------------------ shares reconstruction


class TestBuildShares:
    """Focused tests for the share-reconstruction logic."""

    def test_equal_two_way(self, csv_dir: Path):
        """50/50 split: payer has +50, other has -50, cost is 100."""
        path = _write_csv(csv_dir, "equal.csv", """\
            Date,Description,Category,Cost,Currency,Payer,Freeloader
            2026-01-10,Test,General,100.00,THB,50.00,-50.00
        """)
        trip = load_csv(path)
        shares = {s.name: s for s in trip.expenses[0].shares}

        # Payer: paid 100, owes 50
        assert shares["Payer"].paid == Decimal("100.00")
        assert shares["Payer"].owed == Decimal("50.00")
        assert shares["Payer"].net == Decimal("50.00")

        # Freeloader: paid 0, owes 50
        assert shares["Freeloader"].paid == Decimal("0")
        assert shares["Freeloader"].owed == Decimal("50.00")
        assert shares["Freeloader"].net == Decimal("-50.00")

    def test_net_sums_to_zero(self, csv_dir: Path):
        """Net balances across all shares sum to zero for each expense."""
        path = _write_csv(csv_dir, "netcheck.csv", """\
            Date,Description,Category,Cost,Currency,A,B,C,D
            2026-01-10,Big dinner,Food,4000.00,THB,3000.00,-500.00,-1000.00,-1500.00
            2026-01-11,Tickets,Entertainment,1200.00,THB,400.00,400.00,-400.00,-400.00
        """)
        trip = load_csv(path)
        for exp in trip.expenses:
            total_net = sum(s.net for s in exp.shares)
            assert abs(total_net) < Decimal("0.05"), f"Net imbalance in {exp.description}: {total_net}"

    def test_a_person_with_zero_net_is_not_in_the_expense(self, csv_dir: Path):
        """Zero net means uninvolved, so they are neither charged nor credited.

        Splitting the cost with them anyway would invent money the Cost column
        does not account for, and would credit someone who was not there.
        """
        path = _write_csv(csv_dir, "uninvolved.csv", """\
            Date,Description,Category,Cost,Currency,Payer,Rider,Absent
            2026-01-10,Two-seat flight,Plane,2000.00,THB,1000.00,-1000.00,0.00
        """)
        trip = load_csv(path)
        shares = {s.name: s for s in trip.expenses[0].shares}

        assert shares["Absent"].paid == Decimal("0")
        assert shares["Absent"].owed == Decimal("0")
        assert shares["Payer"].paid == Decimal("2000.00")
        assert shares["Payer"].owed == Decimal("1000.00")
        assert shares["Rider"].owed == Decimal("1000.00")

    def test_paid_and_owed_each_sum_to_the_cost(self, csv_dir: Path):
        """The reconstruction must not create or destroy money."""
        path = _write_csv(csv_dir, "conserved.csv", """\
            Date,Description,Category,Cost,Currency,A,B,C,D,E
            2026-01-10,Group flight,Plane,94496.00,INR,-18899.20,0.00,75596.80,-18899.20,-37798.40
            2026-01-11,Two payers,General,1000.00,THB,300.00,200.00,-200.00,-150.00,-150.00
        """)
        trip = load_csv(path)
        for exp in trip.expenses:
            assert abs(sum(s.paid for s in exp.shares) - exp.cost) < Decimal("0.05"), (
                f"paid does not sum to cost for {exp.description}"
            )
            assert abs(sum(s.owed for s in exp.shares) - exp.cost) < Decimal("0.05"), (
                f"owed does not sum to cost for {exp.description}"
            )


class TestSummaryRow:
    def test_trailing_total_balance_row_is_skipped(self, csv_dir: Path):
        """Splitwise appends a balances row that is not an expense."""
        path = _write_csv(csv_dir, "summary.csv", """\
            Date,Description,Category,Cost,Currency,A,B
            2026-01-10,Dinner,Food,500.00,THB,250.00,-250.00

            2026-01-27,Total balance, , ,THB,250.00,-250.00
        """)
        trip = load_csv(path)
        assert [e.description for e in trip.expenses] == ["Dinner"]
