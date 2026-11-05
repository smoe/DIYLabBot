"""Run with the Python bundled with FreeCAD; never replaces an existing model."""
from solidcraftbot_freecad import App, MODEL, build, open_model, validate

doc = open_model() if MODEL.exists() else build()
report = validate(doc)
print("FreeCAD validation:", report["passed"], "; bodies:", report["body_count"],
      "; checked poses:", len(report["motion_checks"]), flush=True)
App.closeDocument(doc.Name)
