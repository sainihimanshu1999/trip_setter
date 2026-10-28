"""Classify a Splitwise expense into a transport mode and a spend bucket.

This is what makes the journey map work: when someone splits a Grab ride,
we recognise it as a cab and the map draws a cab line. Rules are scored so the
most specific signal wins, and every result carries the reason it matched so
the UI can explain itself on hover.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class Mode(StrEnum):
    """How the group physically moved. NONE means this expense isn't transport."""

    PLANE = "plane"
    TRAIN = "train"
    CAB = "cab"
    FERRY = "ferry"
    BUS = "bus"
    BIKE = "bike"
    WALK = "walk"
    NONE = "none"


class Bucket(StrEnum):
    """What kind of spending this was, for the category breakdown."""

    TRAVEL = "travel"
    STAY = "stay"
    FOOD = "food"
    ACTIVITY = "activity"
    SHOPPING = "shopping"
    FEES = "fees"
    MISC = "misc"


#: Modes that should be drawn as a line on the journey map, in draw order.
DRAWABLE_MODES: tuple[Mode, ...] = (
    Mode.PLANE,
    Mode.TRAIN,
    Mode.FERRY,
    Mode.BUS,
    Mode.CAB,
    Mode.BIKE,
    Mode.WALK,
)

#: Presentation metadata consumed by both the API and the SVG renderer.
#: Colours are chosen to carry weight on a white canvas and to stay
#: distinguishable from each other, since they are the only thing telling a
#: ferry line apart from a train line.
MODE_STYLE: dict[Mode, dict[str, object]] = {
    Mode.PLANE: {"label": "Flight", "glyph": "plane", "colour": "#2563eb", "arc": 0.42, "dash": "14 9", "speed": 1.0},
    Mode.TRAIN: {"label": "Train", "glyph": "train", "colour": "#7c3aed", "arc": 0.10, "dash": "10 6", "speed": 1.45},
    Mode.FERRY: {"label": "Ferry", "glyph": "boat", "colour": "#0d9488", "arc": 0.18, "dash": "2 8", "speed": 1.7},
    Mode.BUS: {"label": "Bus", "glyph": "bus", "colour": "#db2777", "arc": 0.14, "dash": "12 7", "speed": 1.5},
    Mode.CAB: {"label": "Cab", "glyph": "car", "colour": "#d97706", "arc": 0.22, "dash": "7 5", "speed": 1.15},
    Mode.BIKE: {"label": "Scooter", "glyph": "bike", "colour": "#4d7c0f", "arc": 0.16, "dash": "5 5", "speed": 1.3},
    Mode.WALK: {"label": "Walk", "glyph": "walk", "colour": "#6b7280", "arc": 0.08, "dash": "2 7", "speed": 2.2},
}

BUCKET_STYLE: dict[Bucket, dict[str, str]] = {
    Bucket.TRAVEL: {"label": "Getting around", "colour": "#2563eb", "icon": "route"},
    Bucket.STAY: {"label": "Stays", "colour": "#7c3aed", "icon": "bed"},
    Bucket.FOOD: {"label": "Food & drink", "colour": "#ea580c", "icon": "bowl"},
    Bucket.ACTIVITY: {"label": "Tours & activities", "colour": "#0d9488", "icon": "ticket"},
    Bucket.SHOPPING: {"label": "Shopping", "colour": "#db2777", "icon": "bag"},
    Bucket.FEES: {"label": "Visas & fees", "colour": "#ca8a04", "icon": "stamp"},
    Bucket.MISC: {"label": "Everything else", "colour": "#717171", "icon": "dot"},
}


@dataclass(frozen=True, slots=True)
class Rule:
    """A keyword rule. `weight` breaks ties; higher is more specific."""

    mode: Mode
    bucket: Bucket
    keywords: tuple[str, ...]
    weight: int = 10


# Weight tiers. The important distinction is between words naming a *vehicle*
# and words naming a *destination*: "Grab to DMK airport" is a cab ride, not a
# flight, so airport codes and piers must score below taxi/bus keywords.
W_VEHICLE = 30   # explicit vehicle or operator: "ferry", "AirAsia", "sleeper"
W_ROAD = 26      # road vehicles, slightly lower so rail/air/water win ties
W_PLACE = 14     # transport infrastructure only hints at the mode
W_SPEND = 22     # non-transport spending categories

