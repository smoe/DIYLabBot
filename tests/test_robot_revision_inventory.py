"""Exact-reference inventory coverage, drift detection and honest source context."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import report_robot_revision_inventory as inventory


class RobotRevisionInventoryTests(unittest.TestCase):
    def write_json(self, root, name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
        return path

    def test_exact_values_and_keys_include_schema_but_exclude_prose_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_json(root, inventory.SOURCE, {"id": "fixture"})
            pin = inventory.digest(source)
            self.write_json(root, "model/fixture.json", {
                "note": "See " + inventory.SOURCE + " for details",
                "current": {"source": inventory.SOURCE, "source_sha256": pin},
                "sources": {inventory.SOURCE: {"source": inventory.SOURCE, "source_sha256": pin}},
                "array": [inventory.SOURCE],
            })
            self.write_json(root, "model/fixture.schema.json", {"const": inventory.SOURCE})
            self.write_json(root, "model/history/frozen.json", {"source": inventory.SOURCE})
            self.write_json(root, "elsewhere/ignored.json", {"source": inventory.SOURCE})
            entries = inventory.direct_references(root)
            self.assertEqual(len(entries), 5)
            self.assertEqual({e["file"] for e in entries}, {"model/fixture.json", "model/fixture.schema.json"})
            key = next(e for e in entries if e["occurrence"] == "key")
            self.assertEqual(key["json_pointer"], "/sources/model~1robot.json")
            self.assertEqual(key["classification"], "current")
            schema = next(e for e in entries if e["file"].endswith(".schema.json"))
            self.assertEqual((schema["role"], schema["classification"]), ("schema_path_constraint", "unpinned"))

    def test_unknown_new_reference_is_discovered_without_curated_filename_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_json(root, inventory.SOURCE, {})
            self.assertEqual(inventory.direct_references(root), [])
            self.write_json(root, "model/new/nested.scene.json", {"new": [{"path": inventory.SOURCE}]})
            entries = inventory.direct_references(root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["json_pointer"], "/new/0/path")
            self.assertEqual(entries[0]["classification"], "unpinned")

    def test_only_immediately_associated_pin_applies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_json(root, inventory.SOURCE, {})
            self.write_json(root, "model/fixture.json", {
                "source_sha256": inventory.digest(source),
                "unrelated": {"source": inventory.SOURCE},
                "path_ref": {"path": inventory.SOURCE, "sha256": inventory.HISTORICAL_SHA256},
            })
            entries = inventory.direct_references(root)
            self.assertEqual(entries[0]["classification"], "historical_mixed")
            self.assertEqual(entries[1]["classification"], "unpinned")

    def test_current_source_mutation_changes_pin_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.write_json(root, inventory.SOURCE, {})
            self.write_json(root, "model/fixture.json", {"source": inventory.SOURCE, "sha256": inventory.digest(source)})
            self.assertEqual(inventory.direct_references(root)[0]["classification"], "current")
            source.write_text('{"changed":true}\n', encoding="utf-8")
            self.assertEqual(inventory.direct_references(root)[0]["classification"], "mismatched_unresolved")

    def test_invalid_and_conflicting_pins_fail_instead_of_choosing_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_json(root, inventory.SOURCE, {})
            name = "model/fixture.json"
            self.write_json(root, name, {"source": inventory.SOURCE, "sha256": "not-a-digest"})
            with self.assertRaisesRegex(ValueError, "Invalid source pin"):
                inventory.direct_references(root)
            self.write_json(root, name, {"source": inventory.SOURCE, "sha256": "0" * 64, "source_sha256": "1" * 64})
            with self.assertRaisesRegex(ValueError, "Conflicting source pins"):
                inventory.direct_references(root)

    def test_repository_inventory_matches_and_includes_optional_type_family(self):
        expected = inventory.serialized(inventory.inventory())
        checked_in = (inventory.ROOT / inventory.OUTPUT).read_text(encoding="utf-8")
        self.assertEqual(checked_in, expected)
        report = json.loads(expected)
        rows = report["direct_references"]
        # Independent literal walk catches newly introduced consumers as well as
        # changes to the scanner's known role/name assumptions.
        found = set()

        def visit(value, path):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == inventory.SOURCE:
                        found.add((path, "key"))
                    if child == inventory.SOURCE:
                        found.add((path, "value"))
                    visit(child, path)
            elif isinstance(value, list):
                for child in value:
                    if child == inventory.SOURCE:
                        found.add((path, "value"))
                    visit(child, path)

        for path in (inventory.ROOT / "model").rglob("*.json"):
            relative = path.relative_to(inventory.ROOT)
            if relative.parts[:2] != ("model", "history"):
                visit(json.loads(path.read_text(encoding="utf-8")), relative.as_posix())
        self.assertEqual({(r["file"], r["occurrence"]) for r in rows}, found)
        type_file = "model/robot-types/arm-nobrake.type.json"
        if (inventory.ROOT / type_file).is_file():
            self.assertTrue(any(r["file"] == type_file and r["json_pointer"] == "/family"
                                and r["role"] == "type_family_reference" for r in rows))

    def test_contexts_cover_h02_native_metadata_and_all_known_mixed_consumers(self):
        report = inventory.inventory()
        contexts = {item["id"]: item for item in report["reviewed_consumer_contexts"]}
        h02 = contexts["h02-validation-build-and-native-metadata"]
        self.assertEqual(h02["classification"], "historical_mixed")
        self.assertIn("historical native use remains unsupported", h02["finding"])
        self.assertTrue(any(e["file"] == "scripts/build_neutral_freecad.py" for e in h02["evidence"]))
        self.assertIn("tr01-workcell-and-l01-instances", contexts)
        self.assertIn("analytics-tools-workspace-and-native-context", contexts)
        self.assertIn("mb01-unpinned-arm-load", contexts)
        self.assertIn("water-practice-current-default-and-old-transitive-pins", contexts)
        historical = {r["file"] for r in report["direct_references"] if r["classification"] == "historical_mixed"}
        self.assertEqual(historical, {"model/h02-arm-pickup.scene.json", "model/tr01-l01-workcell.protocol.json",
                                      "model/analytics-tools.shared.json", "model/equipment/analytics-workspace.json"})
        self.assertNotIn("historical_consistent", {r["classification"] for r in report["direct_references"]})

    def test_changed_reviewed_code_requires_fresh_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/example.py").write_text("changed()\n", encoding="utf-8")
            contexts = ({"id": "fixture", "models": [], "evidence": {"scripts/example.py": ["original()"]}},)
            with mock.patch.object(inventory, "REVIEWED_CONTEXTS", contexts):
                with self.assertRaisesRegex(ValueError, "Consumer evidence changed; review fixture"):
                    inventory.reviewed_contexts(root)

    def test_check_detects_drift_without_writing_and_cli_regenerates_deterministically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            output = root / inventory.OUTPUT
            output.write_bytes(b"stale\n")
            before = hashlib.sha256(output.read_bytes()).hexdigest()
            with mock.patch.object(inventory, "ROOT", root), mock.patch.object(inventory, "inventory", return_value={"fixture": 1}):
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(inventory.main(["--check"]), 1)
                self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), before)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(inventory.main([]), 0)
                once = output.read_bytes()
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(inventory.main([]), 0)
                    self.assertEqual(inventory.main(["--check"]), 0)
                self.assertEqual(output.read_bytes(), once)
                self.assertNotIn(str(root).encode(), once)


if __name__ == "__main__":
    unittest.main()
