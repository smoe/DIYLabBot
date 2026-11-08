"""Generate SolidCraft review snapshots of the shared pickup scene.

Dynamic ownership/IK remains in the shared player and FreeCAD macro; these
derived STEP instances are deliberately posed snapshots, not another master.
"""
import json
from pathlib import Path
import shutil
import subprocess
import math
from concurrent.futures import ThreadPoolExecutor
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup


def main():
    context=json.loads((cf.ROOT/'tmp/cf01-robot-pickup-context.json').read_text());out=Path(context['out']);cad=Path(context['cad'])
    mesh=json.loads((out/'scene-mesh.json').read_text());reports=[]
    def export(label):
        commands=[{'command':'file.insert_step','params':{'path':str(out/(label+'.step')),'name':'CF01_Robot_'+label,'names':'product'}}]
        steel=[b['id'].replace('.','_') for b in mesh['bodies'] if b['role'].startswith('steel_')]
        commands.append({'command':'material.assign','params':{'bodies':steel,'material':'Steel'}})
        # Repeated glyphs/servo instances share STEP prototypes. Apply the inspection
        # palette to unique functional bodies instead of guessing aliases for instances.
        functional={'BaseHousing','ContainmentEnvelope','ChamberFloor','CommandLid','Rotor','Tube01','ClosedCap01','GripperBody','ToolMount'}
        functional.update({'Rack.Guide','Rack.Base','Rack.OrientationKey','BenchSurface'})
        for b in mesh['bodies']:
            if b['id'] in functional:commands.append({'command':'appearance.assign','params':{'bodies':[b['id'].replace('.','_')],'color':b['color'],'opacity':b['opacity']}})
        commands.append({'command':'document.metadata.set','params':{'values':{'org.solidcraftbot.cf01-pickup':{'scene_source':'model/centrifuge-cf01.robot-pickup.shared.json','source_hashes':context['source_hashes'],'phase':label,'representation':'posed review snapshot, no live handoff constraints'}}}})
        path=out/(label+'.solidcraft.commands.json');cf.write(path,{'commands':commands})
        target=cad/('CF01_Robot_'+label+'.sc');measurement=out/(label+'.solidcraft.json')
        subprocess.run([context.get('solidcraft_cli') or shutil.which('solidcraft-cli') or 'solidcraft-cli','run',str(path),'--save',str(target),'--json-out',str(measurement),'--quiet'],check=True,cwd=cf.ROOT)
        actual=json.loads(measurement.read_text());names={b['name'] for b in actual['bodies']};expected={b['id'].replace('.','_') for b in mesh['bodies']}
        bad=[b['name'] for b in actual['bodies'] if not b['closed'] or b['volume_mm3'] is None or b['volume_mm3']<=0]
        bench=next(b for b in actual['bodies'] if b['name']=='BenchSurface');source_bench=pickup.load()['bench_surface']
        volume_expected=math.prod(source_bench['size_mm'])
        bounds={'min':source_bench['origin_mm'],'max':[a+b for a,b in zip(source_bench['origin_mm'],source_bench['size_mm'])]}
        bench_passed=bench['closed'] and bench['volume_mm3'] is not None and abs(bench['volume_mm3']-volume_expected)<1e-3 and all(abs(a-b)<1e-6 for key in ['min','max'] for a,b in zip(bench['bbox'][key],bounds[key]))
        if bad or len(actual['bodies'])!=len(expected):
            return {'phase':label,'passed':False,'body_count':len(actual['bodies']),'expected_body_count':len(expected),'solidcraft':str(target),
                    'invalid_or_open_bodies':bad,'workspace_bench_passed':bench_passed,
                    'limitation':'Current SolidCraft STEP import leaves these complex bodies open; source geometry is unchanged. No closure check was waived.'}
        reference=json.loads((out/'snapshot-metrics.json').read_text())[label]
        volume=sum(b['volume_mm3'] for b in actual['bodies']);center=[sum(b['center_of_mass'][i]*b['volume_mm3'] for b in actual['bodies'])/volume for i in range(3)]
        ve=abs(volume-reference['volume_mm3'])/reference['volume_mm3'];ce=math.dist(center,reference['center_mm'])
        assert ve<.001 and ce<.02,(ve,ce)
        return {'phase':label,'passed':True,'body_count':len(expected),'solidcraft':str(target),'source':'derived named STEP snapshot of native shared scene',
            'workspace_bench_passed':bench_passed,'relative_volume_error':ve,'center_error_mm':ce,'source_ids_with_STEP_aliases':sorted(expected-names),
            'appearance_scope':'functional unique bodies retain source appearances; repeated prototype palette simplified'}
    with ThreadPoolExecutor(max_workers=2) as pool:reports=list(pool.map(export,['Grasp','RackReleased']))
    cf.write(out/'solidcraft-scene-validation.json',{'passed':all(r['passed'] for r in reports),'snapshots':reports,'dynamic_handoff_supported_in_this_export':False})
    print(json.dumps(reports))
    if not all(r['passed'] for r in reports):raise SystemExit('SolidCraft snapshot validation failed; see solidcraft-scene-validation.json')


if __name__=='__main__':main()
