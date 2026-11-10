"""Build native SolidCraft CF01 review scenes, independently of FreeCAD.

Only shared JSON, existing native recipes and archived vendor STEP are build
inputs. --compare-freecad optionally adds a cross-CAD check from a JSON report;
it never supplies geometry. The two output poses are frozen review snapshots.
"""
import argparse
import json
import math
from pathlib import Path
import tool_paths
import subprocess
from concurrent.futures import ThreadPoolExecutor
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import centrifuge_pickup_solidcraft as native
import robot_components
import robot_spec as robot
import solidcraft_vendor as vendor


def validate_snapshot(base,actual,manifest,matrices):
    names=[n for b in manifest for n in b['names']]
    before={b['name']:b for b in base['bodies']};after={b['name']:b for b in actual['bodies']}
    if len(before)!=len(base['bodies']) or len(after)!=len(actual['bodies']) or set(before)!=set(names) or set(after)!=set(names):
        raise ValueError('Native snapshot body identities/count changed')
    checks=[]
    for body in manifest:
        for name in body['names']:
            a=vendor.aggregate(before,[name]);b=vendor.aggregate(after,[name])
            ve=abs(a['volume_mm3']-b['volume_mm3'])/a['volume_mm3']
            ce=math.dist(robot.transform(matrices[body['group']],a['center_of_mass']),b['center_of_mass'])
            checks.append({'body':name,'source_body':body['id'],'passed':ve<1e-4 and ce<.001,
                           'relative_volume_error':ve,'center_error_mm':ce})
    return {'passed':all(c['passed'] for c in checks),'body_count':len(names),
            'source_body_count':len(manifest),'all_bodies_closed':True,
            'acceptance':{'relative_volume_error':1e-4,'center_error_mm':.001,'closure_required':True},
            'body_checks':checks}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    tool_paths.add_tool_arguments(parser,freecad=False)
    parser.add_argument('--context',type=Path,help='Optional enclosing multi-backend build directories; geometry still comes from shared sources')
    parser.add_argument('--compare-freecad',type=Path,help='Optional snapshot-metrics.json cross-check, not a build input')
    args=parser.parse_args()
    context=json.loads(args.context.read_text(encoding='utf-8')) if args.context else None
    # An explicit option overrides the enclosing build's recorded runtime.
    # Standalone builds use the shared environment/PATH/install lookup.
    args.solidcraft_cli=args.solidcraft_cli or (context or {}).get('solidcraft_cli') or tool_paths.solidcraft_cli()
    tool_paths.resolve_tool_arguments(parser,args)
    scene=pickup.load();data=pickup.trajectory(scene)
    if context is not None:
        for name,sha in context['source_hashes'].items():
            if cf.digest(cf.ROOT/name)!=sha:raise ValueError('Enclosing build source changed: '+name)
    else:
        stem='centrifuge-cf01-solidcraft-'+cf.digest(pickup.SOURCE)[:12];revision=stem;n=1
        while (cf.ROOT/'exports/generated'/revision).exists():n+=1;revision=stem+'-r'+str(n)
        context={'revision':revision,'out':str(cf.ROOT/'exports/generated'/revision),'cad':str(cf.ROOT/'cad/generated'/revision)}
    out,cad=(Path(context[key]) for key in ['out','cad'])
    out.mkdir(parents=True,exist_ok=True);cad.mkdir(parents=True,exist_ok=True)
    if (out/'solidcraft-scene-validation.json').exists():raise ValueError('Preserve the previous build; use a new revision')
    cli=args.solidcraft_cli
    sections,vendor_report=vendor.prepare(pickup.arm_source(scene),cli,out/'solidcraft-vendor')
    commands,manifest=native.construction(scene,sections)
    base_path=cad/'CF01_NativeBase.sc'
    base=vendor.run(cli,commands,out/'native-base.commands.json',out/'native-base.json',save=base_path)
    for body in base['bodies']:vendor.aggregate({body['name']:body},[body['name']])
    reference=json.loads(args.compare_freecad.read_text(encoding='utf-8')) if args.compare_freecad else None
    def export_pose(item):
        label,time_s=item
        commands,matrices=native.placements(scene,data,time_s)
        commands.append({'command':'document.metadata.set','params':{'values':{'org.solidcraftbot.cf01-pickup':{
            'scene_source':str(pickup.SOURCE.relative_to(cf.ROOT)),'scene_sha256':cf.digest(pickup.SOURCE),
            'phase':label,'time_s':time_s,'representation':'Native source-derived frozen review pose; no live handoff constraints',
            'body_manifest':manifest,'freecad_required':False}}}})
        target=cad/('CF01_Robot_'+label+'.sc')
        actual=vendor.run(cli,commands,out/(label+'.solidcraft.commands.json'),out/(label+'.solidcraft.json'),**{'in':base_path,'save':target})
        check=validate_snapshot(base,actual,manifest,matrices)
        check.update(phase=label,solidcraft=str(target),workspace_bench_passed=next(c['passed'] for c in check['body_checks'] if c['body']=='BenchSurface'))
        if reference:
            total=vendor.aggregate({b['name']:b for b in actual['bodies']},[n for b in manifest for n in b['names']])
            expected=reference[label]
            ve=abs(total['volume_mm3']-expected['volume_mm3'])/expected['volume_mm3'];ce=math.dist(total['center_of_mass'],expected['center_mm'])
            check['freecad_comparison']={'passed':ve<.001 and ce<.02,'relative_volume_error':ve,'center_error_mm':ce,
                'source':str(args.compare_freecad),'sha256':cf.digest(args.compare_freecad),
                'volume_semantics':'Native case pieces summed, reference case Boolean-unioned; small original seam overlaps retained'}
            check['passed']=check['passed'] and check['freecad_comparison']['passed']
        return check
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports=list(pool.map(export_pose,[('Grasp',21.5),('RackReleased',60)]))
    sources=[pickup.SOURCE,cf.SOURCE,pickup.protocol.SOURCE,cf.ROOT/scene['sources']['robot'],
             *pickup.workspace.source_dependencies(pickup.workspace.load(pickup.assembly.validate_reference(scene['environment']))),
             *[cf.ROOT/'scripts'/p for p in ['export_centrifuge_robot_pickup_solidcraft.py','centrifuge_pickup_solidcraft.py',
                'solidcraft_vendor.py','centrifuge_robot_pickup.py','centrifuge_model.py','robot_spec.py','robot_components.py',
                'robot_cameras.py','servo_mounting_design.py','synthetic_workspace.py','rack_slots.py','furniture_model.py','assembly_model.py','cf01_collision_scope.py']]]
    library=robot_components.library(pickup.arm_source(scene))
    sources += [cf.ROOT/p['step'] for part in library['parts'].values() for p in part['sections'].values()]
    hashes={str(p.relative_to(cf.ROOT)):cf.digest(p) for p in sources}
    hashes.update(vendor_report['source_sha256'])
    for part in vendor_report['parts']:hashes[part['original']['path']]=part['original']['sha256']
    from cf01_collision_scope import collision_scope
    result={'format':'solidcraftbot.native-cf01-review/1','passed':all(r['passed'] for r in reports),'revision':context['revision'],
            'collision_scope':collision_scope(scene,data),
            'freecad_required':False,'native_recipes':True,'dynamic_handoff_supported_in_this_export':False,
            'solidcraft_version':subprocess.check_output([cli,'--version'],text=True).strip(),
            'source_files_sha256':hashes,
            'artifact_sha256':{str(p.relative_to(cf.ROOT)):cf.digest(p) for p in [base_path,*[Path(r['solidcraft']) for r in reports],*out.rglob('*.json'),*out.rglob('*.step')]},
            'vendor_exterior':vendor_report,'body_manifest':manifest,'snapshots':reports,
            'limitations':['Frozen review poses; native handoff motion study, complete loading paths, hardware and manufacturing qualification are not established.',
                           'X2/X4 case pieces remain a rigid assembly under their original semantic housing ID; original internal overlaps are not removed.']}
    cf.write(out/'solidcraft-scene-validation.json',result)
    cf.write(cf.ROOT/'cad/centrifuge-cf01/solidcraft-pickup-build-report.json',result)
    print(json.dumps({'passed':result['passed'],'freecad_required':False,'revision':context['revision'],
          'report':str(out/'solidcraft-scene-validation.json'),'body_count':len(base['bodies']),
          'snapshots':[{k:r[k] for k in ['phase','passed','body_count']} for r in reports]}))
    if not result['passed']:raise SystemExit('Native SolidCraft snapshot validation failed')


if __name__=='__main__':main()
