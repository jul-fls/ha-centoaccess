"""Focused checks for the CentoAccess API client."""

import importlib
from pathlib import Path
import sys
from types import ModuleType
import unittest


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "centoaccess"
package = ModuleType("centoaccess")
package.__path__ = [str(COMPONENT)]
sys.modules["centoaccess"] = package
aiohttp_stub = ModuleType("aiohttp")
aiohttp_stub.ClientSession = object
sys.modules["aiohttp"] = aiohttp_stub
api = importlib.import_module("centoaccess.api")


class FakeResponse:
    def __init__(self, data=None, *, text="", status=200):
        self.data = data
        self.body = text
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(self.status)

    async def json(self, content_type=None):
        return self.data

    async def text(self):
        return self.body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_by_postal_code_authenticates_and_returns_all_matches(self):
        session = FakeSession(
            FakeResponse({"token": "jwt"}),
            FakeResponse([
                {"id": 12, "name": "BEAUTIRAN"},
                {"id": 135, "name": "CASTRES-GIRONDE"},
                {"id": 53, "name": "Ville de Portets"},
            ]),
        )
        client = api.CentoAccessClient(session)
        applications = await client.search_applications("33640")
        self.assertEqual([item["id"] for item in applications], [12, 135, 53])
        self.assertEqual(session.calls[0][0], "POST")
        self.assertEqual(
            session.calls[1][2]["params"],
            {"key": "33640", "order[name]": "ASC"},
        )

    async def test_fetch_discovers_panel_id_from_tiles(self):
        panel_html = '<main data-token="panel-jwt"></main>'
        session = FakeSession(
            FakeResponse({"token": "api-jwt"}),
            FakeResponse({"id": 135, "name": "CASTRES-GIRONDE"}),
            FakeResponse([{"type": "WebViewTile", "url": "/panel/panel_web/1535"}]),
            FakeResponse([{"id": 1, "title": "Fête locale"}]),
            FakeResponse([{"id": 2, "title": "Travaux"}]),
            FakeResponse([{"id": 3, "title": "Mairie"}]),
            FakeResponse([{"id": 4, "title": "Site internet"}]),
            FakeResponse(text=panel_html),
            FakeResponse({"messages": [{"id": 5}]}),
        )
        client = api.CentoAccessClient(session)
        data = await client.fetch(135)
        self.assertEqual(data.application_id, 135)
        self.assertEqual(data.panel_id, "1535")
        self.assertEqual(len(data.events), 1)
        self.assertEqual(len(data.news), 1)
        self.assertEqual(len(data.useful_info), 1)
        self.assertEqual(data.panel_data["messages"][0]["id"], 5)
        authorization = session.calls[-1][2]["headers"]["Authorization"]
        self.assertIn("Bearer panel-jwt", authorization)

    async def test_fetch_without_panel_still_returns_commune_data(self):
        session = FakeSession(
            FakeResponse({"token": "api-jwt"}),
            FakeResponse({"id": 99, "name": "Commune"}),
            FakeResponse([]),
            FakeResponse([]),
            FakeResponse([]),
            FakeResponse([]),
            FakeResponse([]),
        )
        data = await api.CentoAccessClient(session).fetch(99)
        self.assertIsNone(data.panel_id)
        self.assertEqual(data.panel_data, {})


if __name__ == "__main__":
    unittest.main()
