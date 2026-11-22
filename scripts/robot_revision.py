"""Explicit, source-checked loading of a robot type revision without CAD."""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

import assembly_model
import robot_components
import robot_spec


ROOT = robot_spec.ROOT
FAMILY = "model/robot.json"
CATALOG = "model/robot-revisions.json"
CATALOG_FORMAT = "solidcraftbot.robot-revisions/1"
TYPE_FORMAT = "solidcraftbot.robot-type/1"
TYPE_ID = r"[a-z][a-z0-9_]*"
ALIAS = TYPE_ID + r"@R[0-9]+"
SHA256 = r"[0-9a-f]{64}"
ENTRY_FIELDS = {
    "type", "type_sha256", "family_snapshot", "family_sha256",
    "dependencies_sha256", "producers_sha256", "materialized_sha256",
    "revision_sha256",
}
PRODUCERS = {
    "scripts/assembly_model.py",
    "scripts/robot_spec.py",
    "scripts/robot_components.py",
    "scripts/robot_cameras.py",
    "scripts/robot_services.py",
    "scripts/servo_mounting_design.py",
    "scripts/x6_mounting_design.py",
}


@dataclass(frozen=True)
class RobotRevision:
    alias: str
    revision_sha256: str
    source_path: Path
    source_sha256: str
    materialized_sha256: str


def canonical_sha256(value):
    """Hash UTF-8 canonical JSON using the revision format's serialization rules."""
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _path(relative, *directories):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Expected a project-relative revision path")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
        raise ValueError("Invalid revision path: " + relative)
    resolved = assembly_model.project_path(relative, ROOT)
    if not any(resolved.is_relative_to(ROOT / directory) for directory in directories):
        raise ValueError("Revision path is outside its expected directory: " + relative)
    return resolved


def _checked_bytes(path, expected):
    if not _matches(SHA256, expected):
        raise ValueError("Invalid revision checksum: " + str(path))
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("Missing revision input: " + str(path)) from exc
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Revision input checksum mismatch: " + str(path))
    return data


def _select(selector):
    catalog = json.loads(_path(CATALOG, "model").read_bytes())
    if (not isinstance(catalog, dict) or set(catalog) != {"format", "revisions"}
            or catalog["format"] != CATALOG_FORMAT
            or not isinstance(catalog["revisions"], dict) or not catalog["revisions"]):
        raise ValueError("Invalid robot revision catalog")
    aliases = catalog["revisions"]
    identities = {}
    for alias, entry in aliases.items():
        if (not _matches(ALIAS, alias) or not isinstance(entry, dict)
                or set(entry) != ENTRY_FIELDS or not _matches(SHA256, entry["revision_sha256"])):
            raise ValueError("Invalid robot revision entry: " + alias)
        identity = entry["revision_sha256"]
        if identity in identities:
            raise ValueError("Duplicate robot revision identity: " + identity)
        identities[identity] = alias
    if _matches(SHA256, selector):
        alias = identities.get(selector)
    else:
        alias = selector if _matches(ALIAS, selector) else None
    if alias not in aliases:
        raise ValueError("Unknown robot revision: " + str(selector))
    entry = aliases[alias]
    manifest = {key: value for key, value in entry.items() if key != "revision_sha256"}
    if canonical_sha256({"format": CATALOG_FORMAT, **manifest}) != entry["revision_sha256"]:
        raise ValueError("Robot revision identity mismatch: " + alias)
    return alias, entry


