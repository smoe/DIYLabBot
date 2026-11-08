"""Rebuild T01 from one source in SolidCraft and FreeCAD, then compare both."""
from pathlib import Path
import argparse
import tool_paths
import json
import math
import shutil
import subprocess
import sys
import time
import tip_collector_model as model


def write(path,value): Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def compare(actual,expected,source_name):
    refs={b['body']:b for b in expected}; checks=[]
    if set(refs)!={b['name'] for b in actual['bodies']}: raise AssertionError('Body names/count')
    for b in actual['bodies']:
        ref=refs[b['name']]; error=abs(b['volume_mm3']-ref['volume_mm3'])/ref['volume_mm3']
        com=math.dist(b['center_of_mass'],ref.get('center_of_mass_mm',ref.get('world_center_of_mass_mm')))
        bb=max(abs(v-w) for key in ['min','max'] for v,w in zip(b['bbox'][key],ref['bbox'][key]))
        checks.append({'body':b['name'],'relative_volume_error':error,'com_error_mm':com,'bbox_error_mm':bb,
            'passed':b['closed'] and error<0.001 and com<0.01 and bb<0.001,'reference':source_name})
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args=parser.parse_args(); tool_paths.resolve_tool_arguments(parser, args); spec=model.load(); started=time.monotonic()
    stem='tip-collector-t01-'+model.digest(model.SOURCE)[:12]; revision=stem; counter=1
    while (model.ROOT/'cad/generated'/revision).exists():
        counter+=1; revision=stem+'-r'+str(counter)
    cad=model.ROOT/'cad/generated'/revision; out=model.ROOT/'exports/generated'/revision
    cad.mkdir(parents=True); out.mkdir(parents=True)
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    cases=[('default',{}),('groove_M_7',{'groove_M':7}),('raised_bin_10',{'bin_h':160})]
    reports=[]; native_edits=[]
    for name,overrides in cases:
        p=model.parameters(spec,overrides)
        prefix=cad/(spec['id'] if name=='default' else spec['id']+'_'+name)
        sc=prefix.with_suffix('.sc'); fc=prefix.with_suffix('.FCStd'); step=out/(name+'.step')
        command_file=out/(name+'.commands.json'); case_file=out/(name+'.case.json')
        sc_file=out/(name+'.solidcraft.json'); fc_file=out/(name+'.freecad.json')
        write(command_file,{'source_sha256':model.digest(model.SOURCE),'commands':model.solidcraft_commands(spec,p)})
        write(case_file,{'id':name,'overrides':overrides})
        print('Collector case: '+name,flush=True)
        subprocess.run([args.solidcraft_cli,'run',str(command_file),'--save',str(sc),'--out',str(step),'--json-out',str(sc_file),'--quiet'],check=True,cwd=model.ROOT)
        subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_tip_collector_freecad.py'),str(fc),str(case_file),str(fc_file),str(step)],check=True,cwd=model.ROOT)
        scm=json.loads(sc_file.read_text(encoding='utf-8')); fcm=json.loads(fc_file.read_text(encoding='utf-8'))
        analytic=compare(scm,model.references(spec,p),'analytic volume/first moment')
        cross=compare(scm,fcm['geometry'],'FreeCAD native BRep')
        presentation=persist(fc,model.expanded(spec,p),fcm['geometry'])
        result={'id':name,'overrides':overrides,'passed':fcm['passed'] and all(c['passed'] for c in analytic+cross) and presentation['passed'],
            'body_comparisons':cross,'solidcraft_analytic_checks':analytic,'maximum_step_xor_mm3':max(c['xor_mm3'] for c in fcm['solidcraft_step_xor']),
            'freecad_native_parameter_edits':fcm['native_parameter_edits'],'freecad_presentation':presentation,
            'files':{k:str(v.relative_to(model.ROOT)).replace('\\','/') for k,v in {'solidcraft':sc,'freecad':fc,'step':step,'solidcraft_measurements':sc_file,'freecad_validation':fc_file}.items()},
            'artifact_sha256':{'solidcraft':model.digest(sc),'freecad':model.digest(fc),'step':model.digest(step)}}
        reports.append(result); write(out/'cases-progress.json',reports)
        if not result['passed']: raise AssertionError('Collector comparison failed: '+name)
        if name=='default':
            for parameter,value in [('groove_M',7),('bin_h',160)]:
                edit=out/('native-edit-'+parameter+'.commands.json'); measured=out/('native-edit-'+parameter+'.solidcraft.json')
                write(edit,{'commands':[{'command':'parameters.change','params':{'name':parameter,'expression':str(value)+' mm'}}]})
                subprocess.run([args.solidcraft_cli,'eval',str(edit),'--in',str(sc),'--json-out',str(measured)],check=True,cwd=model.ROOT,stdout=subprocess.DEVNULL)
                checks=compare(json.loads(measured.read_text(encoding='utf-8')),model.references(spec,model.parameters(spec,{parameter:value})),'analytic native-edit geometry')
                native_edits.append({'parameter':parameter,'value_mm':value,'passed':all(c['passed'] for c in checks),'body_checks':checks,
                    'saved_default_unchanged':True})
        print('Passed: %d bodies, STEP XOR max %.9g mm3'%(len(cross),result['maximum_step_xor_mm3']),flush=True)
    sources=[model.SOURCE,model.ROOT/spec['marking_asset'],Path(__file__),model.ROOT/'scripts/tip_collector_model.py',
        model.ROOT/'scripts/build_tip_collector_freecad.py',model.ROOT/'scripts/robot_spec.py',model.ROOT/'scripts/freecad/persist_station_view.py']
    report={'format':'solidcraftbot.collector-cross-cad/1','source':'model/tip-collector-t01.shared.json','source_sha256':model.digest(model.SOURCE),
        'source_files_sha256':{str(p.relative_to(model.ROOT)).replace('\\','/'):model.digest(p) for p in sources},
        'passed':all(c['passed'] for c in reports+native_edits),'body_count':14,'umr_bodies':['UMR_U_0','UMR_M_1','UMR_R_2'],
        'cases':reports,'solidcraft_native_parameter_edits':native_edits,'elapsed_s':time.monotonic()-started,
        'limitations':['Concept geometry; groove sizes and tip/pipette fit remain unqualified','Static station has no joints; robot unchanged and full motion envelope untested',
            'No force, stiffness, contamination or waste-pile validation','Native edits are not written back to the shared source',
            'Label outline scale or text changes require a source rebuild; native supported edit checks cover bin_h and groove_M',
            'FreeCAD colours/camera saved and structurally checked; no FreeCAD GUI render verified']}
    write(out/'build-report.json',report); write(model.ROOT/'cad/tip-collector-t01/shared-build-report.json',report)
    if not report['passed']: raise AssertionError('Native edit check failed')
    print('Both collector CADs passed: cad/tip-collector-t01/shared-build-report.json',flush=True)


if __name__=='__main__': main()
