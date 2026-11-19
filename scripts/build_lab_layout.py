"""Build the shared L01 scene in FreeCAD, optionally compare SolidCraft."""
from pathlib import Path
import argparse
import tool_paths
import json
import shutil
import subprocess
import sys
import hashlib
import lab_layout_model as model
import lab_room_model as room
from build_instrument_concepts import freecad_environment


def write(path,data): Path(path).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')


def source_snapshot(s):
    """Freeze construction inputs before native work, including vendor bytes."""
    paths=[model.SOURCE,Path(__file__),model.ROOT/'scripts/lab_layout_model.py',
           model.ROOT/'scripts/build_lab_layout_freecad.py',model.ROOT/'scripts/lab_room_model.py',
           model.ROOT/'scripts/build_lab_room_freecad.py']
    paths += [model.ROOT/ref['source'] for ref in s['assets'].values()]
    paths += room.source_dependencies(room.load(model.assembly.validate_reference(s['assets']['room'])))
    paths += [model.ROOT/'scripts'/name for name in [
        'assembly_model.py','robot_spec.py','robot_components.py','robot_cameras.py','robot_services.py',
        'servo_mounting_design.py','x6_mounting_design.py','centrifuge_model.py','centrifuge_mechanisms.py','sample_transport_model.py','tip_collector_model.py',
        'build_neutral_freecad.py','build_centrifuge_freecad.py','build_sample_transport_freecad.py',
        'build_tip_collector_freecad.py','lab_equipment.py','build_lab_equipment_freecad.py',
        'build_tube_carrier_freecad.py','tube_carrier_model.py','tube_cam_model.py',
        'instrument_concept.py','tapestation_model.py','build_instrument_concepts.py','build_tube_carrier.py',
        'tool_paths.py','freecad/solidcraftbot_freecad.py','freecad/persist_station_view.py','freecad/persist_view.py']]
    paths += [model.ROOT/'model'/name for name in ['assembly-reference.schema.json','lab-layout.schema.json','lab-equipment.schema.json']]
    arm=model.robot.load(model.ROOT/s['assets']['arm']['source'])
    if 'vendor_library' in arm:
        import robot_components
        paths.append(model.ROOT/arm['vendor_library']['path'])
        for part in robot_components.library(arm)['parts'].values():
            paths += [model.ROOT/part[key]['path'] for key in ('interface_spec','interface_check') if key in part]
            paths += [model.ROOT/section['step'] for section in part['sections'].values()]
    return {str(path.relative_to(model.ROOT)):model.digest(path) for path in paths}


def verify_source_snapshot(context):
    pins=context.get('source_files_sha256')
    if not pins: raise ValueError('Prepared source snapshot missing; prepare the layout again')
    for name,expected in pins.items():
        path=model.assembly.project_path(name,model.ROOT)
        if not path.is_file() or model.digest(path)!=expected:
            raise ValueError('Layout input changed during build; rebuild: '+name)


