"""TR01 native primitives and booleans; independent kernel and translation checks."""
from pathlib import Path
import json
import math
import sys
import FreeCAD as App
import Part
import sample_transport_model as model
from build_tube_carrier_freecad import measurements, interference, step_check


def build(spec,p,variant,path):
    if Path(path).exists(): raise FileExistsError(path)
    source=model.expanded(spec,p,variant); doc=App.newDocument(variant['id'])
    controller=doc.addObject('App::FeaturePython','Controller')
    for key,value in [('SourceFile',str(model.SOURCE.relative_to(model.ROOT))),('SpecSHA256',model.digest(model.SOURCE)),('Status',spec['status'])]:
        controller.addProperty('App::PropertyString',key,'Source'); setattr(controller,key,value)
    controller.addProperty('App::PropertyString','ParametersJSON','Source'); controller.ParametersJSON=json.dumps(p)
    groups={c['id']:doc.addObject('App::Part',c['id']) for c in source['components']}
    controller.addProperty('App::PropertyString','LoadFramesJSON','Source'); controller.LoadFramesJSON=json.dumps(source['frames'])
    latest={}; meta={b['id']:b for b in source['bodies']}
    for operation in source['operations']:
        s=operation['shape']; name=operation['id']; target=operation['body']; group=groups[meta[target]['component']]
        obj=doc.addObject('Part::Box' if s['kind']=='box' else 'Part::Cylinder',name+'_Primitive'); group.addObject(obj)
        if s['kind']=='box': obj.Length,obj.Width,obj.Height=s['size']
        else:
            obj.Radius=s['radius']; obj.Height=s['height']
            obj.Placement.Rotation=App.Rotation(App.Vector(0,0,1),App.Vector(*s['axis']))
        obj.Placement.Base=App.Vector(*s['origin'])
        if operation['action']!='create':
            boolean=doc.addObject('Part::Cut' if operation['action']=='cut' else 'Part::Fuse',name+'_Result')
            group.addObject(boolean); boolean.Base=latest[target]; boolean.Tool=obj; boolean.Refine=True; obj=boolean
        latest[target]=obj
    doc.recompute()
    for name,obj in latest.items():
        obj.Label=name
        for key,value in [('SourceBody',name),('RigidLink',meta[name]['component']),('ModelRole',meta[name]['role'])]:
            obj.addProperty('App::PropertyString',key,'Source'); setattr(obj,key,value)
    doc.recompute(); doc.saveAs(str(path)); return doc


def validate(output,case_path,report_path,step_path):
    spec=model.load(); case=json.loads(Path(case_path).read_text(encoding='utf-8'))
    variant=next(v for v in spec['variants'] if v['id']==case['variant']); p=model.parameters(spec,case['overrides'])
    source=model.expanded(spec,p,variant); doc=build(spec,p,variant,output)
    geometry=measurements(doc); exact=step_check(doc,step_path)
    baseline={b['body']:b for b in geometry}; motion=[]
    frame_checks=[{'id':source['frames'][0]['id'],
        'error_mm':abs(baseline['HandoffDeck']['bbox']['max'][2]-source['frames'][0]['origin_mm'][2])}]
    frame_checks += [{'id':f['id'],'error_mm':abs(baseline[f['id'].replace('Datum','')]['bbox']['min'][2]-f['origin_mm'][2])}
        for f in source['interfaces']]
    for check in frame_checks: check['passed']=check['error_mm']<1e-7
    # CAD body validity and reference-envelope clearances, including different
    # bodies carried on one rigid chassis. This is not a manufactured fit test.
    intrusions=[]
    from build_tube_carrier_freecad import objects
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
    from solidcraftbot_freecad import world_shape
    cover=world_shape(next(o for o in objects(doc) if o.SourceBody=='TransportCover'))
    for obj in objects(doc):
        if obj.ModelRole in ['closed_plate_reference_envelope','closed_lid_reference_envelope','closed_tube_reference_envelope']:
            volume=cover.common(world_shape(obj)).Volume
            if volume>1e-5: intrusions.append({'sample':obj.SourceBody,'cover_intersection_mm3':volume})
    for sample in model.samples(source):
        doc.recompute(); error=0
        for b in measurements(doc):
            displacement=sample['travel_mm'] if b['component']=='Car' and source['joints'] else 0
            expected=baseline[b['body']]['world_center_of_mass_mm'][:]; expected[0]+=displacement
            error=max(error,math.dist(expected,b['world_center_of_mass_mm']))
        collision=interference(doc)
        motion.append({**sample,'max_translation_error_mm':error,**collision,'passed':error<1e-6 and collision['passed']})
    doc.recompute(); doc.save(); App.closeDocument(doc.Name)
    doc=App.openDocument(str(output)); doc.recompute(); reopened=measurements(doc)
    reopened_ok=len(reopened)==len(geometry) and all(b['valid'] and b['solid_count']==1 for b in reopened)
    passed=all(b['valid'] and b['solid_count']==1 for b in geometry) and all(c['passed'] for c in exact+motion+frame_checks) and not intrusions and reopened_ok
    report={'passed':passed,'case':case,'geometry':geometry,'solidcraft_step_xor':exact,'motion_samples':motion,
        'cover_sample_intrusions':intrusions,'interfaces':source['interfaces'],'frame_geometry_checks':frame_checks,'capacity':source['capacity'],
        'reopened_passed':reopened_ok,'freecad_version':App.Version(),
        'backend':'Native Part primitives, fuses and cuts; static floor concept; shared source rebuild for dimensions'}
    Path(report_path).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8'); App.closeDocument(doc.Name)
    print(json.dumps({'passed':passed,'variant':variant['id'],'bodies':len(geometry),'samples':len(motion),
        'failed_samples':[s['id'] for s in motion if not s['passed']],'cover_intrusions':intrusions}),flush=True)
    if not passed: raise AssertionError('TR01 validation failed: '+str(report_path))


if __name__=='__main__':
    import build_sample_transport_freecad as backend
    backend.validate(*sys.argv[1:])
