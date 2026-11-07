"""Reproducible scene build: native source snapshots, SolidCraft composition, QA."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
import lab_layout_model as model
import lab_room_model as room


def write(path,data): Path(path).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')


def prepare(args):
    s=model.load(); stem='lab-layout-l01-'+model.digest(model.SOURCE)[:12]; revision=stem; n=1
    while (model.ROOT/'cad/generated'/revision).exists():n+=1;revision=stem+'-r'+str(n)
    cad=model.ROOT/'cad/generated'/revision;out=model.ROOT/'exports/generated'/revision;cad.mkdir(parents=True);out.mkdir(parents=True)
    context={'revision':revision,'cad':str(cad),'out':str(out),'source_sha256':model.digest(model.SOURCE)}
    path=out/'context.json';write(path,context)
    subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_lab_layout_freecad.py'),str(path)],check=True,cwd=model.ROOT)
    context=json.loads(path.read_text(encoding='utf-8'))
    validation=json.loads((out/'layout-validation.json').read_text(encoding='utf-8'))
    if model.digest(model.SOURCE)!=context['source_sha256']: raise ValueError('Layout source changed during preparation; rebuild')
    if not validation['passed']: raise ValueError('Layout checks failed; inspect '+str(out/'layout-validation.json'))
    room_source=room.load(model.assembly.validate_reference(s['assets']['room']))
    commands=room.solidcraft_commands(room_source,room.parameters(room_source))
    for snapshot in context['snapshots']:
        commands.append({'command':'file.insert_step','params':{'path':snapshot['step'],'name':snapshot['id'],'names':'product','matrix':snapshot['matrix']}})
        for b in snapshot['bodies']:commands.append({'command':'appearance.assign','params':{'bodies':[b['name']],**b['appearance']}})
    p=model.parameters(s)
    for c in s['corridors']:
        x0,x1,y0,y1=[model.robot.evaluate(v,p) for v in c['bounds']]
        commands += [{'command':'solid.box','params':{'name':c['id'],'body_name':c['id'],'corner':[x0,y0,0.1],'length':x1-x0,'width':y1-y0,'height':1.5}},
            {'command':'appearance.assign','params':{'bodies':[c['id']],'color':c['color'],'opacity':0.32}}]
    commands.append({'command':'document.metadata.set','params':{'values':{'org.solidcraftbot.lab-layout':{'source':str(model.SOURCE.relative_to(model.ROOT)),'sha256':context['source_sha256'],'status':s['status']}}}})
    write(out/'scene.commands.json',{'commands':commands});print(path,flush=True);return context


def finish(context,args):
    out=Path(context['out']);cad=Path(context['cad']);s=model.load();scene=cad/'LabLayout_L01.sc';measure=out/'solidcraft-scene.json'
    if model.digest(model.SOURCE)!=context['source_sha256']: raise ValueError('Layout source changed since preparation; rebuild')
    if not scene.exists():subprocess.run([args.solidcraft_cli,'run',str(out/'scene.commands.json'),'--save',str(scene),'--json-out',str(measure),'--quiet'],check=True,cwd=model.ROOT)
    # Named asset snapshots are independently placed. Match each physical body
    # to the corresponding source-derived native FreeCAD body through its ID.
    sc=json.loads(measure.read_text(encoding='utf-8'));known={b['name']:b for b in sc['bodies']}
    native=json.loads((out/'layout-validation.json').read_text(encoding='utf-8'))
    checks=[]
    for snap in context['snapshots']:
        names=[b['name'] for b in snap['bodies']];missing=[name for name in names if name not in known]
        if missing:raise ValueError('STEP did not retain expected body names: '+str(missing[:8]))
        v=sum(known[name]['volume_mm3'] for name in names);c=[sum(known[name]['volume_mm3']*known[name]['center_of_mass'][i] for name in names)/v for i in range(3)]
        ref=native['instance_metrics'][snap['id']];ve=abs(v-ref['volume_mm3'])/ref['volume_mm3'];ce=sum((a-b)**2 for a,b in zip(c,ref['center_of_mass_mm']))**0.5
        checks.append({'instance':snap['id'],'body_count':len(names),'volume_relative_error':ve,'center_error_mm':ce,'passed':ve<0.001 and ce<0.05 and all(known[n]['closed'] for n in names)})
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'));from persist_station_view import persist
    style_spec={'bodies':[{'id':name,'appearance':style} for name,style in context['styles'].items()]}
    fc_geometry=[]
    # Presentation only needs the bounds and IDs; equipment is already saved.
    for name in context['styles']:
        b=known[name];fc_geometry.append({'body':name,'bbox':b['bbox']})
    presentation=persist(context['scene_file'],style_spec,fc_geometry)
    paths=[model.SOURCE,model.ROOT/'scripts/lab_layout_model.py',Path(__file__),model.ROOT/'scripts/build_lab_layout_freecad.py',model.ROOT/'scripts/lab_room_model.py',model.ROOT/'scripts/build_lab_room_freecad.py']
    paths += [model.ROOT/ref['source'] for ref in s['assets'].values()]
    paths += room.source_dependencies(room.load(model.assembly.validate_reference(s['assets']['room'])))
    paths += [model.ROOT/'scripts'/name for name in ['assembly_model.py','robot_spec.py','robot_components.py','centrifuge_model.py','sample_transport_model.py','tip_collector_model.py','build_neutral_freecad.py','build_centrifuge_freecad.py','build_sample_transport_freecad.py','build_tip_collector_freecad.py']]
    paths += [model.ROOT/'model/assembly-reference.schema.json',model.ROOT/'model/lab-layout.schema.json']
    report={'format':'solidcraftbot.lab-layout-build/1','revision':context['revision'],'source_sha256':context['source_sha256'],
        'passed':native['passed'] and all(c['passed'] for c in checks),'layout_validation':native,'instance_cross_cad':checks,'presentation':presentation,
        'source_files_sha256':{str(p.relative_to(model.ROOT)):model.digest(p) for p in paths},'asset_sources':s['assets'],
        'files':{'solidcraft':str(scene.relative_to(model.ROOT)),'freecad':str(Path(context['scene_file']).relative_to(model.ROOT)),'validation':str((out/'layout-validation.json').relative_to(model.ROOT))},
        'artifact_sha256':{'solidcraft':model.digest(scene),'freecad':model.digest(context['scene_file'])},'limitations':s['limitations'],
        'renderings':[str(p.relative_to(model.ROOT)) for p in cad.glob('*.png')]}
    write(out/'build-report.json',report); target=model.ROOT/'cad/lab-layout-l01';target.mkdir(exist_ok=True);write(target/'shared-build-report.json',report)
    print(json.dumps({'passed':report['passed'],'instances':len(checks),'static_interferences':len(native['static_interferences']),'vehicle_samples':native['vehicle_route']['samples']}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--finish',type=Path)
    parser.add_argument('--solidcraft-cli',default=shutil.which('solidcraft-cli') or 'solidcraft-cli')
    parser.add_argument('--freecad-python',default=str(Path.home()/'AppData/Local/Programs/FreeCAD 27.1/bin/python.exe'));args=parser.parse_args()
    context=json.loads(args.finish.read_text(encoding='utf-8')) if args.finish else prepare(args)
    if not args.prepare_only:finish(context,args)


if __name__=='__main__':main()
