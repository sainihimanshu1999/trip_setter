# Thailand trip dashboard

**Live: <https://sainihimanshu1999.github.io/trip_setter/>**

Shared trip expenses pulled from Splitwise, bookings kept locally, and a
journey map where **every transport line exists because someone split an
expense for it**. Split a Delhi–Bangkok flight and a dashed flight arc draws
itself between those two cities with a plane crawling along it. Hover or click
the line and you get the expense behind it: amount, date, who paid, and
everyone's share.

Python, FastAPI, SQLite, and hand-written SVG. No npm, no bundler, no chart
library — the easing, stagger and theme all match the rest of the page because
the same code draws them.

The published site is the same app rendered ahead of time. GitHub Pages runs no
Python, so `scripts/build_static.py` drives the real FastAPI app through its own
test client and saves what comes out: three HTML pages, thirteen JSON endpoints
and the static assets copied verbatim. Nothing is reimplemented for the static
build, so a bug cannot exist in one and not the other.

---

## Run it

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m uvicorn app.main:app --reload
```

Open <http://localhost:8000>. It starts with realistic sample Thailand data, so
everything works before you connect anything.

---

## Connect your own Splitwise

Two ways in: **CSV import** (free) or **API** (requires Splitwise Pro).

### Option A — CSV import (no Pro subscription needed)

The Splitwise API now requires a Pro subscription for third-party access. If you
don't have Pro, export your group as a spreadsheet instead:

1. Open your trip group on [splitwise.com](https://www.splitwise.com).
2. Click the **settings gear** → **"Export as spreadsheet"**.
3. Drop the downloaded `.csv` into `data/`.
4. Reload. The header badge flips from "Sample data" to your group name.

The app reads the most recently modified `.csv` in `data/`, re-checked on every
request, so a fresh export is picked up without a restart.

> **Keep one CSV in `data/`.** Newest-by-mtime wins, silently. Two exports
> sitting there means a `touch` or an editor save can swap your whole dataset
> with no log line and no sign on the dashboard. `.gitignore` keeps
> `data/archive/` out of the running for exactly this reason.

`data/expenses.csv` is the one tracked file: the upload panel writes it, the
Pages build reads it, and the deploy workflow triggers on it. Pin a different
one with `SPLITWISE_CSV_PATH=data/Thailand_2026.csv`, or set it to `none` to
ignore the folder and stay on sample data.

### Option B — API (requires Splitwise Pro)

1. Subscribe to [Splitwise Pro](https://www.splitwise.com/pro).
2. Register an app at <https://secure.splitwise.com/apps> (any name and URL).
3. Generate a **personal API key** on its detail page.
4. `cp .env.example .env` and set `SPLITWISE_API_KEY=...`
5. Restart. The badge flips to "Live".

> **Data priority:** API key (live) → CSV file (csv) → demo JSON (demo). With
> both a key and a CSV, the API wins.

By default the group whose type is `trip` is picked automatically. To choose
one, hit `/api/groups` for the ids and set `splitwise_group_id` in `trip.toml`.

---

## Configuration

Two files, split by whether the value is a secret.

**`trip.toml` — committed.** Dates, title, currencies, the FX fallback table,
`splitwise_group_id`, the `github_*` publishing settings, cache TTL, seeding.

```toml
trip_title = "Thailand"
trip_start = 2026-10-05
trip_end = 2026-10-17
trip_currency = "THB"
home_currency = "INR"

