"""Tests for French commune resolution and CentoAccess matching."""

import importlib
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "centoaccess"
if "centoaccess" not in sys.modules:
    package = ModuleType("centoaccess")
    package.__path__ = [str(COMPONENT)]
    sys.modules["centoaccess"] = package
if "aiohttp" not in sys.modules:
    sys.modules["aiohttp"] = ModuleType("aiohttp")
aiohttp_stub = sys.modules["aiohttp"]
aiohttp_stub.ClientSession = object
aiohttp_stub.ClientTimeout = lambda total: None
location = importlib.import_module("centoaccess.location")


class FakeResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(self.status)

    async def json(self):
        return self.data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self.responses.pop(0))


class CommuneMatchingTests(unittest.TestCase):
    def test_exact_commune_is_kept_from_shared_postcode_results(self):
        applications = [
            {"id": 243, "name": "Beautiran"},
            {"id": 135, "name": "CASTRES-GIRONDE"},
            {"id": 5, "name": "Ville de Portets"},
        ]
        matches = location.matching_applications("Castres-Gironde", applications)
        self.assertEqual([item["id"] for item in matches], [135])

    def test_municipal_name_prefix_is_accepted(self):
        matches = location.matching_applications(
            "Portets", [{"id": 5, "name": "Ville de Portets"}]
        )
        self.assertEqual([item["id"] for item in matches], [5])

    def test_neighbouring_commune_is_not_accepted(self):
        matches = location.matching_applications(
            "Saint-Selve", [{"id": 135, "name": "CASTRES-GIRONDE"}]
        )
        self.assertEqual(matches, [])

    def test_french_error_explains_unsupported_commune(self):
        translations = json.loads(
            (COMPONENT / "translations" / "fr.json").read_text(encoding="utf-8")
        )
        message = translations["config"]["error"]["not_centoaccess"]
        self.assertIn("n'utilise pas CentoAccess", message)
        self.assertIn("ne peut donc pas être configurée", message)


class LocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_gps_resolves_to_official_commune(self):
        session = FakeSession(
            [{"code": "33109", "nom": "Castres-Gironde"}],
            {
                "code": "33109",
                "nom": "Castres-Gironde",
                "codesPostaux": ["33640"],
            },
        )
        found = await location.from_coordinates(
            session, 44.696436, -0.445060, "home"
        )
        self.assertEqual(found.code, "33109")
        self.assertEqual(found.commune, "Castres-Gironde")
        self.assertEqual(found.postcode, "33640")
        self.assertEqual(found.unique_id, "home")

    async def test_postal_prefix_lists_all_matching_communes(self):
        session = FakeSession(
            [
                {
                    "code": "33109",
                    "nom": "Castres-Gironde",
                    "codesPostaux": ["33640"],
                },
                {
                    "code": "33063",
                    "nom": "Bordeaux",
                    "codesPostaux": ["33000", "33100"],
                },
                {
                    "code": "75056",
                    "nom": "Paris",
                    "codesPostaux": ["75001"],
                },
            ]
        )
        choices = await location.search_postal_prefix(session, "33")
        self.assertEqual(
            [choice.value for choice in choices],
            ["33000:33063", "33100:33063", "33640:33109"],
        )

    async def test_postal_selection_keeps_postcode(self):
        session = FakeSession(
            {
                "code": "33109",
                "nom": "Castres-Gironde",
                "codesPostaux": ["33640"],
            }
        )
        selected = location.PostalChoice("33640", "33109", "Castres-Gironde")
        found = await location.from_postal_choice(session, selected)
        self.assertEqual(found.code, "33109")
        self.assertEqual(found.postcode, "33640")

    async def test_postal_prefix_requires_at_least_two_digits(self):
        session = FakeSession()
        with self.assertRaises(location.InvalidLocation):
            await location.search_postal_prefix(session, "3")
        self.assertFalse(session.calls)

    async def test_full_address_keeps_coordinates_and_postcode(self):
        session = FakeSession(
            {
                "features": [
                    {
                        "properties": {
                            "score": 0.96,
                            "citycode": "33109",
                            "postcode": "33640",
                            "label": "1 Place de la Mairie 33640 Castres-Gironde",
                            "type": "housenumber",
                            "id": "ban-123",
                        },
                        "geometry": {"coordinates": [-0.445, 44.696]},
                    }
                ]
            },
            {
                "code": "33109",
                "nom": "Castres-Gironde",
                "codesPostaux": ["33640"],
            },
        )
        found = await location.from_address(
            session, "1 place de la Mairie 33640 Castres-Gironde"
        )
        self.assertEqual(found.code, "33109")
        self.assertEqual(found.postcode, "33640")
        self.assertEqual(found.latitude, 44.696)


if __name__ == "__main__":
    unittest.main()
