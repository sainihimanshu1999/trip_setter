"""SQLite engine and session plumbing."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings
from .models import Base, Booking

log = logging.getLogger("trip.db")

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _build_engine(settings: Settings) -> Engine:
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        settings.database_url,
        echo=False,
        future=True,
        # FastAPI serves requests from a threadpool, so the connection must not
        # be pinned to the creating thread.
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        # WAL survives concurrent reads during a write; foreign keys are off by
        # default in SQLite and we rely on the bookings -> places constraint.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings())
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False,
        )
    return _SessionFactory


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and startup tasks."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(seed_if_empty: bool | None = None) -> None:
    """Create tables, and seed the itinerary the first time only."""
    settings = get_settings()
    Base.metadata.create_all(get_engine())

    should_seed = settings.auto_seed if seed_if_empty is None else seed_if_empty
    if not should_seed:
        return

    with session_scope() as session:
        existing = session.scalar(select(Booking.id).limit(1))
        if existing is not None:
            return

    from .seed import seed_itinerary  # imported late to avoid a cycle

    log.info("Empty database, seeding the itinerary")
    seed_itinerary()


def reset_db() -> None:
    """Drop and recreate everything. Used by tests and `--reseed`."""
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
