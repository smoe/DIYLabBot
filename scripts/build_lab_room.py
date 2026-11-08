"""Build both native L01 room models, compare parameter variants and native edits."""
from pathlib import Path
import argparse
import tool_paths
import json
import shutil
import subprocess
import sys
import lab_room_model as model
from build_tube_carrier import compare


def write(path,data):
    Path(path).parent.mkdir(parents=True,exist_ok=True); Path(path).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')


def prepare():
    spec=model.load(); stem='lab-room-l01-'+model.digest(model.SOURCE)[:12]; revision=stem; n=1
    while (model.ROOT/'cad/generated'/revision).exists(): n+=1; revision=stem+'-r'+str(n)
    cad=model.ROOT/'cad/generated'/revision; out=model.ROOT/'exports/generated'/revision; cad.mkdir(parents=True); out.mkdir(parents=True)
    context={'revision':revision,'source_sha256':model.digest(model.SOURCE),'cad':str(cad),'out':str(out),'cases':[]}
    for name,overrides in [('default',{}),('wider_curved',{'room_width':7100,'facade_bulge':650}),
            ('deeper_storage',{'left_depth':7600,'right_depth':7100,'bench_height':950,'upper_depth':400}),
            ('support_shifted',{'support_offset_x':250,'support_width':400,'support_depth':550}),
            ('island_shelf_variant',{'island_length':3600,'island_shelf_top_z':1550,'island_shelf_depth':400,'island_shelf_end_inset':200,
             'island_cupboard_bottom_z':1850,'island_cupboard_height':500,'island_cupboard_depth':450})]:
        p=model.parameters(spec,overrides); files={'solidcraft':cad/(name+'.sc'),'freecad':cad/(name+'.FCStd'),
            'commands':out/(name+'.commands.json'),'case':out/(name+'.case.json'),'step':out/(name+'.step'),
            'sc_measurements':out/(name+'.solidcraft.json'),'fc_report':out/(name+'.freecad.json')}
        write(files['commands'],{'commands':model.solidcraft_commands(spec,p),'source_sha256':context['source_sha256']})
        write(files['case'],{'id':name,'overrides':overrides})
        context['cases'].append({'id':name,'overrides':overrides,'files':{k:str(v) for k,v in files.items()}})
    path=out/'context.json'; write(path,context); print(path,flush=True); return context


def finish(context,args):
    spec=model.load()
    if model.digest(model.SOURCE)!=context['source_sha256']: raise ValueError('Source changed since preparation')
    sys.path.insert(0,str(model.ROOT/'scripts/freecad')); from persist_station_view import persist
    cases=[]; native=[]
    for case in context['cases']:
        f=case['files']; p=model.parameters(spec,case['overrides'])
        if not Path(f['solidcraft']).exists():
            subprocess.run([args.solidcraft_cli,'run',f['commands'],'--save',f['solidcraft'],'--out',f['step'],'--json-out',f['sc_measurements'],'--quiet'],check=True,cwd=model.ROOT)
        if not Path(f['freecad']).exists():
            subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_lab_room_freecad.py'),f['freecad'],f['case'],f['fc_report'],f['step']],check=True,cwd=model.ROOT)
        fc=json.loads(Path(f['fc_report']).read_text(encoding='utf-8')); sc=json.loads(Path(f['sc_measurements']).read_text(encoding='utf-8'))
        cross=compare(sc,fc['geometry']); view=persist(f['freecad'],model.expanded(spec,p),fc['geometry'])
        for index,edit in enumerate(fc['native_parameter_edits']):
            script=Path(context['out'])/(case['id']+f'.native-{index}.commands.json'); measured=script.with_name(case['id']+f'.native-{index}.solidcraft.json')
            write(script,{'commands':[{'command':'parameters.change','params':{'name':key,'expression':str(value)+' mm'}} for key,value in edit['overrides'].items()]})
            subprocess.run([args.solidcraft_cli,'eval',str(script),'--in',f['solidcraft'],'--json-out',str(measured)],check=True,cwd=model.ROOT,stdout=subprocess.DEVNULL)
            checks=compare(json.loads(measured.read_text(encoding='utf-8')),edit['geometry'])
            native.append({'case':case['id'],'overrides':edit['overrides'],'passed':all(c['passed'] for c in checks),
                'max_com_error_mm':max(c['com_error_mm'] for c in checks),'body_checks':checks})
        item={'id':case['id'],'overrides':case['overrides'],'passed':fc['passed'] and all(c['passed'] for c in cross) and view['passed'],
            'bodies':len(cross),'cross_kernel_comparisons':cross,'maximum_step_xor_mm3':max(c['xor_mm3'] for c in fc['solidcraft_step_xor']),
            'frames':fc['frame_geometry_checks'],'window_assembly_checks':fc['window_assembly_checks'],'island_shelf_checks':fc['island_shelf_checks'],'circulation':fc['circulation'],'presentation':view,
            'solidcraft_execution':case.get('solidcraft_execution',{'backend':'CLI'}),
            'files':{k:str(Path(v).relative_to(model.ROOT)).replace('\\','/') for k,v in f.items()},
            'artifact_sha256':{k:model.digest(f[k]) for k in ['solidcraft','freecad','step']}}
        cases.append(item); write(Path(context['out'])/'cases-progress.json',cases)
        if not item['passed'] or any(not e['passed'] for e in native): raise AssertionError('L01 cross-CAD or native edit mismatch')
    paths=[model.SOURCE,Path(__file__),model.ROOT/'scripts/lab_room_model.py',model.ROOT/'scripts/build_lab_room_freecad.py',
        model.ROOT/'scripts/build_tube_carrier.py',model.ROOT/'scripts/build_tube_carrier_freecad.py',model.ROOT/'scripts/build_neutral_freecad.py',
        model.ROOT/'scripts/robot_spec.py',model.ROOT/'scripts/freecad/solidcraftbot_freecad.py',model.ROOT/'scripts/freecad/persist_station_view.py',model.ROOT/'scripts/freecad/persist_view.py']
    paths+=model.source_dependencies(spec)
    report={'format':'solidcraftbot.room-cross-cad/1','revision':context['revision'],'source':str(model.SOURCE.relative_to(model.ROOT)),
        'source_sha256':model.digest(model.SOURCE),'source_files_sha256':{str(p.relative_to(model.ROOT)):model.digest(p) for p in paths},
        'passed':all(c['passed'] for c in cases+native),'cases':cases,'native_parameter_edits':native,
        'renderings':[{'path':str(p.relative_to(model.ROOT)).replace('\\','/'),'sha256':model.digest(p),'source':'SolidCraft model render'} for p in Path(context['cad']).glob('*.png')],
        'limitations':spec['limitations']+['Native parameter edits are tested but are not written back to the source','No ROS environment, navigation map or physical human/machine layout validation','FreeCAD presentation metadata saved; interactive GUI not tested']}
    write(Path(context['out'])/'build-report.json',report); write(model.ROOT/'cad/lab-room-l01/shared-build-report.json',report)
    print('L01 native models passed: cad/lab-room-l01/shared-build-report.json',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    parser.add_argument('--prepare-only',action='store_true'); parser.add_argument('--finish',type=Path); args=parser.parse_args(); tool_paths.resolve_tool_arguments(parser, args, required=not args.prepare_only)
    context=json.loads(args.finish.read_text(encoding='utf-8')) if args.finish else prepare()
    if not args.prepare_only: finish(context,args)


if __name__=='__main__': main()