[fx_rates]
THB = 2.81
USD = 94.94
```

**`.env` — gitignored.** `SPLITWISE_API_KEY`, `GITHUB_TOKEN`, `DATABASE_URL`,
`SPLITWISE_CSV_PATH`.

The split exists because **`.env` never reaches the Pages build.** It is
gitignored, and the workflow does not create one, so anything configured there
applied to the local dashboard and was silently ignored by the published site —
which fell back to the defaults in `app/config.py`. `trip.toml` is read by
both. Change a value, commit, and the deploy follows; it is in the workflow's
path filter, so it redeploys on its own.

Source order, highest first:

| | source | for |
|---|---|---|
| 1 | environment variables | CI, and `scripts/build_static.py` |
| 2 | `.env` | your machine: secrets, local overrides |
| 3 | `trip.toml` | the committed, shared answer |
| 4 | `app/config.py` | defaults, last resort |

`.env` sits above `trip.toml` deliberately, so you can try a different window
locally without committing it. A missing `trip.toml` contributes nothing rather
than failing.

Everything is converted into `home_currency` so a THB ferry ticket and an INR
flight booking can share a chart. Rates come from
[frankfurter.dev](https://frankfurter.dev) (free, no key) and fall back to
`[fx_rates]` when offline. A currency in neither place is passed through **1:1
and logged** — it understates rather than dropping the expense, so add anything
your trip actually spends in.

---

## Publishing

```
Update data (browser)  ->  commits data/expenses.csv  ->  Actions  ->  Pages
Pull latest (local)    <-  reads   data/expenses.csv  <-  GitHub
Refresh    (local)     <-  re-reads the local file only
```

**Update data** appears on the static site and commits a CSV straight to the
repo, which rebuilds and republishes in well under a minute. Either paste a
token or use the no-token fallback, which hands you GitHub's own upload page
authenticated by the session you already have.

**Pull latest** (`POST /api/pull`) brings a published export back down onto your
machine. Without it the flow was one-way: an upload moved the live site forward
while a local checkout kept serving whatever it last had on disk. The repo is
read off your `origin` remote, so a normal clone needs no configuration; a
private repo additionally needs `GITHUB_TOKEN`. The download is **parsed before
it is allowed to replace anything**, so a truncated response or an HTML error
page cannot destroy a working file, and the file it replaces is kept in
`data/archive/`.

**Refresh** (`POST /api/refresh`) only drops the in-process cache and re-reads
the local file plus fresh FX rates. It cannot see a GitHub commit.

Both local buttons hide themselves on the static site, which has no server to
re-read a file or write a pulled one.

---

## What the numbers mean

The two mistakes worth knowing about up front, because both produce figures
that look wrong while every individual number is correct.

### paid, owed, net, balance

Four different quantities. Picking the wrong one is the easiest way to
misread the dashboard.

| field | meaning |
|---|---|
| `paid` | expenses they fronted for the group |
| `settled_out` | money they paid back to someone |
| `paid_total` | `paid + settled_out`. Every rupee they handed over |
| `owed` | their share of the group's spending |
| `settled_in` | money someone paid back to them |
| `owed_total` | `owed + settled_in`. Everything they are on the hook for |
| `net` | `paid − owed`. Did they front the group's costs? Ignores settling up |
| `balance` | `paid_total − owed_total`. Where they stand now |

Paying someone back is money leaving your pocket exactly like paying for a
hotel is, so it counts in `paid_total`. Before it did, Shruti's bar was **zero
length** despite her having handed over ₹67,783 — all of it as repayments.

A worked example from the real data. Himanshu fronted ₹70,805 of a ₹3,45,371
trip, which is more than an even share, and yet he **owes** ₹12,201:

```
fronted       70,805.00   two flights and a train on his own card
paid back     18,899.20   to pranjal
              ---------
handed over   89,704.20   <- the bar

own share     68,300.07   his slice of all seven expenses
repaid to him 33,605.33   from Lakshay
              ---------
on the hook  101,905.40   <- the tick

balance      -12,201.20   he owes this: Lakshay repaid him 33,605
                          when only 21,404 was outstanding