def _load_type(alias, entry):
    if not _matches(r"model/robot-types/[a-z0-9_-]+\.type\.json", entry["type"]):
        raise ValueError("Invalid robot type path: " + alias)
    path = _path(entry["type"], "model/robot-types")
    definition = json.loads(_checked_bytes(path, entry["type_sha256"]))
    if (not isinstance(definition, dict)
            or set(definition) != {"format", "id", "family", "options", "bindings"}
            or definition["format"] != TYPE_FORMAT
            or not _matches(TYPE_ID, definition["id"])
            or definition["id"] != alias.split("@")[0] or definition["family"] != FAMILY
            or definition["options"] != {}
            or not isinstance(definition["bindings"], dict)
            or set(definition["bindings"]) != {"actuator_selection"}
            or definition["bindings"]["actuator_selection"] != "model/actuator-selection.json"):
        raise ValueError("Unsupported robot type definition: " + str(path))
    return definition


def _check_dependencies(spec, definition, pins):
    if not isinstance(pins, dict):
        raise ValueError("Expected robot revision dependency checksums")
    for relative, expected in pins.items():
        _checked_bytes(_path(relative, "model", "cad/vendor"), expected)

    # Use the same vendor library checker as the arm's geometry validation.
    library = robot_components.library(spec)
    paths = {spec["vendor_library"]["path"], *definition["bindings"].values()}
    if "mobile_base" in spec:
        paths.add(spec["mobile_base"]["source"])
    for part in library["parts"].values():
        paths.update(part[field]["path"] for field in ("interface_spec", "interface_check") if field in part)
        paths.update(section["step"] for section in part["sections"].values())
    missing, extra = paths - pins.keys(), pins.keys() - paths
    if missing or extra:
        raise ValueError(f"Robot revision dependency set mismatch: missing {sorted(missing)}, extra {sorted(extra)}")


def _read_revision(revision, source_sha256):
    alias, entry = _select(revision)
    if source_sha256 is not None and source_sha256 != entry["family_sha256"]:
        raise ValueError("Conflicting source_sha256 for robot revision: " + alias)
    definition = _load_type(alias, entry)
    if not _matches(SHA256, entry["family_sha256"]) or entry["family_snapshot"] != (
        f"model/history/robot-{entry['family_sha256'][:12]}.json"
    ):
        raise ValueError("Invalid robot family snapshot path or checksum: " + alias)
    source_path = _path(entry["family_snapshot"], "model/history")
    spec = json.loads(_checked_bytes(source_path, entry["family_sha256"]))
    if canonical_sha256(spec) != entry["materialized_sha256"]:
        raise ValueError("Robot revision materialized checksum mismatch: " + alias)
    producers = entry["producers_sha256"]
    if not isinstance(producers, dict) or producers.keys() != PRODUCERS:
        raise ValueError("Robot revision producer set mismatch: " + alias)
    for relative, expected in producers.items():
        _checked_bytes(_path(relative, "scripts"), expected)
    _check_dependencies(spec, definition, entry["dependencies_sha256"])
    return RobotRevision(
        alias, entry["revision_sha256"], source_path, entry["family_sha256"],
        entry["materialized_sha256"],
    ), spec


def resolve_robot_revision(revision, *, source_sha256=None):
    """Return the checked revision identity, path and content checksums."""
    resolved, _ = _read_revision(revision, source_sha256)
    return resolved


def load_robot_revision(revision, overrides=None, *, source_sha256=None):
    """Load a verified arm, then apply any declared driving-parameter overrides."""
    _, spec = _read_revision(revision, source_sha256)
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("Expected robot parameter overrides object")
        spec = assembly_model.parameter_variant(spec, overrides)
    return robot_spec.validate(spec)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision", help="Revision alias or full revision SHA-256")
    parser.add_argument("--source-sha256", help="Optional expected checksum of the snapshot bytes")
    args = parser.parse_args(argv)
    try:
        resolved, spec = _read_revision(args.revision, args.source_sha256)
        document = {
            "revision": resolved.alias,
            "revision_sha256": resolved.revision_sha256,
            "source": resolved.source_path.relative_to(ROOT).as_posix(),
            "source_sha256": resolved.source_sha256,
            "materialized_sha256": resolved.materialized_sha256,
            "robot": robot_spec.validate(spec),
        }
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
