"""Report exact legacy robot references and source-reviewed consumer contexts.

This is an inventory, not a resolver or a CAD/motion qualification. JSON scanning
is exhaustive within the declared scope; consumer notes are deliberately reviewed
examples rather than an automatically inferred dependency graph.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "model/robot.json"
OUTPUT = "docs/robot-revision-inventory.json"
REVIEW_BASE = "7537f9e4a1f3adecb6217faa64aabcbdc231f68a"
HISTORICAL_SHA256 = "2fa84f95044690321ab774a1af807c404ee0e77a98b7770d5402f45313afa8e7"

# Evidence is intentionally narrow: changed code requires another source review,
# not just a newly stamped claim that an entire historical chain is compatible.
REVIEWED_CONTEXTS = (
    {
        "id": "legacy-default-and-generic-reference-gate",
        "classification": "current",
        "models": [],
        "finding": "The legacy default is the current robot file. Generic assembly validation compares raw file bytes; instance loading and artifact resolution use that same strict gate. No generic historical revision resolution is inferred.",
        "evidence": {
            "scripts/robot_spec.py": ['SPEC = ROOT / "model/robot.json"'],
            "scripts/assembly_model.py": ["robot.digest(path)!=ref['source_sha256']", "path = validate_reference(ref)", "source = validate_reference(ref, root)"],
        },
    },
    {
        "id": "h02-validation-build-and-native-metadata",
        "classification": "historical_mixed",
        "models": ["model/h02-arm-pickup.scene.json", "model/h02-rack-transfer.scene.json"],
        "finding": "H02's historical arm pin fails against the current alias before Program can load it. Build dependency collection repeats generic validation. The FreeCAD adapter builds program.arm, but the shared native builder stamps and checks current robot.SPEC hashes. A source-only historical resolver would not repair this native chain; historical native use remains unsupported without separate adaptation and new evidence.",
        "evidence": {
            "scripts/h02_arm_pickup.py": ["for ref in s['sources'].values():assembly.validate_reference(ref)", "self.arm=robot.load(assembly.validate_reference(s['sources']['robot']))"],
            "scripts/build_h02_arm_pickup.py": ["*[model.assembly.validate_reference(r) for r in program.definition['sources'].values()]", "paths.update(model.assembly.validate_reference(r) for r in program.transfer['sources'].values())"],
            "scripts/build_h02_arm_freecad.py": ["doc=arm_native.build(program.arm,cad/'arm-source.FCStd')"],
            "scripts/build_neutral_freecad.py": ["controller.SpecSHA256=model.digest(model.SPEC)", 'result={"spec_sha256":model.digest(model.SPEC)', "if doc.Controller.SpecSHA256!=model.digest(model.SPEC):"],
        },
    },
    {
        "id": "tr01-workcell-and-l01-instances",
        "classification": "historical_mixed",
        "models": ["model/tr01-l01-workcell.protocol.json", "model/lab-layout-l01.shared.json"],
        "finding": "TR01 validates its historical arm_source even when an actor later obtains its arm from current L01 instances. New actors fall back to the explicit arm_source. These paths mix current layout binding and an older arm pin; the inventory does not make them one historical revision.",
        "evidence": {
            "scripts/tr01_workcell.py": ["for key in ('layout','floor_motion','arm_source','tool_reference','limits_reference'):floor.assembly.validate_reference(s[key])", "source=floor.layout.instance_source(layout,original) if original else floor.robot.load(floor.assembly.validate_reference(s['arm_source']))"],
            "scripts/lab_layout_model.py": ["assembly.validate_reference(ref)", "assembly.resolve_artifact(ref)", "return assembly.load_instance(provider(kind),s['assets'][key],overrides,parameters(s))"],
        },
    },
    {
        "id": "analytics-tools-workspace-and-native-context",
        "classification": "historical_mixed",
        "models": ["model/analytics-tools.shared.json", "model/equipment/analytics-workspace.json", "model/two-arm-analytics.shared.json"],
        "finding": "Both the analytical tool mount and analytical workspace arm carry the old arm pin. Tool validation, corner-post construction and arm instances pass through generic validation. The concept build additionally obtains the vendor library from the current CF01 pickup composition. Fixing one mount reference would not qualify or consistently migrate this complete chain.",
        "evidence": {
            "scripts/analytics_concept.py": ["assembly.validate_reference(spec['robot_mount'])", "arm = robot.load(assembly.validate_reference(spec['robot_mount']))", "variants = [assembly.load_instance(robot, v['source'], v.get('overrides')) for v in arms.values()]"],
            "scripts/build_analytics_concept.py": ["scene = pickup.load()", "library = robot_components.library(pickup.arm_source(scene))"],
        },
    },
    {
        "id": "cf01-composed-arm-source",
        "classification": "current",
        "models": ["model/equipment/cf01-workspace.json", "model/synthetic-cf01-workspace.shared.json", "model/centrifuge-cf01.robot-pickup.shared.json"],
        "finding": "The CF01 scene stores no direct robot filename. Workspace binding injects it from the pinned equipment asset, and the pickup loader then reads that path with its parameter overrides. Absence from the exact-literal list does not mean absence of a robot dependency.",
        "evidence": {
            "scripts/synthetic_workspace.py": ["assembly.validate_reference(ref)", "result['sources'].update(robot=arm['source']['source'],centrifuge=station['source']['source'])"],
            "scripts/centrifuge_robot_pickup.py": ["def arm_source(scene):return robot.load(ROOT/scene['sources']['robot'],scene.get('robot_parameter_overrides_mm'))"],
        },
    },
    {
        "id": "mb01-unpinned-arm-load",
        "classification": "unpinned",
        "models": ["model/mobile-base-mb01.shared.json", "model/mobile-base.schema.json"],
        "finding": "MB01 resolves its unpinned arm_source directly and loads current file bytes. Its schema const fixes only a pathname. The reverse robot.mobile_base reference is checked for identity, not a pinned arm revision.",
        "evidence": {
            "scripts/mobile_base_model.py": ["arm_path = (ROOT/spec['arm_source']).resolve()", "arm = robot.load(arm_path)", "arm.get('mobile_base',{}).get('source')"],
        },
    },
    {
        "id": "water-practice-current-default-and-old-transitive-pins",
        "classification": "historical_mixed",
        "models": ["model/water-practice-l01.motion.json", "model/analytics-tools.shared.json", "model/tr01-l01-workcell.protocol.json"],
        "finding": "Water practice pins the current robot in its input map but kinematics calls robot.load() without an explicit reference. Its analytics/TR01 dependencies still contain older robot pins. A separate named L01 context-equivalence check strips source_sha256 fields and compares default geometry/poses; that limited equivalence is not historical robot resolution or renewed native/motion qualification.",
        "evidence": {
            "scripts/water_practice_l01.py": ["if digest(ROOT/ref['source']) != ref['source_sha256']:", "arm = robot.load()", "kit = read(ROOT/'model/analytics-tools.shared.json')"],
            "scripts/water_practice_context.py": ["if k!='source_sha256'", "if set(changed)-EQUIVALENCE_CANDIDATES:", "Default room geometry and all layout poses only; not parameter variants"],
        },
    },
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pointer_part(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def exact_references(value, pointer=""):
    """Yield exact key/value literals with their immediate containing object.

    A matching map key has the associated object as its pin context. Strings
    that merely mention the path in prose do not count as exact references.
    """
    if isinstance(value, dict):
        for key in sorted(value):
            child = value[key]
            location = pointer + "/" + pointer_part(key)
            if key == SOURCE:
                yield location, "key", child if isinstance(child, dict) else {}
            if isinstance(child, str) and child == SOURCE:
                yield location, "value", value
            yield from exact_references(child, location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            location = pointer + "/" + str(index)
            if child == SOURCE:
                yield location, "value", {}
            yield from exact_references(child, location)


def classify(pin, current_sha256):
    if pin is None:
        return "unpinned"
    if pin == current_sha256:
        return "current"
    if pin == HISTORICAL_SHA256:
        return "historical_mixed"
    return "mismatched_unresolved"


def direct_references(root):
    root = Path(root)
    current = digest(root / SOURCE)
    entries = []
    for path in sorted((root / "model").rglob("*.json")):
        relative = path.relative_to(root)
        if relative.parts[:2] == ("model", "history"):
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for pointer, occurrence, context in exact_references(document):
            pins = {key: context[key] for key in ("source_sha256", "sha256") if key in context}
            if any(not isinstance(pin, str) or not re.fullmatch("[0-9a-f]{64}", pin) for pin in pins.values()):
                raise ValueError(f"Invalid source pin: {relative.as_posix()}#{pointer}")
            if len(set(pins.values())) > 1:
                raise ValueError(f"Conflicting source pins: {relative.as_posix()}#{pointer}")
            pin = next(iter(pins.values()), None)
            if path.name.endswith(".schema.json"):
                role = "schema_path_constraint"
            elif relative.parts[:2] == ("model", "robot-types"):
                role = "type_family_reference"
            elif occurrence == "key":
                role = "source_map_key"
            elif pointer.rsplit("/", 1)[-1] in ("geometry_source", "joint_bindings_source"):
                role = "descriptive_source_metadata"
            else:
                role = "source_reference"
            entries.append({"file": relative.as_posix(), "json_pointer": pointer,
                            "occurrence": occurrence, "role": role,
                            "pin_fields": pins, "classification": classify(pin, current)})
    return entries


def reviewed_contexts(root):
    result = []
    for context in REVIEWED_CONTEXTS:
        item = {key: value for key, value in context.items() if key != "evidence"}
        item["evidence"] = []
        for name, snippets in context["evidence"].items():
            text = (root / name).read_text(encoding="utf-8")
            for snippet in snippets:
                if snippet not in text:
                    raise ValueError(f"Consumer evidence changed; review {context['id']}: {name}: {snippet}")
            item["evidence"].append({"file": name, "sha256": digest(root / name), "required_snippets": snippets})
        for name in item["models"]:
            if not (root / name).is_file():
                raise ValueError("Reviewed model context is missing: " + name)
        item["model_sha256"] = {name: digest(root / name) for name in item["models"]}
        result.append(item)
    return result


def inventory(root=ROOT):
    root = Path(root)
    entries = direct_references(root)
    return {
        "format": "solidcraftbot.robot-revision-inventory/1",
        "derived": True,
        "review_baseline_commit": REVIEW_BASE,
        "scope": {"model_glob": "model/**/*.json", "excluded_subtree": "model/history/",
                  "exact_literal": SOURCE, "include_object_keys": True,
                  "consumer_context": "Explicit source review, not exhaustive call-graph inference",
                  "git_independence": "No live HEAD, timestamps or absolute checkout paths in generated output"},
        "current_source": {"path": SOURCE, "raw_sha256": digest(root / SOURCE)},
        "classification_meanings": {
            "current": "Immediate raw pin matches current robot bytes, or a reviewed current consumer context; no qualification claim.",
            "historical_mixed": "Known old raw robot pin or reviewed chain mixing old pins/current reads. Not historical_consistent and not native qualification.",
            "unpinned": "No adjacent source pin; a schema pathname constraint or metadata alone does not resolve a revision.",
            "mismatched_unresolved": "Other nonmatching pin; no historical provenance inferred.",
        },
        "known_historical_pin": {"raw_sha256": HISTORICAL_SHA256,
                                 "provenance": "docs/line-ending-migration.json robot entry new_sha256 and Git blob 6a25eeb:model/robot.json; historical byte identity only"},
        "summary": {"direct_occurrences": len(entries), "direct_files": len({v["file"] for v in entries}),
                    "classification_counts": dict(sorted(Counter(v["classification"] for v in entries).items()))},
        "direct_references": entries,
        "reviewed_consumer_contexts": reviewed_contexts(root),
        "qualification_limits": [
            "Inventory only: no consumer, schema, existing source pin or historical evidence is migrated.",
            "No CAD builds, native or collision/motion checks, hardware execution or biological qualification are performed.",
            "An opt-in robot resolver is not generic assembly-reference support or historical native build support.",
            "Matching the main robot hash does not establish a complete, consistently pinned dependency closure.",
        ],
    }


def serialized(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the checked-in inventory differs; write nothing")
    args = parser.parse_args(argv)
    try:
        expected = serialized(inventory())
        path = ROOT / OUTPUT
        if args.check:
            if not path.is_file() or path.read_bytes() != expected.encode("utf-8"):
                print("Robot revision inventory is stale; review inputs, then regenerate with scripts/report_robot_revision_inventory.py", file=sys.stderr)
                return 1
            print("Robot revision inventory is current")
        else:
            path.write_text(expected, encoding="utf-8", newline="\n")
            print("Wrote " + OUTPUT)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
