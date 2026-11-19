"""Compile a pipetting protocol without device commands or inventory effects."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import pipetting_protocol as protocol
import pipetting_station as station
import labware_transfer as handling


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')


def pins(path):
    spec=station.read(path)
    paths=station.source_paths(station.assembly.validate_reference(spec['setup']))
    paths += [Path(path),*[(station.ROOT/name) for name in ('scripts/pipetting_protocol.py','scripts/pipetting_station.py','scripts/run_pipetting_protocol.py',
        'scripts/tip_supply_model.py','scripts/assembly_model.py','scripts/robot_spec.py','scripts/furniture_model.py','scripts/synthetic_workspace.py',
        'scripts/analytics_concept.py','scripts/tip_collector_model.py','scripts/tube_carrier_model.py','scripts/lab_layout_model.py',
        'scripts/labware_transfer.py','scripts/centrifuge_robot_pickup.py','scripts/rack_slots.py')]]
    return {str(p.resolve().relative_to(station.ROOT)):station.robot.digest(p) for p in sorted(set(paths))}


def build(path=protocol.SOURCE,output_root=None):
    path=Path(path).resolve();before=pins(path)
    is_handling=station.read(path).get('format')=='solidcraftbot.pipetting-transfer-protocol/1'
    if is_handling:
        context=station.compile_setup(station.assembly.validate_reference(station.read(path)['setup']))
        result=handling.plan(context,path)
        result['endpoint_reachability']=handling.endpoint_report(context)
        station.require(result['endpoint_reachability']['passed'],'Handling endpoint reachability failed')
    else:result=protocol.compile_protocol(path)
    require=station.require
    require(pins(path)==before,'Source changed during protocol compilation')
    stamp=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()[:12]
    base=Path(output_root or station.ROOT/'exports/pipetting')/(('handling-' if is_handling else 'plan-')+stamp)
    dest=base;index=1
    while dest.exists():index+=1;dest=base.with_name(base.name+'-r'+str(index))
    dest.mkdir(parents=True)
    result['source_files_sha256']=before
    write(dest/'plan.json',result)
    files=['plan.json']
    if not is_handling:
        with (dest/'well-volumes.csv').open('w',newline='') as stream:
            materials=list(result['component_balance']['initial_ul'])
            writer=csv.writer(stream);writer.writerow(['location','total_ul',*[m+'_ul' for m in materials],'homogeneous_assumed'])
            for name,well in result['final_wells'].items():
                writer.writerow([name,well['total_ul'],*[well['components_ul'].get(m,0) for m in materials],well['homogeneous_assumed']])
        files.append('well-volumes.csv')
    write(dest/'build-report.json',{'passed':True,'scope':result['scope'],'source_files_sha256':before,
        'files':{name:{'path':str(dest/name),'sha256':station.robot.digest(dest/name)} for name in files},
        'transfer_count':len(result['steps'] if is_handling else result['transfers']),
        'tip_usage':result.get('tip_usage'),'hardware_ready':False})
    return dest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','handling-plan'])
    parser.add_argument('--protocol',type=Path)
    parser.add_argument('--output-root',type=Path)
    args=parser.parse_args();dest=build(args.protocol or (handling.PROTOCOL if args.command=='handling-plan' else protocol.SOURCE),args.output_root)
    print('Validated planning projection: '+str(dest))


if __name__=='__main__':main()
