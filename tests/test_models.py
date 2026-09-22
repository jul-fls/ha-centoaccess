"""Tests for CentoAccess data normalization."""

from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
from types import ModuleType
import unittest


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "centoaccess"
package = ModuleType("centoaccess")
package.__path__ = [str(COMPONENT)]
sys.modules["centoaccess"] = package
models = importlib.import_module("centoaccess.models")
absolute_url = models.absolute_url
information_summary = models.information_summary
panel_slides = models.panel_slides


class ModelTests(unittest.TestCase):
    def test_absolute_url(self):
        self.assertEqual(
            absolute_url("/uploads/photo.jpg"),
            "https://centoweb4.centaure-systems.fr/uploads/photo.jpg",
        )
        self.assertEqual(
            absolute_url("https://example.org/photo.jpg"),
            "https://example.org/photo.jpg",
        )

    def test_information_summary_keeps_public_fields(self):
        summary = information_summary({
            "id": 3,
            "title": "Mairie",
            "phone": "0557000000",
            "mainImage": {"path": "/image.jpg"},
        })
        self.assertEqual(summary["title"], "Mairie")
        self.assertEqual(summary["phone"], "0557000000")
        self.assertTrue(summary["image_url"].endswith("/image.jpg"))

    def test_panel_slides_are_deduplicated_and_resolve_media(self):
        message = {
            "id": 10,
            "name": "Marché",
            "currentVersion": {"id": 20},
            "MessagePlaylists": [{"id": 30}],
        }
        panel = {
            "messages": [message, message.copy()],
            "message_playlists": [{"id": 30, "enabled": True}],
            "versioned_messages": [{"id": 20, "Frames": [{"id": 40}]}],
            "frames": [{"id": 40, "Elements": [{"id": 50}]}],
            "elements": [{"id": 50, "type": "Image", "path": "/market.jpg"}],
            "timeslots": [{
                "MessagePlaylist": {"id": 30},
                "dateStart": "2026-01-01T00:00:00+00:00",
                "dateEnd": "2026-12-31T00:00:00+00:00",
            }],
        }
        slides = panel_slides(panel, datetime(2026, 6, 1, tzinfo=timezone.utc))
        self.assertEqual(len(slides), 1)
        self.assertTrue(slides[0]["active"])
        image_url = slides[0]["frames"][0]["elements"][0]["image_url"]
        self.assertTrue(image_url.endswith("/market.jpg"))


if __name__ == "__main__":
    unittest.main()
