"""Explicit R0 selection preserves checked source semantics without CAD builds."""
from contextlib import contextmanager, ExitStack
from dataclasses import FrozenInstanceError
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assembly_model as assembly
import robot_cameras as cameras
import robot_components as components
import robot_revision as revisions
import robot_services as services
import robot_spec as robot

ALIAS = "arm_nobrake@R0"
REGISTRY = "model/robot-revisions.json"
SNAPSHOT = "model/history/robot-978fa3557abc.json"
SOURCE_SHA256 = "978fa3557abcfe549f5c2bd572c761d387310c2983f1d4e60cfd903df621bfdd"


def canonical_sha256(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def repin_manifest(registry):
    entry = registry["revisions"][ALIAS]
    unsigned = {key: value for key, value in entry.items() if key != "revision_sha256"}
    entry["revision_sha256"] = canonical_sha256({"format": registry["format"], **unsigned})


@contextmanager
def isolated_repository():
    """Copy inputs before tampering; never write real sources or their hardlinks."""
    registry = json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))
    entry = registry["revisions"][ALIAS]
    paths = {REGISTRY, entry["type"], entry["family_snapshot"], "model/robot.json"}
    paths.update(entry["dependencies_sha256"])
    paths.update(entry["producers_sha256"])
    paths.update(str(path.relative_to(ROOT)) for path in (ROOT / "model").glob("*robot*schema.json"))
    with tempfile.TemporaryDirectory(prefix="robot-revision-test-") as directory:
        temporary_root = Path(directory).resolve()
        for relative in sorted(paths):
            destination = temporary_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        with ExitStack() as patches:
            for module in (revisions, robot, components):
                patches.enter_context(mock.patch.object(module, "ROOT", temporary_root))
            patches.enter_context(mock.patch.object(robot, "SPEC", temporary_root / "model/robot.json"))
            yield temporary_root, registry


class RobotRevisionContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = revisions.resolve_robot_revision(ALIAS)
        cls.baseline = robot.load(ROOT / SNAPSHOT)

    def test_alias_and_content_identity_resolve_the_same_frozen_record(self):
        record = self.record
        self.assertEqual(record.alias, ALIAS)
        self.assertEqual(record.source_path, (ROOT / SNAPSHOT).resolve())
        self.assertTrue(record.source_path.is_absolute())
        self.assertEqual(record.source_sha256, SOURCE_SHA256)
        self.assertEqual(record.materialized_sha256, canonical_sha256(self.baseline))
        self.assertEqual(revisions.resolve_robot_revision(record.revision_sha256), record)
        self.assertEqual(revisions.load_robot_revision(record.revision_sha256), self.baseline)
        self.assertEqual(revisions.resolve_robot_revision(ALIAS, source_sha256=SOURCE_SHA256), record)
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            record.alias = "changed"

    def test_revision_identity_covers_the_full_manifest(self):
        registry = json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))
        entry = registry["revisions"][ALIAS]
        self.assertIn("scripts/x6_mounting_design.py", entry["producers_sha256"])
        unsigned = {key: value for key, value in entry.items() if key != "revision_sha256"}
        self.assertEqual(self.record.revision_sha256,
                         canonical_sha256({"format": registry["format"], **unsigned}))

    def test_unknown_selectors_and_mismatched_source_pins_fail_closed(self):
        for selector in ("arm_nobrake@R99", "0" * 64, "../model/robot.json", "", None):
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                revisions.load_robot_revision(selector)
        for pin in ("0" * 64, "not-a-sha256", SOURCE_SHA256.upper()):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                revisions.resolve_robot_revision(ALIAS, source_sha256=pin)

    def test_generic_assembly_validation_retains_its_strict_contract(self):
        with self.assertRaisesRegex(ValueError, "Unsupported assembly reference fields"):
            assembly.validate_reference({"source": "model/robot.json", "revision": ALIAS})
        with self.assertRaisesRegex(ValueError, "Pinned assembly source changed"):
            assembly.validate_reference({"source": "model/robot.json", "source_sha256": "0" * 64})

    def test_robot_fk_commands_scenario_and_controls_match_the_snapshot(self):
        selected = revisions.load_robot_revision(ALIAS)
        self.assertEqual(selected, self.baseline)
        self.assertEqual(robot.control_data(selected), robot.control_data(self.baseline))
        self.assertEqual(robot.solidcraft_commands(selected), robot.solidcraft_commands(self.baseline))
        self.assertEqual(robot.appearances(selected), robot.appearances(self.baseline))
        for angles in (robot.home(self.baseline), [0] * 6, [35, 40, 55, 20, 70, -45]):
            with self.subTest(angles=angles):
                self.assertEqual(robot.forward(selected, angles), robot.forward(self.baseline, angles))
        for scenario in self.baseline["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                self.assertEqual(robot.sample_scenario(selected, scenario["id"]),
                                 robot.sample_scenario(self.baseline, scenario["id"]))
        self.assertEqual(cameras.audit(selected), cameras.audit(self.baseline))
        self.assertEqual(services.audit(selected), services.audit(self.baseline))
        self.assertEqual(services.audit(selected)["physical_validation"]["status"], "not_performed")

    def test_dimensional_override_moves_derived_joint_frames_and_fk(self):
        selected = revisions.load_robot_revision(ALIAS, {"upper_len": 220})
        expected = robot.load(ROOT / SNAPSHOT, {"upper_len": 220})
        self.assertEqual(selected, expected)
        before, after = robot.parameters(self.baseline), robot.parameters(selected)
        self.assertEqual(after["upper_len"] - before["upper_len"], 20)
        self.assertEqual(after["elbow_z"] - before["elbow_z"], 20)
        self.assertEqual(after["flange_z"] - before["flange_z"], 20)
        baseline_frame = robot.frame(self.baseline["joints"][2], before)
        selected_frame = robot.frame(selected["joints"][2], after)
        self.assertEqual(selected_frame[2][3] - baseline_frame[2][3], 20)
        self.assertNotEqual(robot.forward(selected), robot.forward(self.baseline))
        self.assertEqual(revisions.load_robot_revision(ALIAS), self.baseline)

    def test_structural_unknown_and_derived_overrides_are_rejected(self):
        for overrides in ({"brakes": True}, {"unknown_length": 100}, {"elbow_z": 400},
                          {"upper_len": True}, {"upper_len": float("nan")}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                revisions.load_robot_revision(ALIAS, overrides)

    def test_explicit_r0_does_not_follow_edits_to_the_primary_robot(self):
        with isolated_repository() as (temporary_root, _):
            current = temporary_root / "model/robot.json"
            changed = copy.deepcopy(self.baseline)
            changed["parameters"]["upper_len"]["expression"] = "240"
            write_json(current, changed)
            self.assertNotEqual(robot.load(current), self.baseline)
            self.assertEqual(revisions.load_robot_revision(ALIAS), self.baseline)
            current.unlink()
            self.assertEqual(revisions.load_robot_revision(ALIAS), self.baseline)

    def test_raw_family_snapshot_and_type_pins_are_enforced(self):
        for field in ("family_snapshot", "type"):
            with self.subTest(field=field), isolated_repository() as (temporary_root, registry):
                path = temporary_root / registry["revisions"][ALIAS][field]
                path.write_bytes(path.read_bytes() + b"\n")
                with self.assertRaises(ValueError):
                    revisions.resolve_robot_revision(ALIAS)

    def test_materialized_and_manifest_hashes_are_independently_checked(self):
        for field in ("materialized_sha256", "revision_sha256"):
            with self.subTest(field=field), isolated_repository() as (temporary_root, registry):
                registry["revisions"][ALIAS][field] = "0" * 64
                if field == "materialized_sha256":
                    repin_manifest(registry)
                write_json(temporary_root / REGISTRY, registry)
                with self.assertRaises(ValueError):
                    revisions.load_robot_revision(ALIAS)

    def test_dependency_and_producer_bytes_and_presence_are_checked(self):
        for group in ("dependencies_sha256", "producers_sha256"):
            for mutation in ("changed", "missing"):
                with self.subTest(group=group, mutation=mutation), isolated_repository() as (temporary_root, registry):
                    relative = next(iter(registry["revisions"][ALIAS][group]))
                    path = temporary_root / relative
                    if mutation == "changed":
                        path.write_bytes(path.read_bytes() + b"\n")
                    else:
                        path.unlink()
                    with self.assertRaises(ValueError):
                        revisions.resolve_robot_revision(ALIAS)

    def test_incomplete_or_undeclared_input_sets_cannot_hide_behind_a_new_manifest_hash(self):
        for group, directory in (("dependencies_sha256", "model"), ("producers_sha256", "scripts")):
            for mutation in ("removed", "undeclared"):
                with self.subTest(group=group, mutation=mutation), isolated_repository() as (temporary_root, registry):
                    pins = registry["revisions"][ALIAS][group]
                    if mutation == "removed":
                        del pins[next(iter(pins))]
                    else:
                        path = temporary_root / directory / "undeclared-input.json"
                        write_json(path, {"unused": True})
                        pins[str(path.relative_to(temporary_root))] = robot.digest(path)
                    repin_manifest(registry)
                    write_json(temporary_root / REGISTRY, registry)
                    with self.assertRaises(ValueError):
                        revisions.load_robot_revision(ALIAS)

    def test_rehashed_type_cannot_enable_unimplemented_structural_options(self):
        with isolated_repository() as (temporary_root, registry):
            entry = registry["revisions"][ALIAS]
            path = temporary_root / entry["type"]
            definition = json.loads(path.read_text(encoding="utf-8"))
            definition["options"]["brakes"] = True
            write_json(path, definition)
            entry["type_sha256"] = robot.digest(path)
            repin_manifest(registry)
            write_json(temporary_root / REGISTRY, registry)
            with self.assertRaises(ValueError):
                revisions.load_robot_revision(ALIAS)

    def test_cli_emits_checked_robot_and_explicit_source_provenance(self):
        completed = subprocess.run([sys.executable, str(ROOT / "scripts/robot_revision.py"), ALIAS],
                                   cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["revision"], ALIAS)
        self.assertEqual(result["revision_sha256"], self.record.revision_sha256)
        self.assertEqual(result["source"], SNAPSHOT)
        self.assertEqual(result["source_sha256"], SOURCE_SHA256)
        self.assertEqual(result["materialized_sha256"], self.record.materialized_sha256)
        self.assertEqual(result["robot"], self.baseline)


if __name__ == "__main__":
    unittest.main()
