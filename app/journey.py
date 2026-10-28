"""Build the journey graph: nodes for places, edges for every movement.

Two kinds of edge end up on the map:

* **Leg edges** come from the itinerary. Delhi to Bangkok is a flight whether or
  not anyone has filed the expense yet, so the line exists but renders dim
  until spending backs it up.
* **Local edges** come from expenses that are transport but do not cross between
  cities. A tuk tuk in Bangkok becomes a short cab arc looping off the Bangkok
  node, which is the behaviour of "split a cab, get a cab line".

Expenses attach to places by date first, then by keyword, so "Grab to DMK
airport" lands on Bangkok even though the word Bangkok never appears.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analytics import Analytics
from .classify import DRAWABLE_MODES, Mode, mode_style, normalise_text, text_matches
from .domain import ZERO, Expense
from .models import Booking, Leg, Place

#: SVG coordinate space the frontend expects. The viewBox matches.
CANVAS_W = 1000.0
CANVAS_H = 620.0
PAD_X = 110.0
PAD_Y = 90.0

NODE_MIN_R = 17.0
NODE_MAX_R = 40.0
#: Clear space demanded between two node edges after relaxation. 58px is the
#: smallest value that keeps a node's name label off its neighbour's pin when
#: several stops sit close together, such as islands along one coast.
NODE_GAP = 58.0
#: Vertical room reserved beyond a node's radius for its name label, which sits
#: either above or below the circle. The preview map enlarges label text, so
#: this is sized for the larger of the two.
LABEL_ROOM = 36.0
CENTS = Decimal("0.01")


def _equirect(places: list[Place]) -> dict[str, tuple[float, float]]:
    """Raw equirectangular projection, longitude corrected for latitude."""
    mean_lat = math.radians(sum(p.lat for p in places) / len(places))
    kx = math.cos(mean_lat) or 1.0
    return {p.slug: (p.lon * kx, -p.lat) for p in places}  # -lat: SVG y grows down


def _fit(
    raw: dict[str, tuple[float, float]],
    pad_x: float = PAD_X,
    pad_y: float = PAD_Y,
) -> dict[str, tuple[float, float]]:
    """Scale a raw projection into the canvas, preserving aspect ratio."""
    xs = [p[0] for p in raw.values()]
    ys = [p[1] for p in raw.values()]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = (x_max - x_min) or 1.0
    y_span = (y_max - y_min) or 1.0

    usable_w = CANVAS_W - 2 * pad_x
    usable_h = CANVAS_H - 2 * pad_y
    scale = min(usable_w / x_span, usable_h / y_span)
    off_x = pad_x + (usable_w - x_span * scale) / 2
    off_y = pad_y + (usable_h - y_span * scale) / 2

    return {
        slug: (off_x + (x - x_min) * scale, off_y + (y - y_min) * scale)
        for slug, (x, y) in raw.items()
    }


def _relax(
    coords: dict[str, tuple[float, float]],
    radii: dict[str, float],
    iterations: int = 120,
) -> dict[str, tuple[float, float]]:
    """Push overlapping nodes apart.

    Neighbouring stops can be a short hop apart while the projection is scaled
    to fit the whole trip, which puts them inside each other's pins. This
    nudges them to at least touching distance while keeping the overall shape.
    """
    points = {slug: [x, y] for slug, (x, y) in coords.items()}
    slugs = list(points)

    for _ in range(iterations):
        moved = 0.0
        for i, a in enumerate(slugs):
            for b in slugs[i + 1:]:
                ax, ay = points[a]
                bx, by = points[b]
                dx, dy = bx - ax, by - ay
                dist = math.hypot(dx, dy)
                want = radii.get(a, NODE_MIN_R) + radii.get(b, NODE_MIN_R) + NODE_GAP
                if dist >= want:
                    continue
                if dist < 1e-6:
                    # Exactly coincident: pick an arbitrary but stable direction.
                    dx, dy, dist = 1.0, 0.0, 1.0
                push = (want - dist) / 2
                ux, uy = dx / dist, dy / dist
                points[a] = [ax - ux * push, ay - uy * push]
                points[b] = [bx + ux * push, by + uy * push]
                moved += push
        if moved < 0.25:
            break

    # Keep everything on canvas, leaving room for the label that sits above or
    # below each node. Without the label allowance a node pushed to the bottom
    # edge gets its name clipped by the viewBox.
    out: dict[str, tuple[float, float]] = {}
    for slug, (x, y) in points.items():
        r = radii.get(slug, NODE_MIN_R)
        out[slug] = (
            round(min(max(x, r + 8), CANVAS_W - r - 8), 2),
            round(min(max(y, r + LABEL_ROOM), CANVAS_H - r - LABEL_ROOM), 2),
        )
    return out


def main_country(places: list[Place]) -> str:
    """The country most of the trip happens in. Everywhere else is a gateway."""
    counts: dict[str, int] = defaultdict(int)
    for place in places:
        counts[place.country or ""] += 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""


def project(
    places: list[Place],
    radii: dict[str, float] | None = None,
) -> dict[str, tuple[float, float]]:
    """Lay the places out on the SVG canvas.

    Places in the trip's main country are projected geographically. Anywhere
    else is a *gateway* - the airport you flew in from - and gets pinned to the
    canvas edge along its true compass bearing, because including Delhi in the
    same linear projection as Thailand squashes Thailand into a smudge.
    """
    if not places:
        return {}
    if len(places) == 1:
        return {places[0].slug: (CANVAS_W / 2, CANVAS_H / 2)}

    home = main_country(places)
    core = [p for p in places if (p.country or "") == home]
    gateways = [p for p in places if (p.country or "") != home]
    if not core:
        core, gateways = places, []

    radii = radii or {}
    coords = _fit(_equirect(core), PAD_X, PAD_Y) if len(core) > 1 else {
        core[0].slug: (CANVAS_W / 2, CANVAS_H / 2)
    }
    coords = _relax(coords, radii)

    if gateways:
        cx = sum(x for x, _ in coords.values()) / len(coords)
        cy = sum(y for _, y in coords.values()) / len(coords)
        mean_lat = sum(p.lat for p in core) / len(core)
        mean_lon = sum(p.lon for p in core) / len(core)
        kx = math.cos(math.radians(mean_lat)) or 1.0

        for index, gate in enumerate(gateways):
            # True bearing from the cluster centre, in canvas space.
            dx = (gate.lon - mean_lon) * kx
            dy = -(gate.lat - mean_lat)
            norm = math.hypot(dx, dy) or 1.0
            ux, uy = dx / norm, dy / norm
            r = radii.get(gate.slug, NODE_MIN_R)
            # Walk out to the canvas border along that bearing.
            margin_x = CANVAS_W / 2 - r - 14
            margin_y = CANVAS_H / 2 - r - LABEL_ROOM
            steps = [margin_x / abs(ux) if abs(ux) > 1e-6 else float("inf"),
                     margin_y / abs(uy) if abs(uy) > 1e-6 else float("inf")]
            reach = min(steps)
            # Stagger multiple gateways so they never stack.
            reach -= index * (2 * r + NODE_GAP)
            coords[gate.slug] = (
                round(min(max(CANVAS_W / 2 + ux * reach, r + 8), CANVAS_W - r - 8), 2),
                round(min(max(CANVAS_H / 2 + uy * reach, r + LABEL_ROOM),
                          CANVAS_H - r - LABEL_ROOM), 2),
            )

    return coords


@dataclass(slots=True)
class NodeAcc:
    place: Place
    spend: Decimal = ZERO
    expense_count: int = 0
    modes: set[str] = field(default_factory=set)
    buckets: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    top: list[tuple[str, Decimal]] = field(default_factory=list)


def _places_for_date(places: list[Place], when: date | None) -> list[Place]:
    """Every place whose stay covers this date.

    Returns more than one on a travel day, because the day you leave Bangkok
    for Koh Samui you were genuinely in both.
    """
    if when is None:
        return []
    out = []
    for place in places:
        start, end = place.arrive_on, place.depart_on
        if start and end and start <= when <= end:
            out.append(place)
        elif start and not end and when >= start:
            out.append(place)
    return out


def _best_keyword_place(places: list[Place], expense: Expense) -> Place | None:
    """Longest matching place alias wins; ties go to the earlier stop."""
    haystack = normalise_text(f"{expense.description} {expense.details}")
    if not haystack:
        return None
    best: tuple[int, Place] | None = None
    for place in sorted(places, key=lambda p: p.order_index):
        for term in place.terms():
            clean = normalise_text(term)
            if clean and text_matches(haystack, clean):
                score = len(clean)
                # Strictly greater, so the earliest place keeps a tie.
                if best is None or score > best[0]:
                    best = (score, place)
    return best[1] if best else None


def attribute(places: list[Place], expense: Expense) -> Place | None:
    """Pick the place an expense belongs to.

    An unambiguous date decides it outright. On a travel day the date covers two
    places, so the description breaks the tie ("Khao soi dinner" is Chiang Mai,
    "Grab to DMK" is Bangkok); failing that we assume the place being travelled
    to, since that is where the rest of the day happened. Expenses dated outside
    every stay, such as flights booked months ahead, fall back to keywords.
    """
    candidates = _places_for_date(places, expense.date)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return (
            _best_keyword_place(candidates, expense)
            or max(candidates, key=lambda p: p.order_index)
        )
    return _best_keyword_place(places, expense)


def _mentions_place(haystack: str, place: Place | None) -> bool:
    """Does this text name the given place, by name, slug or alias?"""
    if place is None:
        return False
    return any(text_matches(haystack, term) for term in place.terms())


def _match_leg(
    legs: list[Leg],
    by_slug: dict[str, Place],
    expense: Expense,
) -> Leg | None:
    """Tie a transport expense to an itinerary leg, or return None for a local ride.

    Date proximity alone is not enough: a Krabi four-islands boat tour sits one
    day before the Phi Phi ferry and would wrongly absorb it. A match needs
    real evidence, meaning the operator, the ticket reference, or both endpoints
    named in the text. Date proximity only promotes a single-endpoint hint.

    Requiring evidence rather than dates is also what lets a flight booked three
    months early still attach to its leg.
    """
    if expense.mode == Mode.NONE:
        return None

    text = normalise_text(f"{expense.description} {expense.details}")
    best: tuple[int, Leg] | None = None

    for leg in legs:
        if leg.mode != str(expense.mode):
            continue

        origin = by_slug.get(leg.from_slug)
        destination = by_slug.get(leg.to_slug)
        hits_from = _mentions_place(text, origin)
        hits_to = _mentions_place(text, destination)

        operator = normalise_text(leg.operator)
        reference = normalise_text(leg.reference).replace(" ", "")
        compact = text.replace(" ", "")

        by_operator = bool(operator) and operator in text
        by_reference = bool(reference) and reference in compact
        both_ends = hits_from and hits_to

        gap = (
            abs((leg.depart_at.date() - expense.date).days)
            if leg.depart_at and expense.date else 999
        )

        strong = by_operator or by_reference or both_ends
        # A transfer is identified by where it goes. Naming only the origin
        # proves nothing: you are already there. That is the difference between
        # "Ferry Ao Nang to Phi Phi" and a round-trip boat tour out of Ao Nang.
        weak = gap <= 1 and hits_to
        # Flights and trains are commonly booked months early, so a "Flight to
        # BKK" expense filed in September should still match the October leg
        # if the mode and destination match. Relax the gap for these modes.
        prebooked = hits_to and leg.mode in ("plane", "train") and gap <= 60
        if not (strong or weak or prebooked):
            continue

        score = 0
        if by_reference:
            score += 45
        if by_operator:
            score += 30
        if both_ends:
            score += 35
        elif hits_from or hits_to:
            score += 10
        if prebooked and not (strong or weak):
            score += 5  # weaker than a day-of match but still counts
        if gap == 0:
            score += 25
        elif gap <= 1:
            score += 15
        elif gap <= 3:
            score += 5

        if best is None or score > best[0]:
            best = (score, leg)

    return best[1] if best else None


def _label_sides(
    coords: dict[str, tuple[float, float]],
    radii: dict[str, float],
) -> dict[str, str]:
    """Put each node's name above it, unless a neighbour is sitting there.

    Stops along one coast stack almost vertically, so a label placed above one
    node would land on top of the pin above it.
    """
    sides: dict[str, str] = {}
    for slug, (x, y) in coords.items():
        r = radii.get(slug, NODE_MIN_R)
        above_blocked = below_blocked = False
        for other, (ox, oy) in coords.items():
            if other == slug:
                continue
            orad = radii.get(other, NODE_MIN_R)
            if abs(ox - x) > 96:       # too far sideways to collide
                continue
            if abs(oy - (y - r - 16)) < orad + 10:
                above_blocked = True
            if abs(oy - (y + r + 20)) < orad + 10:
                below_blocked = True
        sides[slug] = "bottom" if above_blocked and not below_blocked else "top"
    return sides


def _expense_brief(expense: Expense) -> dict:
    """What the map shows when you hover or select a line.

    The whole point of an edge is the expense behind it, so this carries who
    paid and the original currency, not just a converted number.
    """
    return {
        "id": expense.id,
        "description": expense.description,
        "details": expense.details,
        "amount": float(expense.home_cost.quantize(CENTS)),
        "original": float(expense.cost),
        "currency": expense.currency,
        "date": expense.date.isoformat() if expense.date else None,
        "payers": expense.payer_names,
        "mode": str(expense.mode),
        "reason": expense.reason,
        "shares": [
            {"name": s.name, "owed": float(s.owed)}
            for s in expense.shares if s.owed > 0
        ],
    }


def build_journey(session: Session, analytics: Analytics) -> dict:
    """Assemble the node/edge payload the SVG renderer consumes."""
    places = list(session.scalars(
        select(Place).order_by(Place.order_index)
    ).all())
    legs = list(session.scalars(select(Leg).order_by(Leg.order_index)).all())
    bookings = list(session.scalars(select(Booking)).all())

    if not places:
        return {
            "canvas": {"width": CANVAS_W, "height": CANVAS_H},
            "nodes": [], "edges": [], "legend": [], "currency": analytics.currency,
        }

    nodes: dict[str, NodeAcc] = {p.slug: NodeAcc(place=p) for p in places}
    by_slug: dict[str, Place] = {p.slug: p for p in places}
    booking_counts: dict[int, int] = defaultdict(int)
    stay_places: set[int] = set()
    for booking in bookings:
        if booking.place_id:
            booking_counts[booking.place_id] += 1
            if booking.kind == "stay":
                stay_places.add(booking.place_id)

    # Expenses matched to itinerary legs, and leftover local movements.
    leg_expenses: dict[int, list[Expense]] = defaultdict(list)
    local: dict[tuple[str, str], list[Expense]] = defaultdict(list)

    for expense in analytics.trip.expenses:
        if expense.is_payment:
            continue

        home = expense.home_cost
        place = attribute(places, expense)

        if place is not None:
            acc = nodes[place.slug]
            acc.spend += home
            acc.expense_count += 1
            acc.buckets[str(expense.bucket)] += home
            if expense.mode != Mode.NONE:
                acc.modes.add(str(expense.mode))
            acc.top.append((expense.description, home))

        if expense.mode in DRAWABLE_MODES:
            leg = _match_leg(legs, by_slug, expense)
            if leg is not None:
                leg_expenses[leg.id].append(expense)
            elif place is not None:
                # Transport that did not cross cities: a ride within a place.
                local[(place.slug, str(expense.mode))].append(expense)

    # ---------------------------------------------------------------- nodes
    # Radii are needed before layout, because the relaxation pass pushes nodes
    # apart by their drawn size.
    spends = [acc.spend for acc in nodes.values()]
    max_spend = max(spends) if spends else ZERO
    radii: dict[str, float] = {}
    for slug, acc in nodes.items():
        ratio = float(acc.spend / max_spend) if max_spend > 0 else 0.0
        radii[slug] = NODE_MIN_R + (NODE_MAX_R - NODE_MIN_R) * math.sqrt(ratio)

    coords = project(places, radii)
    label_sides = _label_sides(coords, radii)
    home_country = main_country(places)

    node_rows = []
    for slug, acc in nodes.items():
        x, y = coords[slug]
        ratio = float(acc.spend / max_spend) if max_spend > 0 else 0.0
        acc.top.sort(key=lambda kv: kv[1], reverse=True)
        node_rows.append({
            "id": slug,
            "name": acc.place.name,
            "region": acc.place.region,
            "country": acc.place.country,
            "gateway": (acc.place.country or "") != home_country,
            "lat": acc.place.lat,
            "lon": acc.place.lon,
            "x": x,
            "y": y,
            "r": round(radii[slug], 2),
            "label_side": label_sides[slug],
            "order": acc.place.order_index,
            "arrive_on": acc.place.arrive_on.isoformat() if acc.place.arrive_on else None,
            "depart_on": acc.place.depart_on.isoformat() if acc.place.depart_on else None,
            "nights": acc.place.nights,
            "blurb": acc.place.blurb,
            "spend": float(acc.spend.quantize(CENTS)),
            "spend_ratio": round(ratio, 4),
            "expense_count": acc.expense_count,
            "booking_count": booking_counts.get(acc.place.id, 0),
            "has_stay": acc.place.id in stay_places,
            "modes": sorted(acc.modes),
            "buckets": {k: float(v.quantize(CENTS)) for k, v in acc.buckets.items()},
            "top_expenses": [
                {"description": d, "amount": float(v.quantize(CENTS))}
                for d, v in acc.top[:4]
            ],
        })
    node_rows.sort(key=lambda n: n["order"])

    # ---------------------------------------------------------------- edges
    edge_rows = []
    seen_pairs: dict[frozenset[str], int] = defaultdict(int)

    for leg in legs:
        if leg.from_slug not in coords or leg.to_slug not in coords:
            continue
        matched = leg_expenses.get(leg.id, [])
        cost = sum((e.home_cost for e in matched), ZERO)
        style = mode_style(leg.mode)

        # A second edge between the same two places bows the other way, so a
        # return leg does not sit on top of the outbound one.
        pair = frozenset((leg.from_slug, leg.to_slug))
        seen_pairs[pair] += 1
        arc_sign = 1 if seen_pairs[pair] % 2 else -1

        edge_rows.append({
            "id": f"leg-{leg.id}",
            "kind": "leg",
            "from": leg.from_slug,
            "to": leg.to_slug,
            "mode": leg.mode,
            "label": " ".join(x for x in (leg.operator, leg.reference) if x),
            "operator": leg.operator,
            "reference": leg.reference,
            "depart_at": leg.depart_at.isoformat() if leg.depart_at else None,
            "arrive_at": leg.arrive_at.isoformat() if leg.arrive_at else None,
            "duration_minutes": leg.duration_minutes,
            "order": leg.order_index,
            "notes": leg.notes,
            "booking_url": leg.booking_url,
            "cost": float(cost.quantize(CENTS)),
            "expense_count": len(matched),
            "has_spend": bool(matched),
            "arc": style["arc"] * arc_sign,
            "colour": style["colour"],
            "dash": style["dash"],
            "glyph": style["glyph"],
            "speed": style["speed"],
            "mode_label": style["label"],
            "expenses": [
                _expense_brief(e)
                for e in sorted(matched, key=lambda e: e.home_cost, reverse=True)
            ],
        })

    # Local rides orbit their node, one arc per mode per place.
    for (slug, mode), expenses in sorted(local.items()):
        style = mode_style(mode)
        cost = sum((e.home_cost for e in expenses), ZERO)
        node = next((n for n in node_rows if n["id"] == slug), None)
        if node is None:
            continue
        edge_rows.append({
            "id": f"local-{slug}-{mode}",
            "kind": "local",
            "from": slug,
            "to": slug,
            "mode": mode,
            "label": f"{style['label']} around {node['name']}",
            "operator": "",
            "reference": "",
            "depart_at": min(
                (e.date.isoformat() for e in expenses if e.date), default=None,
            ),
            "arrive_at": None,
            "duration_minutes": 0,
            "order": node["order"] * 10 + 5,
            "notes": "",
            "booking_url": "",
            "cost": float(cost.quantize(CENTS)),
            "expense_count": len(expenses),
            "has_spend": True,
            "arc": style["arc"],
            "colour": style["colour"],
            "dash": style["dash"],
            "glyph": style["glyph"],
            "speed": style["speed"],
            "mode_label": style["label"],
            "expenses": [
                _expense_brief(e)
                for e in sorted(expenses, key=lambda e: e.home_cost, reverse=True)
            ],
        })

    edge_rows.sort(key=lambda e: (e["order"], e["kind"] == "local"))

    # --------------------------------------------------------------- legend
    used_modes: dict[str, dict] = {}
    for edge in edge_rows:
        entry = used_modes.setdefault(edge["mode"], {
            "mode": edge["mode"],
            "label": edge["mode_label"],
            "colour": edge["colour"],
            "dash": edge["dash"],
            "glyph": edge["glyph"],
            "cost": 0.0,
            "count": 0,
        })
        entry["cost"] += edge["cost"]
        entry["count"] += edge["expense_count"]

    legend = sorted(used_modes.values(), key=lambda m: m["cost"], reverse=True)
    for entry in legend:
        entry["cost"] = round(entry["cost"], 2)

    return {
        "canvas": {"width": CANVAS_W, "height": CANVAS_H},
        "currency": analytics.currency,
        "nodes": node_rows,
        "edges": edge_rows,
        "legend": legend,
        "totals": {
            "places": len(node_rows),
            "legs": len([e for e in edge_rows if e["kind"] == "leg"]),
            "local": len([e for e in edge_rows if e["kind"] == "local"]),
            "transport_spend": round(sum(e["cost"] for e in edge_rows), 2),
        },
    }
