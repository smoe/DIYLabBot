"""Source-bound full-arm H02 pickup, independent CAD builds and continuous audit."""
import argparse
import copy
import itertools
import json
import math
from pathlib import Path
import subprocess
import h02_arm_pickup as model
import h02_arm_solidcraft as sc
import h02_direct_pickup as local
import solidcraft_vendor as vendor
import robot_components
import build_extraction_kit_station as common
import tool_paths


def sources(program):
    paths=set(local.dependencies(program.local_scene))|{model.SOURCE,model.SCHEMA,Path(__file__),
        model.ROOT/'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py',
        *[model.assembly.validate_reference(r) for r in program.definition['sources'].values()]}
    for name in ['h02_arm_pickup.py','h02_arm_solidcraft.py','solidcraft_audit_session.py','build_h02_arm_freecad.py',
                 'build_h02_direct_pickup.py','build_h02_direct_pickup_freecad.py','build_tube_carrier.py','build_tube_carrier_freecad.py',
                 'build_neutral_freecad.py','build_relative_floorplan.py','build_extraction_kit_station.py','extraction_kit_station.py',
                 'robot_components.py','robot_cameras.py','servo_mounting_design.py','x6_mounting_design.py','sample_motion.py',
                 'solidcraft_vendor.py','tool_paths.py','freecad/solidcraftbot_freecad.py','freecad/persist_station_view.py','freecad/persist_view.py']:
        paths.add(model.ROOT/'scripts'/name)
    library=robot_components.library(program.arm);paths.add(model.ROOT/program.arm['vendor_library']['path'])
    for part in library['parts'].values():
        for field in ['interface_spec','interface_check']:
            if field in part:paths.add(model.ROOT/part[field]['path'])
        for section in part['sections'].values():paths.add(model.ROOT/section['step'])
    for name in ['cad/vendor/myactuator/manifest.json','cad/vendor/myactuator/geometry-check.json','model/assembly-reference.schema.json']:
        paths.add(model.ROOT/name)
    manifest=json.loads((model.ROOT/'cad/vendor/myactuator/manifest.json').read_text())
    for entry in manifest['models']:
        for file in entry['files']:
            if file['kind']=='step':paths.add(model.ROOT/file['path'])
    if getattr(program,'program_kind',None)=='h02-rack-transfer':
        paths.update([program.source_path,program.schema_path,model.ROOT/'scripts/h02_rack_transfer.py',model.ROOT/'scripts/h02_transfer_adapters.py',model.ROOT/'scripts/h02_native_pose_boxes.py',model.ROOT/'scripts/cf01_unload_path.py',model.ROOT/'scripts/rack_slots.py'])
        paths.update(model.assembly.validate_reference(r) for r in program.transfer['sources'].values())
    return {common.relative(path):model.robot.digest(path) for path in sorted(paths)}


def vendor_cache(program,path):
    """Only source- and artifact-pinned SolidCraft manufacturer round trips."""
    path=Path(path).resolve()
    if not path.is_relative_to(model.ROOT):raise ValueError('Vendor cache must be a local project build report')
    report=json.loads(path.read_text());common.verify_pins(report['source_sha256'])
    library=robot_components.library(program.arm);sections={}
    expected={op['part'] for link in program.arm['links'] for op in link['recipe'] if op['action']=='vendor_component' and op['section']=='housing'}&vendor.AFFECTED
    if not report['passed'] or report['freecad_required'] or {p['part'] for p in report['parts']}!=expected:raise ValueError('Wrong vendor cache scope')
    for entry in report['parts']:
        part=library['parts'][entry['part']]
        if entry['registration']!=part['vendor_to_output_frame'] or not entry['passed'] or not all(v['passed'] for v in entry['comparisons']):raise ValueError('Invalid vendor round-trip evidence')
        if model.robot.digest(model.ROOT/entry['original']['path'])!=entry['original']['sha256']:raise ValueError('Vendor original changed')
        for item in [entry['output'],*entry['isolated_parts']]:
            if model.robot.digest(item['step'])!=item['sha256']:raise ValueError('Vendor cache artifact changed')
        sections[str(model.ROOT/part['sections']['housing']['step'])]=entry['output']
    return sections,{'report':common.relative(path),'sha256':model.robot.digest(path),'inputs_and_artifacts_verified':True,
                     'source_sha256':report['source_sha256'],'representation':'Original closed housing pieces; no FreeCAD build dependency'}