# Ordered roughly specific -> generic. Thailand-specific operators and slang
# are included because that is what actually shows up in trip descriptions.
KEYWORD_RULES: tuple[Rule, ...] = (
    # --- air -------------------------------------------------------------
    Rule(Mode.PLANE, Bucket.TRAVEL, (
        "flight", "flights", "airfare", "air fare", "plane", "airline", "airlines",
        "boarding pass", "airasia", "air asia", "nok air", "nokair",
        "bangkok airways", "thai airways", "thai smile", "thai lion", "vietjet",
        "scoot", "indigo", "vistara", "emirates", "etihad", "spicejet", "akasa",
        "web check in", "excess baggage", "seat selection", "e-ticket",
    ), weight=W_VEHICLE),
    # --- rail ------------------------------------------------------------
    Rule(Mode.TRAIN, Bucket.TRAVEL, (
        "train", "rail", "railway", "sleeper", "bts", "mrt", "skytrain",
        "sky train", "airport rail link", "srt", "night train",
        "overnight train", "rabbit card", "metro", "subway", "berth",
    ), weight=W_VEHICLE),
    # --- water -----------------------------------------------------------
    Rule(Mode.FERRY, Bucket.TRAVEL, (
        "ferry", "boat", "speedboat", "speed boat", "longtail", "long tail",
        "long-tail", "catamaran", "lomprayah", "raja ferry", "seatran",
        "river boat", "island hop", "island hopping", "transfer boat",
        "dive boat", "liveaboard",
    ), weight=W_VEHICLE),
    # --- road, shared ----------------------------------------------------
    Rule(Mode.BUS, Bucket.TRAVEL, (
        "bus", "coach", "minivan", "mini van", "van transfer", "shuttle",
        "songthaew", "song thaew", "baht bus", "sprinter", "vip bus",
        "bus ticket", "joint ticket",
    ), weight=W_ROAD + 2),
    # --- road, private ---------------------------------------------------
    Rule(Mode.CAB, Bucket.TRAVEL, (
        "cab", "taxi", "grab", "grabcar", "grab car", "bolt", "uber", "ola",
        "tuk tuk", "tuk-tuk", "tuktuk", "auto", "rickshaw", "meter taxi",
        "airport taxi", "private transfer", "car transfer", "drop off",
        "pickup", "pick up", "toll", "expressway", "indrive", "in drive",
        "cabbie", "driver tip", "private car", "chauffeur",
    ), weight=W_ROAD),
    # --- two wheels ------------------------------------------------------
    Rule(Mode.BIKE, Bucket.TRAVEL, (
        "scooter", "motorbike", "moped", "bike rental", "bicycle", "cycle",
        "motorcycle", "grabbike", "grab bike", "win motorcy", "helmet",
    ), weight=W_ROAD),
    Rule(Mode.WALK, Bucket.TRAVEL, ("walking tour", "free walking", "on foot"), weight=20),
    # --- weak locational hints: only decide the mode when nothing else did -
    Rule(Mode.PLANE, Bucket.TRAVEL, (
        "dmk", "bkk", "cnx", "hkt", "kbv", "usm", "cei", "utp", "airport",
        "terminal 21 airport", "suvarnabhumi", "don mueang", "baggage", "pnr",
    ), weight=W_PLACE),
    Rule(Mode.FERRY, Bucket.TRAVEL, (
        "pier", "jetty", "chao phraya", "tonsai", "ao nang pier",
    ), weight=W_PLACE),
    Rule(Mode.TRAIN, Bucket.TRAVEL, (
        "hua lamphong", "krung thep aphiwat", "station",
    ), weight=W_PLACE),
    # --- fuel / parking sit under travel but draw no line ----------------
    Rule(Mode.NONE, Bucket.TRAVEL, (
        "petrol", "fuel", "gas station", "diesel", "parking", "car rental",
        "rental car", "insurance excess",
    ), weight=24),
    # --- stays -----------------------------------------------------------
    Rule(Mode.NONE, Bucket.STAY, (
        "hotel", "hostel", "resort", "airbnb", "agoda", "booking.com",
        "guesthouse", "guest house", "homestay", "villa", "bungalow",
        "room", "accommodation", "stay", "check-in", "dorm", "capsule",
        "oyo", "treebo", "night charge", "extra bed",
    ), weight=24),
    # --- food ------------------------------------------------------------
    Rule(Mode.NONE, Bucket.FOOD, (
        "food", "lunch", "dinner", "breakfast", "brunch", "cafe", "coffee",
        "restaurant", "street food", "pad thai", "mango sticky", "som tam",
        "tom yum", "khao", "noodle", "noodles", "seafood", "bbq", "buffet",
        "beer", "chang", "leo", "singha", "cocktail", "bucket", "bar",
        "drinks", "smoothie", "shake", "7-eleven", "seven eleven", "711",
        "7/11", "groceries", "grocery", "snacks", "water bottle", "soda",
        "ice cream", "dessert", "rooftop bar", "night market food",
        "swensen", "mcdonald", "kfc", "starbucks", "boba", "bubble tea",
    ), weight=22),
    # --- activities ------------------------------------------------------
    Rule(Mode.NONE, Bucket.ACTIVITY, (
        "tour", "tours", "ticket", "tickets", "entry", "entrance", "pass",
        "museum", "temple", "wat ", "grand palace", "zipline", "atv",
        "elephant", "sanctuary", "snorkel", "snorkelling", "snorkeling",
        "scuba", "diving", "dive", "padi", "kayak", "paddle", "rafting",
        "massage", "spa", "thai massage", "cooking class", "muay thai",
        "show", "cabaret", "ladyboy", "full moon", "party", "club",
        "entrance fee", "national park", "park fee", "viewpoint",
        "safari", "waterfall", "tiger", "aquarium", "bungee", "parasail",
        "jet ski", "yoga", "trek", "trekking", "hike", "zoo", "cinema",
        "island tour", "sunset cruise", "cruise",
    ), weight=W_SPEND),
    # --- shopping --------------------------------------------------------
    Rule(Mode.NONE, Bucket.SHOPPING, (
        "shopping", "souvenir", "souvenirs", "market", "night market",
        "chatuchak", "mbk", "mall", "clothes", "tshirt", "t-shirt", "shirt",
        "shorts", "slippers", "sunglasses", "sunscreen", "pharmacy",
        "medicine", "duty free", "gift", "gifts", "magnet", "pants",
    ), weight=20),
    # --- fees ------------------------------------------------------------
    Rule(Mode.NONE, Bucket.FEES, (
        "visa", "visa fee", "e-visa", "evisa", "insurance", "travel insurance",
        "forex", "atm", "atm fee", "exchange", "currency exchange",
        "bank charge", "conversion fee", "deposit", "tip", "tips",
        "service charge", "laundry", "luggage storage", "locker",
        "sim card", "sim cards", "esim", "e-sim", "data pack",
    ), weight=20),
)

