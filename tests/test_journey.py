"""Journey graph tests.

The two things that must hold: nodes never overlap (or the map is unreadable),
and every transport expense lands on exactly one edge (or money is double
counted on the map).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal

from app.classify import DRAWABLE_MODES, classify
from app.domain import Expense
from app.journey import (
    CANVAS_H,
    CANVAS_W,
    NODE_MAX_R,
    NODE_MIN_R,
    _match_leg,
    attribute,
    build_journey,
    project,
)
from app.models import Leg, Place


def graph(db_session, analytics):
    return build_journey(db_session, analytics)


def _transport_expense(description: str, when: date) -> Expense:
    """An expense classified the same way the real parsers classify it."""
    verdict = classify(description, "", "")
    return Expense(
        id=1, description=description, cost=Decimal("1000"), currency="THB",
        date=when, mode=verdict.mode, bucket=verdict.bucket,
    )


# ------------------------------------------------------------- projection


def test_every_place_gets_coordinates(db_session, analytics):
    g = graph(db_session, analytics)
    assert len(g["nodes"]) == 5
    for node in g["nodes"]:
        assert 0 <= node["x"] <= CANVAS_W
        assert 0 <= node["y"] <= CANVAS_H


def test_nodes_never_overlap(db_session, analytics):
    """Pins that touch are unreadable, so relaxation must separate every pair."""
    g = graph(db_session, analytics)
    nodes = g["nodes"]
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            distance = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
            gap = distance - a["r"] - b["r"]
            assert gap >= -0.5, (
                f"{a['id']} and {b['id']} overlap by {-gap:.1f}px"
            )


def test_node_labels_stay_inside_the_canvas(db_session, analytics):
    """A label outside the viewBox is silently clipped by the browser."""
    g = graph(db_session, analytics)
    for node in g["nodes"]:
        above = node["y"] - node["r"] - 12
        below = node["y"] + node["r"] + 20
        assert above > 0, f"{node['id']} label clipped at the top"
        assert below < CANVAS_H, f"{node['id']} label clipped at the bottom"
        assert node["x"] - node["r"] >= 0
        assert node["x"] + node["r"] <= CANVAS_W


def test_node_labels_do_not_sit_on_other_nodes(db_session, analytics):
    """A name label landing on the circle above it makes the map unreadable."""
    g = graph(db_session, analytics)
    nodes = g["nodes"]
    for a in nodes:
        assert a["label_side"] in ("top", "bottom")
        label_y = (
            a["y"] + a["r"] + 20 if a["label_side"] == "bottom"
            else a["y"] - a["r"] - 12
        )
        for b in nodes:
            if a["id"] == b["id"]:
                continue
            if abs(a["x"] - b["x"]) >= 80:
                continue
            assert abs(label_y - b["y"]) >= b["r"] + 6, (
                f"{a['id']} label overlaps {b['id']}"
            )


def test_gateway_nodes_are_flagged(db_session, analytics):
    g = graph(db_session, analytics)
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id["delhi"]["gateway"] is True
    assert by_id["bangalore"]["gateway"] is True
    assert by_id["bangkok"]["gateway"] is False


def test_node_radius_tracks_spend(db_session, analytics):
    g = graph(db_session, analytics)
    spent = [n for n in g["nodes"] if n["spend"] > 0]
    ranked = sorted(spent, key=lambda n: n["spend"], reverse=True)
    radii = [n["r"] for n in ranked]
    assert radii == sorted(radii, reverse=True)
    assert all(NODE_MIN_R <= n["r"] <= NODE_MAX_R for n in g["nodes"])


def test_foreign_gateway_is_pinned_to_the_edge():
    """Delhi is 2,500km away; projecting it linearly squashes Thailand flat."""
    places = [
        Place(slug="delhi", name="Delhi", country="India", lat=28.6139, lon=77.2090),
        Place(slug="bangkok", name="Bangkok", country="Thailand", lat=13.7563, lon=100.5018),
        Place(slug="koh-samui", name="Koh Samui", country="Thailand", lat=9.5120, lon=100.0067),
        Place(slug="phuket", name="Phuket", country="Thailand", lat=7.8906, lon=98.2969),
    ]
    coords = project(places, {p.slug: 20.0 for p in places})
    thai = [coords[s] for s in ("bangkok", "koh-samui", "phuket")]
    spread_y = max(y for _, y in thai) - min(y for _, y in thai)
    # Thailand must use a real share of the canvas, not a sliver.
    assert spread_y > CANVAS_H * 0.3, f"Thailand collapsed to {spread_y:.0f}px"
    # Delhi sits north-west of Thailand, so up and to the left.
    dx, dy = coords["delhi"]
    assert dy < min(y for _, y in thai)
    assert dx < max(x for x, _ in thai)


def test_projection_handles_a_single_place():
    coords = project([Place(slug="solo", name="Solo", country="Thailand", lat=10.0, lon=100.0)])
    assert coords["solo"] == (CANVAS_W / 2, CANVAS_H / 2)


def test_projection_handles_no_places():
    assert project([]) == {}


# ------------------------------------------------------------- attribution


def test_expenses_land_on_the_right_place(db_session, analytics):
    """Keywords decide when the date cannot.

    The sample expenses are dated a different month to the seeded itinerary, so
    every one of these reaches its place through `match_terms` alone.
    """
    places = db_session.query(Place).order_by(Place.order_index).all()
    expected = {
        "Grand Palace entry tickets": "bangkok",
        "First night dinner - Thipsamai pad thai": "bangkok",
        "Taxi Rassada pier to Patong": "phuket",
        "Grab to Phuket airport": "phuket",
    }
    found = {e.description: e for e in analytics.trip.expenses}
    for description, expected_slug in expected.items():
        # KeyError here means the sample data changed and this test went blind.
        expense = found[description]
        place = attribute(places, expense)
        assert place is not None, description
        assert place.slug == expected_slug, f"{description} -> {place.slug}"


def test_no_transport_expense_lands_on_two_edges(db_session, analytics):
    """Double counting an expense would inflate the map's transport total.

    Expenses whose keywords name a place that is not on this itinerary attach
    to nothing, which is why this checks for duplicates rather than for every
    transport expense being present.
    """
    g = graph(db_session, analytics)
    transport = {
        e.id for e in analytics.trip.expenses
        if e.mode in DRAWABLE_MODES and not e.is_payment
    }
    assert transport

    placed = [x["id"] for edge in g["edges"] for x in edge["expenses"]]
    assert placed, "no expense reached an edge"
    assert len(placed) == len(set(placed)), "an expense is on two edges"
    assert set(placed) <= transport, "a non-transport expense was drawn as a line"


def test_prebooked_flight_still_matches_its_leg(db_session, analytics):
    """Booked ten months early: the operator and flight number are the evidence."""
    g = graph(db_session, analytics)
    edge = next(
        e for e in g["edges"]
        if e["kind"] == "leg" and e["from"] == "delhi" and e["to"] == "bangkok"
    )
    assert edge["has_spend"] is True
    assert any("IndiGo" in x["description"] for x in edge["expenses"])


def test_leg_matching_needs_evidence_not_just_a_nearby_date():
    """A round-trip boat tour out of Krabi is not the transfer to Phi Phi.

    The tour is dated the day before the ferry, so date proximity alone would
    wrongly absorb it. Only the transfer names both ends of the leg.
    """
    krabi = Place(slug="krabi", name="Krabi", country="Thailand",
                  lat=8.0320, lon=98.8210, match_terms="ao nang,railay")
    phi_phi = Place(slug="phi-phi", name="Koh Phi Phi", country="Thailand",
                    lat=7.7407, lon=98.7784, match_terms="phi phi,tonsai")
    ferry = Leg(id=1, from_slug="krabi", to_slug="phi-phi", mode="ferry",
                operator="Ao Nang Princess", reference="ANP-09",
                depart_at=datetime(2026, 1, 19, 9, 0), order_index=0)
    by_slug = {"krabi": krabi, "phi-phi": phi_phi}

    transfer = _transport_expense("Ferry Ao Nang pier to Phi Phi", date(2026, 1, 19))
    tour = _transport_expense("Longtail boat 4 islands tour", date(2026, 1, 18))
    assert transfer.mode == tour.mode, "both must be ferries for this to prove anything"

    assert _match_leg([ferry], by_slug, transfer) is ferry
    assert _match_leg([ferry], by_slug, tour) is None


def test_cab_expenses_become_local_edges(db_session, analytics):
    """Split a cab, get a cab line looping off that city."""
    g = graph(db_session, analytics)
    cabs = [e for e in g["edges"] if e["mode"] == "cab"]
    assert cabs
    assert all(e["kind"] == "local" for e in cabs)
    assert all(e["from"] == e["to"] for e in cabs)
    bangkok = next(e for e in cabs if e["from"] == "bangkok")
    assert bangkok["expense_count"] >= 2
    assert bangkok["cost"] > 0


# ------------------------------------------------------------------ edges


def test_every_edge_carries_what_the_hover_needs(db_session, analytics):
    g = graph(db_session, analytics)
    for edge in g["edges"]:
        for key in ("id", "kind", "from", "to", "mode", "colour", "dash",
                    "glyph", "arc", "cost", "expenses", "has_spend", "mode_label"):
            assert key in edge, f"{edge.get('id')} missing {key}"
        for item in edge["expenses"]:
            # This is what the tooltip renders.
            for key in ("description", "amount", "currency", "date", "payers", "shares"):
                assert key in item, f"expense missing {key}"
            assert item["payers"], "an expense with no payer cannot be explained"


def test_legs_without_spend_are_marked_but_still_present(db_session, analytics):
    """Planned legs stay visible as ghosts so you see what is unpaid."""
    g = graph(db_session, analytics)
    legs = [e for e in g["edges"] if e["kind"] == "leg"]
    assert len(legs) == 5
    for leg in legs:
        assert leg["has_spend"] == bool(leg["expenses"])


def test_legend_covers_every_drawn_mode(db_session, analytics):
    g = graph(db_session, analytics)
    drawn = {e["mode"] for e in g["edges"]}
    assert {m["mode"] for m in g["legend"]} == drawn
    assert all(m["label"] and m["colour"] for m in g["legend"])


def test_totals_match_the_edges(db_session, analytics):
    g = graph(db_session, analytics)
    assert g["totals"]["legs"] == len([e for e in g["edges"] if e["kind"] == "leg"])
    assert g["totals"]["local"] == len([e for e in g["edges"] if e["kind"] == "local"])
    assert g["totals"]["places"] == len(g["nodes"])
