"""FastAPI application entry point.

Run it with:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, get_settings
from .db import init_db
from .deps import TripService
from .routers import api, pages

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("trip")

STATIC_DIR = BASE_DIR / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()

    service = TripService(settings)
    app.state.trip = service
    await service.startup()

    source_label = {
        "live": "LIVE Splitwise",
        "csv": f"CSV {settings.resolved_csv_path.name if settings.resolved_csv_path else ''}",
        "demo": "DEMO (no API key, no CSV)",
    }[settings.data_source]
    log.info(
        "Trip dashboard ready | %s | %s -> %s | totals in %s | FX %s",
        source_label, settings.trip_start, settings.trip_end,
        settings.home_currency, service.fx.source,
    )
    try:
        yield
    finally:
        await service.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.trip_title} trip dashboard",
        description=(
            "Shared trip expenses from Splitwise, bookings from a local "
            "database, and an animated journey map that draws a line for every "
            "flight, train, ferry and cab you split."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(api.router)
    app.include_router(pages.router)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Return JSON rather than an HTML stack trace for API calls."""
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Something broke server-side", "detail": str(exc)},
        )

    return app


app = create_app()
