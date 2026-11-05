"""Export checked H03 native solids and validate all cycle placement matrices."""
import build_tube_carrier_freecad as adapter
import tube_cam_model as model
import tube_cam_cycle as cycle
import MeshPart
import json
import sys
from pathlib import Path
from verify_tube_cam_freecad import matrix


def main(context_path):
    adapter.model=model
    context=json.loads(Path(context_path).read_text());out=Path(context['out'])
    spec=model.load();p=model.parameters(spec);data=cycle.load();source=model.expanded(spec,p)
    meta={b['id']:b for b in source['bodies']};variant=data['variant']
    doc=adapter.App.openDocument(context['freecad']);ready=model.pose(spec,p)
    adapter.set_pose(doc,source,ready);bodies=[o for o in adapter.objects(doc) if o.SourceBody.startswith(variant+'_') and o.ModelRole!='clearance_envelope']
    baseline={o.SourceBody:matrix(adapter.motion.global_placement(o)) for o in bodies}
    inverse={c['id']:model.robot_spec.inverse(model.matrix(source,c['id'],p,ready)) for c in source['components']}
    mesh=[];detail_roles={'closing_wedge_collar','latch_housing','latch_support','spring_bayonet_bolt','bayonet_cross_pin','robot_release_handle'}
    for obj in bodies:
        shape=adapter.motion.world_shape(obj)
        def tessellate(shape):
            native=MeshPart.meshFromShape(Shape=shape,LinearDeflection=0.25,AngularDeflection=0.32,Relative=False)
            vertices,faces=native.Topology
            return {'v':[[round(n,3) for n in model.robot_spec.transform(inverse[obj.RigidLink],list(v))] for v in vertices],'f':[list(f) for f in faces]}
        entry={'id':obj.SourceBody,'group':obj.RigidLink,'role':obj.ModelRole,'opacity':meta[obj.SourceBody]['appearance']['opacity'],**tessellate(shape)}
        if obj.ModelRole in detail_roles:
            if obj.ModelRole in {'closing_wedge_collar','latch_housing','latch_support'}:
                cx=model.evaluate(next(v['center_x'] for v in spec['variants'] if v['id']==variant),p)
                clip=adapter.Part.makeBox(1000,500,1000,adapter.App.Vector(cx+25,data['presentation']['latch_section_y_mm'],-500))
                section=shape.common(clip)
                if not section.isNull() and section.Volume>1e-8:entry['detail']=tessellate(section)
            else:entry['detail']={'v':entry['v'],'f':entry['f']}
        mesh.append(entry)
    checks=[]
    for sample in cycle.samples(spec,p,data):
        adapter.set_pose(doc,source,sample['values']);translation=rotation=joint_error=0
        for name,value in sample['values'].items():joint_error=max(joint_error,abs(getattr(doc.Controller,name).Value-value))
        for obj in bodies:
            delta=model.robot_spec.multiply(model.matrix(source,obj.RigidLink,p,sample['values']),inverse[obj.RigidLink])
            expected=model.robot_spec.multiply(delta,baseline[obj.SourceBody]);actual=matrix(adapter.motion.global_placement(obj))
            translation=max(translation,max(abs(actual[i][3]-expected[i][3]) for i in range(3)))
            rotation=max(rotation,max(abs(actual[i][j]-expected[i][j]) for i in range(3) for j in range(3)))
        checks.append({'time_s':sample['time_s'],'translation_error_mm':translation,'rotation_matrix_error':rotation,'joint_error_deg_or_mm':joint_error,'passed':translation<1e-7 and rotation<1e-9 and joint_error<1e-8})
    adapter.App.closeDocument(doc.Name)
    joints=[{**j,'origin':[model.evaluate(v,p) for v in j['origin']]} for j in source['joints']]
    result={'source_sha256':model.digest(model.SOURCE),'geometry_file_sha256':model.digest(context['freecad']),'bodies':mesh,'joints':joints,'parameters':p,'variant':variant}
    (out/'animation-mesh.json').write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')
    (out/'native-cycle-checks.json').write_text(json.dumps({'passed':all(c['passed'] for c in checks),'samples':checks,'body_count':len(bodies),'scope':'Native FreeCAD input values and full rigid transforms; existing H03 interference evidence retained; no new dense collision or contact simulation'},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':all(c['passed'] for c in checks),'bodies':len(mesh),'triangles':sum(len(b['f']) for b in mesh),'samples':len(checks),'bytes':(out/'animation-mesh.json').stat().st_size}),flush=True)
    if not all(c['passed'] for c in checks):raise AssertionError('Native H03 cycle differs from shared motion')


if __name__=='__main__':main(sys.argv[1])