#: Splitwise's own category names -> our buckets/modes. Lower weight than
#: keywords because "Transportation / Other" is vaguer than "Grab to airport".
CATEGORY_RULES: dict[str, tuple[Mode, Bucket]] = {
    "plane": (Mode.PLANE, Bucket.TRAVEL),
    "bus/train": (Mode.TRAIN, Bucket.TRAVEL),
    "bus": (Mode.BUS, Bucket.TRAVEL),
    "train": (Mode.TRAIN, Bucket.TRAVEL),
    "taxi": (Mode.CAB, Bucket.TRAVEL),
    "car": (Mode.CAB, Bucket.TRAVEL),
    "bicycle": (Mode.BIKE, Bucket.TRAVEL),
    "boat": (Mode.FERRY, Bucket.TRAVEL),
    "gas/fuel": (Mode.NONE, Bucket.TRAVEL),
    "parking": (Mode.NONE, Bucket.TRAVEL),
    "transportation": (Mode.NONE, Bucket.TRAVEL),
    "hotel": (Mode.NONE, Bucket.STAY),
    "rent": (Mode.NONE, Bucket.STAY),
    "mortgage": (Mode.NONE, Bucket.STAY),
    "dining out": (Mode.NONE, Bucket.FOOD),
    "groceries": (Mode.NONE, Bucket.FOOD),
    "liquor": (Mode.NONE, Bucket.FOOD),
    "food and drink": (Mode.NONE, Bucket.FOOD),
    "entertainment": (Mode.NONE, Bucket.ACTIVITY),
    "games": (Mode.NONE, Bucket.ACTIVITY),
    "movies": (Mode.NONE, Bucket.ACTIVITY),
    "music": (Mode.NONE, Bucket.ACTIVITY),
    "sports": (Mode.NONE, Bucket.ACTIVITY),
    "clothing": (Mode.NONE, Bucket.SHOPPING),
    "gifts": (Mode.NONE, Bucket.SHOPPING),
    "electronics": (Mode.NONE, Bucket.SHOPPING),
    "medical expenses": (Mode.NONE, Bucket.FEES),
    "insurance": (Mode.NONE, Bucket.FEES),
    "taxes": (Mode.NONE, Bucket.FEES),
    "services": (Mode.NONE, Bucket.FEES),
    "general": (Mode.NONE, Bucket.MISC),
    "uncategorized": (Mode.NONE, Bucket.MISC),
}

