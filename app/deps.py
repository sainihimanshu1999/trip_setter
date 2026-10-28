"""Shared request dependencies.

One `TripService` lives on `app.state` for the process lifetime so the HTTP
client, its connection pool and the response cache are reused across requests.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from .analytics import Analytics, build_analytics
from .config import Settings, get_settings
from .fx import FxConverter
from .splitwise import SplitwiseClient


class TripService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = SplitwiseClient(settings)
        self.fx = FxConverter(settings)

    @property
    def window(self) -> tuple:
        return (self.settings.trip_start, self.settings.trip_end)

    async def analytics(self) -> Analytics:
        """Fetch (cached) expenses and fold them into the computed view."""
        trip = await self.client.fetch_trip()
        return build_analytics(trip, self.fx, self.window)

    async def startup(self) -> None:
        await self.fx.refresh()

    async def shutdown(self) -> None:
        await self.client.aclose()


def get_service(request: Request) -> TripService:
    return request.app.state.trip


async def get_analytics(
    service: Annotated[TripService, Depends(get_service)],
) -> Analytics:
    return await service.analytics()


SettingsDep = Annotated[Settings, Depends(get_settings)]
ServiceDep = Annotated[TripService, Depends(get_service)]
AnalyticsDep = Annotated[Analytics, Depends(get_analytics)]
