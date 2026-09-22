"""Client for the CentoAccess mobile and public-panel APIs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
from typing import Any

from aiohttp import ClientSession

from .const import API_PASSWORD, API_USERNAME, BASE_URL

PANEL_ID_RE = re.compile(r"/panel/panel_web/(\d+)")
PANEL_TOKEN_RE = re.compile(r'data-token="([^"]+)"')


class CentoAccessError(Exception):
    """Raised when CentoAccess returns an unusable response."""


@dataclass(frozen=True)
class CommuneData:
    """All data published for one CentoAccess application."""

    application: dict[str, Any]
    tiles: list[dict[str, Any]]
    events: list[dict[str, Any]]
    news: list[dict[str, Any]]
    useful_info: list[dict[str, Any]]
    useful_info_links: list[dict[str, Any]]
    panel_id: str | None
    panel_url: str | None
    panel_data: dict[str, Any]

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
            payload = await response.json(content_type=None)
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            raise CentoAccessError("Authentication response contains no token")
        self._token = str(token)

    async def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        retry_auth: bool = True,
    ) -> Any:
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

    async def search_applications(self, query: str) -> list[dict[str, Any]]:
        """Find CentoAccess communes by postal code or name."""
        data = await self._get_json(
            "/applications", {"key": query, "order[name]": "ASC"}
        )
        if not isinstance(data, list):
            raise CentoAccessError("Application search response is not a list")
        return [item for item in data if isinstance(item, dict) and item.get("id")]

    async def get_application(self, application_id: int) -> dict[str, Any]:
        """Fetch one CentoAccess application."""
        data = await self._get_json(f"/applications/{application_id}")
        if not isinstance(data, dict) or not data.get("id"):
            raise CentoAccessError("Application response is invalid")
        return data

    async def _get_public_panel(self, panel_id: str) -> dict[str, Any]:
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
        return data

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

        panel_id = None
        panel_url = None
        for tile in tiles:
            match = PANEL_ID_RE.search(tile.get("url") or "")
            if tile.get("type") == "WebViewTile" and match:
                panel_id = match.group(1)
                panel_url = tile.get("url")
                break
        panel_data = await self._get_public_panel(panel_id) if panel_id else {}

        return CommuneData(
            application=application,
            tiles=tiles,
            events=events,
            news=news,
            useful_info=useful_info,
            useful_info_links=useful_info_links,
            panel_id=panel_id,
            panel_url=panel_url,
            panel_data=panel_data,
        )
