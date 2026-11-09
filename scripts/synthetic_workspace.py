"""Unbounded synthetic workspace with referenced furniture and equipment; no walls."""
import copy
import json
import math
from pathlib import Path
import assembly_model as assembly
import furniture_model as furniture
import robot_spec as robot

ROOT=robot.ROOT
SOURCE=ROOT/'model/synthetic-cf01-workspace.shared.json'


def read(ref):return json.loads(assembly.validate_reference(ref).read_text(encoding='utf-8'))


def pose(xyz,yaw):
    if len(xyz)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in [*xyz,yaw]):raise ValueError('Finite workspace pose required')
    t=robot.identity();c,s=math.cos(math.radians(yaw)),math.sin(math.radians(yaw));t[0][:2]=[c,-s];t[1][:2]=[s,c]
    for i in range(3):t[i][3]=xyz[i]
    return t


def load(path=SOURCE):
    spec=json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format']!='solidcraftbot.synthetic-workspace/1' or spec['units']!={'length':'mm','angle':'deg'}:raise ValueError('Synthetic workspace contract')
    if set(spec['sources'])!={'environment','furniture','furnishings','equipment'}:raise ValueError('Four workspace source layers required')
    for ref in spec['sources'].values():
        if set(ref)!={'source','source_sha256'}:raise ValueError('Workspace sources must be pinned')
    env=read(spec['sources']['environment'])
    if env['format']!='solidcraftbot.synthetic-environment/1' or env['extent']!='unbounded' or env['geometry']!='none':raise ValueError('Explicit unbounded environment without shell required')
    if set(env)-{'format','id','units','extent','geometry','world_frame','purpose'}:raise ValueError('Unbounded environment has no dimensions or boundary geometry')
    catalog=furniture.validate_catalog(read(spec['sources']['furniture']));furnishings=read(spec['sources']['furnishings']);equipment=read(spec['sources']['equipment'])
    if furnishings['format']!='solidcraftbot.furnishings/1' or equipment['format']!='solidcraftbot.equipment-layout/1':raise ValueError('Workspace composition layer contract')
    if any(layer['units']!=spec['units'] for layer in [env,furnishings,equipment]):raise ValueError('Workspace units mismatch')
    if furnishings['parameters'] or furnishings['anchors'] or furnishings['expressions'] or len(furnishings['instances'])!=1:raise ValueError('Minimal workspace supports one reference surface')
    bench=furniture.instantiate(catalog,furnishings['instances'][0],{})
    if len(bench['bodies'])!=1 or len(bench['operations'])!=1 or bench['operations'][0]['shape']['kind']!='box':raise ValueError('Axis-aligned reference surface required')
    frames={env['world_frame']:robot.identity()}
    for frame in bench['frames']:
        t=pose([robot.evaluate(v,{}) for v in frame['origin']],math.degrees(math.atan2(frame['x_axis'][1],frame['x_axis'][0])))
        if frame['id'] in frames:raise ValueError('Duplicate workspace frame')
        frames[frame['id']]=t
    devices={}
    for item in equipment['instances']:
        assembly.validate_instance(item)
        if set(item)-{'id','asset','host','xyz','yaw_deg','overrides'} or 'host' not in item:
            raise ValueError('Equipment requires a framed common assembly instance')
        if item['id'] in devices:raise ValueError('Duplicate equipment instance')
        ref=equipment['assets'][item['asset']];assembly.validate_reference(ref)
        if item['host'] not in frames:raise ValueError('Unknown equipment support frame')
        matrix=robot.multiply(frames[item['host']],pose(item['xyz'],item['yaw_deg']))
        devices[item['id']]={**item,'source':ref,'matrix':matrix}
    return {'spec':spec,'environment':env,'bench':bench,'frames':frames,'devices':devices,'equipment':equipment}


def source_dependencies(workspace):
    return [SOURCE,*[assembly.project_path(r['source']) for r in workspace['spec']['sources'].values()],*[assembly.project_path(r['source']) for r in workspace['equipment']['assets'].values()]]


def materialize_scene(scene):
    if set(scene['sources'])!={'protocol'}:raise ValueError('Device sources must come from equipment assets')
    if 'bench_surface' in scene or 'robot_parameter_overrides_mm' in scene or {'position_mm','yaw_deg'}&set(scene['arm_fixture']) or set(scene['rack'])!={'selected_slot','approach_grip_height_mm'}:
        raise ValueError('Scene geometry and device poses must come from the workspace')
    result=copy.deepcopy(scene);path=assembly.validate_reference(scene['environment']);w=load(path)
    if not {'Arm','CF01','Rack'}<=set(w['devices']):raise ValueError('CF01 workspace requires arm, centrifuge and rack')
    arm,station,rack=(w['devices'][key] for key in ['Arm','CF01','Rack'])
    if station['matrix']!=robot.identity():raise ValueError('Current pickup adapter requires station at workspace origin')
    result['sources'].update(robot=arm['source']['source'],centrifuge=station['source']['source'])
    def xyzyaw(item):
        m=item['matrix'];return [m[i][3] for i in range(3)],math.degrees(math.atan2(m[1][0],m[0][0]))
    xyz,yaw=xyzyaw(arm);result['arm_fixture'].update(position_mm=xyz,yaw_deg=yaw)
    result['robot_parameter_overrides_mm']=arm.get('overrides',{})
    xyz,yaw=xyzyaw(rack);definition=read(rack['source'])
    if definition.pop('format')!='solidcraftbot.guided-tube-rack/1':raise ValueError('Guided rack source required')
    result['rack']={**definition,**scene['rack'],'position_mm':xyz,'yaw_deg':yaw}
    shape=w['bench']['operations'][0]['shape'];body=w['bench']['bodies'][0]
    result['bench_surface']={'origin_mm':[robot.evaluate(v,{}) for v in shape['origin']],'size_mm':[robot.evaluate(v,{}) for v in shape['size']],'role':body['role']}
    return result
