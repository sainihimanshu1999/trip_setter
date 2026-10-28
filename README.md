# Thailand trip dashboard

Shared trip expenses pulled from Splitwise, bookings kept locally, and a
journey map where **every transport line exists because someone split an
expense for it**. Split a Delhi–Bangkok flight and a dashed flight arc draws
itself between those two cities with a plane crawling along it. Hover or click
the line and you get the expense behind it: amount, date, who paid, and
everyone's share.

Python, FastAPI, SQLite, and hand-written SVG. No npm, no build step.

---

## Run it

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m uvicorn app.main:app --reload
```

Open <http://localhost:8000>. It starts with realistic sample Thailand data, so
everything works before you connect anything.

### Connect your own Splitwise

There are two ways to get your real data in: **CSV import** (free) or **API**
(requires Splitwise Pro).

#### Option A — CSV import (no Pro subscription needed)

The Splitwise API now requires a Pro subscription for third-party access. If
you don't have Pro, export your group as a spreadsheet instead:

1. Open your trip group on [splitwise.com](https://www.splitwise.com).
2. Click the **settings gear** → **"Export as spreadsheet"**.
3. Drop the downloaded `.csv` file into the `data/` folder.
4. Restart. The header badge flips from "Sample data" to your group name.

The app auto-detects `.csv` files in `data/` and reads the most recently
modified one, so a fresh export is picked up without a restart. To pin a
specific file instead:

```ini
SPLITWISE_CSV_PATH=data/Thailand_2026.csv
```

Set `SPLITWISE_CSV_PATH=none` to ignore the folder entirely and stay on sample
data.

To refresh, re-export from Splitwise, drop the file in `data/`, and hit the
"Refresh" button (or `POST /api/refresh`).

#### Option B — API (requires Splitwise Pro)

1. Subscribe to [Splitwise Pro](https://www.splitwise.com/pro).
2. Go to <https://secure.splitwise.com/apps> and register an application (any
   name and URL will do, e.g. "Trip dashboard" / `http://localhost:8000`).
3. Open the app's detail page and generate a **personal API key**.
4. `cp .env.example .env` and set `SPLITWISE_API_KEY=...`
5. Restart. The header badge flips from "Sample data" to "Live".

> **Data priority:** API key (live) → CSV file (csv) → demo JSON (demo).
> If you have both an API key and a CSV, the API wins.

By default the app picks the Splitwise group whose type is `trip`. To choose a
specific one, hit `/api/groups` to list your groups and put the id in
`SPLITWISE_GROUP_ID`.

Set your trip dates and currencies in `.env` too:

```ini
TRIP_START=2026-10-05
TRIP_END=2026-10-17
TRIP_CURRENCY=THB
HOME_CURRENCY=INR
```

Everything is converted into `HOME_CURRENCY` so a THB ferry ticket and an INR
flight booking can share a chart. Rates come from
[frankfurter.dev](https://frankfurter.dev) (free, no key) and fall back to the
static table in `.env` when offline.

---

## The three pages

**Dashboard** — total spend, each person's share, per-person expenditure bars
with a tick showing the even split, category breakdown, the day-by-day
timeline, and who owes whom as both a list and an arc graph. Everyone gets a
colour and an avatar, both derived from their name, so the same person reads
the same way on every chart.

**Journey map** — the full route. Click a city for its spend, bookings and
biggest expenses. Click a line for the expenses behind it. Legend chips
filter by transport mode.

**Bookings & tours** — every flight, stay, tour, transfer and visa with its
link, description, dates, cost, confirmation reference and your own notes.
Filter by kind, add and edit inline. This is the part Splitwise cannot store.

---

## How a cab split becomes a cab line

```
Splitwise expense  ->  classify()  ->  attribute to place  ->  match to leg  ->  edge
"Grab to DMK"          mode=cab        Bangkok (by keyword,   no cab leg       cab petal
                       bucket=travel   "dmk")                 exists           at Bangkok

"Bkk to surat          mode=train      Bangkok (by date)      Bangkok ->       train arc
 thani train"          bucket=travel                          Koh Samui leg    between them
```

`app/classify.py` scores keywords against the description, the notes and the
Splitwise category. Three rules earn their keep:

- **A vehicle word beats a destination word.** "Grab to DMK airport" is a cab
  ride, not a flight, so airport codes and piers score below taxi keywords.
- **The first few words win.** "Dinner packed for the train" is food. The head
  of the description names the thing bought; later words only qualify it.
- **Notes are weaker than the description.** "Elephant sanctuary tour (includes
  pickup)" is an activity, not a cab.

