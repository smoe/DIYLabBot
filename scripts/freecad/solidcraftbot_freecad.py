"""Shared FreeCAD motion helpers and retained historical A01 importer.

The FCStd contains native expression-driven placements, no serialized Python
proxy. Current geometry comes from model/robot.json; this is forward kinematics.
"""
from pathlib import Path
import hashlib
import json
import math
import time

import FreeCAD as App
import Part

STEM = "Laborarm_6R_Konzept_A01"
ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "cad" / "freecad" / (STEM + ".FCStd")
REFERENCE = ROOT / "exports" / (STEM + ".freecad-source.json")
REPORT = ROOT / "docs" / (STEM + ".freecad-validation.json")
_panels = globals().get("_panels", [])


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_reference(root=ROOT):
    root = Path(root)
    if not (root / "cad" / (STEM + ".solidcraft")).exists():
        raise ValueError("Legacy CAD files were removed. Open cad/generated/Laborarm_Neutral_Bewegung.FCMacro for the current shared model.")
    data = json.loads((root / "exports" / (STEM + ".freecad-source.json")).read_text(encoding="utf-8"))
    for name, digest in data["source_sha256"].items():
        if sha256(root / name) != digest:
            raise ValueError("Quellstand geaendert; STEP und Gelenkexport gemeinsam erneuern: " + name)
    if len(data["joints"]) != 6 or len(data["components"]) != 7:
        raise ValueError("A01 requires exactly six revolute joints and seven rigid links")
    return data


def placement(matrix):
    """SolidCraft stores matrix columns as rows; transpose for FreeCAD."""
    m = App.Matrix(*[matrix[col][row] for row in range(4) for col in range(4)])
    return App.Placement(m)


def frame_placement(frame):
    x = App.Vector(*frame["x"])
    z = App.Vector(*frame["z"])
    x.normalize()
    z.normalize()
    y = z.cross(x)
    y.normalize()
    x = y.cross(z)
    rot = App.Rotation(x, y, z, "ZXY")
    return App.Placement(App.Vector(*frame["origin"]), rot)


def nominal(data):
    return [j["values"][0]["value"] for j in data["joints"]]


def angles(doc):
    return [getattr(doc.Controller, "J" + str(i)).Value for i in range(1, 7)]


def set_angles(doc, values):
    if len(values) != 6 or not all(math.isfinite(float(v)) for v in values):
        raise ValueError("Six finite joint angles in degrees are required")
    for i, value in enumerate(values, 1):
        lo = getattr(doc.Controller, "J%dMin" % i).Value
        hi = getattr(doc.Controller, "J%dMax" % i).Value
        if not lo - 1e-9 <= value <= hi + 1e-9:
            raise ValueError("J%d outside [%s, %s] deg" % (i, lo, hi))
    for i, value in enumerate(values, 1):
        setattr(doc.Controller, "J%d" % i, float(value))
    doc.recompute()


def global_placement(obj):
    # Only native Part containers and Features are used, no Links.
    parent = obj.getParentGeoFeatureGroup()
    if parent:
        return global_placement(parent).multiply(obj.Placement)
    return obj.Placement


def world_shape(obj):
    shape = obj.Shape.copy()
    shape.Placement = global_placement(obj)
    return shape


def features(doc):
    return [obj for obj in doc.Objects if "SourceBody" in obj.PropertiesList]


def source_color(source, body_name, component_id):
    styles = source.get("appearances", {})
    style = styles.get("bodies", {}).get(body_name)
    style = style or styles.get("components", {}).get(str(component_id), {})
    return tuple(c / 255.0 for c in style.get("color", [180, 190, 200])), style.get("opacity", 1.0)


