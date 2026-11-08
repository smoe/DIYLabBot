"""Build source-bound robot-grasp trajectory and both native scene snapshots."""
import argparse
import json
from pathlib import Path
import tool_paths
import subprocess
import sys
import centrifuge_robot_pickup as pickup
import centrifuge_model as cf
from cf01_rack_batch import Runner, SOURCE as BATCH_SOURCE


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepare-only',action='store_true')
    tool_paths.add_tool_arguments(parser)
    args=parser.parse_args();tool_paths.resolve_tool_arguments(parser,args,required=not args.prepare_only)
    scene=pickup.load();data=pickup.trajectory(scene);stem='centrifuge-cf01-robot-'+cf.digest(pickup.SOURCE)[:12];revision=stem;n=1
    while (cf.ROOT/'exports/generated'/revision).exists():n+=1;revision=stem+'-r'+str(n)
    paths={key:cf.ROOT/top/revision for key,top in [('cad','cad/generated'),('out','exports/generated'),('renders','renders')]}
    for d in paths.values():d.mkdir(parents=True)
    cf_report=json.loads((cf.ROOT/'cad/centrifuge-cf01/shared-build-report.json').read_text());arm_report=json.loads((cf.ROOT/'exports/generated/build-report.json').read_text())
    if not cf_report['passed'] or cf_report['source_sha256']!=data['geometry_sha256']:raise ValueError('Checked centrifuge source required')
    if not arm_report['passed'] or arm_report['spec_sha256']!=data['robot_sha256']:raise ValueError('Checked current robot source required')
    arm_key,arm_path=next((key,path) for key,path in arm_report['artifacts'].items() if str(path).lower().endswith('.fcstd'))
    arm_file=cf.ROOT/arm_path
    if cf.digest(arm_file)!=arm_report['artifact_sha256'][arm_key]:raise ValueError('Arm artifact changed since its checked build')
    station=cf_report['cases'][0]
    if cf.digest(cf.ROOT/station['files']['freecad'])!=station['artifact_sha256']['freecad']:raise ValueError('Centrifuge artifact changed')
    context={'revision':revision,'solidcraft_cli':args.solidcraft_cli,**{k:str(v) for k,v in paths.items()},'arm_native':str(arm_file),
        'centrifuge_native':str(cf.ROOT/cf_report['cases'][0]['files']['freecad']),
        'source_hashes':{str(p.relative_to(cf.ROOT)).replace('\\','/'):cf.digest(p) for p in [pickup.SOURCE,cf.SOURCE,pickup.protocol.SOURCE,cf.ROOT/scene['sources']['robot'],BATCH_SOURCE,*pickup.workspace.source_dependencies(pickup.workspace.load(pickup.assembly.validate_reference(scene['environment'])))]}}
    cf.write(paths['out']/'rack-batch-trace.json',Runner().run())
    cf.write(paths['out']/'trajectory.json',data)
    cf.write(paths['out']/'scene-source.json',scene)
    cf.write(cf.ROOT/'tmp/cf01-robot-pickup-context.json',context)
    cf.write(paths['out']/'context.json',context)
    macro=(cf.ROOT/'scripts/templates/centrifuge_robot_pickup.FCMacro').read_text(encoding='utf-8').replace('__SCRIPTS__',repr(str(cf.ROOT/'scripts'))).replace('__CONTEXT__',repr(str(paths['out']/'context.json')))
    (paths['cad']/'CF01_Robot_Pickup.FCMacro').write_text(macro,encoding='utf-8')
    print(json.dumps(context),flush=True)
    if args.prepare_only:return
    subprocess.run([args.freecad_python,str(cf.ROOT/'scripts/build_centrifuge_robot_pickup_freecad.py')],check=True,cwd=cf.ROOT)
    subprocess.run([args.freecad_python,str(cf.ROOT/'scripts/check_centrifuge_robot_motion.py')],check=True,cwd=cf.ROOT)
    cf.write(paths['out']/'protocol-transfer-trace.json',pickup.mock_transfer_trace())
    subprocess.run([sys.executable,str(cf.ROOT/'scripts/build_centrifuge_robot_pickup_visual.py')],check=True,cwd=cf.ROOT)
    subprocess.run([sys.executable,str(cf.ROOT/'scripts/export_centrifuge_robot_pickup_solidcraft.py'),
        '--context',str(cf.ROOT/'tmp/cf01-robot-pickup-context.json'),'--solidcraft-cli',args.solidcraft_cli,
        '--compare-freecad',str(paths['out']/'snapshot-metrics.json')],check=True,cwd=cf.ROOT)


if __name__=='__main__':main()
