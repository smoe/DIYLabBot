"""Read back native FreeCAD joint values and complete rigid-body transforms."""
import build_tube_carrier_freecad as adapter
import tube_cam_model as model
import json
import math


def matrix(placement):
    value=placement.toMatrix()
    return [[getattr(value,'A%d%d'%(i+1,j+1)) for j in range(4)] for i in range(4)]


def main():
    adapter.model=model
    spec=model.load();folder=model.ROOT/'cad'/spec['family']
    build=json.loads((folder/'shared-build-report.json').read_text(encoding='utf-8'))
    if not build['passed'] or build['source_sha256']!=model.digest(model.SOURCE):
        raise ValueError('Rebuild the current H03 source first')
    cases=[]
    for case in build['cases']:
        path=model.ROOT/case['files']['freecad']
        if model.digest(path)!=case['artifact_sha256']['freecad']:
            raise ValueError('FreeCAD file differs from its build report')
        print('FreeCAD transform checks: '+case['id'],flush=True)
        p=model.parameters(spec,case['overrides']);source=model.expanded(spec,p)
        doc=adapter.App.openDocument(str(path));ready=model.pose(spec,p)
        adapter.set_pose(doc,source,ready)
        bodies=adapter.objects(doc)
        baseline={o.SourceBody:matrix(adapter.motion.global_placement(o)) for o in bodies}
        before={c['id']:model.robot_spec.inverse(model.matrix(source,c['id'],p,ready)) for c in source['components']}
        poses=[]
        for sample in model.samples(spec,p):
            values=sample['joint_values'];adapter.set_pose(doc,source,values)
            translation=0;rotation=0;joint_error=0
            for name,expected in values.items():
                actual=getattr(doc.Controller,name).Value
                joint_error=max(joint_error,abs(actual-expected))
            for obj in bodies:
                delta=model.robot_spec.multiply(model.matrix(source,obj.RigidLink,p,values),before[obj.RigidLink])
                expected=model.robot_spec.multiply(delta,baseline[obj.SourceBody])
                actual=matrix(adapter.motion.global_placement(obj))
                translation=max(translation,math.dist([actual[i][3] for i in range(3)],[expected[i][3] for i in range(3)]))
                rotation=max(rotation,max(abs(actual[i][j]-expected[i][j]) for i in range(3) for j in range(3)))
            poses.append({'id':sample['id'],'maximum_translation_error_mm':translation,
                          'maximum_rotation_matrix_error':rotation,'maximum_joint_value_error_deg_or_mm':joint_error,
                          'passed':translation<1e-7 and rotation<1e-9 and joint_error<1e-8})
        adapter.App.closeDocument(doc.Name)
        cases.append({'id':case['id'],'file':case['files']['freecad'],'sha256':model.digest(path),
                      'bodies_per_pose':len(bodies),'poses':poses,'passed':all(s['passed'] for s in poses)})
    result={'passed':bool(cases) and all(c['passed'] for c in cases),'source_sha256':model.digest(model.SOURCE),
            'verifier_sha256':model.digest(__file__),'cases':cases,
            'scope':'Read-only native joint values and full placement matrices, including rotations; no contact dynamics'}
    (folder/'freecad-transform-checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'poses':sum(len(c['poses']) for c in cases),
                      'failed':[{'case':c['id'],**s} for c in cases for s in c['poses'] if not s['passed']]},indent=2),flush=True)
    if not result['passed']:raise AssertionError('FreeCAD H03 transform mismatch')


if __name__=='__main__':main()