def build(root=ROOT, output=None):
    """Import exact STEP solids and add a persistent six-axis hierarchy."""
    import Import
    import zipfile

    root = Path(root)
    data = load_reference(root)
    output = Path(output) if output else root / "cad" / "freecad" / (STEM + ".FCStd")
    if output.exists():
        raise FileExistsError("Existing model is preserved: " + str(output))
    with zipfile.ZipFile(root / "cad" / (STEM + ".solidcraft")) as archive:
        source = json.loads(archive.read("document.json"))
    imported = App.newDocument("A01_STEP_Source")
    doc = None
    try:
        Import.insert(str(root / "exports" / (STEM + ".step")), imported.Name)
        doc = App.newDocument("SolidCraftBot_A01_FreeCAD")
        doc.Label = "SolidCraftBot A01 - 6R Bewegung"
        controller = doc.addObject("App::FeaturePython", "Controller")
        controller.Label = "Achswinkel (Grad)"
        for prop, value in [("DesignStatus", "Konzept A01; keine Fertigungsfreigabe"),
                            ("SourceSHA256", data["source_sha256"]["cad/" + STEM + ".solidcraft"]),
                            ("StepSHA256", data["source_sha256"]["exports/" + STEM + ".step"]),
                            ("Kinematics", "Six revolute axes; expression-driven forward kinematics"),
                            ("LimitsNote", "Vorlaeufige Demonstrationsgrenzen; kein gepruefter Bewegungsraum")]:
            controller.addProperty("App::PropertyString", prop, "Quelle")
            setattr(controller, prop, value)
            controller.setEditorMode(prop, 1)
        q0 = nominal(data)
        for i, joint in enumerate(data["joints"], 1):
            for suffix, value in [("", q0[i-1]), ("Min", joint["values"][0]["limits"][0]),
                                  ("Max", joint["values"][0]["limits"][1])]:
                prop = "J%d%s" % (i, suffix)
                controller.addProperty("App::PropertyAngle", prop, "Achsen" if not suffix else "Grenzen", joint["name"] + "; deg")
                setattr(controller, prop, value)
                if suffix:
                    controller.setEditorMode(prop, 1)
        robot = doc.addObject("App::Part", "Robot")
        robot.Label = "Laborarm A01 (mm)"
        parent = robot
        previous_frame = App.Placement()
        groups = {}
        for i, component in enumerate(data["components"]):
            transform = placement(component["occurrences"][0].get("transform", [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]))
            if i:
                joint = data["joints"][i-1]
                current_frame = frame_placement(joint["a"]["frame"])
                anchor = doc.addObject("App::Part", "J%d_Anchor" % i)
                anchor.Label = "J%d - %s" % (i, joint["name"].split("_", 1)[-1])
                parent.addObject(anchor)
                anchor.Placement = previous_frame.inverse().multiply(current_frame)
                motion = doc.addObject("App::Part", "J%d_Motion" % i)
                motion.Label = "J%d Drehung" % i
                anchor.addObject(motion)
                motion.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(0,0,1), 0))
                lo, hi = joint["values"][0]["limits"]
                expression = "max(%.15g deg; min(%.15g deg; Controller.J%d)) - %.15g deg" % (lo, hi, i, q0[i-1])
                motion.setExpression("Placement.Rotation.Angle", expression)
                parent = motion
                previous_frame = current_frame
            group = doc.addObject("App::Part", component["name"])
            parent.addObject(group)
            group.Label = component["name"]
            group.Placement = previous_frame.inverse().multiply(transform)
            groups[component["name"]] = group
            original = imported.getObject(component["name"])
            if original is None:
                raise ValueError("STEP component missing: " + component["name"])
            candidates = [o for o in original.Group if o.TypeId == "Part::Feature"]
            unmatched = set(component["bodies"])
            for obj in candidates:
                shape = obj.Shape.copy()
                shape.Placement = transform.inverse().multiply(shape.Placement)
                matches = []
                for body in data["bodies"]:
                    if body["name"] not in unmatched:
                        continue
                    error = (shape.CenterOfMass - App.Vector(*body["center_of_mass"])).Length
                    vol_error = abs(shape.Volume - body["volume_mm3"])
                    # SolidCraft measurements are tessellation based; STEP has
                    # analytic cylindrical surfaces. Match within 0.01 mm and 0.1%.
                    if error < 0.01 and vol_error < max(1e-4, body["volume_mm3"] * 0.001):
                        matches.append(body["name"])
                if len(matches) != 1:
                    raise ValueError("Ambiguous STEP/source mapping: %s -> %s" % (obj.Name, matches))
                name = matches[0]
                unmatched.remove(name)
                solid = doc.addObject("Part::Feature", name)
                group.addObject(solid)
                solid.Label = name
                solid.Shape = shape
                solid.addProperty("App::PropertyString", "SourceBody", "Quelle")
                solid.SourceBody = name
                solid.setEditorMode("SourceBody", 1)
                solid.addProperty("App::PropertyString", "RigidLink", "Quelle")
                solid.RigidLink = component["name"]
                solid.setEditorMode("RigidLink", 1)
                if App.GuiUp:
                    color, opacity = source_color(source, name, component["id"])
                    solid.ViewObject.ShapeColor = color
                    solid.ViewObject.LineColor = (0.16, 0.18, 0.21)
                    solid.ViewObject.Transparency = round(100 * (1-opacity))
            if unmatched:
                raise ValueError("Missing solids: " + str(unmatched))
        doc.recompute()
        if App.GuiUp:
            import FreeCADGui as Gui
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
        output.parent.mkdir(parents=True, exist_ok=True)
        doc.saveAs(str(output))
        return doc
    except Exception:
        if doc is not None:
            App.closeDocument(doc.Name)
        raise
    finally:
        App.closeDocument(imported.Name)


