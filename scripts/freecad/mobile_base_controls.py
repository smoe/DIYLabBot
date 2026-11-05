"""Optional FreeCAD GUI pose selector. Changes the CAD view only, never hardware."""
from pathlib import Path
import json
import sys


def show(root):
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    root=Path(root); sys.path.insert(0,str(root/'scripts'))
    import mobile_base_model as model
    import robot_spec as robot
    from build_mobile_base_freecad import set_state
    report=json.loads((root/'cad/mobile-base-mb01/shared-build-report.json').read_text(encoding='utf-8'))
    if not report['passed'] or report['source_sha256']!=model.digest(model.SOURCE) or report['arm_sha256']!=robot.digest(robot.SPEC):
        raise ValueError('MB01 build is stale; regenerate from the shared source first')
    path=(root/next(s['freecad'] for s in report['states'] if s['id']=='working')).resolve()
    doc=next((d for d in App.listDocuments().values() if d.FileName and Path(d.FileName).resolve()==path),None)
    if doc is None: doc=App.openDocument(str(path))
    App.setActiveDocument(doc.Name)
    spec=model.load(); arm=robot.load(); p=model.parameters(spec)
    window=Gui.getMainWindow(); prior=window.findChild(QtWidgets.QDockWidget,'MB01_PoseSelector')
    if prior: prior.close(); prior.deleteLater()
    dock=QtWidgets.QDockWidget('MB01 — manual base CAD poses',window); dock.setObjectName('MB01_PoseSelector')
    widget=QtWidgets.QWidget(); layout=QtWidgets.QVBoxLayout(widget)
    label=QtWidgets.QLabel('Concept geometry only. No hardware control.\nAfter moving: fresh tip/tube localization before operation.')
    label.setWordWrap(True); layout.addWidget(label)
    for name in spec['poses']:
        button=QtWidgets.QPushButton(name.replace('_',' ').title())
        def apply(checked=False,name=name):
            set_state(doc,model.state(spec,arm,p,name),name)
            Gui.activeDocument().activeView().fitAll()
        button.clicked.connect(apply); layout.addWidget(button)
    layout.addStretch(); dock.setWidget(widget); window.addDockWidget(QtCore.Qt.RightDockWidgetArea,dock); dock.show()
    return dock
