"""Test configuration.

Every test runs against a throwaway SQLite file, in demo mode, with live FX
turned off so the numbers are deterministic. These env vars are set before the
app is imported because settings are read once and cached.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

TMP_DIR = Path(tempfile.mkdtemp(prefix="trip-test-"))

os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DIR / 'test.db'}"
os.environ["SPLITWISE_API_KEY"] = ""      # force demo mode, never hit the network
os.environ["SPLITWISE_GROUP_ID"] = ""
os.environ["SPLITWISE_CSV_PATH"] = "none"  # disable CSV auto-detection in tests
os.environ["FX_LIVE"] = "false"           # static rates -> deterministic totals
os.environ["AUTO_SEED"] = "true"
os.environ["HOME_CURRENCY"] = "INR"
os.environ["TRIP_START"] = "2026-01-10"
os.environ["TRIP_END"] = "2026-01-21"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.analytics import build_analytics  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.fx import FxConverter  # noqa: E402
from app.main import app  # noqa: E402
from app.splitwise import load_demo_trip  # noqa: E402


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(TMP_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def client():
    """TestClient runs the lifespan, which creates and seeds the database."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def trip():
    return load_demo_trip()


@pytest.fixture
def analytics(trip, settings):
    fx = FxConverter(settings)
    return build_analytics(trip, fx, (settings.trip_start, settings.trip_end))


@pytest.fixture
def db_session():
    init_db(seed_if_empty=True)
    with session_scope() as session:
        yield session
