"""Compile, export and certify TR01 floor routes against the checked L01 CAD."""
import argparse
import json
from pathlib import Path
import subprocess
import time

import tool_paths
import tr01_floor_motion as model
from build_extraction_kit_station import write,relative,freecad_environment,measurements,compare


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['freecad','both'],default='both')
    tool_paths.add_tool_arguments(parser)
    args=parser.parse_args();tool_paths.resolve_tool_arguments(parser,args,required={'freecad_python','solidcraft_cli'} if args.backend=='both' else {'freecad_python'})
    s=model.load();revision='tr01-l01-'+model.robot.digest(model.SOURCE)[:12]+'-'+str(time.time_ns())
    cad=model.ROOT/'cad/generated'/revision;out=model.ROOT/'exports/generated'/revision
    cad.mkdir(parents=True);out.mkdir(parents=True)
    context={'vehicle_file':str(cad/'TR01_Loaded.FCStd'),'inspection_file':str(cad/'L01_ParkingInspection.FCStd'),
             'program':str(out/'program.json'),'validation':str(out/'native-clearance.json')}
    write(out/'context.json',context)
    subprocess.run([args.freecad_python,str(model.ROOT/'scripts/check_tr01_floor_motion.py'),str(out/'context.json')],
                   env=freecad_environment(args.freecad_python),check=True)
    program=json.loads(Path(context['program']).read_text());validation=json.loads(Path(context['validation']).read_text())
    cross=[]
    if args.backend=='both':
        spec,p,variant=model.vehicle_source(s,model.layout.load(validate_builds=False))
        commands=out/'vehicle.commands.json';sc=cad/'TR01_Loaded.sc';raw=out/'vehicle.solidcraft.json'
        write(commands,{'commands':model.vehicle.solidcraft_commands(spec,p,variant)})
        subprocess.run([args.solidcraft_cli,'run',str(commands),'--save',str(sc),'--json-out',str(raw),'--quiet'],check=True)
        measured=measurements(json.loads(raw.read_text()),model.vehicle.expanded(spec,p,variant),backend='solidcraft')
        cross=compare(measured,validation['vehicle_geometry'])
        if not all(c['passed'] for c in cross):raise ValueError('Loaded TR01 cross-CAD mismatch')
        context.update(solidcraft_vehicle=str(sc),solidcraft_measurements=str(raw),solidcraft_commands=str(commands))
        poses=[]
        for route in program['routes']:
            x,y,yaw=route['points'][0]['pose_mm_rad'];c=model.math.cos(yaw);q=model.math.sin(yaw)
            command={'command':'occurrence.move','params':{'occurrence':'TR01Travel:1','move_grounded':True,
                         'matrix':[[c,-q,0,x],[q,c,0,y],[0,0,1,0],[0,0,0,1]]}}
            path=out/(route['from']+'.park.commands.json');write(path,{'commands':[
                {'command':'component.insert_design','params':{'path':str(sc),'name':'TR01Travel'}},command]})
            receipt=out/(route['from']+'.park.solidcraft.json')
            before=model.robot.digest(sc)
            subprocess.run([args.solidcraft_cli,'run',str(path),'--json-out',str(receipt),'--quiet'],check=True,timeout=120)
            if model.robot.digest(sc)!=before:raise ValueError('Parking check changed the source vehicle')
            moved={b['body']:b for b in measurements(json.loads(receipt.read_text()),model.vehicle.expanded(spec,p,variant),backend='solidcraft')}
            pose_checks=[]
            for body in measured:
                actual=moved[body['body']]
                expected=model.robot.transform(command['params']['matrix'],body['world_center_of_mass_mm'])
                error=model.math.dist(actual['world_center_of_mass_mm'],expected)
                volume_error=abs(actual['volume_mm3']-body['volume_mm3'])/body['volume_mm3']
                pose_checks.append({'body':body['body'],'center_error_mm':error,'relative_volume_error':volume_error,
                                    'passed':error<.01 and volume_error<.001})
            if not all(c['passed'] for c in pose_checks):raise ValueError('Native SolidCraft parking pose mismatch')
            poses.append({'station':route['from'],'pose_mm_rad':[x,y,yaw],'commands':relative(path),'checks':pose_checks})
            context['park_'+route['from']]=str(path)
            context['park_'+route['from']+'_validation']=str(receipt)
        write(out/'parking-poses.json',poses);context['parking_poses']=str(out/'parking-poses.json')
    # Re-read exported bytes: bounds and no-stop checks run on the payload a
    # downstream player actually consumes, including quantized timestamps.
    for route in program['routes']:
        curve=model.motion.Curve(model.canonical(route['points']))
        actual=model.dynamics(curve,route['dynamics']['radius_mm'])
        if actual!=route['dynamics'] or not model.no_stop(curve)['passed']:raise ValueError('Export round-trip failed')
    model.verify(program['source_files_sha256'])
    files={k:relative(v) for k,v in context.items()}
    report={'format':'solidcraftbot.tr01-l01-build/1','passed':validation['passed'],'revision':revision,
            'source_files_sha256':program['source_files_sha256'],'files':files,
            'artifact_sha256':{key:model.robot.digest(Path(value)) for key,value in context.items()},
            'routes':[{'id':r['id'],'duration_s':r['duration_s'],'dynamics':r['dynamics'],'no_stop':r['no_stop']} for r in program['routes']],
            'collision_validation':validation,'export_round_trip_passed':True,
            'backends':args.backend,'loaded_vehicle_cross_cad':cross,
            'limitations':s['limitations']}
    write(out/'build-report.json',report);(model.ROOT/'cad/tr01-l01').mkdir(exist_ok=True)
    write(model.ROOT/'cad/tr01-l01/shared-build-report.json',report)
    print(relative(out/'build-report.json'),flush=True)


if __name__=='__main__':main()
