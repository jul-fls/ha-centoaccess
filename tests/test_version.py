"""Version and release tag checks."""

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_version.py"
SPEC = importlib.util.spec_from_file_location("check_version", SCRIPT)
check_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_version)


class VersionTests(unittest.TestCase):
    def test_matching_release_tag(self):
        version = check_version.check_version()
        self.assertEqual(check_version.check_version(f"v{version}"), version)

    def test_mismatched_release_tag_is_rejected(self):
        with self.assertRaises(ValueError):
            check_version.check_version("v0.0.0")


if __name__ == "__main__":
    unittest.main()
