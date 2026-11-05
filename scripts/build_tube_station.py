"""Build both native station models and compare analytic and STEP geometry."""
from pathlib import Path
import argparse
import json
import math
import shutil
import subprocess
import sys
import time
import station_model as model


def write(path,data): Path(path).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad-python',default=str(Path.home()/'AppData/Local/Programs/FreeCAD 27.1/bin/python.exe'))
    parser.add_argument('--solidcraft-cli',default=shutil.which('solidcraft-cli') or 'solidcraft-cli')
    args=parser.parse_args(); started=time.monotonic(); spec=model.load()
    revision='tube-station-c01-'+model.digest(model.SOURCE)[:12]; name=revision; n=1
    while (model.ROOT/'cad/generated'/name).exists(): n+=1; name=revision+'-r'+str(n)
    cad=model.ROOT/'cad/generated'/name; exports=model.ROOT/'exports/generated'/name
    cad.mkdir(parents=True); exports.mkdir(parents=True)
    cases=[('default',{}),('raised_10',{'tube_mouth_z':110}),('raised_3',{'tube_mouth_z':103}),('wide_20',{'base_length':220})]
    reports=[]
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    for ident,overrides in cases:
        p=model.parameters(spec,overrides); print('Station case: '+ident,flush=True)
        prefix=cad/(spec['id'] if ident=='default' else spec['id']+'_'+ident)
        sc=prefix.with_suffix('.sc'); fc=prefix.with_suffix('.FCStd'); step=exports/(ident+'.step')
        commands=model.solidcraft_commands(spec,p)
        # Exercise every declared joint end, then restore the saved pose.
        for sample in model.pose_samples(spec):
            commands.extend({'command':'joint.drive','params':{'joint':j,'value':v,'quiet':True}} for j,v in sample['angles_deg'].items())
            commands.append({'command':'joint.solve','params':{}})
        commands.extend({'command':'joint.drive','params':{'joint':j,'value':v,'quiet':True}} for j,v in spec['poses_deg']['pipetting'].items())
        script=exports/(ident+'.commands.json'); measurements=exports/(ident+'.solidcraft.json')
        case_file=exports/(ident+'.case.json'); free_report=exports/(ident+'.freecad.json')
        write(script,{'source_sha256':model.digest(model.SOURCE),'commands':commands}); write(case_file,{'id':ident,'overrides':overrides})
        subprocess.run([args.solidcraft_cli,'run',str(script),'--save',str(sc),'--out',str(step),'--json-out',str(measurements),'--quiet'],check=True,cwd=model.ROOT)
        subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_tube_station_freecad.py'),str(fc),str(case_file),str(free_report),str(step)],check=True,cwd=model.ROOT)
        sc_result=json.loads(measurements.read_text(encoding='utf-8')); f=json.loads(free_report.read_text(encoding='utf-8'))
        others={b['name']:b for b in sc_result['bodies']}; comparisons=[]
        for b in f['geometry']:
            other=others[b['body']]
            com_error=math.dist(b['world_center_of_mass_mm'],other['center_of_mass'])
            volume_error=abs(b['volume_mm3']-other['volume_mm3'])/b['volume_mm3']
            comparisons.append({'body':b['body'],'com_error_mm':com_error,'relative_volume_error':volume_error,'passed':com_error<0.01 and volume_error<0.001})
        presentation=persist(fc,spec,f['geometry'])
        item={'id':ident,'overrides':overrides,'passed':f['passed'] and presentation['passed'] and len(others)==len(spec['bodies']) and all(c['passed'] for c in comparisons),
              'body_comparisons':comparisons,'maximum_step_xor_mm3':max(c['xor_mm3'] for c in f['solidcraft_step_xor']),
              'native_parameter_edit':f.get('native_parameter_edit'),'freecad_presentation':presentation,
              'files':{k:str(v.relative_to(model.ROOT)).replace('\\','/') for k,v in {'solidcraft':sc,'freecad':fc,'solidcraft_step':step,'freecad_validation':free_report,'solidcraft_measurements':measurements}.items()},
              'artifact_sha256':{'solidcraft':model.digest(sc),'freecad':model.digest(fc)}}
        reports.append(item)
        write(exports/'cases-progress.json',reports)
        if not item['passed']: raise AssertionError('Cross-CAD mismatch: '+ident)
        print('Passed: %d bodies, maximum STEP XOR %.9g mm3'%(len(comparisons),item['maximum_step_xor_mm3']),flush=True)
    result={'format':'solidcraftbot.station-cross-cad/1','spec':'model/tube-station-c01.shared.json','source_sha256':model.digest(model.SOURCE),
            'source_files_sha256':{str(p.relative_to(model.ROOT)).replace('\\','/'):model.digest(p) for p in [model.SOURCE,Path(__file__),model.ROOT/'scripts/station_model.py',model.ROOT/'scripts/robot_spec.py',model.ROOT/'scripts/build_tube_station_freecad.py',model.ROOT/'scripts/freecad/persist_station_view.py']},
            'passed':all(c['passed'] for c in reports),'cases':reports,'elapsed_s':time.monotonic()-started,
            'limitations':['Concept geometry only; the documented loading problem remains unresolved','FreeCAD uses native expression-driven placements, not native Assembly solver constraints','STEP XOR checks saved poses; pose probes do not prove swept-volume clearance','GUI presentation metadata is saved and structurally checked; no FreeCAD GUI render has been performed','No native-CAD-to-source round trip; edit the shared JSON and rebuild both CADs','The original C01 artifacts and report remain preserved as historical source state']}
    write(exports/'build-report.json',result)
    write(model.ROOT/'cad/tube-station-c01/shared-build-report.json',result)
    print('Both station CADs passed. Report: cad/tube-station-c01/shared-build-report.json',flush=True)


if __name__=='__main__': main()
