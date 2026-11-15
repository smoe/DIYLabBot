"""Tessellate checked H02 solids; verify replay transforms against native placements."""
import FreeCAD as App
import MeshPart
import json
import sys
from pathlib import Path
import h02_arm_pickup as model
import h02_direct_pickup as local
sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as native
from verify_tube_cam_freecad import matrix


def transforms(program,state):
    result=program.kin.forward(state['joints_deg']);c=state['coordinates']
    for name in ['Tool','FingerLeft','FingerRight','Tube']:
        m=model.robot.identity();m[2][3]=c['TubeZ' if name=='Tube' else 'ToolZ']
        if name=='FingerLeft':m[0][3]=-c['JawLeft']
        if name=='FingerRight':m[0][3]=c['JawRight']
        result[name]=m
    return result


def main(path):
    context=json.loads(Path(path).read_text());program=model.Program();doc=App.openDocument(context['native'])
    grasp=program.state('closure',1);base=transforms(program,grasp)
    source,_,_=local.proof(program.spec,program.p);roles={b['id']:b for b in source['bodies']}
    objects=[o for o in native.features(doc) if o.ModelRole not in ('viewing_cone','fk_probe','negative_control') and o.RigidLink!='Proof' and not o.SourceBody.endswith('MouthKeepout')]
    baseline={o.SourceBody:matrix(native.global_placement(o)) for o in objects};bodies=[]
    for obj in objects:
        inv=model.robot.inverse(base.get(obj.RigidLink,model.robot.identity()))
        mesh=MeshPart.meshFromShape(Shape=native.world_shape(obj),LinearDeflection=.6,AngularDeflection=.35,Relative=False)
        vertices,faces=mesh.Topology
        vertices=[[round(v,1 if obj.RigidLink in program.links else 3) for v in model.robot.transform(inv,list(point))] for point in vertices]
        # View-only vendor detail compaction, never an input to collision checks.
        if obj.RigidLink in program.links:
            lookup={};compact=[];remap=[]
            for point in vertices:
                quantum=1 if obj.ModelRole.startswith('vendor_') else .1
                key=tuple(round(x/quantum) for x in point)
                if key not in lookup:lookup[key]=len(compact);compact.append([round(x*quantum,1) for x in key])
                remap.append(lookup[key])
            vertices=compact;faces=list(dict.fromkeys(tuple(remap[i] for i in f) for f in faces));faces=[f for f in faces if len(set(f))==3]
        bodies.append({'id':obj.SourceBody,'group':obj.RigidLink,'role':obj.ModelRole,'v':vertices,'f':[list(f) for f in faces]})
    checks=[]
    for fraction in [0,.137,.333,.493,.667,.859,1]:
        t=fraction*program.total_duration;phase,u=program.at_time(t)
        state=program.state(phase,u)
        for i,q in enumerate(state['joints_deg'],1):setattr(doc.Controller,'J'+str(i),q)
        for name,value in state['coordinates'].items():setattr(doc.Controller,name,value)
        doc.recompute();current=transforms(program,state);error=0
        for obj in objects:
            group=obj.RigidLink;delta=model.robot.multiply(current.get(group,model.robot.identity()),model.robot.inverse(base.get(group,model.robot.identity())))
            expected=model.robot.multiply(delta,baseline[obj.SourceBody]);actual=matrix(native.global_placement(obj))
            error=max(error,max(abs(a-b) for x,y in zip(expected,actual) for a,b in zip(x,y)))
        checks.append({'time_s':t,'maximum_transform_error':error,'passed':error<1e-7})
    App.closeDocument(doc.Name)
    if not all(c['passed'] for c in checks):raise ValueError('Replay differs from native CAD transforms')
    out=Path(context['out']);(out/'mesh.json').write_text(json.dumps({'bodies':bodies},separators=(',',':')))
    (out/'native-replay-checks.json').write_text(json.dumps({'passed':True,'checks':checks,'bodies':len(bodies),'scope':'Replay placement equivalence; existing continuous collision audit retained'},indent=2)+'\n')
    print('Exported native H02 animation mesh',len(bodies),flush=True)


if __name__=='__main__':main(sys.argv[1])