def expected_placements(data, values):
    """Independent world-axis FK, without FreeCAD expression hierarchy."""
    delta = App.Placement()
    result = {}
    for i, component in enumerate(data["components"]):
        if i:
            joint = data["joints"][i-1]
            frame = frame_placement(joint["a"]["frame"])
            rot = App.Placement(App.Vector(), App.Rotation(App.Vector(0,0,1), values[i-1] - nominal(data)[i-1]))
            delta = delta.multiply(frame).multiply(rot).multiply(frame.inverse())
        transform = placement(component["occurrences"][0].get("transform", [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]))
        result[component["name"]] = delta.multiply(transform)
    return result


def check_collisions(doc, cache=None):
    """BRep intersections; optional cache valid only for unchanged local geometry.

    Cache keys use relative rigid-link transforms. A common movement of both
    bodies cannot change their intersection volume. Callers clear the cache
    after changing dimensions or topology; interactive callers use no cache.
    """
    objects = [obj for obj in features(doc) if not ("ModelRole" in obj.PropertiesList and obj.ModelRole == "viewing_cone")]
    shapes = [(obj, world_shape(obj)) for obj in objects]
    overlaps = []
    checked = 0
    for i, (a, sa) in enumerate(shapes):
        for b, sb in shapes[i+1:]:
            if a.RigidLink == b.RigidLink:
                continue
            checked += 1
            if not sa.BoundBox.intersect(sb.BoundBox):
                continue
            # Face/edge contact cannot have positive intersection volume.
            # Avoid expensive vendor-BRep booleans for exactly touching bounds.
            ab,bb=sa.BoundBox,sb.BoundBox
            if any(min(getattr(ab,k+'Max'),getattr(bb,k+'Max')) <= max(getattr(ab,k+'Min'),getattr(bb,k+'Min')) for k in 'XYZ'):
                continue
            key=None
            if cache is not None:
                relative=global_placement(doc.getObject(a.RigidLink)).inverse().multiply(global_placement(doc.getObject(b.RigidLink)))
                key=(a.SourceBody,b.SourceBody,tuple(round(v,8) for v in relative.toMatrix().A))
            if key is not None and key in cache:volume=cache[key]
            else:
                volume = sa.common(sb).Volume
                if key is not None:cache[key]=volume
            if volume > 1e-4:
                overlaps.append({"a": a.SourceBody, "b": b.SourceBody, "volume_mm3": volume})
    return {"pose_deg": angles(doc), "pairs": checked, "overlaps": overlaps,
            "volume_threshold_mm3": 1e-4, "full_motion_envelope_checked": False}