def native_arm(s,snapshot,cad,out,args):
    """Pose the checked native arm, retaining its vendor-body decomposition."""
    ref=s['assets']['arm'];report_path=model.ROOT/ref['report']
    report=json.loads(report_path.read_text());source=model.instance_source(s,snapshot['instance'])
    upstream=model.ROOT/report['artifacts']['solidcraft']
    if model.digest(upstream)!=report['artifact_sha256']['solidcraft']:raise ValueError('Native arm artifact changed')
    measured=json.loads((model.ROOT/report['artifacts']['solidcraft_measurements']).read_text())['bodies']
    prefix=snapshot['id']+'__';commands=[]
    for name,value in snapshot['instance'].get('overrides',{}).items():
        commands.append({'command':'parameters.change','params':{'name':name,'expression':str(model.robot.evaluate(value,model.parameters(s)))+' '+source['parameters'][name]['unit']}})
    commands.extend({'command':'joint.drive','params':{'joint':j['id'],'value':q,'quiet':True}}
                    for j,q in zip(source['joints'],snapshot['instance']['joints_deg']))
    commands.append({'command':'joint.solve','params':{}})
    commands.extend({'command':'body.rename','params':{'body':b['name'],'name':prefix+b['name']}} for b in measured)
    command_file=out/(snapshot['id']+'.solidcraft.commands.json');target=cad/'assets'/(snapshot['id']+'.sc')
    write(command_file,{'commands':commands})
    key=hashlib.sha256((model.digest(upstream)+json.dumps(commands,sort_keys=True)).encode()).hexdigest()
    cache=model.ROOT/'exports/generated/layout-arm-cache'/(key+'.json')
    saved=json.loads(cache.read_text()) if cache.exists() else None
    if saved and saved['input_sha256']==key and (model.ROOT/saved['path']).is_file() and model.digest(model.ROOT/saved['path'])==saved['sha256']:
        target=model.ROOT/saved['path']
    else:
        subprocess.run([args.solidcraft_cli,'run',str(command_file),'--in',str(upstream),'--save',str(target),'--quiet'],check=True,cwd=model.ROOT,stdout=subprocess.DEVNULL)
        cache.parent.mkdir(parents=True,exist_ok=True)
        write(cache,{'input_sha256':key,'path':str(target.relative_to(model.ROOT)),'sha256':model.digest(target)})
    names=set()
    for body in snapshot['bodies']:
        semantic=body['name'][len(prefix):].split('__Solid')[0]
        names.update(prefix+name for name in report['solidcraft_body_aliases'].get(semantic,[semantic]))
    snapshot.update(solidcraft_native=str(target),solidcraft_native_sha256=model.digest(target),
                    solidcraft_bodies=sorted(names),solidcraft_hidden=[prefix+b['name'] for b in measured if prefix+b['name'] not in names],
                    solidcraft_rigid_metric_bodies=sorted(prefix+n for body in snapshot['bodies'] if body['role']=='vendor_housing'
                        for n in report['solidcraft_body_aliases'].get(body['name'][len(prefix):].split('__Solid')[0],[])),
                    native_arm_parent={'path':str(upstream.relative_to(model.ROOT)),'sha256':model.digest(upstream),
                                       'report':str(report_path.relative_to(model.ROOT)),'report_sha256':model.digest(report_path)})


def prepare_native(args):
    s=model.load(validate_builds=args.backend!='freecad')
    pins=source_snapshot(s)
    stem='lab-layout-l01-'+model.digest(model.SOURCE)[:12]; revision=stem; n=1
    while (model.ROOT/'cad/generated'/revision).exists():n+=1;revision=stem+'-r'+str(n)
    cad=model.ROOT/'cad/generated'/revision;out=model.ROOT/'exports/generated'/revision;cad.mkdir(parents=True);out.mkdir(parents=True)
    context={'revision':revision,'cad':str(cad),'out':str(out),'source_sha256':pins[str(model.SOURCE.relative_to(model.ROOT))],
             'backends':args.backend,'source_files_sha256':pins}
    path=out/'context.json';write(path,context)
    subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_lab_layout_freecad.py'),str(path)],check=True,cwd=model.ROOT,env=freecad_environment(args.freecad_python))
    context=json.loads(path.read_text(encoding='utf-8'))
    if context.get('source_files_sha256')!=pins or context.get('source_sha256')!=pins[str(model.SOURCE.relative_to(model.ROOT))] or context.get('backends')!=args.backend:
        raise ValueError('Foreign native layout context or changed source snapshot')
    validation=json.loads((out/'layout-validation.json').read_text(encoding='utf-8'))
    verify_source_snapshot(context)
    if not validation['passed']: raise ValueError('Layout checks failed; inspect '+str(out/'layout-validation.json'))
    return s,context


