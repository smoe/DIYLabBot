"""FreeCAD viewing adapter and playback of the shared protocol trace."""
import json
import time

import FreeCAD as App
from PySide import QtCore, QtWidgets

import robot_spec as model
import build_neutral_freecad as backend


def show():
    spec=model.load()
    report=json.loads((model.ROOT/"exports/generated/build-report.json").read_text(encoding="utf-8"))
    if report["spec_sha256"]!=model.digest(model.SPEC) or not report["passed"]:
        raise ValueError("Run python scripts/build_models.py for the current specification first")
    path=(model.ROOT/report["artifacts"]["freecad"]).resolve()
    if not path.is_relative_to(model.ROOT.resolve()): raise ValueError("Model path leaves project")
    doc=backend.motion.open_model(model.ROOT,path)
    backend.prepare_gui(doc,spec)
    panel=backend.motion.show_panel(model.ROOT,model_path=path,data=model.control_data(spec),appearances=model.appearances(spec))
    if getattr(panel,"_neutral_protocol_initialized",False): return panel
    panel._neutral_protocol_initialized=True
    scenario=spec["scenarios"][0]
    samples=model.sample_scenario(spec,scenario["id"])
    button=QtWidgets.QPushButton("Run protocol: "+scenario["id"])
    label=QtWidgets.QLabel("Protocol checked at %d sampled poses; no continuous collision proof."%len(samples))
    label.setWordWrap(True)
    layout=panel.widget().layout()
    layout.insertWidget(layout.count()-1,button)
    layout.insertWidget(layout.count()-1,label)
    timer=QtCore.QTimer(panel); timer.setInterval(33)
    panel._neutral_protocol_timer=timer

    def stop(*unused):
        timer.stop(); button.setText("Run protocol: "+scenario["id"])

    def tick():
        if not panel.alive(): stop(); return
        elapsed=time.monotonic()-panel._protocol_started
        if elapsed>=samples[-1]["time_s"]:
            backend.motion.set_angles(doc,samples[-1]["angles_deg"]); panel.refresh()
            stop(); label.setText("Protocol complete; returned to home."); return
        after=next(i for i,s in enumerate(samples) if s["time_s"]>=elapsed)
        a,b=samples[max(0,after-1)],samples[after]
        span=b["time_s"]-a["time_s"]; u=0 if span==0 else (elapsed-a["time_s"])/span
        q=[x+(y-x)*u for x,y in zip(a["angles_deg"],b["angles_deg"])]
        backend.motion.set_angles(doc,q); panel.refresh(); label.setText("Protocol step: "+b["step"])

    def toggle():
        if timer.isActive(): stop(); return
        panel.stop(); backend.motion.set_angles(doc,samples[0]["angles_deg"]); panel.refresh()
        panel._protocol_started=time.monotonic(); button.setText("Stop protocol"); timer.start()

    timer.timeout.connect(tick); button.clicked.connect(toggle)
    panel.play.clicked.connect(stop)
    for other in panel.widget().findChildren(QtWidgets.QPushButton):
        if other is not button and other is not panel.play:
            other.clicked.connect(stop)
    for spin in panel.spins: spin.valueChanged.connect(stop)
    for slider in panel.sliders: slider.valueChanged.connect(stop)
    panel.visibilityChanged.connect(lambda visible: None if visible else stop())
    # Saving only the generated companion persists visibility and appearance.
    doc.save()
    return panel
