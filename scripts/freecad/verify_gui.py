"""GUI integration check, invoked from the supplied FreeCAD verification macro.

Uses Qt timer callbacks so FreeCAD remains responsive during the demo checks.
Only the companion document is changed, and its final saved pose is nominal.
"""
from pathlib import Path
import importlib
import json
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

import solidcraftbot_freecad as bot

_runs = []


def start(root=bot.ROOT):
    importlib.reload(bot)
    root = Path(root)
    data = bot.load_reference(root)
    panel = bot.show_panel(root)
    doc = panel.doc
    report = {"design": bot.STEM, "date": "2026-10-28", "freecad_version": App.Version(),
              "source_sha256": data["source_sha256"], "initial_pose_deg": bot.angles(doc),
              "spinbox_checks": [], "slider_checks": [], "timer_checks": [],
              "full_motion_envelope_checked": False}
    report_path = root / "docs" / (bot.STEM + ".freecad-gui-validation.json")
    panel.reset()
    q0 = bot.nominal(data)

    def check_widgets(kind, widgets, scale):
        for axis, widget in enumerate(widgets):
            panel.reset()
            target = q0[axis] + 5
            widget.setValue(round(target * scale) if scale != 1 else target)
            actual = bot.angles(doc)
            expected = q0.copy()
            expected[axis] = target
            passed = all(abs(a-b) < 1e-8 for a, b in zip(actual, expected))
            passed = passed and panel.sliders[axis].value() == round(target*10)
            passed = passed and abs(panel.spins[axis].value() - target) < 1e-8
            report[kind].append({"axis": axis+1, "pose_deg": actual, "passed": passed})
            if not passed:
                raise AssertionError("Widget/kinematics mismatch for J%d" % (axis+1))

    def save_report():
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def failed():
        report["passed"] = False
        report["error"] = traceback.format_exc()
        panel.reset()
        save_report()
        App.Console.PrintError(report["error"])

    def finish():
        try:
            panel.reset()
            panel.mode.setCurrentIndex(0)
            assert all(abs(a-b) < 1e-8 for a,b in zip(bot.angles(doc), q0))
            bot.prepare_view(doc)
            report["visible_reference_datums"] = [obj.Name for obj in doc.Objects if obj.TypeId in {"App::Origin", "App::Line", "App::Plane", "App::Point"} and obj.ViewObject.Visibility]
            assert not report["visible_reference_datums"]
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
            Gui.updateGui()
            nominal_path = root / "renders" / (bot.STEM + "_FreeCAD_nominal.png")
            Gui.activeDocument().activeView().saveImage(str(nominal_path), 1400, 1050, "White")
            bot.set_angles(doc, bot.demo_angles(data, 0.25))
            panel.refresh()
            Gui.updateGui()
            demo_path = root / "renders" / (bot.STEM + "_FreeCAD_demo.png")
            Gui.activeDocument().activeView().saveImage(str(demo_path), 1400, 1050, "White")
            panel.reset()
            doc.recompute()
            doc.save()
            report["final_pose_deg"] = bot.angles(doc)
            report["model_sha256"] = bot.sha256(doc.FileName)
            report["renders"] = {str(p.relative_to(root)).replace("\\", "/"): bot.sha256(p) for p in [nominal_path, demo_path]}
            report["passed"] = all(x["passed"] for key in ["spinbox_checks", "slider_checks", "timer_checks"] for x in report[key])
            report["notes"] = ["Qt signals exercised on all six spinboxes and sliders",
                               "Real QTimer ran in combined and all six individual modes",
                               "Native FreeCAD view exports; desktop screen capture unavailable",
                               "Demonstration poses are not collision-certified"]
            save_report()
            App.Console.PrintMessage("SolidCraftBot GUI check passed; nominal pose saved.\n")
        except Exception:
            failed()

    def stop_and_check(mode):
        try:
            panel.stop()
            actual = bot.angles(doc)
            moved = [abs(a-b) > 1e-4 for a,b in zip(actual, q0)]
            passed = all(moved) if mode == 0 else moved[mode-1] and sum(moved) == 1
            passed = passed and not panel.timer.isActive() and panel.play.text() == "Demo starten"
            report["timer_checks"].append({"mode": mode, "pose_deg": actual, "moved_axes": moved, "passed": passed})
            if not passed:
                raise AssertionError("Demo timer check failed in mode %d" % mode)
            if mode < 6:
                QtCore.QTimer.singleShot(30, lambda: run_mode(mode+1))
            else:
                QtCore.QTimer.singleShot(30, finish)
        except Exception:
            failed()

    def run_mode(mode):
        try:
            panel.mode.setCurrentIndex(mode)
            panel.toggle()
            assert panel.timer.isActive()
            QtCore.QTimer.singleShot(400, lambda: stop_and_check(mode))
        except Exception:
            failed()

    try:
        check_widgets("spinbox_checks", panel.spins, 1)
        check_widgets("slider_checks", panel.sliders, 10)
        panel.reset()
        _runs.append((panel, report))
        QtCore.QTimer.singleShot(100, lambda: run_mode(0))
    except Exception:
        failed()
