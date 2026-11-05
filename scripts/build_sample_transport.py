"""Reproduce TR01 variants in both native CADs, or finish a SolidCraft MCP build."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
import time
import sample_transport_model as model
from build_tube_carrier import compare


def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def prepare():
    spec=model.load(); stem='sample-transport-tr01-'+model.digest(model.SOURCE)[:12]; revision=stem; n=1
    while (model.ROOT/'cad/generated'/revision).exists(): n+=1; revision=stem+'-r'+str(n)
    cad=model.ROOT/'cad/generated'/revision; out=model.ROOT/'exports/generated'/revision
    cad.mkdir(parents=True); out.mkdir(parents=True); p=model.parameters(spec); cases=[]
    for v in spec['variants']:
        cases.append((v['id'],v,{}))
    # Deck, cassette datums and shared load frame follow the same source height.
    cases.append(('Floor_P2_upper',spec['variants'][0],{'deck_length':380,'deck_width':210,'floor_deck_z':950,'floor_length':550,'floor_width':450,'plate_height':45}))
    cases.append(('Floor_Mixed_lower',spec['variants'][2],{'floor_deck_z':700}))
    context={'revision':revision,'source_sha256':model.digest(model.SOURCE),'cases':[],'cad':str(cad),'out':str(out)}
    for name,v,overrides in cases:
        pp=model.parameters(spec,overrides)
        files={'solidcraft':cad/(name+'.sc'),'freecad':cad/(name+'.FCStd'),'step':out/(name+'.step'),
            'commands':out/(name+'.commands.json'),'case':out/(name+'.case.json'),
            'sc_measurements':out/(name+'.solidcraft.json'),'fc_report':out/(name+'.freecad.json')}
        write(files['commands'],{'source_sha256':context['source_sha256'],'commands':model.solidcraft_commands(spec,pp,v)})
        write(files['case'],{'id':name,'variant':v['id'],'overrides':overrides})
        context['cases'].append({'id':name,'variant':v['id'],'overrides':overrides,'files':{k:str(path) for k,path in files.items()}})
    path=out/'context.json'; write(path,context); print(str(path),flush=True); return context,path


def finish(context,args):
    spec=model.load(); started=time.monotonic(); results=[]
    if model.digest(model.SOURCE)!=context['source_sha256']: raise ValueError('Source changed since preparation')
    sys.path.insert(0,str(model.ROOT/'scripts/freecad')); from persist_station_view import persist
    for case in context['cases']:
        files=case['files']; v=next(v for v in spec['variants'] if v['id']==case['variant']); p=model.parameters(spec,case['overrides'])
        if not Path(files['solidcraft']).exists():
            subprocess.run([args.solidcraft_cli,'run',files['commands'],'--save',files['solidcraft'],'--out',files['step'],
                '--json-out',files['sc_measurements'],'--quiet'],check=True,cwd=model.ROOT)
        if Path(files['freecad']).exists():
            if not Path(files['fc_report']).exists():
                raise FileExistsError('Preserving unvalidated FreeCAD output; start a new build: '+files['freecad'])
            prior=json.loads(Path(files['fc_report']).read_text(encoding='utf-8'))
            expected_case={'id':case['id'],'variant':case['variant'],'overrides':case['overrides']}
            if not prior['passed'] or prior['case']!=expected_case:
                raise ValueError('Existing FreeCAD validation does not match this case; start a new build')
        else:
            subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_sample_transport_freecad.py'),files['freecad'],
                files['case'],files['fc_report'],files['step']],check=True,cwd=model.ROOT)
        scm=json.loads(Path(files['sc_measurements']).read_text(encoding='utf-8')); fcm=json.loads(Path(files['fc_report']).read_text(encoding='utf-8'))
        cross=compare(scm,fcm['geometry']); presentation=persist(files['freecad'],model.expanded(spec,p,v),fcm['geometry'])
        motion_checks=[]
        source=model.expanded(spec,p,v)
        item={'id':case['id'],'variant':case['variant'],'overrides':case['overrides'],
            'solidcraft_execution':case.get('solidcraft_execution',{'backend':'CLI'}),
            'passed':fcm['passed'] and all(c['passed'] for c in cross+motion_checks) and presentation['passed'],
            'body_count':len(cross),'cross_kernel_comparisons':cross,
            'maximum_step_xor_mm3':max(c['xor_mm3'] for c in fcm['solidcraft_step_xor']),
            'motion_samples':len(fcm['motion_samples']),'solidcraft_motion_comparisons':motion_checks,
            'capacity':model.capacity(v),'batch_coverage':model.batch_coverage(spec,v),
            'interfaces':fcm['interfaces'],'frames':source['frames'],'frame_geometry_checks':fcm['frame_geometry_checks'],'presentation':presentation,
            'files':{k:str(Path(path).relative_to(model.ROOT)).replace('\\','/') for k,path in files.items()},
            'artifact_sha256':{k:model.digest(files[k]) for k in ['solidcraft','freecad','step']}}
        results.append(item); write(Path(context['out'])/'cases-progress.json',results)
        if not item['passed']: raise AssertionError('TR01 cross-kernel mismatch: '+case['id'])
    paths=[model.SOURCE,Path(__file__),model.ROOT/'scripts/sample_transport_model.py',model.ROOT/'scripts/build_sample_transport_freecad.py',
        model.ROOT/'scripts/build_tube_carrier.py',model.ROOT/'scripts/build_tube_carrier_freecad.py',model.ROOT/'scripts/robot_spec.py',
        model.ROOT/'scripts/freecad/solidcraftbot_freecad.py',model.ROOT/'scripts/freecad/persist_station_view.py',model.ROOT/'scripts/freecad/persist_view.py']
    report={'format':'solidcraftbot.transport-cross-cad/1','revision':context['revision'],'source':str(model.SOURCE.relative_to(model.ROOT)),
        'source_sha256':model.digest(model.SOURCE),'source_files_sha256':{str(p.relative_to(model.ROOT)):model.digest(p) for p in paths},
        'passed':all(c['passed'] for c in results),'cases':results,'validation_elapsed_s':time.monotonic()-started,
        'handoff_validation':{'status':'not_validated','registered_station_count':len(spec['handoff_requirements']['station_registry']),
            'all_station_reaches_verified':spec['handoff_requirements']['all_station_reaches_verified'],
            'parking_verified':spec['handoff_requirements']['parking_verified'],
            'stationary_holding_verified':spec['handoff_requirements']['stationary_holding_verified'],
            'note':'CAD frame/geometry consistency is checked; no arm reach, local registration or parking performance is established'},
        'limitations':spec['limitations']+['Within-rigid-component overlaps are listed separately, not qualified fits',
        'Static floor geometry only; no wheel motion, arm reach, local registration or navigation validation',
        'FreeCAD saved presentation metadata checked; interactive GUI not tested']}
    report['renderings']=[{'path':str(path.relative_to(model.ROOT)).replace('\\','/'),'sha256':model.digest(path),
        'source':'SolidCraft model render','source_sha256':model.digest(model.SOURCE)} for path in Path(context['cad']).glob('*.png')]
    write(Path(context['out'])/'build-report.json',report); write(model.ROOT/'cad/sample-transport-tr01/shared-build-report.json',report)
    print('TR01 native models passed: cad/sample-transport-tr01/shared-build-report.json',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad-python',default=str(Path.home()/'AppData/Local/Programs/FreeCAD 27.1/bin/python.exe'))
    parser.add_argument('--solidcraft-cli',default=shutil.which('solidcraft-cli') or 'solidcraft-cli')
    parser.add_argument('--prepare-only',action='store_true'); parser.add_argument('--finish',type=Path)
    args=parser.parse_args()
    if args.finish: context=json.loads(args.finish.read_text(encoding='utf-8'))
    else: context,_=prepare()
    if not args.prepare_only: finish(context,args)


if __name__=='__main__': main()