def local_audit(engine,program,variant,directory,raw):
    """Existing shared continuous scopes, evaluated in the combined native scene."""
    spec=local.context(program.local_scene,variant);p=local.parameters(spec);_,pairs,_=local.proof(spec,p)
    by={v['name']:v for v in raw['bodies']};selected=[];checks=[];commands=sc.drive(program,'closure',1)
    for pair in pairs:
        lower=max(0,model.bbox_distance(by[pair['a']]['bbox'],by[pair['b']]['bbox'])-1e-7)
        if lower>=max(5,pair['required_mm']) and not pair['intended_pad_contact']:
            checks.append({**pair,'distance_lower_bound_mm':lower,'passed':True})
        else:
            selected.append(pair)
            commands.extend([{'command':'inspect.measure','params':{'items':[{'type':'body','name':pair['a']},{'type':'body','name':pair['b']}]}},
                             {'command':'inspect.interference','params':{'bodies':[pair['a'],pair['b']]}}])
    result=engine.run(commands);common.write(directory/'local-solidcraft-raw.json',result)
    ds=[r for r in result if isinstance(r,dict) and 'distance_mm' in r];hits=[r for r in result if isinstance(r,dict) and 'interferences' in r]
    if len(ds)!=len(selected) or len(hits)!=len(selected):raise ValueError('Incomplete local native audit')
    for pair,d,h in zip(selected,ds,hits):
        if {v['name'] for v in d['items']}!={pair['a'],pair['b']} or h['checked']!=2 or h['unchecked'] or h['truncated'] or h['budget_exceeded'] or h['pairs_not_checked']:
            raise ValueError('Incomplete or foreign local pair result')
        volume=sum(x['volume_mm3'] for x in h['interferences']);distance=d['distance_mm']
        passed=distance+1e-6>=pair['required_mm'] and volume<=program.local_scene['volume_tolerance_mm3']
        if pair['intended_pad_contact']:passed=passed and distance<=1e-6
        checks.append({**pair,'distance_mm':distance,'overlap_mm3':volume,'passed':passed})
    report={'passed':all(c['passed'] for c in checks),'continuous_checks':checks};common.write(directory/'local-solidcraft.json',report)
    if not report['passed']:raise AssertionError('Combined-scene local sweep audit failed')
    return report


def negative_control(cli,engine,program,native,directory,records,expected_names):
    counter=copy.copy(program);counter.curves={'extraction':program.curves['extraction']}
    selected=[next(r for r in records if r['id']=='ToolMount'),{'id':'ArmMidpathBlocker','group':'Proof','kind':'control','role':'negative_control','names':['ArmMidpathBlocker'],'local_bbox':{'min':[0,0,0],'max':[1,1,1]}}]
    if hasattr(program,'extra_parts'):
        selected[1]['native_zero_bbox']=next(b['bbox'] for b in program.native_zero_measurement['bodies'] if b['name']=='ArmMidpathBlocker')
    negative_dir=directory/'negative-control';negative_dir.mkdir(exist_ok=True)
    provider=sc.Provider(cli,counter,native,negative_dir,selected,expected_names,engine)
    rejected=model.certify(counter,selected,provider);commands=[]
    for u in [0,.5,1]:commands+=sc.drive(program,'extraction',u)+[{'command':'inspect.interference','params':{'bodies':['ToolMount','ArmMidpathBlocker']}}]
    results=engine.run(commands);hits=[v for v in results if isinstance(v,dict) and 'interferences' in v]
    if len(hits)!=3 or any(v['checked']!=2 or v['unchecked'] or v['truncated'] or v['budget_exceeded'] or v['pairs_not_checked'] for v in hits):raise ValueError('Incomplete robot negative control')
    volumes=[sum(h['volume_mm3'] for h in v['interferences']) for v in hits]
    if rejected['passed'] or volumes[1]<.9 or max(volumes[0],volumes[2])>1e-5:raise AssertionError('Midpath robot obstacle was missed')
    result={'rejected_by_continuous_audit':True,'overlap_volumes_mm3':volumes,'audit':rejected};common.write(directory/'negative-solidcraft.json',result)
    return result


