"""Compact source-derived native meshes for the interactive robot pickup cycle."""
import base64
import gzip
import itertools
import json
from pathlib import Path
import centrifuge_robot_pickup as pickup
import centrifuge_model as cf
import robot_spec as robot


def prepare_mesh(context):
    mesh=json.loads((Path(context['out'])/'scene-mesh.json').read_text());scene=pickup.load();arm=pickup.arm_source(scene);kin=pickup.Kinematics(arm,scene)
    mesh['robot_frames']=kin.frames;mesh['arm_base']=kin.base
    attach=pickup.interpolate(mesh['trajectory']['samples'],scene['checks']['attachment_time_s'])
    spec=cf.load();p=cf.parameters(spec);source=cf.expanded(spec,p)
    mesh['tube_attachment_from_tool']=robot.multiply(robot.inverse(kin.tool(attach['joints_deg'])),pickup.rigid_from_cf(source,'PresentedTube',attach['station']))
    mesh['tube_seated_matrix']=pickup.SceneEvaluator(scene,mesh['trajectory']).seated_tube
    rack=pickup.rack_geometry(scene,p);mesh['rack_frame']=rack['frame'];mesh['rack_slots']=rack['slots']
    bottom,axis=cf.pocket(spec,p,1);mesh['grip_reference']=cf.plus(bottom,axis,p['tube_length']-8)
    # Only viewport vendor detail is clustered; native source and BRep QA keep all geometry.
    for b in mesh['bodies']:
        if not b['role'].startswith('vendor_'):continue
        lookup={};vertices=[];remap=[]
        for v in b['v']:
            key=tuple(round(x) for x in v)
            if key not in lookup:lookup[key]=len(vertices);vertices.append(list(key))
            remap.append(lookup[key])
        triangles=[tuple(remap[i] for i in face) for face in b['f']]
        b['v']=vertices;b['f']=[list(t) for t in dict.fromkeys(triangles) if len(set(t))==3]
    bounds={}
    for b in mesh['bodies']:
        bb=bounds.setdefault(b['group'],[[float('inf')]*3,[-float('inf')]*3])
        for v in b['v']:
            for i in range(3):bb[0][i]=min(bb[0][i],v[i]);bb[1][i]=max(bb[1][i],v[i])
    mesh['group_bounds']={name:[list(v) for v in itertools.product(*zip(lo,hi))] for name,(lo,hi) in bounds.items()}
    return mesh


def main():
    context=json.loads((cf.ROOT/'tmp/cf01-robot-pickup-context.json').read_text());mesh=prepare_mesh(context)
    assert mesh['trajectory']['scene_sha256']==cf.digest(pickup.SOURCE)
    packed=base64.b64encode(gzip.compress(json.dumps(mesh,separators=(',',':')).encode(),compresslevel=9,mtime=0)).decode()
    template=(cf.ROOT/'scripts/templates/centrifuge_robot_pickup.html').read_text(encoding='utf-8')
    target=Path(context['renders'])/'cf01-robot-pickup.html';target.write_text(template.replace('__MESH__',packed),encoding='utf-8')
    cf.write(Path(context['out'])/'visualization-mesh-summary.json',{'body_count':len(mesh['bodies']),'triangles':sum(len(b['f']) for b in mesh['bodies']),
        'bytes':target.stat().st_size,'vendor_mesh_cluster_mm':1,'geometry_for_native_checks':'full source BRep, no clustering'})
    if target.stat().st_size>1_000_000:raise ValueError('Inline animation exceeds 1 MB')
    print(json.dumps({'path':str(target),'bytes':target.stat().st_size,'triangles':sum(len(b['f']) for b in mesh['bodies'])}))


if __name__=='__main__':main()
