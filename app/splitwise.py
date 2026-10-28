"""Async Splitwise API client.

Base URL and field names follow the official spec:
https://github.com/splitwise/api-docs (servers: https://secure.splitwise.com/api/v3.0)
Auth is a personal API key presented as an HTTP bearer token.

Three things matter here beyond plain HTTP:

* **Caching.** The API is rate limited, so identical requests inside the TTL
  window are served from memory.
* **Backoff.** A 429 or 5xx is retried with exponential backoff.
* **Graceful degradation.** With no key, or if the API is unreachable, we fall
  back to bundled demo data that has the exact shape of a real response, so the
  dashboard always renders and the parsing path is identical either way.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import DATA_DIR, Settings
from .csv_import import load_csv
from .domain import Expense, Person, TripData

log = logging.getLogger("trip.splitwise")

BASE_URL = "https://secure.splitwise.com/api/v3.0"
PAGE_SIZE = 100
MAX_PAGES = 25
DEMO_FILE = DATA_DIR / "demo_splitwise.json"


class SplitwiseError(RuntimeError):
    """Raised when the API answers with something we cannot use."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _TTLCache:
    """Tiny in-process cache. Plenty for a single-user dashboard."""

    def __init__(self, ttl: int) -> None:
        self.ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if time.monotonic() - stored_at > self.ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._store.clear()


class SplitwiseClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache = _TTLCache(settings.cache_ttl_seconds)
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------------- http

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=httpx.Timeout(20.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.settings.splitwise_api_key.strip()}",
                    "Accept": "application/json",
                    "User-Agent": "trip-dashboard/1.0 (personal, non-commercial)",
                },
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """GET with cache, then retry on 429/5xx."""
        key = f"{path}?{json.dumps(params or {}, sort_keys=True)}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        client = await self._http()
        delay = 1.0
        last_error: Exception | None = None

        for attempt in range(4):
            try:
                response = await client.get(path, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning("Splitwise %s network error (try %d): %s", path, attempt + 1, exc)
            else:
                if response.status_code == 200:
                    payload = response.json()
                    self._cache.set(key, payload)
                    return payload
                if response.status_code in (401, 403):
                    raise SplitwiseError(
                        "Splitwise rejected the API key. Generate a fresh one at "
                        "https://secure.splitwise.com/apps and put it in .env as "
                        "SPLITWISE_API_KEY.",
                        response.status_code,
                    )
                if response.status_code == 404:
                    raise SplitwiseError(f"Splitwise has no {path}", 404)
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                    log.warning(
                        "Splitwise %s returned %d, retrying in %.1fs",
                        path, response.status_code, wait,
                    )
                    last_error = SplitwiseError(
                        f"Splitwise returned {response.status_code}", response.status_code
                    )
                    await asyncio.sleep(wait)
                    delay = min(delay * 2, 8.0)
                    continue
                raise SplitwiseError(
                    f"Splitwise returned {response.status_code}: {response.text[:200]}",
                    response.status_code,
                )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8.0)

        raise SplitwiseError(f"Splitwise unreachable after retries: {last_error}")

    # ------------------------------------------------------- raw endpoints

    async def get_current_user(self) -> dict:
        return (await self._get("/get_current_user")).get("user") or {}

    async def get_groups(self) -> list[dict]:
        return (await self._get("/get_groups")).get("groups") or []

    async def get_group(self, group_id: int) -> dict:
        return (await self._get(f"/get_group/{group_id}")).get("group") or {}

    async def get_expenses(self, group_id: int | None, limit: int = PAGE_SIZE,
                           offset: int = 0) -> list[dict]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if group_id:
            params["group_id"] = group_id
        return (await self._get("/get_expenses", params)).get("expenses") or []

    async def get_all_expenses(self, group_id: int | None) -> list[dict]:
        """Page through every expense in the group."""
        out: list[dict] = []
        for page in range(MAX_PAGES):
            batch = await self.get_expenses(group_id, PAGE_SIZE, page * PAGE_SIZE)
            out.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        return out

    # ------------------------------------------------------- orchestration

    async def resolve_group_id(self) -> tuple[int | None, str]:
        """Use the configured group, else auto-pick the user's trip group."""
        if self.settings.splitwise_group_id:
            gid = self.settings.splitwise_group_id
            try:
                group = await self.get_group(gid)
                return gid, group.get("name") or f"Group {gid}"
            except SplitwiseError:
                return gid, f"Group {gid}"

        groups = await self.get_groups()
        real = [g for g in groups if g.get("id")]
        trips = [g for g in real if (g.get("group_type") or "") == "trip"]
        pool = trips or real
        if not pool:
            return None, "All expenses"

        def updated(group: dict) -> str:
            return group.get("updated_at") or ""

        chosen = max(pool, key=updated)
        return int(chosen["id"]), chosen.get("name") or "Trip"

    async def fetch_trip(self) -> TripData:
        """Everything the dashboard needs, or demo data if that's impossible.

        Priority: API key (live) → CSV file (csv) → demo JSON (demo).
        """
        if self.settings.csv_mode:
            return _load_csv_trip(self.settings)

        if self.settings.demo_mode:
            return load_demo_trip("No API key set, showing sample data.")

        async with self._lock:
            try:
                group_id, group_name = await self.resolve_group_id()
                raw_expenses = await self.get_all_expenses(group_id)
                people = await self._collect_people(group_id, raw_expenses)
            except SplitwiseError as exc:
                log.error("Splitwise fetch failed: %s", exc)
                return load_demo_trip(f"{exc} Showing sample data instead.")
            except Exception as exc:  # noqa: BLE001 - never 500 the dashboard
                log.exception("Unexpected Splitwise failure")
                return load_demo_trip(f"Could not reach Splitwise ({exc}). Showing sample data.")

        expenses = [
            Expense.from_api(raw)
            for raw in raw_expenses
            if not raw.get("deleted_at")
        ]
        expenses.sort(key=lambda e: (e.date or datetime.min.date(), e.id))

        return TripData(
            group_id=group_id,
            group_name=group_name,
            people=people,
            expenses=expenses,
            source="live",
            fetched_at=datetime.now(timezone.utc),
        )

    async def _collect_people(self, group_id: int | None,
                              raw_expenses: list[dict]) -> list[Person]:
        """Members from the group, topped up with anyone seen in expenses."""
        people: dict[int, Person] = {}
        if group_id:
            try:
                group = await self.get_group(group_id)
                for member in group.get("members") or []:
                    person = Person.from_api(member)
                    if person.id:
                        people[person.id] = person
            except SplitwiseError as exc:
                log.warning("Could not load group members: %s", exc)

        for raw in raw_expenses:
            for entry in raw.get("users") or []:
                user = entry.get("user") or {}
                if not user:
                    continue
                person = Person.from_api(user)
                if person.id and person.id not in people:
                    people[person.id] = person

        return sorted(people.values(), key=lambda p: p.name.lower())

    def invalidate(self) -> None:
        self._cache.clear()