`app/journey.py` then decides where each expense sits:

- **Place attribution** uses the date first. On a travel day the date covers two
  cities, so the description breaks the tie, and failing that it assumes the
  city you were heading to.
- **Leg matching needs evidence**, not just a nearby date: the operator name,
  the ticket reference, or both endpoints named. That is why a flight booked
  three months early still attaches to its leg, and why a round-trip boat tour
  out of Krabi does not get mistaken for the ferry to Phi Phi.
- Transport that does not cross cities becomes a **local edge**: a petal looping
  off that city's node. Cabs, tuk tuks, the Skytrain.
- An itinerary leg with **no expense yet** still draws, but as a faint ghost, so
  you can see what is planned versus what is paid for.

### Map layout

Each place is a Google-Maps-style pin whose head grows with the money spent
there, and whose tip marks the actual coordinate. A pin gets a small bed badge
when something is booked to sleep there.

Cities in the trip's main country are projected geographically. Anywhere else
is a *gateway* pinned to the canvas edge along its true compass bearing,
because putting Delhi and Phuket in one linear projection squashes Thailand
into a smudge. Several gateways are staggered along that bearing so Delhi and
Bangalore do not stack. A relaxation pass then pushes overlapping pins apart
and the backend decides which side of each pin has room for its label, so a
name never lands on the pin above it.

---

## Layout

```
app/
  config.py      settings from .env
  classify.py    expense -> transport mode + spend bucket
  csv_import.py  reads Splitwise CSV export (no API key needed)
  domain.py      Person / Share / Expense / TripData
  splitwise.py   async API client: cache, backoff, demo fallback
  fx.py          currency conversion
  analytics.py   per-person totals, breakdowns, settlements
  models.py      SQLAlchemy: Place, Leg, Booking
  db.py          engine, sessions, schema init
  seed.py        the itinerary: places, legs and bookings
  journey.py     nodes and edges for the map
  schemas.py     booking request validation
  deps.py        shared request dependencies
  routers/       api.py (JSON) + pages.py (HTML)
  templates/     base, dashboard, journey, bookings
  static/        theme.css + app/charts/journey/bookings .js
data/
  demo_splitwise.json   sample data in the real API's shape
  trip.db               your bookings (created on first run)
scripts/
  make_demo_data.py     regenerates the sample data
tests/
```

Demo data uses the exact shape of a real `GET /get_expenses` response, so demo
mode and live mode run through the same parsing code and a parsing bug shows up
in both.

---

## API

| Endpoint | What it gives you |
|---|---|
| `GET /api/overview` | totals, per-person figures, settlements, FX state |
| `GET /api/people` | the expenditure bar data |
| `GET /api/categories` | spend by bucket |
| `GET /api/modes` | spend by transport mode |
| `GET /api/timeline` | daily spend across the trip window |
| `GET /api/settlements` | who pays whom, and live balances |
| `GET /api/expenses` | classified expenses; `?mode=`, `?bucket=`, `?limit=` |
| `GET /api/journey` | nodes and edges for the map |
| `GET /api/places`, `/api/legs` | the itinerary |
| `GET /api/meta` | colour and glyph tokens |
| `GET/POST/PATCH/DELETE /api/bookings` | booking CRUD |
| `GET /api/groups` | your Splitwise groups, to find a group id |
| `POST /api/refresh` | drop the cache and re-pull |

Interactive docs at `/docs`.

---

## Tests

```bash
./.venv/bin/python -m pytest tests/ -q
```

Covers the classifier (including every case that was wrong first time), that
money adds up and settlements actually settle, that map nodes never overlap and
no expense lands on two edges, plus every endpoint, page and CRUD path.

---

## Notes

- Expenses are **read-only**. Nothing here writes to your Splitwise account.
- Responses are cached for `CACHE_TTL_SECONDS` (default 120) because the
  Splitwise API is rate limited. "Refresh" clears it.
- If Splitwise is unreachable the dashboard falls back to sample data with a
  banner rather than erroring.
- Booking links are restricted to `http(s)` so a stored `javascript:` URL
  cannot execute when you click a card.
- Respects `prefers-reduced-motion`: all animation is dropped, every final
  state stays visible.
- The Splitwise self-serve API is for personal, non-commercial use. See their
  [terms](https://dev.splitwise.com/).
