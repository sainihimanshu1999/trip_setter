"""Application settings, loaded from environment / .env."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

#: Home-currency units per 1 unit of the key. Defaults are a snapshot taken
#: 2026-10-23 from frankfurter.dev with INR as home; live refresh overrides them.
DEFAULT_FX = {
    "INR": 1.0,
    "THB": 2.81,
    "USD": 94.94,
    "EUR": 106.27,
    "SGD": 74.26,
    "MYR": 23.24,
    "GBP": 122.50,
    "AED": 25.85,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    splitwise_api_key: str = ""
    splitwise_group_id: int | None = None
    splitwise_csv_path: str = ""

    trip_currency: str = "THB"
    home_currency: str = "INR"
    fx_rates: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_FX))
    fx_live: bool = True

    trip_start: date = date(2026, 10, 5)
    trip_end: date = date(2026, 10, 17)

    cache_ttl_seconds: int = 120
    database_url: str = "sqlite:///./data/trip.db"
    auto_seed: bool = True

    trip_title: str = "Thailand"
    trip_subtitle: str = "Bangkok · Koh Samui · Phuket"

    @field_validator("fx_rates", mode="before")
    @classmethod
    def _parse_fx(cls, v: object) -> object:
        """Accept a JSON object string from the env file."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return dict(DEFAULT_FX)
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError as exc:  # pragma: no cover - config error
                raise ValueError(f"FX_RATES must be a JSON object: {exc}") from exc
            return parsed
        return v

    @field_validator("fx_rates", mode="after")
    @classmethod
    def _merge_fx(cls, v: dict[str, float]) -> dict[str, float]:
        """Always keep defaults present so unknown currencies never hard-fail."""
        merged = dict(DEFAULT_FX)
        merged.update({k.upper(): float(x) for k, x in v.items()})
        return merged

    @field_validator("splitwise_group_id", mode="before")
    @classmethod
    def _blank_group_is_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("trip_currency", "home_currency", mode="after")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def data_source(self) -> str:
        """Where expenses come from: "live", "csv" or "demo".

        An API key wins, because it is the only source that is current without
        the user re-exporting anything.
        """
        if self.splitwise_api_key.strip():
            return "live"
        return "csv" if self.resolved_csv_path is not None else "demo"

    @property
    def demo_mode(self) -> bool:
        """True when there is no API key and no CSV, so we serve sample data."""
        return self.data_source == "demo"

    @property
    def csv_mode(self) -> bool:
        """True when expenses are read from a Splitwise CSV export."""
        return self.data_source == "csv"

    @property
    def resolved_csv_path(self) -> Path | None:
        """The CSV to read, or None if there is not one.

        Deliberately re-checked on each access rather than cached: Splitwise
        names each export after the day it was made, so a fresh export lands as
        a new file and should be picked up without a restart. When several are
        present the most recently modified one wins.

        Set `SPLITWISE_CSV_PATH=none` to opt out of auto-detection entirely.
        """
        configured = self.splitwise_csv_path.strip()
        if configured.lower() == "none":
            return None
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = BASE_DIR / path
            return path.resolve() if path.is_file() else None

        candidates = [p for p in DATA_DIR.glob("*.csv") if p.is_file()]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    @property
    def sqlite_path(self) -> Path:
        """Filesystem path behind database_url, for mkdir purposes."""
        url = self.database_url
        prefix = "sqlite:///"
        if url.startswith(prefix):
            raw = url[len(prefix) :]
            path = Path(raw)
            return path if path.is_absolute() else (BASE_DIR / raw).resolve()
        return DATA_DIR / "trip.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