def prepare(args):
    s,context=prepare_native(args)
    if args.backend=='freecad':return context
    cad=Path(context['cad']);out=Path(context['out']);path=out/'context.json'
    room_source=room.load(model.assembly.validate_reference(s['assets']['room']))
    commands=room.solidcraft_commands(room_source,room.parameters(room_source))
    for snapshot in context['snapshots']:
        if snapshot['source_asset']=='arm':
            native_arm(s,snapshot,cad,out,args)
        elif snapshot['source_asset'] in model.EQUIPMENT_PROFILES|model.INSTRUMENTS or snapshot['source_asset']=='centrifuge':
            native_file=cad/'assets'/(snapshot['id']+'.sc');native_commands=out/(snapshot['id']+'.solidcraft.commands.json')
            compiler=model.centrifuge_solidcraft_commands if snapshot['source_asset']=='centrifuge' else model.equipment_solidcraft_commands
            write(native_commands,{'commands':compiler(s,snapshot['instance'])})
            subprocess.run([args.solidcraft_cli,'run',str(native_commands),'--save',str(native_file),'--quiet'],check=True,cwd=model.ROOT,stdout=subprocess.DEVNULL)
            snapshot.update(solidcraft_native=str(native_file),solidcraft_native_sha256=model.digest(native_file))
        if 'solidcraft_native' in snapshot:
            commands.extend([
                {'command':'component.insert_design','params':{'path':snapshot['solidcraft_native'],'name':snapshot['id']}},
                {'command':'occurrence.move','params':{'occurrence':snapshot['id']+':1','matrix':snapshot['matrix'],'move_grounded':True}},
                {'command':'occurrence.ground','params':{'occurrence':snapshot['id']+':1','grounded':True}}])
            if snapshot.get('solidcraft_hidden'):
                commands.append({'command':'browser.visibility','params':{'items':snapshot['solidcraft_hidden'],'visible':False}})
        else:
            commands.append({'command':'file.insert_step','params':{'path':snapshot['step'],'name':snapshot['id'],'names':'product','matrix':snapshot['matrix']}})
            for b in snapshot['bodies']:commands.append({'command':'appearance.assign','params':{'bodies':[b['name']],**b['appearance']}})
    p=model.parameters(s)
    for c in s['corridors']:
        x0,x1,y0,y1=[model.robot.evaluate(v,p) for v in c['bounds']]
        commands += [{'command':'solid.box','params':{'name':c['id'],'body_name':c['id'],'corner':[x0,y0,0.1],'length':x1-x0,'width':y1-y0,'height':1.5}},
            {'command':'appearance.assign','params':{'bodies':[c['id']],'color':c['color'],'opacity':0.32}}]
    commands.append({'command':'document.metadata.set','params':{'values':{'org.solidcraftbot.lab-layout':{'source':str(model.SOURCE.relative_to(model.ROOT)),'sha256':context['source_sha256'],'status':s['status']}}}})
    write(out/'scene.commands.json',{'commands':commands});write(path,context);print(path,flush=True);return context


