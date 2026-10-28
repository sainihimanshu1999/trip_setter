"""Analytics tests: money must add up, and settlements must actually settle."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.analytics import (
    buckets_payload,
    modes_payload,
    overview_payload,
    settle,
    timeline_payload,
)
from app.classify import Mode
from app.fx import FxConverter

CENT = Decimal("0.02")


# ----------------------------------------------------------------- totals


def test_paid_equals_owed_across_the_group(analytics):
    """Every rupee someone paid is a rupee someone else owed."""
    paid = sum(p.paid for p in analytics.people)
    owed = sum(p.owed for p in analytics.people)
    assert abs(paid - owed) < CENT, f"drift of {paid - owed}"


def test_total_spend_equals_sum_of_payments(analytics):
    paid = sum(p.paid for p in analytics.people)
    assert abs(paid - analytics.total_spend) < CENT


def test_bucket_totals_reconcile(analytics):
    total = sum(analytics.by_bucket.values())
    assert abs(total - analytics.total_spend) < CENT


def test_mode_totals_reconcile(analytics):
    total = sum(analytics.by_mode.values())
    assert abs(total - analytics.total_spend) < CENT


def test_daily_totals_reconcile(analytics):
    total = sum(analytics.by_day.values())
    assert abs(total - analytics.total_spend) < CENT


def test_per_head_is_total_over_head_count(analytics):
    expected = analytics.total_spend / analytics.head_count
    assert abs(analytics.per_head - expected) < Decimal("1")


def test_settle_ups_are_not_counted_as_spending(analytics, trip):
    """A payment moves money; it is not a trip cost."""
    payments = [e for e in trip.expenses if e.is_payment]
    assert payments, "demo data should contain settle-ups to exercise this"
    assert analytics.total_settled > 0
    for person in analytics.people:
        # Spending view ignores settle-ups entirely.
        assert person.settled_in >= 0
        assert person.settled_out >= 0


def test_net_and_balance_differ_when_settle_ups_exist(analytics):
    """`net` is spending only; `balance` includes money already repaid."""
    movers = [p for p in analytics.people if p.settled_in or p.settled_out]
    assert movers, "demo data should have someone who settled up"
    assert any(p.net != p.balance for p in movers)


def test_balances_sum_to_zero(analytics):
    assert abs(sum(p.balance for p in analytics.people)) < Decimal("0.1")


def test_prebooked_is_spending_before_the_window(analytics, settings):
    assert analytics.prebooked > 0
    early = sum(
        e.home_cost for e in analytics.trip.expenses
        if e.date and e.date < settings.trip_start and not e.is_payment
    )
    assert abs(analytics.prebooked - early) < CENT


# ------------------------------------------------------------ settlements


def test_settlements_clear_every_balance(analytics):
    """Applying the suggested transfers must leave everyone at zero."""
    balances = {p.person.id: p.balance for p in analytics.people}
    for transfer in analytics.settlements:
        balances[transfer.from_id] += transfer.amount
        balances[transfer.to_id] -= transfer.amount
    for who, remaining in balances.items():
        assert abs(remaining) < Decimal("1"), f"{who} left with {remaining}"


def test_settlements_use_at_most_n_minus_one_transfers(analytics):
    """Greedy matching should never need more than this."""
    assert len(analytics.settlements) <= max(0, len(analytics.people) - 1)


def test_settlements_are_all_positive(analytics):
    assert all(t.amount > 0 for t in analytics.settlements)
    assert all(t.from_id != t.to_id for t in analytics.settlements)


def test_settle_handles_already_square():
    nets = {1: Decimal("0"), 2: Decimal("0")}
    assert settle(nets, {1: "A", 2: "B"}) == []


def test_settle_ignores_rounding_dust():
    nets = {1: Decimal("0.01"), 2: Decimal("-0.01")}
    assert settle(nets, {1: "A", 2: "B"}) == []


def test_settle_simple_two_person_case():
    nets = {1: Decimal("500"), 2: Decimal("-500")}
    result = settle(nets, {1: "Ana", 2: "Ben"})
    assert len(result) == 1
    assert result[0].from_name == "Ben"
    assert result[0].to_name == "Ana"
    assert result[0].amount == Decimal("500.00")


def test_settle_splits_one_creditor_across_debtors():
    nets = {1: Decimal("900"), 2: Decimal("-400"), 3: Decimal("-500")}
    result = settle(nets, {1: "Ana", 2: "Ben", 3: "Cat"})
    assert len(result) == 2
    assert sum(t.amount for t in result) == Decimal("900.00")
    assert all(t.to_id == 1 for t in result)


# ---------------------------------------------------------------- payloads


def test_overview_payload_shape(analytics):
    payload = overview_payload(analytics)
    for key in (
        "currency", "total_spend", "per_head", "head_count", "expense_count",
        "transport_spend", "prebooked", "biggest_day", "people", "settlements", "fx",
    ):
        assert key in payload, f"missing {key}"
    assert payload["currency"] == "INR"
    assert len(payload["people"]) == 4
    assert all(0.0 <= p["bar_ratio"] <= 1.0 for p in payload["people"])


def test_biggest_day_is_inside_the_trip_window(analytics, settings):
    """A flight bought in December must not win 'biggest day'."""
    day, amount = analytics.biggest_day
    assert day is not None
    assert settings.trip_start <= day <= settings.trip_end
    assert amount > 0


def test_bucket_shares_sum_to_one(analytics):
    payload = buckets_payload(analytics)
    assert abs(sum(b["share"] for b in payload["buckets"]) - 1.0) < 0.01


def test_modes_payload_excludes_non_transport(analytics):
    payload = modes_payload(analytics)
    assert payload["modes"]
    assert all(m["key"] != str(Mode.NONE) for m in payload["modes"])
    assert all(m["count"] > 0 for m in payload["modes"])


def test_timeline_is_bounded_and_gap_filled(analytics, settings):
    payload = timeline_payload(analytics)
    days = payload["days"]
    assert days
    assert payload["window"][0] == settings.trip_start.isoformat()
    # Contiguous: 12 days inclusive from 10 to 21 January.
    assert len(days) == 12
    dates = [d["date"] for d in days]
    assert dates == sorted(dates)
    assert payload["prebooked"] > 0
    assert payload["max"] == max(d["amount"] for d in days)


# ---------------------------------------------------------------------- fx


def test_fx_converts_thb_to_inr(settings):
    fx = FxConverter(settings)
    assert fx.home == "INR"
    assert fx.convert(Decimal("100"), "INR") == Decimal("100")
    converted = fx.convert(Decimal("100"), "THB")
    assert converted > Decimal("100")  # THB is worth more than a rupee


def test_fx_unknown_currency_passes_through(settings):
    fx = FxConverter(settings)
    assert fx.convert(Decimal("50"), "XYZ") == Decimal("50")


def test_fx_full_precision_avoids_drift(settings):
    """Converting 1000 small shares must not drift from one big conversion."""
    fx = FxConverter(settings)
    one = fx.convert(Decimal("1000"), "THB")
    many = sum(fx.convert(Decimal("1"), "THB") for _ in range(1000))
    assert abs(one - many) < Decimal("0.01")


@pytest.mark.parametrize("currency", ["THB", "INR", "USD", "EUR"])
def test_fx_knows_the_trip_currencies(settings, currency):
    fx = FxConverter(settings)
    assert currency in fx.rates
    assert fx.rates[currency] > 0
