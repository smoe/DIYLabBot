"""Adaptive native BRep audit of the displayed CF01 retrieval and rack path.

Uses the existing L01 conservative OBB/SAT broad phase. No mesh-based claims.
Sampling bounds are recorded explicitly; this is not swept-volume certification.
"""
import itertools
import json
import math
from pathlib import Path
import FreeCAD as App
import centrifuge_robot_pickup as pickup
import centrifuge_model as cf
import robot_spec as robot
from lab_transfer_model import obb,boxes_overlap


def app(m):return App.Placement(App.Matrix(*[v for row in m for v in row]))


def adaptive_frames(scene,data,evaluate,records):
    corners={}
    for r in records:
        corners.setdefault(r['group'],[]).extend(itertools.product(*zip(r['minimum'],r['maximum'])))
    def state(t):
        sample=pickup.interpolate(data['samples'],t);matrices=evaluate(sample)
        pts=[robot.transform(matrices[g],c) for g,vs in corners.items() for c in vs]
        return {'sample':sample,'matrices':matrices,'points':pts}
    frames=[];max_point=0;max_joint=0
    def append(a,b,depth=0):
        nonlocal max_point,max_joint
        step=max(math.dist(x,y) for x,y in zip(a['points'],b['points']))
        angle=max([abs(x-y) for x,y in zip(a['sample']['joints_deg'],b['sample']['joints_deg'])]+[abs(a['sample']['station']['Lid']-b['sample']['station']['Lid'])])
        if step>scene['checks']['collision_max_point_step_mm'] or angle>scene['checks']['collision_max_joint_step_deg']:
            if depth>12:raise ValueError('Discontinuous or unbounded motion during collision subdivision')
            m=state((a['sample']['time_s']+b['sample']['time_s'])/2);append(a,m,depth+1);append(m,b,depth+1)
        else:max_point=max(max_point,step);max_joint=max(max_joint,angle);frames.append(b)
    previous=state(0);frames.append(previous)
    for sample in data['samples'][1:]:
        current=state(sample['time_s']);append(previous,current);previous=current
    for frame in frames:del frame['points']
    return frames,{'maximum_body_bound_corner_step_mm':max_point,'maximum_joint_or_lid_step_deg':max_joint,
        'maximum_time_step_s':max(b['sample']['time_s']-a['sample']['time_s'] for a,b in zip(frames,frames[1:]))}