def finish(context,args):
    if context.get('backends','both')!=args.backend:
        raise ValueError('Prepared layout backend differs; use the same --backend')
    verify_source_snapshot(context)
    if args.backend=='freecad':return finish_freecad(context)
    out=Path(context['out']);cad=Path(context['cad']);s=model.load();scene=cad/'LabLayout_L01.sc';measure=out/'solidcraft-scene.json'
    if model.digest(model.SOURCE)!=context['source_sha256']: raise ValueError('Layout source changed since preparation; rebuild')
    if not scene.exists():subprocess.run([args.solidcraft_cli,'run',str(out/'scene.commands.json'),'--save',str(scene),'--json-out',str(measure),'--quiet'],check=True,cwd=model.ROOT)
    # Named asset snapshots are independently placed. Match each physical body
    # to the corresponding source-derived native FreeCAD body through its ID.
    sc=json.loads(measure.read_text(encoding='utf-8'));known={b['name']:b for b in sc['bodies']}
    native=json.loads((out/'layout-validation.json').read_text(encoding='utf-8'))
    rigid_checks=[];recovered=[]
    for snap in context['snapshots']:
        if snap['source_asset']!='arm':continue
        if model.digest(snap['solidcraft_native'])!=snap['solidcraft_native_sha256']:raise ValueError('Native arm changed during composition')
        local_path=model.ROOT/'exports/generated/layout-arm-cache'/(snap['solidcraft_native_sha256']+'.metrics.json')
        receipt=local_path.with_suffix('.receipt.json')
        if not (local_path.exists() and receipt.exists() and json.loads(receipt.read_text())=={
            'native_sha256':snap['solidcraft_native_sha256'],'metrics_sha256':model.digest(local_path)}):
            subprocess.run([args.solidcraft_cli,'eval','--in',snap['solidcraft_native'],'--json-out',str(local_path)],check=True,cwd=model.ROOT,stdout=subprocess.DEVNULL)
            write(receipt,{'native_sha256':snap['solidcraft_native_sha256'],'metrics_sha256':model.digest(local_path)})
        local={b['name']:b for b in json.loads(local_path.read_text())['bodies']}
        for name in snap['solidcraft_bodies']:
            before=local[name];actual=known[name]
            if not before.get('closed') or before.get('volume_mm3',0)<=0:raise ValueError('Invalid native local arm body: '+name)
            expected=model.robot.transform(snap['matrix'],before['center_of_mass'])
            if 'volume_mm3' not in actual:
                if name not in snap['solidcraft_rigid_metric_bodies'] or actual.get('error')!='the operation failed: SMLib: solidcore: flat arrays: a NURBS form that is not its analytic surface':
                    raise ValueError('Unmeasured scene body: '+name+': '+str(actual))
                recovered.append({'body':name,'scene_measurement_error':actual['error'],'local_metrics':str(local_path.relative_to(model.ROOT)),
                                  'local_metrics_sha256':model.digest(local_path),'method':'Closed native local body properties under the single rigid instance placement; world surface integration unavailable'})
                actual={**actual,'volume_mm3':before['volume_mm3'],'center_of_mass':expected,'closed':True,'measured_by':'derived from native local properties and rigid placement'}
                known[name]=actual
            else:
                ve=abs(actual['volume_mm3']-before['volume_mm3'])/before['volume_mm3']
                ce=sum((a-b)**2 for a,b in zip(actual['center_of_mass'],expected))**.5
                rigid_checks.append({'body':name,'volume_relative_error':ve,'center_error_mm':ce,
                                     'passed':actual['closed'] and ve<1e-4 and ce<.001})
    checks=[]
    for snap in context['snapshots']:
        names=snap.get('solidcraft_bodies',[b['name'] for b in snap['bodies']]);missing=[name for name in names if name not in known]
        if missing:raise ValueError('STEP did not retain expected body names: '+str(missing[:8]))
        v=sum(known[name]['volume_mm3'] for name in names);c=[sum(known[name]['volume_mm3']*known[name]['center_of_mass'][i] for name in names)/v for i in range(3)]
        ref=native['instance_metrics'][snap['id']];ve=abs(v-ref['volume_mm3'])/ref['volume_mm3'];ce=sum((a-b)**2 for a,b in zip(c,ref['center_of_mass_mm']))**0.5
        checks.append({'instance':snap['id'],'body_count':len(names),'volume_relative_error':ve,'center_error_mm':ce,'passed':ve<0.001 and ce<0.05 and all(known[n]['closed'] for n in names)})
    from build_tube_carrier import compare
    device_bodies=native['equipment_body_metrics']
    device_comparisons=compare({'bodies':[known[b['body']] for b in device_bodies]},device_bodies)
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'));from persist_station_view import persist
    style_spec={'bodies':[{'id':name,'appearance':style} for name,style in context['styles'].items()]}
    # Each CAD retains its native vendor-part subdivision; style the actual
    # FreeCAD bodies using their own measured bounds.
    fc_geometry=native['scene_geometry']
    presentation=persist(context['scene_file'],style_spec,fc_geometry)
    verify_source_snapshot(context)
    report={'format':'solidcraftbot.lab-layout-build/1','revision':context['revision'],'source_sha256':context['source_sha256'],
        'backends':'both','freecad_checks_passed':native['passed'],'cross_cad_checked':True,
        'passed':native['passed'] and presentation['passed'] and all(c['passed'] for c in checks+device_comparisons+rigid_checks),'layout_validation':native,'instance_cross_cad':checks,
        'equipment_body_comparisons':device_comparisons,'presentation':presentation,
        'arm_rigid_placement_checks':rigid_checks,'arm_rigid_metric_derivations':recovered,
        'direct_world_measurements_complete':not recovered,
        'source_files_sha256':context['source_files_sha256'],'asset_sources':s['assets'],
        'files':{'solidcraft':str(scene.relative_to(model.ROOT)),'freecad':str(Path(context['scene_file']).relative_to(model.ROOT)),
                 'validation':str((out/'layout-validation.json').relative_to(model.ROOT)),
                 'solidcraft_measurements':str(measure.relative_to(model.ROOT))},
        'artifact_sha256':{'solidcraft':model.digest(scene),'freecad':model.digest(context['scene_file']),
                           'validation':model.digest(out/'layout-validation.json'),'solidcraft_measurements':model.digest(measure)},'limitations':s['limitations'],
        'native_equipment_models':{snap['id']:{'path':str(Path(snap['solidcraft_native']).relative_to(model.ROOT)),
                                              'sha256':snap['solidcraft_native_sha256']} for snap in context['snapshots'] if snap['source_asset'] in model.EQUIPMENT_PROFILES},
        'native_arm_models':{snap['id']:{'path':str(Path(snap['solidcraft_native']).relative_to(model.ROOT)),
                                       'sha256':snap['solidcraft_native_sha256'],'parent':snap['native_arm_parent']}
                             for snap in context['snapshots'] if snap['source_asset']=='arm'},
        'native_station_models':{snap['id']:{'path':str(Path(snap['solidcraft_native']).relative_to(model.ROOT)),
                                           'sha256':snap['solidcraft_native_sha256']} for snap in context['snapshots'] if snap['source_asset']=='centrifuge'},
        'renderings':[str(p.relative_to(model.ROOT)) for p in cad.glob('*.png')]}
    if recovered:
        report['limitations']=report['limitations']+[
            str(len(recovered))+' vendor housing parts have unavailable world-surface integration in SolidCraft. Their closed native local volumes and centres are transformed by the rigid instance placement; all directly measurable arm bodies verify that placement. Raw errors and derivations are retained.']
    write(out/'build-report.json',report); target=model.ROOT/'cad/lab-layout-l01';target.mkdir(exist_ok=True);write(target/'shared-build-report.json',report)
    if not report['passed']:raise AssertionError('Layout cross-CAD comparison failed')
    print(json.dumps({'passed':report['passed'],'instances':len(checks),'static_interferences':len(native['static_interferences']),'vehicle_samples':native['vehicle_route']['samples']}),flush=True)


