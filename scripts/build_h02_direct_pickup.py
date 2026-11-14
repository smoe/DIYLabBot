"""Build and continuously audit direct H02 pickup in independent CAD backends."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import types
import h02_direct_pickup as model
import tube_carrier_model as portable
import build_extraction_kit_station as common
import build_tube_carrier as carrier
import tool_paths


def bbox_distance(a,b):
    return math.sqrt(sum(max(0,a['min'][i]-b['max'][i],b['min'][i]-a['max'][i])**2 for i in range(3)))


def commands(spec,p,source):
    provider=types.SimpleNamespace(SOURCE=model.SOURCE,expanded=lambda s,p:source,
        pose=model.pose,samples=lambda s,p:[{'id':'grasp','values_mm':model.pose(s,p)}])
    result=portable.solidcraft_commands(spec,p,provider=provider)
    for c in source['components']:
        if 'instance_translation_mm' in c:
            result.append({'command':'solid.move','params':{'bodies':[b['id'] for b in source['bodies'] if b['component']==c['id']],
                           'translate':c['instance_translation_mm']}})
    hidden=[b['id'] for b in source['bodies'] if b['component']=='Proof' or b['id'].endswith('MouthKeepout')]
    result.append({'command':'browser.visibility','params':{'items':hidden,'visible':False}})
    return result


def audit_sc(cli,path,out,spec,p,pairs,measured):
    by_name={b['name']:b for b in measured['bodies']};commands=[];selected=[];checks=[]
    for item in pairs:
        lower=max(0,bbox_distance(by_name[item['a']]['bbox'],by_name[item['b']]['bbox'])-1e-7)
        if lower>=max(5,item['required_mm']) and not item['intended_pad_contact']:
            checks.append({**item,'distance_lower_bound_mm':lower,'method':'native_world_bbox_separation','passed':True})
        else:
            selected.append(item)
            commands.extend([{'command':'inspect.measure','params':{'items':[{'type':'body','name':item['a']},{'type':'body','name':item['b']}]}},
                             {'command':'inspect.interference','params':{'bodies':[item['a'],item['b']]}}])
    negative_pairs=[('extraction_TubeEnvelope','NegativeMidpathBlocker'),('Selected_ReferenceTube','NegativeMidpathBlocker'),
                    ('NegativeLowFingerPad','Selected_CarrierShell')]
    for a,b in negative_pairs:commands.append({'command':'inspect.interference','params':{'bodies':[a,b]}})
    for sample in model.samples(spec,p):
        for name,value in sample['values_mm'].items():commands.append({'command':'joint.drive','params':{'joint':name,'value':value,'quiet':True}})
        commands.extend([{'command':'joint.solve','params':{}},{'command':'inspect.measure','params':{}}])
    commands.append({'command':'inspect.interference','params':{'bodies':['Selected_ReferenceTube','NegativeMidpathBlocker']}})
    script=out/'audit.commands.json';raw=out/'audit.raw.json';common.write(script,{'commands':commands})
    subprocess.run([cli,'run',str(script),'--in',str(path),'--results','--quiet','--json-out',str(raw)],check=True)
    results=json.loads(raw.read_text());distances=[v for v in results if isinstance(v,dict) and 'distance_mm' in v]
    inspections=[v for v in results if isinstance(v,dict) and 'interferences' in v]
    states=[v for v in results if isinstance(v,dict) and isinstance(v.get('bodies'),list) and v['bodies'] and isinstance(v['bodies'][0],dict) and 'bbox' in v['bodies'][0]]
    if len(distances)!=len(selected) or len(inspections)!=len(selected)+4 or len(states)!=len(model.samples(spec,p)):
        raise AssertionError('Incomplete native SolidCraft audit results')
    def volume(v,a,b):
        if v['checked']!=2 or v['unchecked'] or v['truncated'] or v['budget_exceeded'] or v['pairs_not_checked'] or v['skipped_pairs'] or v['count']!=len(v['interferences']):
            raise AssertionError('Incomplete pair interference inspection')
        if any({h['a'],h['b']}!={a,b} for h in v['interferences']):raise AssertionError('Foreign interference pair')
        return sum(h['volume_mm3'] for h in v['interferences'])
    for item,distance,inspection in zip(selected,distances,inspections):
        if {v['name'] for v in distance['items']}!={item['a'],item['b']}:
            raise AssertionError('Foreign distance pair')
        d=distance['distance_mm'];v=volume(inspection,item['a'],item['b'])
        passed=v<=spec['scene']['volume_tolerance_mm3'] and d+1e-6>=item['required_mm']
        if item['intended_pad_contact']:passed=passed and d<=1e-6
        checks.append({**item,'distance_mm':d,'overlap_mm3':v,'method':'native_exact_distance_and_boolean','passed':passed})
    negative=[volume(v,a,b) for v,(a,b) in zip(inspections[len(selected):],negative_pairs+[negative_pairs[1]])]
    negative_pass=negative[0]>1 and negative[2]>1 and max(negative[1],negative[3])<1e-5
    state_checks=[];source=model.expanded(spec,p);body_components={b['id']:b['component'] for b in source['bodies']}
    for sample,state in zip(model.samples(spec,p),states):
        if {b['name'] for b in state['bodies']}!=set(by_name):
            raise AssertionError('Incomplete native state body set')
        errors=[]
        for b in state['bodies']:
            if b['name'] not in body_components:continue
            component=body_components[b['name']];before=by_name[b['name']]
            a=model.displacement(source,component,model.pose(spec,p));delta=model.displacement(source,component,sample['values_mm'])
            errors.append(max(abs(b['bbox'][edge][i]-before['bbox'][edge][i]-delta[i]+a[i]) for edge in ['min','max'] for i in range(3)))
        state_checks.append({'id':sample['id'],'maximum_position_error_mm':max(errors),'passed':max(errors)<1e-5})
    report={'passed':all(c['passed'] for c in checks+state_checks) and negative_pass,
            'continuous_checks':checks,'negative_midpath_control':{'passed':negative_pass,'volumes_mm3':negative},'native_states':state_checks}
    common.write(out/'solidcraft-audit.json',report)
    return report


def build(args):
    scene=model.load();paths=model.dependencies(scene)+[Path(__file__),model.ROOT/'scripts/build_h02_direct_pickup_freecad.py',
        model.ROOT/'scripts/build_tube_carrier_freecad.py',model.ROOT/'scripts/build_neutral_freecad.py',
        model.ROOT/'scripts/freecad/solidcraftbot_freecad.py',model.ROOT/'scripts/build_extraction_kit_station.py',
        model.ROOT/'scripts/build_tube_carrier.py',model.ROOT/'scripts/build_relative_floorplan.py',
        model.ROOT/'scripts/extraction_kit_station.py',model.ROOT/'scripts/tool_paths.py',
        model.ROOT/'scripts/freecad/persist_station_view.py',model.ROOT/'scripts/freecad/persist_view.py',
        model.ROOT/'model/assembly-reference.schema.json']
    pins={str(p.relative_to(model.ROOT)):model.digest(p) for p in paths};common.verify_pins(pins)
    stem='h02-direct-pickup-'+model.digest(model.SOURCE)[:12];revision=stem;n=1
    while (model.ROOT/'exports/generated'/revision).exists():n+=1;revision=stem+'-r'+str(n)
    out=model.ROOT/'exports/generated'/revision;cad=model.ROOT/'cad/generated'/revision;out.mkdir(parents=True);cad.mkdir(parents=True)
    reports=[]
    for variant in scene['variants']:
        spec=model.context(scene,variant);p=model.parameters(spec);profile=model.motion_profile(spec,p);source,pairs,witnesses=model.proof(spec,p)
        folder=out/variant;folder.mkdir();sc=cad/(variant+'.sc');fc=cad/(variant+'.FCStd');step=folder/'model.step'
        script=folder/'build.commands.json';measurement=folder/'solidcraft.json'
        raw=sc_audit=fcm=None;cross=[];files={};views=[]
        if args.backend in ('both','solidcraft'):
            common.write(script,{'commands':commands(spec,p,source)})
            cmd=[args.solidcraft_cli,'run',str(script),'--save',str(sc),'--json-out',str(measurement),'--quiet']
            if args.backend=='both':cmd+=['--out',str(step)]
            subprocess.run(cmd,check=True)
            raw=json.loads(measurement.read_text());sc_audit=audit_sc(args.solidcraft_cli,sc,folder,spec,p,pairs,raw)
            files.update(solidcraft=sc,solidcraft_audit=folder/'solidcraft-audit.json',solidcraft_measurements=measurement,commands=script,
                         solidcraft_audit_commands=folder/'audit.commands.json',solidcraft_audit_raw=folder/'audit.raw.json')
        if args.backend in ('both','freecad'):
            case={'variant':variant,'pins':pins,'freecad':common.relative(fc),'step':common.relative(step) if args.backend=='both' else None,'freecad_report':common.relative(folder/'freecad.json')}
            common.write(folder/'case.json',case)
            subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_h02_direct_pickup_freecad.py'),str(folder/'case.json')],check=True,
                           env=common.freecad_environment(args.freecad_python))
            fcm=json.loads((folder/'freecad.json').read_text());files.update(freecad=fc,freecad_audit=folder/'freecad.json',case=folder/'case.json')
        if args.backend=='both':cross=carrier.compare(raw,fcm['geometry']);files['step']=step
        passed=(sc_audit is None or sc_audit['passed']) and (fcm is None or fcm['passed']) and all(c['passed'] for c in cross)
        item={'variant':variant,'passed':passed,'bodies':len(source['bodies']),'pair_scopes':len(pairs),'body_comparisons':cross,'motion_profile':profile,
              'maximum_step_xor_mm3':max(c['xor_mm3'] for c in fcm['step_checks']) if args.backend=='both' else None,
              'files':{k:common.relative(v) for k,v in files.items()}}
        item['artifact_sha256']={k:model.digest(model.ROOT/v) for k,v in item['files'].items()};reports.append(item)
        common.write(out/'cases-progress.json',reports)
        if not passed:raise AssertionError('Direct pickup failed: '+variant)
        if args.backend in ('both','solidcraft') and not args.no_render:
            render=model.ROOT/'renders'/revision;render.mkdir(exist_ok=True)
            for state in ['grasp','extracted']:
                drive=[{'command':'joint.drive','params':{'joint':name,'value':value,'quiet':True}} for name,value in model.pose(spec,p,state).items()]
                drive.append({'command':'joint.solve','params':{}})
                view_script=folder/(state+'.view.json');common.write(view_script,{'commands':drive});image=render/(variant+'-'+state+'.png')
                camera={'target':[0,0,65],'yaw':-.7,'pitch':.65,'distance':420,'fov':.6}
                cmd=[args.solidcraft_cli,'snapshot',str(view_script),'--in',str(sc),'--out',str(image),'--width','1500','--height','1200','--camera',json.dumps(camera),'--no-grid','--no-axes','--quality','fine']
                subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
                views.append({'state':state,'image':common.relative(image),'sha256':model.digest(image),'camera':camera,
                              'view_script':common.relative(view_script),'view_script_sha256':model.digest(view_script),'command_line':cmd,'visually_reviewed':False})
        item['views']=views
    common.verify_pins(pins)
    for item in reports:
        for k,path in item['files'].items():
            if model.digest(model.ROOT/path)!=item['artifact_sha256'][k]:raise ValueError('Native artifact changed: '+path)
    report={'format':'solidcraftbot.h02-direct-pickup-build/1','revision':revision,'passed':True,'backends':args.backend,'source_files_sha256':pins,
            'cases':reports,'scope':'Continuous conservative tool/tube swept volumes for approach, closure and full local vertical extraction; no arm IK or hardware qualification',
            'limitations':scene['limitations']}
    common.write(out/'build-report.json',report);folder=model.ROOT/'cad/h02-direct-pickup';folder.mkdir(exist_ok=True);common.write(folder/'shared-build-report.json',report)
    print('Direct pickup passed: '+common.relative(out/'build-report.json'),flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend',choices=['both','freecad','solidcraft'],default='both')
    parser.add_argument('--no-render',action='store_true');tool_paths.add_tool_arguments(parser,freecad=True,solidcraft=True)
    args=parser.parse_args(argv);required={'both':('freecad_python','solidcraft_cli'),'freecad':('freecad_python',),'solidcraft':('solidcraft_cli',)}[args.backend]
    selected=argparse.Namespace(**{name:getattr(args,name) for name in required})
    tool_paths.resolve_tool_arguments(parser,selected,required=required)
    for name in required:setattr(args,name,getattr(selected,name))
    return build(args)


if __name__=='__main__':main()
