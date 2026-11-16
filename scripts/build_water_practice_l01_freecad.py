"""Build current-arm water motions against the byte-bound existing L01 scene.

Full native BRep overlap tests are discrete, not a continuous safety proof.
"""
import argparse
import base64
import gzip
import json
import math
import struct
import sys
import time
from pathlib import Path

import FreeCAD as App
import Part
import water_practice_l01 as m
import water_practice_context as context_equivalence
import build_neutral_freecad as arm_native
import build_tr01_workcell_freecad as native
import check_tr01_floor_motion as boxes
from build_synthetic_lab_scene_freecad import primitive
sys.path.insert(0,str(m.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo


def moved(shape,matrix):
    # Separate TopoShape/location wrapper, sharing immutable geometry. A full
    # BRep copy at every sample dominates the check without changing solids.
    result=Part.Shape(shape)
    result.Placement=native.placement(matrix).multiply(result.Placement)
    return result


def canonical(value):
    return __import__('hashlib').sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def geometry_inputs(source):
    import robot_components
    names=['scripts/build_neutral_freecad.py','scripts/robot_components.py','scripts/robot_cameras.py',
           'scripts/servo_mounting_design.py','scripts/freecad/solidcraftbot_freecad.py',
           'scripts/build_synthetic_lab_scene_freecad.py','scripts/check_tr01_floor_motion.py',
           source['vendor_library']['path']]
    for part in robot_components.library(source)['parts'].values():
        names.extend(part[k]['path'] for k in ('interface_spec','interface_check') if k in part)
        names.extend(section['step'] for section in part['sections'].values())
    return {name:m.digest(m.ROOT/name) for name in names}


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n')


def context_inputs(context):
    """Audit original artifacts without rewriting any historical source pins."""
    report=m.read(context/'cad/tr01-workcell/shared-build-report.json')
    visited=set();pending=dict(report['source_files_sha256']);pins=dict(pending)
    while pending:
        name,sha=pending.popitem()
        if name in visited:continue
        visited.add(name)
        path=context/name
        if name in ('scripts/render_tr01_workcell.py','scripts/tr01_workcell_player.html'):continue
        if m.digest(path)!=sha:raise ValueError('Changed original native context: '+name)
        if name.startswith(('cad/','exports/')) and path.suffix=='.json':
            value=m.read(path)
            if isinstance(value,dict):
                for child,digest in value.get('source_files_sha256',{}).items():
                    if child not in visited:pending[child]=digest;pins[child]=digest
    # Only robot cameras changed since the original L01 derivation. The new
    # water scene replaces ALL four native arm instances from current source.
    changed={}
    for name,sha in pins.items():
        if name.startswith(('model/','scripts/','cad/vendor/')) and name not in ('model/robot.json','scripts/render_tr01_workcell.py','scripts/tr01_workcell_player.html'):
            if m.digest(m.ROOT/name)!=sha:changed[name]={'original_sha256':sha,'current_sha256':m.digest(m.ROOT/name)}
    for key,filename in report['files'].items():
        if key in report['artifact_sha256'] and m.digest(context/filename)!=report['artifact_sha256'][key]:
            raise ValueError('Changed native artifact: '+key)
    old=m.read(context/'model/robot.json');new=m.robot.load()
    if [v['id'] for v in old['links']]!=[v['id'] for v in new['links']]:raise ValueError('Link mapping changed')
    for key in ('joints','flange_reference'):
        if old[key]!=new[key]:raise ValueError('L01 arm kinematics changed: '+key)
    # Current parameters may differ solely in camera optics/envelopes.
    if {k:v for k,v in old['parameters'].items() if not k.startswith('cam_')}!={k:v for k,v in new['parameters'].items() if not k.startswith('cam_')}:
        raise ValueError('L01 arm dimensions changed')
    preview=m.read(context/report['files']['preview_data'])
    equivalence=context_equivalence.verify(context,m.ROOT,changed) if changed else None
    return report,preview,pins,equivalence


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--native-context',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();context=args.native_context.resolve();out=m.OUT;out.mkdir(parents=True,exist_ok=True)
    report,preview,pins,equivalence=context_inputs(context)
    definition=m.load()
    program={'definition':definition,'kit':m.read(m.ROOT/'model/analytics-tools.shared.json'),'paths':definition['paths'],'actors':preview['actors']}
    source=m.robot.load();inputs=geometry_inputs(source);arm_meta=out/'arm-build.json'
    cached=m.read(arm_meta) if arm_meta.exists() else None
    if cached and cached['source_files_sha256']=={**inputs,'model/robot.json':m.digest(m.robot.SPEC)} and m.digest(out/cached['file'])==cached['artifact_sha256']:
        arm_path=out/cached['file'];arm=App.openDocument(str(arm_path))
    else:
        arm_path=out/('arm-'+m.digest(m.robot.SPEC)[:12]+'-'+str(time.time_ns())+'.FCStd')
        arm=arm_native.build(source,arm_path)
        write(arm_meta,{'file':arm_path.name,'artifact_sha256':m.digest(arm_path),
                        'source_files_sha256':{**inputs,'model/robot.json':m.digest(m.robot.SPEC)}})
    ref=m.robot.forward(source,geo.angles(arm));local={}
    for obj in geo.features(arm):
        if getattr(obj,'ModelRole','')=='viewing_cone':continue
        local.setdefault(obj.RigidLink,[]).append(moved(geo.world_shape(obj),m.robot.inverse(ref[obj.RigidLink])))
    local_parts=local
    local={link:Part.makeCompound(shapes) for link,shapes in local.items()}
    kit=program['kit'];s=program['definition'];pipette,_=m.tools.kit_parts(kit,s['pipette_case']);fixture,_=m.tools.kit_parts(kit,s['fixture_case'])
    def shapes(parts):
        result=[]
        for part in parts:
            shape=primitive(part['shape'])
            for v in part['additions']:shape=shape.fuse(primitive(v))
            for v in part['cuts']:shape=shape.cut(primitive(v))
            result.append((part['id'],shape))
        return result
    pipette=shapes(pipette);fixture=shapes(fixture)
    doc=App.openDocument(str(context/report['files']['freecad']))
    actors=set(program['actors'])|{'ArmB'}
    static=[(o.Label,geo.world_shape(o)) for o in doc.Objects if hasattr(o,'Shape') and not o.Shape.isNull()
            and not any(o.Label.startswith(a+'.') for a in actors)]
    # Replace the fourth parked arm as well, including its new camera bodies.
    layout=m.read(m.ROOT/'model/lab-layout-l01.shared.json')
    import lab_layout_model as lm
    item=next(i for i in layout['instances'] if i['id']=='ArmB');base=lm.matrix(item,lm.parameters(layout));home=m.robot.forward(source,[0]*6)
    for link,shape in local.items():static.append(('ArmB.'+link,moved(shape,m.robot.multiply(base,home[link]))))
    fixture_records=[]
    for path,definition in program['paths'].items():
        for role in ('source','target'):
            matrix=m.pickup.placement(definition[role+'_mm'],0)
            for name,shape in fixture:
                world=moved(shape,matrix);identity=path+'.'+role+'.'+name
                static.append((identity,world));fixture_records.append((identity,world))
    installation=[]
    original_static=[(name,shape,boxes.box(shape)) for name,shape in static if not name.startswith(tuple(p+'.' for p in program['paths']))]
    for name,shape in fixture_records:
        bound=boxes.box(shape)
        for obstacle,other,ob in original_static:
            if any(bound['max'][i]<=ob['min'][i]+1e-6 or ob['max'][i]<=bound['min'][i]+1e-6 for i in range(3)):continue
            overlap=shape.common(other).Volume
            if overlap>1e-3:installation.append({'fixture':name,'obstacle':obstacle,'overlap_mm3':overlap})
    if installation:raise ValueError('Fixture installation overlaps native scene: '+json.dumps(installation[:10]))
    cache_path=out/'motion-cache.json';cached=m.read(cache_path) if cache_path.exists() else None
    candidate=cached['program'] if cached and canonical(cached['program'])==cached['sha256'] else None
    valid=candidate and candidate['fixture_report_sha256']==m.digest(args.report) and all(m.digest(m.ROOT/name)==sha for name,sha in candidate['source_files_sha256'].items())
    if valid:
        program=candidate
        for actor,values in preview['actors'].items():
            if values!=program['actors'][actor]:raise ValueError('Cached arm frames differ')
    else:
        program=m.compile_program(preview['actors'],m.read(args.report))
        program['fixture_report_sha256']=m.digest(args.report)
        program['flange_reference_mm']=[m.robot.evaluate(v,m.robot.parameters(source)) for v in source['flange_reference']['point']]
        write(cache_path,{'sha256':canonical(program),'program':program})
    print('Water PVA compiled',flush=True)
    checks=[];mesh_records=[];links=[v['id'] for v in source['links']]
    for i,(actor,d) in enumerate(program['actors'].items()):
        d['water_kind']=400+i*20
        for j,link in enumerate(links):
            mesh_records.extend((d['water_kind']+j,shape) for shape in local_parts[link])
        # Semantic tool origin is the flange reference, not the link origin.
        for _,shape in pipette:mesh_records.append((d['water_kind']+7,shape))
    for _,shape in fixture_records:mesh_records.append((480,shape))
    case=kit['cases'][s['fixture_case']]
    mesh_records.append((482,Part.makeCylinder(case['tube_radius_mm']*.85,s['fluid_display_full_height_mm'])))
    # The parked fourth arm's current geometry is displayed in water mode.
    for link,parts in local_parts.items():
        mesh_records.extend((481,moved(shape,m.robot.multiply(base,home[link]))) for shape in parts)
    moving_boxes={name:boxes.box(shape) for name,shape in [*local.items(),*pipette]}
    for path,definition in program['paths'].items():
        actor=definition['actor'];kin=m.kinematics(s,actor,program['actors'])
        obstacles=list(static)
        for other,otherdef in program['paths'].items():
            if other==path:continue
            otherkin=m.kinematics(s,otherdef['actor'],program['actors']);fk=otherkin.forward(otherdef['park'])
            obstacles.extend((otherdef['actor']+'.'+link,moved(shape,fk[link])) for link,shape in local.items())
            flange=m.robot.multiply(fk[source['flange_reference']['link']],m.pickup.placement(otherkin.flange,0))
            obstacles.extend((otherdef['actor']+'.'+name,moved(shape,flange)) for name,shape in pipette)
        obstacles=[(name,shape,boxes.box(shape)) for name,shape in obstacles]
        for part,curve_def in definition['curves'].items():
            curve=m.motion.Curve(curve_def['points']);speed=curve_def['fk_bounds']['velocity_mm_s'];rate=max(curve_def['joint_bounds'][m.F[1]]['max_abs'])
            dt=min(.08,math.radians(.75)/max(rate,1e-9),2/max(speed,1e-9));n=math.ceil(curve.times[-1]/dt)
            times=sorted(set(curve.times+[curve.times[-1]*i/n for i in range(n+1)]));failures=[];queries=0
            for t in times:
                q=[math.degrees(v) for v in curve.evaluate(t)[m.F[0]]];fk=kin.forward(q)
                flange=m.robot.multiply(fk[source['flange_reference']['link']],m.pickup.placement(kin.flange,0))
                moving=[(link,shape,fk[link]) for link,shape in local.items()]
                moving += [(name,shape,flange) for name,shape in pipette]
                for name,original,matrix in moving:
                    b=moving_boxes[name]
                    corners=[m.robot.transform(matrix,[x,y,z]) for x in (b['min'][0],b['max'][0]) for y in (b['min'][1],b['max'][1]) for z in (b['min'][2],b['max'][2])]
                    bound={'min':[min(p[i] for p in corners) for i in range(3)],'max':[max(p[i] for p in corners) for i in range(3)]}
                    shape=None
                    for obstacle,other,ob in obstacles:
                        if name=='L0_Base' and obstacle=='Mount'+actor:continue
                        if any(bound['max'][i]<=ob['min'][i]+1e-6 or ob['max'][i]<=bound['min'][i]+1e-6 for i in range(3)):continue
                        if shape is None:shape=moved(original,matrix)
                        queries+=1;overlap=shape.common(other).Volume
                        if overlap>1e-3:failures.append({'time_s':t,'body':name,'obstacle':obstacle,'overlap_mm3':overlap})
                if failures:break
            check={'path':path,'part':part,'passed':not failures,'samples':len(times),'maximum_step_s':dt,'queries':queries,'failures':failures[:10]}
            checks.append(check);print(json.dumps(check),flush=True)
    # Derived display meshes use the same current native arms and semantic kit.
    vertices=[];groups={}
    for kind,shape in mesh_records:
        pts,faces=shape.tessellate(2.)
        if len(faces)>500:
            b=shape.BoundBox;pts,faces=Part.makeBox(max(.01,b.XLength),max(.01,b.YLength),max(.01,b.ZLength),App.Vector(b.XMin,b.YMin,b.ZMin)).tessellate(2.)
        offset=len(vertices)//3
        vertices.extend(round(float(v)*4) for p in pts for v in p)
        groups.setdefault(kind,[]).extend(offset+i for face in faces for i in face)
    payload=struct.pack('<II',len(vertices)//3,len(groups))+struct.pack('<'+'h'*len(vertices),*vertices)
    for kind,indices in groups.items():payload+=struct.pack('<II',kind,len(indices))+struct.pack('<'+'I'*len(indices),*indices)
    program['mesh']=base64.b64encode(gzip.compress(payload,9)).decode()
    program['native_context']={'revision':report['revision'],'original_arm_sha256':pins['model/robot.json'],
        'replacement_arm_sha256':m.digest(m.robot.SPEC),'all_arm_instances_replaced':True,
        'native_scene_sha256':m.digest(context/report['files']['freecad']),
        'original_context_files_sha256':pins,'default_geometry_equivalence':equivalence,'current_arm_artifact_sha256':m.digest(arm_path)}
    proof={'passed':all(c['passed'] for c in checks),'checks':checks,'fixture_installation_overlaps':installation,
        'scope':'Discrete native current arms and concept pipettor versus unchanged L01 solids, six open fixtures and all other parked current arms. No continuous clearance or self-collision certificate.',
        'excluded_contacts':['L0_Base against own mounting support only'],
        'hardware_executed':False,'limits_qualified':False,'human_speed_comparison':None}
    program['proof']=proof
    program['source_files_sha256'].update({name:sha for name,sha in pins.items()
        if name.startswith(('model/','scripts/','cad/vendor/')) and name not in ('model/robot.json','scripts/tr01_workcell_player.html','scripts/render_tr01_workcell.py')})
    program['source_files_sha256'].update(inputs)
    if equivalence:
        program['source_files_sha256'].update({name:values['current_sha256'] for name,values in equivalence['changed_sources'].items()})
    program['source_files_sha256']['scripts/water_practice_context.py']=m.digest(context_equivalence.__file__)
    program['source_files_sha256']['scripts/build_water_practice_l01_freecad.py']=m.digest(__file__)
    program['program_sha256']=__import__('hashlib').sha256(json.dumps(program,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    write(out/'program.json',program);write(out/'native-proof.json',proof)
    if not proof['passed']:raise ValueError('Water motion native collision check failed')


if __name__=='__main__':
    import build_water_practice_l01_freecad as adapter
    adapter.main()
