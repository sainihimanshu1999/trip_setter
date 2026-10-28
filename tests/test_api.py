"""HTTP tests: every endpoint answers, every page renders, CRUD round-trips."""

from __future__ import annotations

import json
import re

import pytest

JSON_BLOCK = re.compile(
    r'<script type="application/json" id="(data-[^"]+)">(.*?)</script>', re.S
)


# ------------------------------------------------------------------ health


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True        # no key configured in tests
    assert body["home_currency"] == "INR"


@pytest.mark.parametrize("path", [
    "/api/overview", "/api/people", "/api/categories", "/api/modes",
    "/api/timeline", "/api/settlements", "/api/expenses", "/api/journey",
    "/api/places", "/api/legs", "/api/meta", "/api/bookings",
])
def test_every_endpoint_returns_json(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()


# ------------------------------------------------------------------- pages


@pytest.mark.parametrize(("path", "must_contain"), [
    ("/", ["Who spent what", "Where the money went", "Day by day", "data-journey"]),
    ("/journey", ["The route", "Legs", "Spend by place", "place-panel"]),
    ("/bookings", ["Everything booked", "Trip timeline", "booking-dialog"]),
])
def test_pages_render(client, path, must_contain):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    for needle in must_contain:
        assert needle in response.text, f"{path} missing {needle!r}"


def test_pages_embed_valid_json(client):
    """First paint data must parse, or the charts get nothing."""
    for path in ("/", "/journey", "/bookings"):
        html = client.get(path).text
        blocks = JSON_BLOCK.findall(html)
        assert blocks, f"{path} embedded no data"
        for name, body in blocks:
            json.loads(body)  # raises on malformed JSON


def test_dashboard_shows_real_numbers_without_js(client):
    """Server-rendered KPIs, so the page is useful before scripts run."""
    html = client.get("/").text
    assert "Total spent" in html
    # Indian-format rupee figure such as ₹4.38L
    assert re.search(r"\u20b9[\d,.]+[LkM]?", html)


def test_static_assets_served(client):
    for asset in (
        "/static/css/theme.css",
        "/static/js/app.js",
        "/static/js/charts.js",
        "/static/js/journey.js",
        "/static/js/bookings.js",
    ):
        assert client.get(asset).status_code == 200, asset


# -------------------------------------------------------------- payload shape


def test_overview_numbers_are_consistent(client):
    body = client.get("/api/overview").json()
    assert body["total_spend"] > 0
    assert body["head_count"] == 4
    assert len(body["people"]) == 4
    paid = sum(p["paid"] for p in body["people"])
    assert abs(paid - body["total_spend"]) < 0.05
    assert abs(sum(p["balance"] for p in body["people"])) < 0.05


def test_journey_payload_drives_the_map(client):
    body = client.get("/api/journey").json()
    assert body["canvas"]["width"] > 0
    assert len(body["nodes"]) == 5
    assert body["edges"]
    assert body["legend"]
    with_spend = [e for e in body["edges"] if e["has_spend"]]
    assert with_spend, "no edge has an expense behind it"
    # Every drawn line must be able to explain itself on hover.
    for edge in with_spend:
        assert edge["expenses"]
        assert all(x["payers"] for x in edge["expenses"])


def test_expenses_exclude_settle_ups_by_default(client):
    default = client.get("/api/expenses?limit=500").json()["expenses"]
    assert all(not e["is_payment"] for e in default)

    with_payments = client.get("/api/expenses?limit=500&include_payments=true").json()
    assert any(e["is_payment"] for e in with_payments["expenses"])


def test_expenses_filter_by_mode(client):
    body = client.get("/api/expenses?mode=cab&limit=100").json()
    assert body["expenses"]
    assert all(e["mode"] == "cab" for e in body["expenses"])


def test_expenses_filter_by_bucket(client):
    body = client.get("/api/expenses?bucket=food&limit=100").json()
    assert body["expenses"]
    assert all(e["bucket"] == "food" for e in body["expenses"])


def test_expense_limit_is_bounded(client):
    assert client.get("/api/expenses?limit=0").status_code == 422
    assert client.get("/api/expenses?limit=99999").status_code == 422


def test_meta_exposes_style_tokens(client):
    body = client.get("/api/meta").json()
    assert "plane" in body["modes"]
    assert body["modes"]["plane"]["colour"].startswith("#")
    assert "food" in body["buckets"]
    assert "flight" in body["booking_kinds"]


def test_groups_endpoint_explains_demo_mode(client):
    body = client.get("/api/groups").json()
    assert body["demo_mode"] is True
    assert "SPLITWISE_API_KEY" in body["hint"]


def test_refresh_reloads(client):
    body = client.post("/api/refresh").json()
    assert body["refreshed"] is True
    assert body["expense_count"] > 0


# ---------------------------------------------------------- bookings CRUD


def test_seeded_bookings_have_links_and_descriptions(client):
    body = client.get("/api/bookings").json()
    assert body["count"] >= 6
    for booking in body["bookings"]:
        assert booking["title"]
        assert booking["description"]
        assert booking["kind_label"]
        assert booking["colour"].startswith("#")


def test_booking_round_trip(client):
    payload = {
        "kind": "tour",
        "title": "Test night safari",
        "provider": "Night Safari",
        "url": "https://example.com/safari",
        "description": "A tram through the park after dark.",
        "starts_at": "2026-01-15T18:30:00",
        "ends_at": "2026-01-15T21:30:00",
        "cost": 3200,
        "currency": "thb",
        "confirmation": "NS-1",
        "status": "pending",
        "notes": "Book the 19:00 tram.",
    }
    created = client.post("/api/bookings", json=payload)
    assert created.status_code == 201
    booking = created.json()
    assert booking["id"]
    assert booking["currency"] == "THB"       # normalised to upper case
    assert booking["status"] == "pending"

    fetched = client.get(f"/api/bookings/{booking['id']}").json()
    assert fetched["title"] == payload["title"]

    patched = client.patch(
        f"/api/bookings/{booking['id']}",
        json={"status": "confirmed", "cost": 2900},
    ).json()
    assert patched["status"] == "confirmed"
    assert patched["cost"] == 2900
    assert patched["title"] == payload["title"]   # untouched field survives

    assert client.delete(f"/api/bookings/{booking['id']}").status_code == 204
    assert client.get(f"/api/bookings/{booking['id']}").status_code == 404


def test_booking_can_attach_to_a_place(client):
    place = client.get("/api/places").json()["places"][1]
    created = client.post("/api/bookings", json={
        "title": "Place-linked booking", "place_id": place["id"],
        "url": "https://example.com",
    })
    assert created.status_code == 201
    body = created.json()
    assert body["place"] == place["name"]
    assert body["place_slug"] == place["slug"]
    client.delete(f"/api/bookings/{body['id']}")


def test_booking_filters(client):
    flights = client.get("/api/bookings?kind=flight").json()
    assert flights["count"] > 0
    assert all(b["kind"] == "flight" for b in flights["bookings"])


@pytest.mark.parametrize("bad_url", [
    "javascript:alert(document.cookie)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
])
def test_dangerous_url_schemes_are_rejected(client, bad_url):
    """These would execute when someone clicks the booking card link."""
    response = client.post("/api/bookings", json={"title": "bad", "url": bad_url})
    assert response.status_code == 422


def test_end_before_start_is_rejected(client):
    response = client.post("/api/bookings", json={
        "title": "time travel",
        "starts_at": "2026-01-10T10:00:00",
        "ends_at": "2026-01-09T10:00:00",
    })
    assert response.status_code == 422


def test_unknown_place_is_rejected(client):
    response = client.post("/api/bookings", json={"title": "ghost", "place_id": 999999})
    assert response.status_code == 422


def test_empty_title_is_rejected(client):
    assert client.post("/api/bookings", json={"title": ""}).status_code == 422


def test_negative_cost_is_rejected(client):
    assert client.post(
        "/api/bookings", json={"title": "refund", "cost": -50}
    ).status_code == 422


def test_missing_booking_returns_404(client):
    assert client.get("/api/bookings/999999").status_code == 404
    assert client.patch("/api/bookings/999999", json={"title": "x"}).status_code == 404
    assert client.delete("/api/bookings/999999").status_code == 404


def test_seed_is_idempotent_across_restarts(client):
    """init_db runs on every boot and must not duplicate the itinerary."""
    from app.seed import seed_itinerary

    before = client.get("/api/bookings").json()["count"]
    added = seed_itinerary()
    after = client.get("/api/bookings").json()["count"]
    assert added == {"places": 0, "legs": 0, "bookings": 0}
    assert before == after
