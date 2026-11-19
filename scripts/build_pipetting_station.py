"""Build the PS01 static station independently in FreeCAD and/or SolidCraft."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pipetting_station as model
import pipetting_protocol as protocol
import run_pipetting_protocol as planning
import solidcraft_vendor as vendor
import tip_collector_model as collector
import tool_paths
import labware_transfer as handling


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')


def source_pins():
    pins=planning.pins(protocol.SOURCE)
    paths=[model.ROOT/'scripts'/name for name in (
        'build_pipetting_station.py','build_pipetting_station_freecad.py','build_neutral_freecad.py',
        'build_tip_collector_freecad.py','build_synthetic_lab_scene_freecad.py','robot_components.py',
        'robot_cameras.py','solidcraft_vendor.py','synthetic_lab_scene.py','tool_paths.py','build_instrument_concepts.py',
        'freecad/solidcraftbot_freecad.py','freecad/persist_station_view.py','freecad/persist_view.py')]
    paths.extend((model.ROOT/'cad/vendor/myactuator').rglob('*.json'))
    paths.extend((model.ROOT/'cad/vendor/myactuator').rglob('*.step'))
    paths.extend(model.ROOT/'model'/name for name in ('tip-collector-t01-markings.json','x6-mounting-interface.json','x4-mounting-interface.json','x2-mounting-interface.json'))
    for path in paths:
        if path.is_file():pins[str(path.relative_to(model.ROOT))]=model.robot.digest(path)
    pins[str(handling.PROTOCOL.relative_to(model.ROOT))]=model.robot.digest(handling.PROTOCOL)
    return pins


def verify_pins(pins):
    for name,digest in pins.items():
        model.require(model.robot.digest(model.assembly.project_path(name))==digest,'Native build source changed: '+name)


def groups(context,plan):
    """The same static construction and forecast liquid marks feed both adapters."""
    result=copy.deepcopy(context['groups'])
    colors={'A':(51,135,220),'B':(231,153,38),'Buffer':(181,211,215)}
    for identity,definition in context['labware'].items():
        parts=[]
        for key,well in definition['wells'].items():
            forecast=plan['final_wells'][identity+'.'+key];volume=forecast['total_ul']
            if not volume:continue
            z=well['bottom_mm'][2];height=volume/well['cross_section_mm2']
            cavity=well['cavity']
            shape=(model.cylinder(well['bottom_mm'],cavity['radius'],height) if cavity['kind']=='cylinder'
                   else model.box(cavity['origin'],cavity['size'][:2]+[height]))
            rgb=[round(sum(colors.get(name,(150,180,190))[channel]*amount for name,amount in forecast['components_ul'].items())/volume) for channel in range(3)]
            parts.append(model.part('Forecast_'+key,shape,'#'+''.join('%02x'%v for v in rgb),role='ideal_planned_liquid_not_an_observation'))
        if parts:result.append({'id':identity+'Forecast','parts':parts,'matrix':definition['matrix']})
    return result


def solidcraft_build(context,plan,cli,dest):
    replacements,vendor_report=vendor.prepare(context['arm'],cli,dest/'vendor')
    commands,manifest=[],[]
    for identity,entry in context['arms'].items():
        item=context['spatial']['devices'][identity]
        extra,mapping=model.tools.arm_commands(item,entry['state'],replacements)
        commands.extend(extra);manifest.extend(mapping)
    for group in groups(context,plan):
        extra,mapping=model.tools.primitive_commands(group['id'],group['parts'],group['matrix'])
        commands.extend(extra);manifest.extend(mapping)
    item=context['spatial']['devices']['PS01Waste'];spec=collector.load(model.assembly.validate_reference(item['source']));p=collector.parameters(spec)
    expanded=collector.expanded(spec,p)
    extra,mapping=model.tools.namespace(collector.solidcraft_commands(spec,p),item['id'],spec['parameters'],[b['id'] for b in expanded['bodies']]+[c['id'] for c in expanded['components']])
    commands.extend(extra)
    for component in expanded['components']:
        commands.append({'command':'occurrence.move','params':{'occurrence':mapping[component['id']]+':1','matrix':item['matrix'],'space':'world','move_grounded':True}})
    manifest.extend({'instance':item['id'],'source_body':b['id'],'names':[mapping[b['id']]]} for b in expanded['bodies'])
    commands.append({'command':'document.metadata.set','params':{'values':{'org.solidcraftbot.pipetting-station':{
        'source':'model/pipetting-station-ps01.shared.json','setup':'model/pipetting-station-ps01.setup.json',
        'scope':'Static two-arm station with carriers, unmeasured box envelopes and ideal forecast liquid volumes; no executed pipetting or labware-transfer path'}}}})
    output=dest/'PS01.solidcraft'
    measured=vendor.run(cli,commands,dest/'solidcraft.commands.json',dest/'solidcraft-measurements.json',save=output)
    actual={b['name']:b for b in measured['bodies']}
    expected={name for item in manifest for name in item['names']}
    model.require(len(actual)==len(measured['bodies']) and set(actual)==expected,'SolidCraft scene body identities differ')
    model.require(all(b['closed'] and b['volume_mm3']>0 for b in actual.values()),'Invalid SolidCraft body')
    report={'passed':True,'file':str(output),'body_count':len(actual),'manifest':manifest,
            'measurements':measured,'vendor_report':vendor_report,'freecad_construction_dependency':False}
    write(dest/'solidcraft-report.json',report)
    for name,camera in [('overview',{'target':[0,0,220],'yaw':-.7,'pitch':.85,'distance':2000})]:
        with (dest/(name+'.log')).open('w') as log:
            subprocess.run([cli,'snapshot','--in',str(output),'--out',str(dest/(name+'.png')),
                '--width','1700','--height','1100','--camera',json.dumps(camera),'--no-grid','--no-axes','--quality','fine'],
                check=True,cwd=model.ROOT,stdout=log,stderr=subprocess.STDOUT)
    return report


def compare(solid,native):
    actual={b['name']:b for b in solid['measurements']['bodies']};checks=[]
    for record in solid['manifest']:
        name=record['instance']+'.'+record['source_body'];ref=native['bodies'][name]
        measured=model.tools.scene_model.instance_metrics([actual[k] for k in record['names']])
        volume=abs(measured['volume_mm3']-ref['volume_mm3'])/ref['volume_mm3']
        center=model.math.dist(measured['center_of_mass_mm'],ref['center_of_mass_mm'])
        bbox=max(abs(measured['bbox'][edge][i]-ref['bbox'][edge][i]) for edge in ('min','max') for i in range(3))
        checks.append({'body':name,'relative_volume_error':volume,'center_error_mm':center,'bbox_error_mm':bbox,
                       'passed':volume<.001 and center<.02 and bbox<.02})
    model.require({r['instance']+'.'+r['source_body'] for r in solid['manifest']}==set(native['bodies']),'Cross-CAD semantic body mismatch')
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['freecad','solidcraft','both'],default='both')
    parser.add_argument('--output-root',type=Path,default=model.ROOT/'exports/pipetting-cad')
    tool_paths.add_tool_arguments(parser)
    args=parser.parse_args()
    tool_paths.resolve_tool_arguments(parser,args,required={'freecad_python','solidcraft_cli'} if args.backend=='both' else {args.backend+'_python' if args.backend=='freecad' else 'solidcraft_cli'})
    pins=source_pins();context=model.compile_setup();plan=protocol.compile_protocol(context=context)
    stamp=hashlib.sha256(json.dumps(pins,sort_keys=True).encode()).hexdigest()[:12]
    base=args.output_root/('ps01-'+stamp);dest=base;i=1
    while dest.exists():i+=1;dest=base.with_name(base.name+'-r'+str(i))
    dest.mkdir(parents=True)
    reach=handling.endpoint_report(context)
    transfer=handling.plan(context)
    model.require(reach['passed'],'Handling-arm endpoint IK failed')
    write(dest/'build-context.json',{'source_files_sha256':pins,'plan':plan,'handling_endpoints':reach,'handling_plan':transfer})
    native=solid=None
    if args.backend in ('freecad','both'):
        from build_instrument_concepts import freecad_environment
        with (dest/'freecad.log').open('w') as log:
            subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_pipetting_station_freecad.py'),str(dest.resolve())],
                check=True,cwd=model.ROOT,env=freecad_environment(args.freecad_python),stdout=log,stderr=subprocess.STDOUT)
        native=model.read(dest/'freecad-report.json')
    if args.backend in ('solidcraft','both'):
        solid=solidcraft_build(context,plan,args.solidcraft_cli,dest)
    comparisons=compare(solid,native) if native and solid else []
    verify_pins(pins)
    passed=all(c['passed'] for c in comparisons) and all(r['passed'] for r in (native,solid) if r is not None)
    files={p.name:{'path':str(p.resolve()),'sha256':model.robot.digest(p)} for p in dest.iterdir() if p.suffix in {'.FCStd','.solidcraft','.png'} or p.name in {'freecad-report.json','solidcraft-report.json','build-context.json'}}
    report={'format':'solidcraftbot.pipetting-station-build/1','passed':passed,'source_files_sha256':pins,'backend':args.backend,
        'cross_cad_performed':bool(native and solid),'cross_cad_comparisons':comparisons,'files':files,
        'cross_cad_tolerances':{'relative_volume':.001,'center_mm':.02,'exact_bbox_mm':.02},
        'handling_endpoints':reach,'handling_plan':transfer,'handling_interface':handling.grip_interface_report(context['handling']['source']),
        'tip_box_geometry':'unmeasured planning envelopes only; no vendor box profiles or physical tips',
        'tip_boxes_and_tips_modeled':False,'qualification':context['station']['qualifications'],
        'scope':'Independent static CAD construction and parked-pose checks; liquid shapes are ideal protocol forecasts. No pipetting trajectory or physical execution validation.'}
    write(dest/'build-report.json',report)
    print(json.dumps({'passed':passed,'report':str(dest/'build-report.json'),'compared_bodies':len(comparisons)}),flush=True)
    model.require(passed,'PS01 native checks failed; inspect the report')


if __name__=='__main__':main()
