"""Generate `data/demo_splitwise.json` in the exact shape of a real
`GET /get_expenses` + `GET /get_group/{id}` response.

Using the real payload shape means demo mode exercises the same parsing code as
live mode, so a bug in parsing shows up in demo too. Run with:

    python scripts/make_demo_data.py
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "demo_splitwise.json"

MEMBERS = [
    {"id": 101, "first_name": "Himanshu", "last_name": "Saini"},
    {"id": 102, "first_name": "Aarav", "last_name": "Mehta"},
    {"id": 103, "first_name": "Meera", "last_name": "Iyer"},
    {"id": 104, "first_name": "Rohan", "last_name": "Kapoor"},
]
ALL = [m["id"] for m in MEMBERS]
NAMES = {m["id"]: m for m in MEMBERS}

# (date, description, category, cost, currency, payer, participants, details)
E = [
    # --- pre-trip, booked from home in INR ------------------------------
    ("2025-12-02", "IndiGo flights Delhi to Bangkok (4 pax)", "Plane", "71600", "INR", 101, ALL,
     "6E 1051 DEL-BKK, booked on goindigo.in, PNR R4T9KQ"),
    ("2025-12-05", "Thailand visa fee x4", "General", "9600", "INR", 102, ALL,
     "e-Visa processed online"),
    ("2025-12-09", "Travel insurance", "Insurance", "4800", "INR", 103, ALL, ""),
    ("2025-12-14", "Bangkok hotel deposit - Riverside", "Hotel", "18400", "INR", 101, ALL,
     "Agoda booking, 3 nights, 2 twin rooms"),

    # --- day 1, Bangkok --------------------------------------------------
    ("2026-01-10", "Grab to DMK airport", "Taxi", "1180", "INR", 104, ALL, "2 cabs from Dwarka"),
    ("2026-01-10", "Airport Rail Link to Phaya Thai", "Bus/train", "180", "THB", 102, ALL, ""),
    ("2026-01-10", "Grab to hotel", "Taxi", "220", "THB", 101, ALL, ""),
    ("2026-01-10", "AIS tourist SIM cards x4", "General", "1196", "THB", 103, ALL, "15GB, 8 days"),
    ("2026-01-10", "First night dinner - Thipsamai pad thai", "Dining out", "980", "THB", 104, ALL, ""),

    # --- day 2, Bangkok temples -----------------------------------------
    ("2026-01-11", "Grand Palace entry tickets", "Entertainment", "2000", "THB", 101, ALL,
     "500 THB each"),
    ("2026-01-11", "Tuk tuk to Wat Pho", "Taxi", "300", "THB", 102, ALL, "Haggled down from 500"),
    ("2026-01-11", "Chao Phraya river boat day pass", "Transportation", "600", "THB", 103, ALL, ""),
    ("2026-01-11", "Street food lunch at Tha Tien", "Dining out", "520", "THB", 104, ALL, ""),
    ("2026-01-11", "Thai massage x4", "Entertainment", "1600", "THB", 101, ALL,
     "Wat Pho massage school"),
    ("2026-01-11", "Rooftop bar at Sala Rattanakosin", "Liquor", "2400", "THB", 102, ALL, ""),

    # --- day 3, Bangkok markets -----------------------------------------
    ("2026-01-12", "BTS Rabbit cards top up", "Bus/train", "800", "THB", 103, ALL, ""),
    ("2026-01-12", "Chatuchak weekend market shopping", "Clothing", "3200", "THB", 104, ALL,
     "Shirts and souvenirs"),
    ("2026-01-12", "7-Eleven snacks and water", "Groceries", "340", "THB", 101, ALL, ""),
    ("2026-01-12", "Muay Thai tickets Rajadamnern", "Entertainment", "6000", "THB", 102, ALL,
     "Ringside, booked via muaythai.com"),
    ("2026-01-12", "Dinner - Jay Fai area", "Dining out", "1850", "THB", 103, ALL, ""),

    # --- day 4, fly to Chiang Mai ---------------------------------------
    ("2026-01-13", "Grab to DMK terminal 2", "Taxi", "420", "THB", 104, ALL, ""),
    ("2026-01-13", "AirAsia FD3435 BKK-CNX", "Plane", "4760", "THB", 101, ALL,
     "Booked on airasia.com, 20kg baggage added"),
    ("2026-01-13", "Songthaew to Old City", "Transportation", "240", "THB", 102, ALL,
     "Red truck, 60 THB each"),
    ("2026-01-13", "Chiang Mai guesthouse 3 nights", "Hotel", "9600", "THB", 103, ALL,
     "Booking.com, Old City near Tha Phae Gate"),
    ("2026-01-13", "Khao soi dinner", "Dining out", "480", "THB", 104, ALL, ""),

    # --- day 5, elephants -----------------------------------------------
    ("2026-01-14", "Elephant Nature Park full day tour", "Entertainment", "10000", "THB", 101, ALL,
     "Ethical sanctuary, includes pickup and lunch"),
    ("2026-01-14", "Night Bazaar street food", "Dining out", "760", "THB", 102, ALL, ""),
    ("2026-01-14", "Chang beers at Zoe in Yellow", "Liquor", "900", "THB", 103, ALL, ""),

    # --- day 6, cooking + temples ---------------------------------------
    ("2026-01-15", "Thai cooking class", "Entertainment", "4800", "THB", 104, ALL,
     "Thai Farm Cooking School, market tour included"),
    ("2026-01-15", "Scooter rental x2 for Doi Suthep", "Bicycle", "600", "THB", 101, ALL,
     "250 THB per bike per day plus helmets"),
    ("2026-01-15", "Doi Suthep entrance", "Entertainment", "120", "THB", 102, [101, 102, 103], ""),
    ("2026-01-15", "Petrol for scooters", "Gas/fuel", "160", "THB", 103, ALL, ""),

    # --- day 7, overnight train -----------------------------------------
    ("2026-01-16", "Overnight sleeper train CNX to Bangkok", "Bus/train", "3608", "THB", 101, ALL,
     "Train 10, second class AC sleeper, lower berths"),
    ("2026-01-16", "Taxi to Chiang Mai station", "Taxi", "200", "THB", 102, ALL, ""),
    ("2026-01-16", "Dinner packed for the train", "Groceries", "420", "THB", 103, ALL, ""),

    # --- day 8, fly to Krabi --------------------------------------------
    ("2026-01-17", "Thai Lion Air to Krabi", "Plane", "5240", "THB", 104, ALL, "SL762 DMK-KBV"),
    ("2026-01-17", "Airport taxi to Ao Nang", "Taxi", "800", "THB", 101, ALL, ""),
    ("2026-01-17", "Ao Nang beachfront hotel 2 nights", "Hotel", "7800", "THB", 102, ALL, ""),
    ("2026-01-17", "Seafood dinner on Ao Nang beach", "Dining out", "2100", "THB", 103, ALL, ""),

    # --- day 9, islands --------------------------------------------------
    ("2026-01-18", "Longtail boat 4 islands tour", "Transportation", "4800", "THB", 104, ALL,
     "Private longtail, Chicken Island, Tup, Poda, Railay"),
    ("2026-01-18", "National park fee", "General", "1600", "THB", 101, ALL, "400 THB each"),
    ("2026-01-18", "Lunch at Railay Beach", "Dining out", "880", "THB", 102, ALL, ""),
    ("2026-01-18", "Sunscreen and beach stuff", "General", "650", "THB", 103, ALL, ""),

    # --- day 10, ferry to Phi Phi ---------------------------------------
    ("2026-01-19", "Ferry Ao Nang pier to Phi Phi", "Transportation", "1600", "THB", 104, ALL,
     "Ao Nang Princess, 400 THB each"),
    ("2026-01-19", "Phi Phi hotel 1 night", "Hotel", "4200", "THB", 101, ALL, ""),
    ("2026-01-19", "Snorkelling trip to Maya Bay", "Entertainment", "5200", "THB", 102, ALL,
     "Speedboat, early morning to beat crowds"),
    ("2026-01-19", "Phi Phi beach bar buckets", "Liquor", "1400", "THB", 103, [101, 102, 104], ""),

    # --- day 11, Phuket --------------------------------------------------
    ("2026-01-20", "Ferry Phi Phi to Phuket", "Transportation", "1800", "THB", 101, ALL, ""),
    ("2026-01-20", "Taxi Rassada pier to Patong", "Taxi", "700", "THB", 102, ALL, ""),
    ("2026-01-20", "Patong hotel last night", "Hotel", "5600", "THB", 103, ALL, ""),
    ("2026-01-20", "Simon Cabaret show", "Entertainment", "3200", "THB", 104, ALL, ""),
    ("2026-01-20", "Last dinner - Kalim seafood", "Dining out", "2600", "THB", 101, ALL, ""),
    ("2026-01-20", "Duty free and gifts", "Gifts", "4100", "THB", 102, ALL, ""),

    # --- day 12, home ----------------------------------------------------
    ("2026-01-21", "Grab to Phuket airport", "Taxi", "900", "THB", 103, ALL, ""),
    ("2026-01-21", "Airport lunch before HKT-DEL", "Dining out", "1240", "THB", 104, ALL, ""),
    ("2026-01-21", "Excess baggage HKT-DEL", "Plane", "2400", "THB", 101, ALL, ""),
]

# Settle-up payments, which the API marks with payment=true.
PAYMENTS = [
    ("2026-01-22", "Aarav paid Himanshu", "12000", "INR", 102, 101),
    ("2026-01-23", "Rohan paid Himanshu", "8500", "INR", 104, 101),
]

CENTS = Decimal("0.01")


def q(value: Decimal) -> str:
    return str(value.quantize(CENTS, rounding=ROUND_HALF_UP))


def user_blob(uid: int) -> dict:
    m = NAMES[uid]
    return {
        "id": uid,
        "first_name": m["first_name"],
        "last_name": m["last_name"],
        "picture": {"medium": None, "small": None, "large": None},
        "custom_picture": False,
        "registration_status": "confirmed",
    }


def split_equally(cost: Decimal, participants: list[int]) -> dict[int, Decimal]:
    """Even split with the rounding remainder pushed onto the first person,
    exactly how Splitwise keeps shares summing to the total."""
    n = len(participants)
    base = (cost / n).quantize(CENTS, rounding=ROUND_HALF_UP)
    shares = {uid: base for uid in participants}
    drift = cost - base * n
    if drift:
        shares[participants[0]] = (shares[participants[0]] + drift).quantize(CENTS)
    return shares


def build() -> dict:
    expenses = []
    eid = 500100

    for day, desc, category, cost_s, currency, payer, participants, details in E:
        eid += 1
        cost = Decimal(cost_s)
        owed = split_equally(cost, participants)
        users = []
        for uid in participants:
            paid = cost if uid == payer else Decimal("0")
            users.append({
                "user": user_blob(uid),
                "user_id": uid,
                "paid_share": q(paid),
                "owed_share": q(owed[uid]),
                "net_balance": q(paid - owed[uid]),
            })
        if payer not in participants:  # payer not sharing the cost
            users.append({
                "user": user_blob(payer),
                "user_id": payer,
                "paid_share": q(cost),
                "owed_share": "0.00",
                "net_balance": q(cost),
            })

        repayments = [
            {"from": uid, "to": payer, "amount": q(owed[uid])}
            for uid in participants
            if uid != payer
        ]

        expenses.append({
            "id": eid,
            "group_id": 7731,
            "friendship_id": None,
            "expense_bundle_id": None,
            "description": desc,
            "repeats": False,
            "repeat_interval": "never",
            "email_reminder": False,
            "email_reminder_in_advance": -1,
            "next_repeat": None,
            "details": details or None,
            "comments_count": 0,
            "payment": False,
            "transaction_confirmed": False,
            "cost": q(cost),
            "currency_code": currency,
            "repayments": repayments,
            "date": f"{day}T09:00:00Z",
            "created_at": f"{day}T09:05:00Z",
            "created_by": user_blob(payer),
            "updated_at": f"{day}T09:05:00Z",
            "updated_by": None,
            "deleted_at": None,
            "deleted_by": None,
            "category": {"id": 18, "name": category},
            "receipt": {"large": None, "original": None},
            "users": users,
        })

    for day, desc, amount_s, currency, payer, payee in PAYMENTS:
        eid += 1
        amount = Decimal(amount_s)
        expenses.append({
            "id": eid,
            "group_id": 7731,
            "description": desc,
            "details": None,
            "payment": True,
            "transaction_confirmed": True,
            "cost": q(amount),
            "currency_code": currency,
            "repayments": [{"from": payer, "to": payee, "amount": q(amount)}],
            "date": f"{day}T12:00:00Z",
            "created_at": f"{day}T12:00:00Z",
            "created_by": user_blob(payer),
            "updated_at": f"{day}T12:00:00Z",
            "deleted_at": None,
            "category": {"id": 18, "name": "Payment"},
            "receipt": {"large": None, "original": None},
            "users": [
                {
                    "user": user_blob(payer), "user_id": payer,
                    "paid_share": q(amount), "owed_share": "0.00",
                    "net_balance": q(amount),
                },
                {
                    "user": user_blob(payee), "user_id": payee,
                    "paid_share": "0.00", "owed_share": q(amount),
                    "net_balance": q(-amount),
                },
            ],
        })

    group = {
        "id": 7731,
        "name": "Thailand 2026",
        "group_type": "trip",
        "updated_at": "2026-01-23T12:00:00Z",
        "simplify_by_default": True,
        "members": [
            {**user_blob(m["id"]), "balance": [{"currency_code": "THB", "amount": "0.0"}]}
            for m in MEMBERS
        ],
        "original_debts": [],
        "simplified_debts": [],
        "invite_link": "https://www.splitwise.com/join/demo",
    }

    return {"group": group, "expenses": expenses}


def main() -> None:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    total = sum(Decimal(e["cost"]) for e in payload["expenses"] if not e["payment"])
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  {len(payload['expenses'])} expenses, {len(MEMBERS)} people")
    print(f"  gross cost across currencies: {total}")


if __name__ == "__main__":
    main()