```

So the chart reads directly. **The bar is everything they handed over, the tick
on their row is everything they are on the hook for, and the gap between the
two is their balance** — green when the bar is past the tick and the group owes
them, red when it falls short and they owe. Every bar and tick sits on one
group-wide scale, so rows are comparable. Hover for the arithmetic.

Both sides sum to the same figure, which is the check worth knowing:

```
sum(paid_total) == sum(owed_total) == total_spend + total_settled
```

### Total spent is cost, not cash flow

Two different headline figures, and conflating them double-counts:

| | |
|---|---|
| **Total spent** | ₹3,45,371 — what the trip cost. Real expenses only |
| **Cash that changed hands** | ₹5,52,340 — the above plus ₹2,06,969 of repayments |

A settle-up is not extra spending: it repays a share of an expense already
inside "Total spent". Shruti paying pranjal ₹18,899 is her settling the flight
that is already counted. Adding the two together as spending would count that
money twice, so they are shown as separate tiles.

### `per_head` is an average, not anyone's bill

`total_spend ÷ head_count`. It ignores who was actually on each expense, so it
matches nobody when people skipped some: the average here is ₹57,562 while
actual shares run ₹39,030 to ₹68,300. The tile shows the spread next to the
average for that reason, and each person's real share is the tick on their own
row in the chart.

### An expense date is just a date

This one is load-bearing, and the dashboard used to get it wrong.

A Splitwise expense carries whatever date it was given when it was entered. It
does **not** say anyone was travelling that day, or that a trip was underway.
A flight sits on the day it was paid for, not the day it was taken.

So nothing sorts expenses into inside-the-trip and outside-the-trip. There is
no "booked in advance" figure, no after-the-trip figure, and the day-by-day
chart has no window to draw inside. The axis runs from the earliest dated
expense to the latest, every dated expense is a bar, and therefore:

```
sum(timeline bars) == total_spend        (minus anything with no date at all)
```

That identity is the point. The previous version drew only dates inside
`trip_start..trip_end`, which left ₹84,402 counted in the total and absent from
the chart below it — a dashboard that looked internally consistent while
disagreeing with itself. An expense with no date cannot go on a time axis, so
it is reported as `undated` rather than dropped onto a guessed date.

`trip_start` and `trip_end` still exist, but only to label the trip in the
header. They touch no expense figure.

### Two figures that look like they should agree, and don't

- **"Getting around" ≠ the travel bucket.** Fuel, parking and car rental are
  classified `(mode=none, bucket=travel)`. They are in the travel bucket but
  excluded from the transport KPI, which filters out `mode=none`.
- **Per-person `by_bucket` ≠ global `by_bucket`.** The global one accumulates
  each expense's full value; the per-person one accumulates that person's
  share.

---

## Reading a Splitwise export

`app/csv_import.py`. An export is not a fixed document — it grows every time
you add an expense, and the columns are not promised to stay put.

### The header is read into a dictionary

```
Date, Description, Category, Cost, Currency, <Person 1>, <Person 2>, ...
```

Nothing depends on where a column *sits*. The header is resolved once into a
`ColumnMap` from canonical field name to the spelling this file uses, and every
row is addressed through it. `Expense_Date`, `DATE` and `date` all land on the
same field; so do `Amount`, `Cost` and `Total`.

Anything unrecognised is a person — **except** a known non-person header
(`Notes`, `Deleted At`, `Created By`, …). Without that list, a column Splitwise
adds later would become a group member whose "net" is whatever that column
holds, corrupting every share on every row. Ignored columns are reported, so a
person who goes missing is explainable.

### Identities come from content, not position

- **A person's id is a hash of their name.** It was the column index, which
  broke the moment two exports of the same trip listed the six members in
  different orders — every person silently inherited whoever had occupied their
  column.
- **An expense's id is a hash of its date, description, cost and currency**,
  with an occurrence counter so genuine duplicates stay distinct. It was the
  row number, so inserting a row repointed every id after it.

### Reconstructing `paid` and `owed`

The export gives only each person's **net** for a row: positive means they are
owed, negative means they owe. The API reports `paid` and `owed` separately, so
they are rebuilt:

- **net < 0** — paid nothing, owes exactly `−net`.
- **net > 0** — fronted money. What the payers owe between them is
  `cost − (what the debtors owe)`, split across payers in proportion to their
  net. Their `paid` is then `net + owed`.
- **net == 0** — not in this expense. Someone who paid exactly their own share
  looks identical here, but splitting the cost with them anyway would invent
  money the `Cost` column does not account for and credit someone who was not
  there.

When the nets sum to zero and someone fronted money, this keeps both
`sum(paid) == cost` and `sum(owed) == cost`. Rows that break either
precondition are reconstructed as best they can be and **recorded**, never
silently fudged:

| flag | meaning |
|---|---|
| `cost_below_splits` | debtor shares exceed `Cost`; the payer's share would go negative, so it is clamped at zero |
| `no_payer` | no column has a positive net, so nothing carries the row's cost |
| `missing_currency` | blank Currency cell; defaulted to `trip_currency` |
| `unparsed_date` | date cell in no recognised format |

### Money cells

Grouping is ambiguous across locales and the export does not say which it used,
so the separator nearest the end decides. `1,200.50` and `1.200,50` both read as
1200.50. A bare `18899,20` is a decimal comma, because reading it as grouping
would give 1889920 and inflate the row a hundredfold with nothing looking
wrong. A comma-only value is grouped when its last group is three digits, which
covers Western `12,345,678` and Indian `1,23,456` alike.

`NaN`, `Infinity` and `sNaN` are **rejected**. `Decimal` accepts all three as
literals, and a NaN compares `False` against everything, so no threshold check
catches it — it would spread through every total and then serialise as a bare
`NaN` token that breaks `JSON.parse` in the browser.

### Settle-ups

The export has no `payment` flag, so a row is a settle-up when its description
or category contains `payment`, `settle up`, `settled up`, `settle all` or
`repayment`. Settle-ups move money between people without being trip spending:
they affect balances, never totals.

This is substring matching, which cuts both ways. "Hotel payment" would be
treated as a settle-up and vanish from every spend figure; a settle-up with a
custom description would be counted as spending. `/api/ingest` lists every row
it flagged, which is where to look if a total is off by exactly one expense.

### Does it add up?

`GET /api/ingest` reports what the header was understood to mean, which rows
were skipped and why, every anomaly above, and four checks:

| check | catches |
|---|---|
| `paid_matches_total` | shares that do not reconstruct to the total |
| `owed_matches_total` | the same at the other end |
| `balances_sum_to_zero` | a sign error in the reconstruction |
| `chart_matches_total` | money in a total but missing from the timeline |

If one stops matching it says so, instead of showing a plausible wrong number.

---

## The three pages

**Dashboard** — total spend, each person's share, per-person bars with a tick
at the even split and each person's real balance beside their name, category
breakdown, spend per expense date, and who owes whom as both a list and an arc
graph. Everyone gets a colour and an avatar derived from their name, so the
same person reads the same way on every chart.

**Journey map** — the full route. Click a city for its spend, bookings and
biggest expenses. Click a line for the expenses behind it. Legend chips filter
by transport mode.

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

Every result carries the reason it matched, so the UI can explain itself on
hover. The classifier only labels — it can move money between buckets, never
change a total.

`app/journey.py` then decides where each expense sits:

- **Place attribution** uses the date first. On a travel day the date covers two
  cities, so the description breaks the tie, and failing that it assumes the
  city you were heading to.
- **Leg matching needs evidence**, not just a nearby date: the operator name,
  the ticket reference, or both endpoints named. A flight expense is allowed up
  to a 60-day gap from its leg, precisely because a booking date is not a
  travel date. That is why a flight bought three months early still attaches,
  and why a round-trip boat tour out of Krabi is not mistaken for the ferry to
  Phi Phi.
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

## Colour

The backend owns every colour; the frontend hardcodes none. `GET /api/meta`
serves the tokens.

- **People** get a colour by their position in the paid-ranked list, from a
  ten-colour palette chosen for contrast against white, against each other, and
  for colour-blind safety. Avatars are derived from the name, so the same person
  looks the same everywhere.
- **Transport modes** have their own seven colours, and a mode's colour is also
  its line colour on the map.
- **Spend buckets** have seven more, and **no bucket colour may equal a mode
  colour.** The category breakdown sits beside the map's mode legend on the
  dashboard, and the two palettes used to be the same list: "Getting around"
  was drawn in the plane blue and "Stays" in the train violet, so accommodation
  appeared in the colour the map uses for rail.

Dark mode resolves to an explicit `data-theme` attribute in an inline `<head>`
script before first paint, so the stylesheet needs one palette instead of the
same tokens twice, and a dark-mode user never sees a white flash.

---

## Layout

```
app/
  config.py      settings: env vars, .env, then trip.toml
  classify.py    expense -> transport mode + spend bucket
  csv_import.py  Splitwise CSV export: column dictionary, stable ids, report
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
  expenses.csv          your export (tracked; the site builds from it)
  archive/              superseded exports (gitignored)
  trip.db               your bookings (created on first run)