def validate(doc, root=ROOT):
    data = load_reference(root)
    q0 = nominal(data)
    saved = angles(doc)
    report = {"design": STEM, "date": "2026-10-28", "freecad_version": App.Version(),
              "method": "STEP solids + native expression hierarchy, independent world-axis FK comparison",
              "model_sha256": sha256(doc.FileName),
              "source_sha256": data["source_sha256"], "units": {"length":"mm", "angle":"deg"},
              "body_count": len(features(doc)), "rigid_links": 7, "revolute_axes": 6,
              "geometry_checks": [], "motion_checks": [], "full_motion_envelope_checked": False}
    try:
        set_angles(doc, q0)
        refs = {b["name"]: b for b in data["bodies"]}
        for obj in features(doc):
            ref = refs[obj.SourceBody]
            shape = obj.Shape.copy()
            shape.Placement = App.Placement()
            # Shapes store geometry in the source component coordinates.
            check = {"body": obj.SourceBody, "valid": shape.isValid(), "solids": len(shape.Solids),
                     "volume_error_mm3": abs(shape.Volume - ref["volume_mm3"]),
                     "relative_volume_error": abs(shape.Volume - ref["volume_mm3"]) / ref["volume_mm3"],
                     "com_error_mm": (shape.CenterOfMass - App.Vector(*ref["center_of_mass"])).Length}
            report["geometry_checks"].append(check)
        poses = [("nominal", q0)]
        for i in range(6):
            q = q0.copy()
            q[i] += 5
            poses.append(("J%d_plus_5_deg" % (i+1), q))
        for sample in range(17):
            poses.append(("demo_%02d" % sample, demo_angles(data, sample / 16.0)))
        for label, q in poses:
            set_angles(doc, q)
            expected = expected_placements(data, q)
            error = 0.0
            for name, target in expected.items():
                actual = global_placement(doc.getObject(name))
                # Off-origin probe points also detect a lost axial rotation.
                for point in [App.Vector(), App.Vector(17,0,0), App.Vector(0,23,0), App.Vector(0,0,31)]:
                    error = max(error, (actual.multVec(point) - target.multVec(point)).Length)
            report["motion_checks"].append({"pose": label, "angles_deg": q, "max_probe_error_mm": error})
        motion_path = Path(root) / "exports" / (STEM + ".motion-reference.json")
        motion_reference = json.loads(motion_path.read_text(encoding="utf-8"))
        if motion_reference["source_sha256"] != data["source_sha256"]:
            raise ValueError("Motion reference belongs to a different source revision")
        report["solidcraft_solver_comparison"] = []
        for sample in motion_reference["samples"]:
            set_angles(doc, sample["angles_deg"])
            error = 0.0
            for component in sample["components"]:
                target = placement(component["transform"])
                actual = global_placement(doc.getObject(component["name"]))
                for point in [App.Vector(), App.Vector(17,0,0), App.Vector(0,23,0), App.Vector(0,0,31)]:
                    error = max(error, (actual.multVec(point) - target.multVec(point)).Length)
            report["solidcraft_solver_comparison"].append({"pose": sample["label"], "max_probe_error_mm": error})
        set_angles(doc, q0)
        report["nominal_collision_check"] = check_collisions(doc)
        report["passed"] = (report["body_count"] == 38
                            and all(c["valid"] and c["solids"] == 1 and c["relative_volume_error"] < 0.001 and c["com_error_mm"] < 0.01 for c in report["geometry_checks"])
                            and all(c["max_probe_error_mm"] < 1e-6 for c in report["motion_checks"])
                            and all(c["max_probe_error_mm"] < 1e-6 for c in report["solidcraft_solver_comparison"])
                            and not report["nominal_collision_check"]["overlaps"])
        report["limitations"] = ["No native Assembly solver joints: prescribed serial forward kinematics",
                                  "SolidCraft body measurements are tessellated; STEP analytic-solid mapping tolerances: 0.01 mm COM and 0.1 percent volume",
                                  "Imported solid geometry; SolidCraft feature history is not transferred",
                                  "Collision test covers nominal pose only; demonstration path and full joint ranges are not collision-certified",
                                  "No tool, forces, dynamics, payload, precision, stiffness or safety validation"]
        path = Path(root) / "docs" / (STEM + ".freecad-validation.json")
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if not report["passed"]:
            raise AssertionError("FreeCAD validation failed; see " + str(path))
        return report
    finally:
        set_angles(doc, saved)