def build(args):
    if getattr(args,'transfer',False):
        import h02_rack_transfer as transfer
        program=transfer.Program()
    else:program=model.Program()
    analysis=program.audit();pins=sources(program);source=getattr(program,'source_path',model.SOURCE);kind=getattr(program,'program_kind','h02-arm-pickup')
    stem=kind+'-'+model.robot.digest(source)[:12];revision=stem;n=1
    while (model.ROOT/'exports/generated'/revision).exists():n+=1;revision=stem+'-r'+str(n)
    out=model.ROOT/'exports/generated'/revision;cad=model.ROOT/'cad/generated'/revision;render=model.ROOT/'renders'/revision
    for p in [out,cad,render]:p.mkdir(parents=True)
    sections=None;vendor_report=None
    if args.backend in ('both','solidcraft'):
        if args.vendor_cache:sections,vendor_report=vendor_cache(program,args.vendor_cache)
        else:
            sections,report=vendor.prepare(program.arm,args.solidcraft_cli,out/'vendor')
            vendor_report={'report':common.relative(out/'vendor/vendor-build-report.json'),'sha256':model.robot.digest(out/'vendor/vendor-build-report.json'),'inputs_and_artifacts_verified':True}
    cases=[]
    for variant in program.local_scene['variants']:
        directory=out/variant;models=cad/variant
        for p in [directory,models]:p.mkdir()
        case={'variant':variant,'program_kind':kind,'pins':pins,'directory':common.relative(directory),'cad_directory':common.relative(models)};common.write(directory/'case.json',case)
        fc=None;sc_report=None
        if args.backend in ('both','freecad'):
            subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_h02_arm_freecad.py'),str(directory/'case.json')],check=True,env=common.freecad_environment(args.freecad_python))
            fc=json.loads((directory/'freecad-report.json').read_text())
        if args.backend in ('both','solidcraft'):
            native,records,raw,aliases,engine=sc.construct(args.solidcraft_cli,program,variant,directory,models,sections)
            try:
                local_audit(engine,program,variant,directory,raw);program.local_certified=True
                provider=sc.Provider(args.solidcraft_cli,program,native,directory,records,[b['name'] for b in raw['bodies']],engine)
                audit=model.certify(program,records,provider);common.write(directory/'continuous-solidcraft.json',audit)
                if not audit['passed']:raise AssertionError('Continuous SolidCraft audit failed: '+str(audit['failures'])[:2000])
                negative=negative_control(args.solidcraft_cli,engine,program,native,directory,records,[b['name'] for b in raw['bodies']])
                if getattr(program,'native_batch_drive',False):
                    from h02_native_pose_boxes import STUDY
                    engine.run([{'command':'motion.delete','params':{'study':STUDY}}]);program.native_batch_drive=False
                poses=[]
                for name,phase,u in getattr(program,'native_poses',[('approach','approach',0),('grasp','closure',1),('extracted','extraction',1)]):
                    data=engine.run(sc.drive(program,phase,u)+[{'command':'inspect.measure','params':{}}]);measurement=sc.measurements(data)[0]
                    pose=models/(name+'.sc');engine.tool('save',{'path':str(pose)})
                    view=None
                    if not args.no_render:
                        image=render/(variant+'-'+name+'.png');camera={'target':[0,-120,155],'yaw':-.65,'pitch':.55,'distance':1250,'fov':.6}
                        engine.tool('screenshot',{'path':str(image),'source':'model','width':1500,'height':1200,'camera':camera,'grid':False,'axes':False})
                        if not image.exists():raise ValueError('Native screenshot missing')
                        view={'path':common.relative(image),'sha256':model.robot.digest(image),'camera':camera,'visually_reviewed':False}
                    poses.append({'state':name,'file':common.relative(pose),'measurement':measurement,'view':view})
                contacts=[]
                if hasattr(program,'extra_parts'):
                    controls=sc.drive(program,'release',0)
                    for body in ['Selected_ReferenceTube','CarriedEnvelope']:
                        controls.extend([{'command':'inspect.measure','params':{'items':[{'type':'body','name':body},{'type':'body','name':'Rack_Base'}]}},{'command':'inspect.interference','params':{'bodies':[body,'Rack_Base']}}])
                    values=engine.run(controls);distances=[v for v in values if isinstance(v,dict) and 'distance_mm' in v];overlaps=[v for v in values if isinstance(v,dict) and 'interferences' in v]
                    if len(distances)!=2 or len(overlaps)!=2:raise ValueError('Incomplete native support checks')
                    for d,h in zip(distances,overlaps):
                        if d['distance_mm']>1e-6 or h['unchecked'] or h['truncated'] or h['budget_exceeded'] or h['pairs_not_checked'] or sum(v['volume_mm3'] for v in h['interferences'])>program.local_scene['volume_tolerance_mm3']:raise ValueError('Invalid rack support contact')
                        contacts.append({'distance_mm':d['distance_mm'],'overlap_mm3':sum(v['volume_mm3'] for v in h['interferences']),'passed':True})
                sc_report={'passed':True,'support_contacts':contacts,'records':records,'poses':poses,'aliases':aliases,'continuous_audit':common.relative(directory/'continuous-solidcraft.json'),'negative_control':negative,'native_evaluation':'Native solved occurrence frames and construction BRep bounding enclosures, exact BRep distances for nearby pairs' if hasattr(program,'extra_parts') else 'Native BRep metrology'}
                common.write(directory/'solidcraft-report.json',sc_report)
            finally:engine.close()
        comparison=[]
        if fc and sc_report:
            for f,s in zip(fc['poses'],sc_report['poses']):
                actual={b['name']:b for b in s['measurement']['bodies']}
                expected={n for b in f['geometry'] if not b['body'].endswith('view_CONE') for n in sc_report['aliases'].get(b['body'],[b['body']])}
                if set(actual)!=expected:raise AssertionError('Cross-CAD body sets differ')
                for b in f['geometry']:
                    names=sc_report['aliases'].get(b['body'],[b['body']])
                    if b['body'].endswith('view_CONE'):continue
                    other=sc.aggregate(actual,names);ve=abs(b['volume_mm3']-other['volume_mm3'])/b['volume_mm3'];ce=math.dist(b['center_of_mass'],other['center_of_mass'])
                    be=max(abs(a-c) for edge in ['min','max'] for a,c in zip(b['bbox'][edge],other['bbox'][edge]))
                    comparison.append({'pose':f['state'],'body':b['body'],'relative_volume_error':ve,'center_error_mm':ce,'bbox_error_mm':be,'passed':b['closed'] and ve<.001 and ce<.01 and be<.01})
            if not all(v['passed'] for v in comparison):raise AssertionError('Cross-CAD mismatch: '+str([v for v in comparison if not v['passed']])[:3000])
        case_report={'variant':variant,'passed':True,'freecad_report':common.relative(directory/'freecad-report.json') if fc else None,
            'solidcraft_report':common.relative(directory/'solidcraft-report.json') if sc_report else None,'cross_cad_comparisons':comparison}
        cases.append(case_report);common.write(out/'cases-progress.json',cases);common.verify_pins(pins)
    report={'format':'solidcraftbot.h02-arm-pickup-build/1','revision':revision,'passed':True,'backends':args.backend,'source_files_sha256':pins,
        'analytic_reach_and_motion':analysis,'vendor_preparation':vendor_report,'cases':cases,'limitations':getattr(program,'transfer',program.definition)['limitations'],
        'collision_scope':'Continuous under the recorded allowed-collision matrix; no hardware or formal floating-point certificate'}
    artifacts={common.relative(p):model.robot.digest(p) for p in [*cad.rglob('*.FCStd'),*cad.rglob('*.sc'),*out.rglob('*.json'),*render.glob('*.png')] if p.is_file()}
    report['artifact_sha256']=artifacts;common.verify_pins(pins);common.write(out/'build-report.json',report)
    current=model.ROOT/'cad'/kind;current.mkdir(exist_ok=True);common.write(current/'shared-build-report.json',report)
    print('Both arm pickups passed: '+common.relative(out/'build-report.json'),flush=True)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend',choices=['both','freecad','solidcraft'],default='both');parser.add_argument('--transfer',action='store_true');parser.add_argument('--vendor-cache');parser.add_argument('--no-render',action='store_true')
    tool_paths.add_tool_arguments(parser);args=parser.parse_args(argv)
    required={'both':('freecad_python','solidcraft_cli'),'freecad':('freecad_python',),'solidcraft':('solidcraft_cli',)}[args.backend]
    options=argparse.Namespace(**{n:getattr(args,n) for n in required});tool_paths.resolve_tool_arguments(parser,options,required=required)
    for n in required:setattr(args,n,getattr(options,n))
    return build(args)


if __name__=='__main__':main()