def finish_freecad(context):
    """Publish actual native validation without inventing another CAD's checks."""
    verify_source_snapshot(context)
    out=Path(context['out']);s=model.load(validate_builds=False)
    native=json.loads((out/'layout-validation.json').read_text(encoding='utf-8'))
    if native.get('passed') is not True or native.get('geometry_valid') is not True:
        raise ValueError('A successful complete native L01 validation is required')
    geometry=native.get('scene_geometry',[])
    names=[body['body'] for body in geometry]
    if not names or len(names)!=len(set(names)) or len(names)!=native.get('body_count') or native.get('invalid_objects')!=[]:
        raise ValueError('Complete unique native L01 bodies are required')
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'));from persist_station_view import persist
    presentation=persist(context['scene_file'],{'bodies':[{'id':name,'appearance':style} for name,style in context['styles'].items()]},geometry)
    if presentation['passed'] is not True:raise ValueError('Native L01 presentation metadata failed')
    verify_source_snapshot(context)
    files={'freecad':str(Path(context['scene_file']).relative_to(model.ROOT)),
           'validation':str((out/'layout-validation.json').relative_to(model.ROOT))}
    report={'format':'solidcraftbot.lab-layout-build/1','revision':context['revision'],
        'source_sha256':context['source_sha256'],'backends':'freecad','freecad_checks_passed':True,
        'cross_cad_checked':False,'passed':True,'layout_validation':native,'presentation':presentation,
        'freecad_runtime':context.get('freecad_runtime'),
        'source_files_sha256':context['source_files_sha256'],'asset_sources':s['assets'],
        'files':files,'artifact_sha256':{key:model.digest(model.ROOT/path) for key,path in files.items()},
        'limitations':s['limitations']+[
            'Independent FreeCAD construction and sampled static layout/access validation only; no SolidCraft or cross-CAD comparison in this build.',
            'Saved presentation metadata is not a GUI, browser, continuous-motion, human-access or hardware safety qualification.']}
    write(out/'build-report.json',report)
    target=model.ROOT/'cad/lab-layout-l01';target.mkdir(exist_ok=True);write(target/'shared-build-report.json',report)
    print(json.dumps({'passed':True,'backends':'freecad','cross_cad_checked':False,'bodies':native['body_count'],
                      'vehicle_samples':native['vehicle_route']['samples']}),flush=True)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--finish',type=Path)
    parser.add_argument('--backend',choices=['both','freecad'],default='both')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args=parser.parse_args(argv)
    if args.backend=='freecad':
        args.freecad_python=args.freecad_python or tool_paths.default_freecad_python()
        if not args.freecad_python:parser.error('FreeCAD Python not found; pass --freecad-python or set '+tool_paths.FREECAD_ENV)
    else:tool_paths.resolve_tool_arguments(parser, args)
    context=json.loads(args.finish.read_text(encoding='utf-8')) if args.finish else prepare(args)
    if not args.prepare_only:finish(context,args)


if __name__=='__main__':main()
