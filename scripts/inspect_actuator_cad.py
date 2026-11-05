"""Check vendor STEP geometry with FreeCAD's core, without Qt/FreeCADGui.

Run with FreeCAD's bundled Python. Writes conservative boxes in vendor file
coordinates; these are geometry envelopes, not approved joint clearances.
"""
import FreeCAD as App
import Part

from pathlib import Path
import hashlib
import json
import re
import time

ROOT = Path(__file__).resolve().parents[1]


def inspect():
    manifest_path = ROOT / "cad/vendor/myactuator/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = []
    for record in manifest["models"]:
        started = time.monotonic()
        step = next(f for f in record["files"] if f["kind"] == "step")
        path = ROOT / step["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != step["sha256"]:
            raise ValueError("Vendor STEP changed: " + step["path"])
        print("Checking " + record["part"], flush=True)
        shape = Part.read(str(path))
        bounds = shape.BoundBox
        lo = [bounds.XMin, bounds.YMin, bounds.ZMin]
        hi = [bounds.XMax, bounds.YMax, bounds.ZMax]
        size = [b-a for a,b in zip(lo,hi)]
        solids = shape.Solids
        solid_checks = [solid.isValid() for solid in solids]
        removed = []
        for index, (solid, valid) in enumerate(zip(solids, solid_checks)):
            if valid:
                continue
            b = solid.BoundBox
            dimensions = [b.XLength, b.YLength, b.ZLength]
            # The current X4 exterior file contains two microscopic, invalid
            # solids. Only that bounded cleanup is permitted here. Keep the
            # original untouched and report every omitted entity explicitly.
            if record["part"] == "RMD-X4-P36-36-E-L" and abs(solid.Volume) < 0.001 and max(dimensions) < 0.2:
                removed.append({"source_solid_index_zero_based": index, "volume_mm3": solid.Volume,
                                "bbox_size_mm": dimensions, "reason": "Microscopic invalid solid; self-intersecting/unorientable source geometry"})
            else:
                raise ValueError("Vendor solid needs manual review: %s #%s" % (record["part"], index))
        directory = path.parent / "derived"
        directory.mkdir(exist_ok=True)
        # The X4 also contains legitimate open shells. Flattening only Solids
        # would discard much of the housing. Preserve the full topology tree.
        excluded = [solids[item["source_solid_index_zero_based"]] for item in removed]
        def preserve(node):
            if any(node.isSame(bad) for bad in excluded):
                return None
            if node.ShapeType == "Compound":
                children = [preserve(child) for child in node.childShapes()]
                return Part.makeCompound([child for child in children if child is not None])
            return node
        reference = preserve(shape)
        reference_path = directory / "cad-reference.step"
        if not reference_path.exists():
            reference.exportStep(str(reference_path))
        reopened = Part.read(str(reference_path))
        rb = reopened.BoundBox
        bbox_delta = max(abs(a-b) for a,b in zip(lo+hi,[rb.XMin,rb.YMin,rb.ZMin,rb.XMax,rb.YMax,rb.ZMax]))
        volume_delta = abs(shape.Volume-reopened.Volume)
        box = Part.makeBox(*size, App.Vector(*lo))
        proxy_path = directory / "conservative-box.step"
        if not proxy_path.exists():
            box.exportStep(str(proxy_path))
        # The unit declaration and CAD timestamp come from the STEP source,
        # while the imported dimensions use FreeCAD's native millimetres.
        raw = path.read_text(encoding="latin-1")
        millimetre_units = bool(re.search(r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", raw))
        stamp = re.search(r"'([0-9]{4}-[0-9]{2}-[0-9]{2}T[^']+)'", raw[:1000])
        result = {"part": record["part"], "bundle_revision": record["revision"], "source": step["path"],
                  "source_sha256": step["sha256"], "step_timestamp": stamp.group(1) if stamp else None,
                  "freecad_version": App.Version(), "native_length_unit": "mm", "step_declares_mm": millimetre_units,
                  "shape_valid": shape.isValid(), "solids": len(solids), "invalid_solids": solid_checks.count(False),
                  "faces": len(shape.Faces), "edges": len(shape.Edges), "geometric_volume_mm3": shape.Volume,
                  "cad_reference": reference_path.relative_to(ROOT).as_posix(),
                  "cad_reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                  "cad_reference_valid": reopened.isValid(), "cad_reference_solids": len(reopened.Solids),
                  "cad_reference_faces": len(reopened.Faces), "omitted_invalid_micro_solids": removed,
                  "reference_bbox_max_difference_mm": bbox_delta, "reference_volume_difference_mm3": volume_delta,
                  "reference_volume_relative_difference": volume_delta / abs(shape.Volume),
                  "validation_scope": "Assembly/reference geometry only; no manufacturing interface approval",
                  "acceptance": {"bbox_max_difference_mm": 0.00001, "volume_relative_difference": 0.00001,
                                 "all_reference_solids_valid": True, "reference_topology_preserved": True},
                  "bbox_mm": {"min": lo, "max": hi, "size": size, "centre": [(a+b)/2 for a,b in zip(lo,hi)]},
                  "conservative_box": proxy_path.relative_to(ROOT).as_posix(), "clearance_margin_mm": 0,
                  "housing_and_rotor_partition_verified": False, "mounting_interface_verified": False,
                  "import_elapsed_s": time.monotonic()-started,
                  "notes": ["Bounds include every supplied solid, including projecting connectors/fasteners if present.",
                            "Geometric volume is not a measured mass or inertia.",
                            "File origin and axes remain vendor-defined; housing/output frames need drawing-based registration."]}
        result["passed"] = bool(millimetre_units and solids and reopened.isValid()
                                and all(s.isValid() for s in reopened.Solids) and all(1 < v < 500 for v in size)
                                # STEP round-trip of the mixed shells/solids can
                                # change volume integration slightly. Permit at
                                # most 10 ppm for this reference representation;
                                # all bounds and retained faces must match.
                                and bbox_delta < 0.00001 and volume_delta < max(0.001, abs(shape.Volume)*1e-5)
                                and len(reopened.Faces) == len(reference.Faces)
                                and len(removed) <= 2)
        (directory / "geometry-check.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
        results.append(result)
        print(record["part"], "solids", len(solids), "faces", len(shape.Faces), "bounds mm", [round(x,3) for x in size], "passed", result["passed"], flush=True)
    report = {"backend": "FreeCAD core STEP reader; no GUI process", "models": results,
              "passed": all(r["passed"] for r in results), "robot_geometry_modified": False}
    (manifest_path.parent / "geometry-check.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    if not report["passed"]:
        raise AssertionError("Inspect the vendor geometry reports")


if __name__ == "__main__":
    import inspect_actuator_cad
    inspect_actuator_cad.inspect()
