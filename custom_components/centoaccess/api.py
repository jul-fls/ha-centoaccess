"""Client for the CentoAccess mobile and public-panel APIs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
from typing import cast
from aiohttp import ClientSession

from .const import API_PASSWORD, API_USERNAME, BASE_URL
from .models import JsonObject, as_object, object_list

PANEL_ID_RE = re.compile(r"/panel/panel_web/(\d+)")
PANEL_TOKEN_RE = re.compile(r'data-token="([^"]+)"')


class CentoAccessError(Exception):
    """Raised when CentoAccess returns an unusable response."""


@dataclass(frozen=True)
class CommuneData:
    """All data published for one CentoAccess application."""

    application: JsonObject
    tiles: list[JsonObject]
    events: list[JsonObject]
    news: list[JsonObject]
    useful_info: list[JsonObject]
    useful_info_links: list[JsonObject]
    panel_id: str | None
    panel_url: str | None
    panel_data: JsonObject

    @property
    def application_id(self) -> int:
        """Return the CentoAccess application identifier."""
        return int(self.application["id"])

    @property
    def name(self) -> str:
        """Return the published commune name."""
        return str(self.application.get("name") or self.application_id)


@dataclass
class CentoAccessClient:
    """Small authenticated client matching the official mobile calls."""

    session: ClientSession
    base_url: str = BASE_URL
    _token: str | None = field(default=None, init=False)

    @property
    def api_url(self) -> str:
        """Return the API root."""
        return f"{self.base_url}/api"

    async def _authenticate(self) -> None:
        async with self.session.post(
            f"{self.api_url}/login_check",
            json={"username": API_USERNAME, "password": API_PASSWORD},
            headers={"Accept": "application/json"},
        ) as response:
            response.raise_for_status()
            payload = as_object(await response.json(content_type=None))
        token = payload.get("token")
        if not token:
            raise CentoAccessError("Authentication response contains no token")
        self._token = str(token)

    async def _get_json(
        self,
        path: str,
        params: JsonObject | None = None,
        *,
        retry_auth: bool = True,
    ) -> object:
        if not self._token:
            await self._authenticate()
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        async with self.session.get(
            f"{self.api_url}{path}", headers=headers, params=params
        ) as response:
            if response.status == 401 and retry_auth:
                self._token = None
                return await self._get_json(path, params, retry_auth=False)
            response.raise_for_status()
            return await response.json(content_type=None)

    async def search_applications(self, query: str) -> list[JsonObject]:
        """Find CentoAccess communes by postal code or name."""
        data = await self._get_json(
            "/applications", {"key": query, "order[name]": "ASC"}
        )
        if not isinstance(data, list):
            raise CentoAccessError("Application search response is not a list")
        return [item for item in object_list(cast(object, data)) if item.get("id")]

    async def get_application(self, application_id: int) -> JsonObject:
        """Fetch one CentoAccess application."""
        data = await self._get_json(f"/applications/{application_id}")
        application = as_object(data)
        if not application.get("id"):
            raise CentoAccessError("Application response is invalid")
        return application

    async def _get_public_panel(self, panel_id: str) -> JsonObject:
        panel_url = f"{self.base_url}/panel/panel_web/{panel_id}"
        async with self.session.get(panel_url) as response:
            response.raise_for_status()
            html = await response.text()
        match = PANEL_TOKEN_RE.search(html)
        if not match:
            raise CentoAccessError("Public panel token was not found")
        headers = {
            "Authorization": f"Bearer {match.group(1)}",
            "Accept": "application/json",
        }
        async with self.session.get(
            f"{self.api_url}/data_panel_web/{panel_id}", headers=headers
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
        if not isinstance(data, dict):
            raise CentoAccessError("Public panel response is invalid")
        return as_object(cast(object, data))

    async def fetch(self, application_id: int) -> CommuneData:
        """Fetch all mobile-app information for one commune."""
        application = await self.get_application(application_id)
        app_filter = {"application.id": application_id, "enabled": 1}
        tiles, events, news, useful_info, useful_info_links = await asyncio.gather(
            self._get_json("/tiles", app_filter),
            self._get_json("/event_informations", app_filter),
            self._get_json("/news_informations", app_filter),
            self._get_json(
                "/useful_info_informations",
                {"application": application_id, "enabled": 1},
            ),
            self._get_json(
                "/useful_info_information_links",
                {"usefulInfoParent.application": application_id},
            ),
        )
        collections = (tiles, events, news, useful_info, useful_info_links)
        if not all(isinstance(collection, list) for collection in collections):
            raise CentoAccessError("One of the commune collections is invalid")

        tile_items = object_list(tiles)
        event_items = object_list(events)
        news_items = object_list(news)
        useful_info_items = object_list(useful_info)
        useful_info_link_items = object_list(useful_info_links)

        panel_id = None
        panel_url = None
        for tile in tile_items:
            url = tile.get("url")
            match = PANEL_ID_RE.search(url if isinstance(url, str) else "")
            if tile.get("type") == "WebViewTile" and match:
                panel_id = match.group(1)
                panel_url = url
                break
        panel_data = await self._get_public_panel(panel_id) if panel_id else {}

        return CommuneData(
            application=application,
            tiles=tile_items,
            events=event_items,
            news=news_items,
            useful_info=useful_info_items,
            useful_info_links=useful_info_link_items,
            panel_id=panel_id,
            panel_url=panel_url,
            panel_data=panel_data,
        )
