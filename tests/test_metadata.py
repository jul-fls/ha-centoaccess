"""Catch repository metadata mistakes before Hassfest and HACS do."""

import json
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "centoaccess"


class MetadataTests(unittest.TestCase):
    def test_manifest_keys_and_hacs_fields(self):
        manifest = json.loads(
            (INTEGRATION / "manifest.json").read_text(encoding="utf-8")
        )
        keys = list(manifest)
        self.assertEqual(keys[:2], ["domain", "name"])
        self.assertEqual(keys[2:], sorted(keys[2:]))
        self.assertEqual(manifest["domain"], "centoaccess")
        self.assertTrue(manifest["issue_tracker"].startswith("https://github.com/"))

    def test_brand_icon_is_square_png(self):
        icon = (INTEGRATION / "brand" / "icon.png").read_bytes()
        self.assertEqual(icon[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", icon[16:24]), (256, 256))


if __name__ == "__main__":
    unittest.main()
