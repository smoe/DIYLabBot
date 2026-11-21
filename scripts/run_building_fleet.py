#!/usr/bin/env python3
"""Compile, independently check, build and serve the opt-in BF01 simulation.

Only existing checked native geometry is consumed; CAD models are never
silently rebuilt. Serving is restricted to the loopback interface.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import building_fleet_model as model
from building_fleet_geometry_checks import GeometryChecks
from building_fleet_routes import Navigation
from building_fleet_runner import compile_program, prepare_program
from build_extraction_kit_station import freecad_environment
from export_building_fleet_vehicle_freecad import checked_camera_report
import export_building_walkthrough_freecad as native
import tool_paths


def project_path(value, *, output=False):
    path=(model.ROOT/Path(value)).resolve()
    if not path.is_relative_to(model.ROOT):raise ValueError('Project-local BF01 path required')
    if output and not path.is_relative_to((model.ROOT/'exports/building-fleet').resolve()):
        raise ValueError('BF01 output must stay in the ignored fleet export tree')
    return path


def artifact(path):
    path=project_path(path)
    if not path.is_file():raise ValueError('Missing BF01 artifact: '+str(path))
    return {'path':str(path.relative_to(model.ROOT)),'sha256':model.digest(path)}


def write(path, value):
    path=project_path(path,output=True)
    if path.exists():raise FileExistsError('Evidence is immutable: '+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def navigation(source,args):
    export=project_path(args.walkthrough_export)
    if args.navigation_cache:return Navigation.from_cache(source,export,project_path(args.navigation_cache))
    return Navigation(source,export)


def generator_pins():
    names=('building_fleet_checks.py','building_fleet_geometry_checks.py','building_fleet_depot.py','building_fleet_zones.py',
           'building_fleet_runner.py','building_fleet_missions.py','building_fleet_resources.py',
           'building_fleet_motion.py','building_fleet_control.py','building_fleet_services.py',
           'building_fleet_dispatch.py','building_fleet_comm.py','building_fleet_sim.py',
           'building_fleet_lift_checks.py','building_fleet_lift_geometry.py',
           'building_fleet_support.py','building_fleet_floor.py','building_fleet_clearance.py',
           'check_building_fleet_freecad.py','run_building_fleet.py')
    return {'scripts/'+name:model.digest(model.ROOT/'scripts'/name)for name in names}


def runtime_records(program, directory):
    """Write the received journal and derive bounded per-vehicle distances."""
    from building_fleet_motion import interval_extrema
    import tr01_floor_motion as floor
    directory=project_path(directory,output=True)
    journal=directory/'received-telemetry.jsonl'
    with journal.open('x',encoding='utf-8',newline='\n')as stream:
        for message in program['received_messages']:
            stream.write(json.dumps(message,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n')
    vehicles=[]
    for row in program['trajectories']:
        lower=upper=0.;holds={}
        for episode in row['episodes']:
            if episode['mode']!='driving':
                reason=episode['hold_reason'];holds[reason]=holds.get(reason,0.)+episode['end_s']-episode['start_s']
                continue
            curve=floor.motion.Curve(floor.canonical(episode['points']))
            for a,b in zip(curve.points,curve.points[1:]):
                lower=max(0.,math.nextafter(lower+math.dist(a[floor.F[0]][:2],b[floor.F[0]][:2]),-math.inf))
                bound=interval_extrema(curve,a['time_s'],b['time_s'],1)
                speed=math.hypot(*(max(abs(bound[k][i])for k in('min','max'))for i in range(2)))
                upper=math.nextafter(upper+math.nextafter(speed,math.inf)*(b['time_s']-a['time_s']),math.inf)
        messages=[m for m in program['received_messages']if m['vehicle_id']==row['vehicle_id']and m['kind']=='event']
        missions={m['payload']['details']['mission_id']for m in messages
            if m['payload']['event']=='mission_assigned'and m['payload']['details'].get('acknowledged')is True}
        vehicles.append({'vehicle_id':row['vehicle_id'],'distance_lower_mm':lower,'distance_upper_mm':upper,
            'received_acknowledged_missions':len(missions),'hold_duration_by_reason_s':holds,
            'actual_inspections':sum(w['vehicle_id']==row['vehicle_id']for w in program['inspection_witnesses'])})
    return {'received_journal':artifact(journal),'vehicles':vehicles,
            'distance_method':'Sum of actual polynomial endpoint chords (lower) and per-interval analytic velocity bounds times duration (upper); cabin vertical travel reported separately by the lift service'}


def independent_check(program_path,source,nav,catalog,native_proof,output):
    from building_fleet_checks import check_program
    geometry=GeometryChecks(source,nav)
    def callback(program,config,navigation_,trajectories,lift):
        return geometry.exported(program,config,navigation_,trajectories,lift,native_report=native_proof,
                                 program_reference=artifact(program_path))
    return check_program(program_path,source,nav,resource_catalog=catalog,geometry_check=callback,output=output)


def compile_fleet(args):
    source=model.load();started=time.monotonic();out=project_path(args.output_dir,output=True)
    if out.exists():raise FileExistsError('Use a fresh BF01 evidence directory: '+str(out))
    camera=project_path(args.camera_report);checked_camera_report(camera)
    pins={**model.source_pins(source),**model.protected_pins(),**generator_pins()}
    out.mkdir(parents=True)
    try:
        nav=navigation(source,args);pins.update(nav._cache_pins())
        progress=lambda row:print(json.dumps(row,ensure_ascii=False),flush=True)
        cache=project_path(args.resource_cache,output=True)if args.resource_cache else out/'resource-catalog-cache'
        prepared=prepare_program(source,nav,progress=progress,resource_cache=cache);preparation_elapsed=time.monotonic()-started
        runtime_started=time.monotonic()
        program=compile_program(source,nav,out,prepared=prepared,progress=progress,
                                geometry_checker=GeometryChecks(source,nav),artifacts={
                                    'walkthrough_report':artifact(nav.mesh.export/'build-report.json'),
                                    'camera_report':artifact(camera)})
        runtime_elapsed=time.monotonic()-runtime_started;native.verify_pins(pins)
        program['source_files_sha256'].update(pins)
        program['artifacts']={'walkthrough_report':artifact(nav.mesh.export/'build-report.json'),
                              'camera_report':artifact(camera)}
        path=out/'program.json';write(path,program);records=runtime_records(program,out)
        python=args.freecad_python or tool_paths.default_freecad_python()
        if not python:raise ValueError('Installed FreeCAD Python required for the complete native audit; use --freecad-python')
        proof=out/'native-check.json'
        native_started=time.monotonic()
        subprocess.run([str(python),str(model.ROOT/'scripts/check_building_fleet_freecad.py'),str(path),'--out',str(proof)],
            cwd=model.ROOT,env=freecad_environment(python),check=True)
        native_elapsed=time.monotonic()-native_started;export_started=time.monotonic()
        checked=independent_check(path,source,nav,prepared[1],proof,out/'export-check.json')
        elapsed=time.monotonic()-started
        report={'format':'solidcraftbot.building-fleet-report/1','passed':checked['passed'],
            'program':artifact(path),'export_check':artifact(out/'export-check.json'),'native_check':artifact(proof),
            'source_files_sha256':pins,'seed':program['seed'],'model_time_s':program['duration_s'],
            'playback_factor':1,'elapsed_s':elapsed,'runtime_budget_target_s':600,'runtime_budget_met':runtime_elapsed<=600,
            'phase_elapsed_s':{'preparation':preparation_elapsed,'simulation':runtime_elapsed,
                               'native':native_elapsed,'independent_export':time.monotonic()-export_started},
            'program_bytes':path.stat().st_size,'statistics':program['statistics'],
            'runtime_records':records,
            'qualification':source['qualification'],'native_full_program_checked':True,'browser_checked':False,
            'limitations':source['limitations']}
        write(out/'fleet-report.json',report)
        if not checked['passed']:raise RuntimeError('Independent programme check failed; see export-check.json')
        return report
    except Exception as exc:
        write(out/'compile-failure.json',{'format':'solidcraftbot.building-fleet-compile-failure/1',
            'passed':False,'seed':source['missions']['seed'],'error':str(exc),'exception':type(exc).__name__,
            'source_files_sha256':pins,'elapsed_s':time.monotonic()-started,'complete_fleet_qualified':False})
        raise


def check_fleet(args):
    source=model.load();nav=navigation(source,args)
    prepared=prepare_program(source,nav,resource_cache=project_path(args.resource_cache,output=True)if args.resource_cache else None)
    return independent_check(project_path(args.program),source,nav,prepared[1],
                             project_path(args.native_proof),project_path(args.out,output=True))


def serve(directory):
    with ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(project_path(directory))))as server:
        print('http://127.0.0.1:'+str(server.server_port)+'/index.html',flush=True)
        server.serve_forever()


def parser():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    def nav_options(item):
        item.add_argument('--walkthrough-export',required=True)
        item.add_argument('--navigation-cache',help='Current source-pinned static cache; stale data fails closed')
        item.add_argument('--resource-cache',help='Optional source/route-bound static alias cache; stale data fails closed')
    compile_=sub.add_parser('compile');nav_options(compile_)
    compile_.add_argument('--camera-report',required=True);compile_.add_argument('--output-dir',required=True)
    tool_paths.add_tool_arguments(compile_,solidcraft=False)
    check=sub.add_parser('check');nav_options(check);check.add_argument('program')
    check.add_argument('--native-proof',required=True);check.add_argument('--out',required=True)
    build=sub.add_parser('build');build.add_argument('program');build.add_argument('--native-proof',required=True)
    build.add_argument('--export-check',required=True);build.add_argument('--vehicle-mesh',required=True)
    build.add_argument('--output-dir',required=True);build.add_argument('--serve',action='store_true')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    if args.command=='compile':result=compile_fleet(args)
    elif args.command=='check':result=check_fleet(args)
    else:
        from build_building_fleet_demo import build
        result=build(args.program,args.native_proof,args.vehicle_mesh,args.output_dir,export_check_report=args.export_check)
        if args.serve:serve(args.output_dir)
    print(json.dumps({'passed':result['passed'],'command':args.command},ensure_ascii=False))
    return 0 if result['passed']else 1


if __name__=='__main__':raise SystemExit(main())
