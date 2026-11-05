"""Refresh metrics of already validated MB01 FreeCAD files without rebuilding.

Only identical source snapshots are accepted. Native geometry is copied into a
new revision. Original BRep collision evidence is retained with its checksum;
kinematic frames, tight bounds and parameter-dependent geometry are rechecked.
"""
from pathlib import Path
import json
import sys
import FreeCAD as App
import mobile_base_model as model
import robot_spec as robot
import build_mobile_base_freecad as native


def main(output,report_path,previous_report):
    previous=Path(previous_report).resolve(); old=json.loads(previous.read_text())
    spec=model.load(); arm=robot.load(); p=model.parameters(spec)
    if json.loads((previous.parent/'mobile-source.json').read_text())!=spec or json.loads((previous.parent/'arm-source.json').read_text())!=arm:
        raise ValueError('Reusing FreeCAD requires identical arm and base sources')
    if not old['passed'] or not old['reopened'] or any(s['overlaps'] for s in old['samples']):
        raise ValueError('Previous native collision validation did not pass')
    doc=App.openDocument(str(output))
    if doc.Controller.SpecSHA256!=robot.digest(robot.SPEC) or doc.Controller.MB01_SourceSHA256!=model.digest(model.SOURCE):
        raise ValueError('Native FreeCAD source metadata does not match')
    for sample,prior in zip(model.samples(spec,arm,p),old['samples']):
        if sample['id']!=prior['id']: raise ValueError('Changed collision sample sequence')
        native.set_state(doc,sample['state'],sample['id'])
        if native.probe_error(doc,spec,arm,p,sample['state'])>=1e-6: raise AssertionError('Reopened native frame mismatch')
    old['state_geometry']={}
    for name in spec['poses']:
        state=model.state(spec,arm,p,name); native.set_state(doc,state,name)
        geometry=native.measurements(doc)
        if not all(b['valid'] and b['solid_count']==1 for b in geometry): raise AssertionError('Invalid copied native geometry')
        contact=native.contact_geometry(spec,p,state,geometry)
        if not contact['passed']: raise AssertionError('Contact geometry changed')
        old['envelopes'][name]={'assembly':native.envelope(geometry),'arm':native.envelope(geometry,True),'contact_geometry':contact}
        old['state_geometry'][name]=geometry
    old['geometry']=old['state_geometry']['working']; old['working_geometry']=old['geometry']
    for edit in old['native_parameter_changes']:
        parameter=edit['parameter']; value=edit['value_mm']
        setattr(doc.ModelParameters,parameter,value); doc.recompute()
        changed=model.parameters(spec,{parameter:value}); state=model.state(spec,arm,changed,'working')
        native.set_state(doc,state,'parameter_check')
        edit['geometry']=native.measurements(doc)
        error=native.probe_error(doc,spec,arm,changed,state)
        if error>=1e-6: raise AssertionError('Native parameter frame mismatch')
        edit['max_probe_error_mm']=error
        setattr(doc.ModelParameters,parameter,p[parameter]); doc.recompute()
    App.closeDocument(doc.Name)
    old['reused_collision_evidence']={'report':str(previous.relative_to(model.ROOT)).replace('\\','/'),
        'sha256':model.digest(previous),'method':'Identical source snapshots and native saved geometry; original BRep collision results retained; all sample frames rechecked',
        'tight_bounds_refreshed':True,'geometry_rebuilt':False}
    Path(report_path).write_text(json.dumps(old,indent=2)+'\n',encoding='utf-8')
    print('Native source, frame probes, tight bounds and dimension variants rechecked',flush=True)


if __name__=='__main__':
    import recheck_mobile_geometry
    recheck_mobile_geometry.main(*sys.argv[1:])