def audit(scene,data,records):
    evaluate=pickup.SceneEvaluator(scene,data);arm=pickup.arm_source(scene);indices={'Arm.'+l['id']:i for i,l in enumerate(arm['links'])}
    frames,spacing=adaptive_frames(scene,data,evaluate,records);seen=set();pair_cache={};collisions=[];checks=[];exact=0;distance_tests=0
    nearest=None;best=float('inf');unique=0
    def category(a,b,t):
        ak,bk=a['kind'],b['kind'];an,bn=a['id'],b['id']
        tubea=an in ('Tube01','ClosedCap01');tubeb=bn in ('Tube01','ClosedCap01')
        if ak==bk=='arm':return 'nonadjacent_arm' if abs(indices[a['group']]-indices[b['group']])>1 else None
        if {ak,bk}=={'arm','gripper'}:return 'arm_tool' if (a if ak=='arm' else b)['group']!='Arm.L6_BareFlange' else None
        if ak==bk=='gripper':return None # Designed internal assembly/contact interfaces.
        if (ak in ('arm','gripper')) != (bk in ('arm','gripper')):
            other=b if ak in ('arm','gripper') else a;moving=a if other is b else b
            if other['kind']=='station' and (tubea or tubeb) and moving['id'] in ('LeftFingerPad','RightFingerPad') and other['id']=='Tube01':return None
            return 'robot_environment'
        if tubea!=tubeb and t>=scene['checks']['attachment_time_s']:return 'tube_environment'
        return None
    for index,frame in enumerate(frames):
        sample=frame['sample'];t=sample['time_s'];matrices=frame['matrices']
        signature=tuple(round(v,8) for matrix in matrices.values() for row in matrix for v in row)
        if signature in seen:continue
        seen.add(signature);unique+=1;items=[];hits=[]
        for r in records:
            matrix=matrices[r['group']];items.append({**r,'matrix':matrix,'box':obb(matrix,r['minimum'],r['maximum']),'actual':None})
        def actual(a):
            if a['actual'] is None:
                shape=a['shape'].copy();shape.Placement=app(a['matrix']).multiply(shape.Placement);a['actual']=shape
            return a['actual']
        for i,a in enumerate(items):
            for b in items[i+1:]:
                cat=category(a,b,t)
                if not cat:continue
                # Exact nearest robot-to-station/rack clearance, excluding handled
                # tube contacts. Bench/base support is a separate contact pair.
                equipment=cat=='robot_environment' and (a['kind'] in ('station','rack') or b['kind'] in ('station','rack')) and a['id'] not in ('Tube01','ClosedCap01') and b['id'] not in ('Tube01','ClosedCap01')
                if equipment:
                    lower=math.sqrt(sum(max(0,a['box']['min'][j]-b['box']['max'][j],b['box']['min'][j]-a['box']['max'][j])**2 for j in range(3)))
                    if lower<best-1e-8:
                        distance=actual(a).distToShape(actual(b))[0];distance_tests+=1
                        if distance<best:best=distance;nearest={'a':a['id'],'b':b['id'],'time_s':t,'phase':sample['phase']}
                if not boxes_overlap(a['box'],b['box']):continue
                relative=robot.multiply(robot.inverse(a['matrix']),b['matrix'])
                key=(a['id'],b['id'],tuple(round(v,8) for row in relative for v in row))
                if key not in pair_cache:pair_cache[key]=actual(a).common(actual(b)).Volume;exact+=1
                volume=pair_cache[key]
                if volume>1e-3:
                    hit={'a':a['id'],'b':b['id'],'time_s':t,'phase':sample['phase'],'category':cat,'volume_mm3':volume};hits.append(hit);collisions.append(hit)
        checks.append({'time_s':t,'phase':sample['phase'],'passed':not hits,'collision_count':len(hits)})
        if index%50==0 or hits:print(json.dumps({'audit_frame':index,'of':len(frames),'time_s':t,'hits':hits,'exact_overlap_tests':exact}),flush=True)
        if len(collisions)>=12:break
    return {'passed':not collisions and index==len(frames)-1 and best>=scene['checks']['minimum_robot_equipment_clearance_mm'],'requested_frames':len(frames),'unique_states_checked':unique,'samples':checks,
        'spacing':spacing,'collisions':collisions,'exact_overlap_tests':exact,'exact_distance_tests':distance_tests,
        'minimum_robot_equipment_distance_mm':best,'nearest_pair':nearest,
        'minimum_robot_equipment_clearance_required_mm':scene['checks']['minimum_robot_equipment_clearance_mm'],
        'coverage':['robot and tool versus complete centrifuge including moving lid','robot/tool versus rack and bench','carried tube versus remaining centrifuge, rack, bench and arm','nonadjacent arm self collisions','cap and non-pad tool clearance'],
        'exclusions':['within each rigid link and adjacent arm joint interfaces','tool/flange mounting interface','internal tool assembly','intended tube/contact-pad grasp contact'],
        'scope':'Adaptive discrete BRep intersections of the exact joint-interpolated playback path. Spacing bounds apply to sampled body-bounds corners, not a continuous swept-volume proof.'}


def main():
    context=json.loads((cf.ROOT/'tmp/cf01-robot-pickup-context.json').read_text());out=Path(context['out']);scene=pickup.load();data=json.loads((out/'trajectory.json').read_text())
    import sys
    sys.path.insert(0,str(cf.ROOT/'scripts/freecad'));import solidcraftbot_freecad as motion
    doc=App.openDocument(str(Path(context['cad'])/'CF01_Robot_Closed.FCStd'));evaluate=pickup.SceneEvaluator(scene,data);zero=evaluate(pickup.interpolate(data['samples'],0));records=[]
    for obj in motion.features(doc):
        shape=motion.world_shape(obj);shape.Placement=app(robot.inverse(zero[obj.RigidLink])).multiply(shape.Placement);bb=shape.BoundBox
        records.append({'id':obj.SourceBody,'group':obj.RigidLink,'kind':obj.SceneAsset,'role':obj.ModelRole,'shape':shape,
            'minimum':[bb.XMin,bb.YMin,bb.ZMin],'maximum':[bb.XMax,bb.YMax,bb.ZMax]})
    result=audit(scene,data,records);cf.write(out/'native-motion-validation.json',result);App.closeDocument(doc.Name)
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','coverage','exclusions')}),flush=True)
    if not result['passed']:raise AssertionError('Robot/rack path collisions: inspect native-motion-validation.json')


if __name__=='__main__':
    import check_centrifuge_robot_motion as backend
    backend.main()
