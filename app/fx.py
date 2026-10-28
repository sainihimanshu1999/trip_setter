"""Currency conversion.

A Thailand trip generates THB expenses while the flights were probably booked
in INR, so totals are meaningless until everything is in one currency. Rates
come from frankfurter.dev (free, no API key) and fall back to the static table
in settings when offline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from .config import Settings

log = logging.getLogger("trip.fx")

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
CENTS = Decimal("0.01")


class FxConverter:
    """Holds `home per 1 unit of foreign` rates and converts money."""

    def __init__(self, settings: Settings) -> None:
        self.home = settings.home_currency
        self._settings = settings
        self.rates: dict[str, Decimal] = {
            code.upper(): Decimal(str(rate))
            for code, rate in settings.fx_rates.items()
        }
        self.rates[self.home] = Decimal("1")
        self.source = "static"
        self.as_of: str | None = None

    def convert(self, amount: Decimal, currency: str) -> Decimal:
        """Convert into the home currency at full precision.

        Deliberately not rounded: thousands of per-share conversions each
        rounded to 2dp accumulate visible drift, so rounding happens once at
        the presentation boundary instead.
        """
        code = (currency or self.home).upper()
        if code == self.home:
            return amount
        rate = self.rates.get(code)
        if rate is None:
            # Unknown currency: pass the number through rather than drop the
            # expense, and say so in the logs.
            log.warning("No FX rate for %s, treating 1 %s as 1 %s", code, code, self.home)
            return amount
        return amount * rate

    def rate_for(self, currency: str) -> Decimal:
        return self.rates.get((currency or self.home).upper(), Decimal("1"))

    async def refresh(self) -> None:
        """Pull live rates. Silently keeps the static table on any failure."""
        if not self._settings.fx_live:
            return
        wanted = sorted(c for c in self.rates if c != self.home)
        if not wanted:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(
                    FRANKFURTER_URL,
                    params={"base": self.home, "symbols": ",".join(wanted)},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001 - FX is a nice-to-have
            log.warning("Live FX refresh failed, using static rates: %s", exc)
            return

        # Frankfurter returns foreign-per-home; we want home-per-foreign.
        received = payload.get("rates") or {}
        updated = 0
        for code, foreign_per_home in received.items():
            try:
                value = Decimal(str(foreign_per_home))
            except Exception:  # noqa: BLE001
                continue
            if value > 0:
                self.rates[code.upper()] = (Decimal("1") / value).quantize(Decimal("0.000001"))
                updated += 1

        if updated:
            self.source = "frankfurter.dev"
            self.as_of = payload.get("date") or datetime.now(timezone.utc).date().isoformat()
            log.info("FX refreshed: %d rates as of %s", updated, self.as_of)

    def as_json(self) -> dict:
        return {
            "home": self.home,
            "source": self.source,
            "as_of": self.as_of,
            "rates": {code: float(rate) for code, rate in sorted(self.rates.items())},
        }
