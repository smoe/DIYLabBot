"""Independent OCC construction and continuous-sweep audit; STEP is comparison only."""
import FreeCAD as App
import sys
from pathlib import Path
import json
import types
import xml.etree.ElementTree as ET
import zipfile
import h02_direct_pickup as model
import build_tube_carrier_freecad as native
import build_extraction_kit_station as evidence
import build_relative_floorplan as compare


def presentation(path,source,geometry,hidden):
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    report=persist(path,source,geometry)
    with zipfile.ZipFile(path) as archive:contents={n:archive.read(n) for n in archive.namelist()}
    document=ET.fromstring(contents['Document.xml']);gui=ET.fromstring(contents['GuiDocument.xml'])
    names={o.get('name') for o in document.findall('ObjectData/Object')
           if (o.find("Properties/Property[@name='SourceBody']/String") is not None and
               o.find("Properties/Property[@name='SourceBody']/String").get('value') in hidden)}|{'Proof'}
    for provider in gui.findall('ViewProviderData/ViewProvider'):
        if provider.get('name') in names:
            provider.find("Properties/Property[@name='Visibility']/Bool").set('value','false')
    contents['GuiDocument.xml']=ET.tostring(gui,encoding='utf-8',xml_declaration=True)
    temp=path.with_suffix('.visibility-tmp')
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in contents.items():archive.writestr(name,data)
    temp.replace(path)
    with zipfile.ZipFile(path) as archive:
        if any(archive.read(name)!=data for name,data in contents.items()):
            raise AssertionError('Presentation archive changed native geometry bytes')
    report['visible_final_bodies']=len(source['bodies'])-len(hidden)
    report['hidden_proof_and_keepout_bodies']=sorted(hidden)
    return report


def build(case_path):
    case=json.loads(Path(case_path).read_text());evidence.verify_pins(case['pins'])
    scene=model.load();spec=model.context(scene,case['variant']);p=model.parameters(spec)
    source,pairs,witnesses=model.proof(spec,p)
    provider=types.SimpleNamespace(ROOT=model.ROOT,SOURCE=model.SOURCE,digest=model.digest,evaluate=model.evaluate,
        expanded=lambda s,p:source,pose=model.pose,validate_pose=model.validate_pose)
    native.model=provider
    doc=native.build(spec,p,model.ROOT/case['freecad'])
    for c in source['components']:
        if 'instance_translation_mm' in c:
            doc.getObject(c['id']).Placement.Base=App.Vector(*c['instance_translation_mm'])
    doc.recompute();geometry=native.measurements(doc)
    shapes={o.SourceBody:native.motion.world_shape(o) for o in native.objects(doc)}
    checks=[]
    for item in pairs:
        a,b=shapes[item['a']],shapes[item['b']]
        distance=a.distToShape(b)[0]
        overlap=a.common(b).Volume if a.BoundBox.intersect(b.BoundBox) else 0.
        passed=overlap<=scene['volume_tolerance_mm3'] and distance+1e-6>=item['required_mm']
        if item['intended_pad_contact']:passed=passed and distance<=1e-6
        checks.append({**item,'distance_mm':distance,'overlap_mm3':overlap,'passed':passed})
    tube=shapes['Selected_ReferenceTube'];block=shapes['NegativeMidpathBlocker']
    final=tube.copy();final.translate(App.Vector(0,0,p['tube_travel']))
    negative={'middle_volume_mm3':shapes['extraction_TubeEnvelope'].common(block).Volume,
              'start_volume_mm3':tube.common(block).Volume,'end_volume_mm3':final.common(block).Volume,
              'lowered_finger_overlap_mm3':shapes['NegativeLowFingerPad'].common(shapes['Selected_CarrierShell']).Volume}
    negative['passed']=negative['middle_volume_mm3']>1 and negative['lowered_finger_overlap_mm3']>1 and max(negative['start_volume_mm3'],negative['end_volume_mm3'])<1e-5
    states=[]
    for sample in model.samples(spec,p):
        native.set_pose(doc,source,sample['values_mm']);measured=native.measurements(doc);errors=[]
        for before,after in zip(geometry,measured):
            a=model.displacement(source,before['component'],model.pose(spec,p))
            b=model.displacement(source,before['component'],sample['values_mm'])
            errors.append(max(abs(after['bbox'][edge][i]-before['bbox'][edge][i]-b[i]+a[i]) for edge in ['min','max'] for i in range(3)))
        states.append({'id':sample['id'],'maximum_position_error_mm':max(errors),'passed':max(errors)<1e-6})
    native.set_pose(doc,source,model.pose(spec,p))
    step=native.step_check(doc,model.ROOT/case['step']) if case.get('step') else []
    for obj in native.objects(doc):
        if obj.SourceBody in witnesses or obj.SourceBody.endswith('MouthKeepout'):
            if obj.ViewObject:obj.ViewObject.Visibility=False
    doc.save();App.closeDocument(doc.Name)
    doc=App.openDocument(str(model.ROOT/case['freecad']));reopen=compare.comparison(geometry,native.measurements(doc));App.closeDocument(doc.Name)
    hidden=set(witnesses)|{b['id'] for b in source['bodies'] if b['id'].endswith('MouthKeepout')}
    view=presentation(model.ROOT/case['freecad'],source,geometry,hidden)
    evidence.verify_pins(case['pins'])
    passed=all(x['passed'] for x in checks+states+step+reopen) and negative['passed'] and view['passed']
    report={'passed':passed,'pins':case['pins'],'geometry':geometry,'continuous_checks':checks,
            'negative_midpath_control':negative,'native_states':states,'step_checks':step,'reopen':reopen,'presentation':view}
    evidence.write(model.ROOT/case['freecad_report'],report)
    print(json.dumps({'variant':case['variant'],'passed':passed,'pairs':len(checks),
        'failed':[c for c in checks+states if not c['passed']]}),flush=True)
    if not passed:raise AssertionError('H02 direct-pickup OCC audit failed')


if __name__=='__main__':build(sys.argv[1])
