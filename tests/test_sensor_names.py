"""Guard the translated entity names shown on the device page."""

import ast
import json
from pathlib import Path
from typing import cast
import unittest


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "centoaccess"


class SensorNameTests(unittest.TestCase):
    def test_all_sensors_have_distinct_translated_names(self):
        tree = ast.parse((COMPONENT / "sensor.py").read_text(encoding="utf-8"))
        sensor_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "CentoAccessSensor"
        )
        self.assertTrue(any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_attr_has_entity_name"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and node.value.value is True
            for node in sensor_class.body
        ))
        keys: list[str] = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CentoAccessSensorDescription"
            ):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "translation_key"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    keys.append(keyword.value.value)
        self.assertEqual(len(keys), 5)
        for language in ("fr", "en"):
            catalog = cast(
                dict[str, dict[str, dict[str, dict[str, str]]]],
                json.loads(
                    (COMPONENT / "translations" / f"{language}.json").read_text(
                        encoding="utf-8"
                    )
                ),
            )
            translations = catalog["entity"]["sensor"]
            names = [translations[key]["name"] for key in keys]
            self.assertEqual(len(set(names)), len(keys))
            self.assertTrue(all(names))


if __name__ == "__main__":
    unittest.main()