# --------------------------------------------------------------- csv import


def _load_csv_trip(settings: Settings) -> TripData:
    """Load trip data from a Splitwise CSV export."""
    csv_path = settings.resolved_csv_path
    if csv_path is None:
        return load_demo_trip("CSV path configured but file not found. Showing sample data.")
    try:
        trip = load_csv(csv_path)
        log.info("Loaded %d expenses from CSV: %s", len(trip.expenses), csv_path)
        return trip
    except (ValueError, OSError) as exc:
        log.error("CSV import failed: %s", exc)
        return load_demo_trip(f"CSV import error: {exc}. Showing sample data.")


# --------------------------------------------------------------- demo data


def _load_demo_payload() -> dict:
    if not DEMO_FILE.exists():
        return {"group": {"id": 0, "name": "Demo trip", "members": []}, "expenses": []}
    return json.loads(DEMO_FILE.read_text(encoding="utf-8"))


def load_demo_trip(warning: str | None = None) -> TripData:
    """Parse the bundled sample payload through the real parsing path."""
    payload = _load_demo_payload()
    group = payload.get("group") or {}
    raw_expenses = payload.get("expenses") or []

    people: dict[int, Person] = {}
    for member in group.get("members") or []:
        person = Person.from_api(member)
        people[person.id] = person
    for raw in raw_expenses:
        for entry in raw.get("users") or []:
            user = entry.get("user") or {}
            if user:
                person = Person.from_api(user)
                people.setdefault(person.id, person)

    expenses = [Expense.from_api(r) for r in raw_expenses if not r.get("deleted_at")]
    expenses.sort(key=lambda e: (e.date or datetime.min.date(), e.id))

    return TripData(
        group_id=group.get("id"),
        group_name=group.get("name") or "Thailand",
        people=sorted(people.values(), key=lambda p: p.name.lower()),
        expenses=expenses,
        source="demo",
        warning=warning,
        fetched_at=datetime.now(timezone.utc),
    )