CATEGORY_WEIGHT = 12
#: A keyword in the first few words is usually the thing actually bought:
#: "Dinner packed for the train" is food, not rail travel.
HEAD_BONUS = 10
HEAD_WORDS = 3
#: `details`/notes are context rather than the subject, so they score lower.
#: "Elephant sanctuary tour (includes pickup)" is an activity, not a cab.
DETAILS_PENALTY = 8
MAX_WEIGHT = W_VEHICLE + HEAD_BONUS

_TOKEN_SPLIT = re.compile(r"[^a-z0-9/]+")


@dataclass(frozen=True, slots=True)
class Classification:
    mode: Mode
    bucket: Bucket
    confidence: float
    reason: str

    @property
    def draws_line(self) -> bool:
        return self.mode in DRAWABLE_MODES


def _normalise(text: str | None) -> str:
    """Lowercase, strip accents, collapse whitespace. Keeps '/' for 'bus/train'."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(_TOKEN_SPLIT.split(folded.lower())).strip()


def _matches(haystack: str, keyword: str) -> bool:
    """Word-boundary-ish match that still works for multi-word keywords."""
    kw = keyword.strip()
    if not kw:
        return False
    if " " in kw or "/" in kw:
        return kw in haystack
    return re.search(rf"\b{re.escape(kw)}\b", haystack) is not None


#: Public aliases: other modules match place names against expense text with
#: exactly the same normalisation rules the classifier uses.
normalise_text = _normalise
text_matches = _matches


def _score_text(
    text: str,
    scores: dict[tuple[Mode, Bucket], int],
    reasons: dict[tuple[Mode, Bucket], str],
    *,
    head_bonus: bool,
    penalty: int,
    label: str,
) -> None:
    """Fold one text field into the running score table."""
    if not text:
        return
    head = " ".join(text.split()[:HEAD_WORDS])

    for rule in KEYWORD_RULES:
        best_weight = 0
        best_kw = ""
        for kw in rule.keywords:
            if not _matches(text, kw):
                continue
            weight = rule.weight - penalty
            if head_bonus and _matches(head, kw):
                weight += HEAD_BONUS
            if weight > best_weight:
                best_weight, best_kw = weight, kw
        if not best_kw:
            continue
        key = (rule.mode, rule.bucket)
        if best_weight > scores.get(key, 0):
            scores[key] = best_weight
            reasons[key] = f'matched "{best_kw.strip()}" in {label}'


def classify(
    description: str | None,
    category_name: str | None = None,
    details: str | None = None,
) -> Classification:
    """Work out the transport mode and spend bucket for one expense.

    Signal strength, strongest first: a vehicle word near the start of the
    description, the same word later in the description, the Splitwise
    category, then anything found only in the notes.
    """
    scores: dict[tuple[Mode, Bucket], int] = {}
    reasons: dict[tuple[Mode, Bucket], str] = {}

    _score_text(
        _normalise(description), scores, reasons,
        head_bonus=True, penalty=0, label="description",
    )
    _score_text(
        _normalise(details), scores, reasons,
        head_bonus=False, penalty=DETAILS_PENALTY, label="notes",
    )

    category = _normalise(category_name)
    if category:
        hit = CATEGORY_RULES.get(category)
        if hit is None:
            for name, pair in CATEGORY_RULES.items():
                if name in category or category in name:
                    hit = pair
                    break
        if hit is not None and CATEGORY_WEIGHT > scores.get(hit, 0):
            scores[hit] = CATEGORY_WEIGHT
            reasons[hit] = f'Splitwise category "{category_name}"'

    if not scores:
        return Classification(Mode.NONE, Bucket.MISC, 0.0, "no rule matched")

    # Prefer the highest weight; on a tie prefer the one that draws a line,
    # since a drawable mode is strictly more informative for the map.
    best = max(scores.items(), key=lambda kv: (kv[1], kv[0][0] in DRAWABLE_MODES))
    (mode, bucket), weight = best
    confidence = min(1.0, round(weight / MAX_WEIGHT, 2))
    return Classification(mode, bucket, confidence, reasons[(mode, bucket)])


def mode_style(mode: Mode | str) -> dict[str, object]:
    """Lookup styling for a mode, tolerant of raw strings from the DB."""
    try:
        key = Mode(mode)
    except ValueError:
        key = Mode.NONE
    return dict(MODE_STYLE.get(key, {
        "label": "Other", "glyph": "dot", "colour": "#717171",
        "arc": 0.1, "dash": "4 4", "speed": 1.0,
    }))


def bucket_style(bucket: Bucket | str) -> dict[str, str]:
    try:
        key = Bucket(bucket)
    except ValueError:
        key = Bucket.MISC
    return dict(BUCKET_STYLE[key])
