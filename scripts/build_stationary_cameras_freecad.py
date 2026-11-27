"""Derive and measure native FreeCAD camera geometry without another CAD backend."""

import argparse
import json
from pathlib import Path

import FreeCAD as App

import build_tube_carrier_freecad as native
import stationary_camera as model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=model.VARIANTS)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    spec = model.materialize(model.load(), args.variant)
    p = model.parameters(spec)
    source = model.expanded(spec, p)
    native.model = model
    doc = native.build(spec, p, args.output)
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(args.output))
    try:
        doc.recompute()
        default_geometry = native.measurements(doc)
        sample_geometry = []
        for sample in model.samples(spec, p):
            native.set_pose(doc, source, sample["joint_values"])
            sample_geometry.append(native.measurements(doc))
        report = {
            "default_geometry": default_geometry,
            "sample_geometry": sample_geometry,
            "freecad_version": App.Version(),
        }
        args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    finally:
        App.closeDocument(doc.Name)


if __name__ == "__main__":
    main()
