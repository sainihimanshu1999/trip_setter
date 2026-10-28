"""Classifier tests.

The cases that earned their own test are the ones that were wrong first time:
a cab ride to an airport, a boat ticket to a pier, a food expense that happens
to mention a train, and a tour whose notes mention a pickup.
"""

from __future__ import annotations

import pytest

from app.classify import Bucket, Mode, classify


@pytest.mark.parametrize(
    ("description", "category", "expected"),
    [
        # --- unambiguous vehicles ------------------------------------------
        ("AirAsia FD3435 BKK-CNX", "Plane", Mode.PLANE),
        ("IndiGo flights Delhi to Bangkok", "Plane", Mode.PLANE),
        ("Overnight sleeper train CNX to Bangkok", "Bus/train", Mode.TRAIN),
        ("BTS Rabbit cards top up", None, Mode.TRAIN),
        ("Airport Rail Link to Phaya Thai", "Bus/train", Mode.TRAIN),
        ("Ferry Ao Nang pier to Phi Phi", "Transportation", Mode.FERRY),
        ("Longtail boat 4 islands tour", None, Mode.FERRY),
        ("Songthaew to Old City", "Transportation", Mode.BUS),
        ("Tuk tuk to Wat Pho", None, Mode.CAB),
        ("Grab to hotel", "Taxi", Mode.CAB),
        ("Scooter rental x2 for Doi Suthep", "Bicycle", Mode.BIKE),
        # --- a vehicle word must beat a destination word -------------------
        ("Grab to DMK airport", "Transportation", Mode.CAB),
        ("Airport taxi to Ao Nang", "Taxi", Mode.CAB),
        ("Taxi from Hua Lamphong station", None, Mode.CAB),
        ("Taxi Rassada pier to Patong", "Taxi", Mode.CAB),
        # --- non-transport spending draws no line --------------------------
        ("Pad thai dinner", "Dining out", Mode.NONE),
        ("Patong hotel last night", "Hotel", Mode.NONE),
        ("Thai massage x4", None, Mode.NONE),
        ("Petrol for scooters", "Gas/fuel", Mode.NONE),
        ("Dinner packed for the train", "Groceries", Mode.NONE),
        ("Airport lunch before HKT-DEL", "Dining out", Mode.NONE),
    ],
)
def test_transport_mode(description, category, expected):
    assert classify(description, category).mode == expected


@pytest.mark.parametrize(
    ("description", "category", "expected"),
    [
        ("Riverside Bangkok 3 nights", "Hotel", Bucket.STAY),
        ("Old City guesthouse", None, Bucket.STAY),
        ("Khao soi dinner", "Dining out", Bucket.FOOD),
        ("7-Eleven snacks and water", "Groceries", Bucket.FOOD),
        ("Chang beers at Zoe in Yellow", "Liquor", Bucket.FOOD),
        ("Elephant Nature Park full day tour", "Entertainment", Bucket.ACTIVITY),
        ("Muay Thai tickets Rajadamnern", "Entertainment", Bucket.ACTIVITY),
        ("Grand Palace entry tickets", None, Bucket.ACTIVITY),
        ("Chatuchak weekend market shopping", "Clothing", Bucket.SHOPPING),
        ("Duty free and gifts", "Gifts", Bucket.SHOPPING),
        ("Thailand visa fee x4", None, Bucket.FEES),
        ("AIS tourist SIM cards x4", "General", Bucket.FEES),
        ("Grab to DMK airport", "Taxi", Bucket.TRAVEL),
    ],
)
def test_spend_bucket(description, category, expected):
    assert classify(description, category).bucket == expected


def test_notes_are_weaker_than_description():
    """A tour that includes a pickup is a tour, not a cab ride."""
    result = classify(
        "Elephant Nature Park full day tour",
        "Entertainment",
        "Ethical sanctuary, includes pickup and lunch",
    )
    assert result.mode == Mode.NONE
    assert result.bucket == Bucket.ACTIVITY


def test_head_word_beats_trailing_modifier():
    """The first words name the thing bought; later words only qualify it."""
    assert classify("Dinner packed for the train").bucket == Bucket.FOOD
    assert classify("Train ticket for dinner service").mode == Mode.TRAIN


def test_description_beats_category():
    """A specific description overrides a vague Splitwise category."""
    result = classify("Grab to the pier", "General")
    assert result.mode == Mode.CAB


def test_category_used_when_description_is_useless():
    result = classify("asdf qwer", "Plane")
    assert result.mode == Mode.PLANE
    assert "category" in result.reason


def test_unmatched_is_misc_not_an_error():
    result = classify("zzzzz", None)
    assert result.mode == Mode.NONE
    assert result.bucket == Bucket.MISC
    assert result.confidence == 0.0


def test_empty_input_is_safe():
    for args in ((None, None, None), ("", "", ""), ("   ", None, None)):
        result = classify(*args)
        assert result.mode == Mode.NONE


def test_classification_always_explains_itself():
    result = classify("Ferry to Phi Phi", "Transportation")
    assert result.reason
    assert 0.0 < result.confidence <= 1.0


def test_draws_line_matches_mode():
    assert classify("Ferry to Phi Phi").draws_line is True
    assert classify("Pad thai dinner").draws_line is False


def test_accents_and_case_are_normalised():
    assert classify("FERRY to Phi Phi").mode == Mode.FERRY
    assert classify("Caf\u00e9 breakfast").bucket == Bucket.FOOD


def test_word_boundaries_prevent_false_positives():
    """'pass' must not match inside 'passport'; 'bus' not inside 'business'."""
    assert classify("Passport photos").mode == Mode.NONE
    assert classify("Business lounge access").mode == Mode.NONE