def demo_angles(data, phase, axis=None):
    q = nominal(data)
    amplitudes = [12, 5, 5, 12, 5, 15]
    wave = math.sin(2 * math.pi * phase)
    for i in range(6):
        if axis is None or axis == i:
            q[i] += amplitudes[i] * wave
    return q


def open_model(root=ROOT, model_path=None):
    model = Path(model_path) if model_path else Path(root) / "cad" / "freecad" / (STEM + ".FCStd")
    for doc in App.listDocuments().values():
        if doc.FileName and Path(doc.FileName).resolve() == model.resolve():
            App.setActiveDocument(doc.Name)
            return doc
    if model.exists():
        return App.openDocument(str(model))
    if model_path:
        raise FileNotFoundError("Generate the shared model first: " + str(model))
    return build(root)


def prepare_view(doc):
    """Hide reference datums created with App::Part, then frame the real solids."""
    if not App.GuiUp:
        return
    import FreeCADGui as Gui
    for obj in doc.Objects:
        if obj.TypeId in {"App::Origin", "App::Line", "App::Plane", "App::Point"}:
            obj.ViewObject.Visibility = False
    Gui.updateGui()
    view = Gui.getDocument(doc.Name).activeView()
    view.viewAxonometric()
    view.fitAll()


def show_panel(root=ROOT, model_path=None, data=None, appearances=None):
    import FreeCADGui as Gui
    try:
        from PySide import QtCore, QtWidgets
    except ImportError:
        from PySide import QtCore, QtGui as QtWidgets
    data = data or load_reference(root)
    doc = open_model(root, model_path)
    if appearances is None:
        import zipfile
        with zipfile.ZipFile(Path(root) / "cad" / (STEM + ".solidcraft")) as archive:
            source = json.loads(archive.read("document.json"))
    else:
        source = appearances
    components = {c["name"]: c["id"] for c in data["components"]}
    for obj in features(doc):
        color, opacity = source_color(source, obj.SourceBody, components[obj.RigidLink])
        obj.ViewObject.ShapeColor = color
        obj.ViewObject.LineColor = (0.16, 0.18, 0.21)
        obj.ViewObject.Transparency = round(100 * (1-opacity))
    prepare_view(doc)
    for panel in list(_panels):
        try:
            same_document = panel.doc.Name == doc.Name
        except (ReferenceError, RuntimeError):
            panel.close()
            _panels.remove(panel)
            continue
        if same_document:
            panel.show()
            panel.raise_()
            return panel

    class MotionPanel(QtWidgets.QDockWidget):
        def __init__(self):
            super().__init__("SolidCraftBot - Bewegung", Gui.getMainWindow())
            self.doc = doc
            self.doc_name = doc.Name
            self.setObjectName("SolidCraftBotMotionPanel")
            widget = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(widget)
            text = QtWidgets.QLabel("A01 · 6 Drehachsen · Winkel in Grad\nKonzept mit freiem Flansch")
            layout.addWidget(text)
            self.sliders, self.spins = [], []
            names = ["Sockel", "Schulter", "Ellenbogen", "Unterarm", "Handgelenk", "Flansch"]
            for i, joint in enumerate(data["joints"]):
                row = QtWidgets.QHBoxLayout()
                row.addWidget(QtWidgets.QLabel("J%d %s" % (i+1, names[i])))
                slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
                lo, hi = joint["values"][0]["limits"]
                slider.setRange(round(lo*10), round(hi*10))
                spin = QtWidgets.QDoubleSpinBox()
                spin.setRange(lo, hi)
                spin.setDecimals(1)
                spin.setSingleStep(1)
                spin.setSuffix(" °")
                row.addWidget(slider, 1)
                row.addWidget(spin)
                layout.addLayout(row)
                self.sliders.append(slider)
                self.spins.append(spin)
                slider.valueChanged.connect(lambda value, axis=i: self.change(axis, value / 10))
                spin.valueChanged.connect(lambda value, axis=i: self.change(axis, value))
            self.mode = QtWidgets.QComboBox()
            self.mode.addItem("Alle sechs Achsen")
            for i, name in enumerate(names, 1):
                self.mode.addItem("J%d %s einzeln" % (i, name))
            layout.addWidget(self.mode)
            row = QtWidgets.QHBoxLayout()
            self.play = QtWidgets.QPushButton("Demo starten")
            self.play.clicked.connect(self.toggle)
            reset = QtWidgets.QPushButton("Standpose")
            reset.clicked.connect(self.reset)
            row.addWidget(self.play)
            row.addWidget(reset)
            layout.addLayout(row)
            collision = QtWidgets.QPushButton("Aktuelle Pose auf Überschneidung prüfen")
            collision.clicked.connect(self.collisions)
            layout.addWidget(collision)
            self.status = QtWidgets.QLabel()
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            note = QtWidgets.QLabel("Demonstrationsgrenzen. Animation ohne laufende Kollisionsprüfung.\nKeine Dynamik- oder Präzisionssimulation.")
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch()
            self.setWidget(widget)
            self.timer = QtCore.QTimer(self)
            self.timer.setInterval(33)
            self.timer.timeout.connect(self.tick)
            self.refresh()
            Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, self)
            self.setMinimumWidth(400)

        def alive(self):
            return App.listDocuments().get(self.doc_name) is self.doc

        def refresh(self):
            if not self.alive():
                self.stop()
                self.status.setText("Dokument geschlossen; Makro erneut starten.")
                return
            q = angles(self.doc)
            for i, value in enumerate(q):
                for widget, displayed in [(self.sliders[i], round(value*10)), (self.spins[i], value)]:
                    widget.blockSignals(True)
                    widget.setValue(displayed)
                    widget.blockSignals(False)
            reference = getattr(self.doc.Controller, "FlangeReference", App.Vector(*data.get("flange_reference_mm", [0,0,585])))
            point = global_placement(self.doc.L6_BareFlange).multVec(reference)
            self.status.setText("Flanschflächenmitte: X %.1f · Y %.1f · Z %.1f mm" % (point.x, point.y, point.z))

        def change(self, axis, value):
            self.stop()
            if self.alive():
                q = angles(self.doc)
                q[axis] = value
                set_angles(self.doc, q)
                self.refresh()

        def stop(self):
            self.timer.stop()
            self.play.setText("Demo starten")

        def reset(self):
            self.stop()
            if self.alive():
                set_angles(self.doc, nominal(data))
                self.refresh()

        def toggle(self):
            if self.timer.isActive():
                self.stop()
                return
            self.reset()
            self.started = time.monotonic()
            self.play.setText("Demo stoppen")
            self.timer.start()

        def tick(self):
            if not self.alive():
                self.refresh()
                return
            index = self.mode.currentIndex()
            set_angles(self.doc, demo_angles(data, (time.monotonic() - self.started) / 8, index-1 if index else None))
            self.refresh()

        def collisions(self):
            self.stop()
            if not self.alive():
                return
            self.status.setText("Prüfe aktuelle Pose …")
            Gui.updateGui()
            result = check_collisions(self.doc)
            if result["overlaps"]:
                self.status.setText("%d Überschneidung(en): %s" % (len(result["overlaps"]), "; ".join(x["a"] + " / " + x["b"] for x in result["overlaps"])))
            else:
                self.status.setText("Aktuelle Pose: keine Volumenüberschneidung zwischen starren Baugruppen > 0,0001 mm³. Kein Nachweis für die Bewegung dazwischen.")

        def closeEvent(self, event):
            self.stop()
            super().closeEvent(event)

    panel = MotionPanel()
    _panels.append(panel)
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    panel.show()
    return panel