scripts/
  build_static.py       renders the site for GitHub Pages
  make_demo_data.py     regenerates the sample data
tests/
trip.toml        trip dates, currencies, FX fallback (committed)
.env             secrets and machine-local overrides (gitignored)
```

**Expenses are never stored in the database.** `models.py` defines only
`Place`, `Leg` and `Booking`. The whole Splitwise dataset is re-parsed on every
request, folded into an in-memory `Analytics`, and thrown away. So `trip.db`
cannot be the source of a wrong expense figure — only a wrong booking.

Demo data uses the exact shape of a real `GET /get_expenses` response, so demo
mode and live mode run through the same parsing code and a parsing bug shows up
in both.

---

## API

| Endpoint | What it gives you |
|---|---|
| `GET /api/overview` | totals, per-person figures, settlements, FX state |
| `GET /api/people` | the expenditure bar data, with `paid_total` and `owed_total` |
| `GET /api/categories` | spend by bucket |
| `GET /api/modes` | spend by transport mode |
| `GET /api/timeline` | spend per expense date |
| `GET /api/settlements` | who pays whom, and live balances |
| `GET /api/expenses` | classified expenses; `?mode=`, `?bucket=`, `?limit=` |
| `GET /api/journey` | nodes and edges for the map |
| `GET /api/places`, `/api/legs` | the itinerary |
| `GET /api/meta` | colour and glyph tokens |
| `GET /api/ingest` | how the data parsed, and whether the totals reconcile |
| `GET/POST/PATCH/DELETE /api/bookings` | booking CRUD |
| `GET /api/groups` | your Splitwise groups, to find a group id |
| `POST /api/refresh` | drop the cache and re-read the local file |
| `POST /api/pull` | fetch the published export from GitHub |

Interactive docs at `/docs`.

---

## Tests

```bash
./.venv/bin/python -m pytest tests/ -q
```

Covers the classifier (including every case that was wrong first time), that
money adds up and settlements actually settle, that a person keeps their id
when an export reorders its columns and an expense keeps its id when rows are
appended, that every dated expense reaches the timeline, that map nodes never
overlap and no expense lands on two edges, plus every endpoint, page and CRUD
path.

The deploy runs them before it publishes, so a parsing regression stops the
build instead of reaching the site.

---

## Notes

- Expenses are **read-only**. Nothing here writes to your Splitwise account.
- Responses are cached for `cache_ttl_seconds` (default 120) because the
  Splitwise API is rate limited. "Refresh" clears it. CSV mode is not cached —
  the file is re-read every request.
- If Splitwise is unreachable the dashboard falls back to sample data with a
  banner rather than erroring.
- A partial live FX response still reports the whole table as live, while some
  rates stay on the static snapshot. `GET /api/overview` returns the FX source
  and date it is actually using.
- Booking links are restricted to `http(s)` so a stored `javascript:` URL
  cannot execute when you click a card.
- Respects `prefers-reduced-motion`: all animation is dropped, every final
  state stays visible.
- The Splitwise self-serve API is for personal, non-commercial use. See their
  [terms](https://dev.splitwise.com/).
