"""Reproducible CF01 shared-source build, dual-CAD comparisons and renderings."""
import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import centrifuge_model as model
from centrifuge_control import request_schema,demo


def compare(actual,expected,step_geometry):
    refs={b['body']:b for b in expected}; bodies=actual['bodies']
    exact={b['body']:b for b in step_geometry}
    if set(refs)!={b['name'] for b in bodies}: raise AssertionError('CAD body identity mismatch')
    result=[]
    for b in bodies:
        ref=refs[b['name']]; v=abs(b['volume_mm3']-ref['volume_mm3'])/ref['volume_mm3']
        com=math.dist(b['center_of_mass'],ref['world_center_of_mass_mm'])
        # Display meshes can overshoot trimmed curved faces. Use exact exported
        # STEP extents and OCC optimal bounds, not conservative untrimmed bounds.
        bb=max(abs(x-y) for k in ['min','max'] for x,y in zip(exact[b['name']]['bbox'][k],ref['bbox'][k]))
        display_bb=max(abs(x-y) for k in ['min','max'] for x,y in zip(b['bbox'][k],ref['bbox'][k]))
        step_volume=abs(exact[b['name']]['volume_mm3']-ref['volume_mm3'])/ref['volume_mm3']
        step_com=math.dist(exact[b['name']]['center_of_mass'],ref['world_center_of_mass_mm'])
        result.append({'body':b['name'],'relative_volume_error':v,'com_error_mm':com,'bbox_error_mm':bb,
                       'display_bbox_error_mm':display_bb,'step_relative_volume_error':step_volume,'step_com_error_mm':step_com,
                       'passed':b['closed'] and exact[b['name']]['valid'] and exact[b['name']]['closed'] and ref['valid'] and ref['solid_count']==1 and max(v,step_volume)<0.001 and max(com,step_com)<0.01 and bb<0.01})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--solidcraft-cli',default=shutil.which('solidcraft-cli') or 'solidcraft-cli')
    parser.add_argument('--freecad-python',default=str(Path.home()/'AppData/Local/Programs/FreeCAD 27.1/bin/python.exe'))
    parser.add_argument('--finish-existing',action='store_true',help='Finish renders/reports for the last fully checked build, verifying its source, commands and artifact hashes')
    args=parser.parse_args(); started=time.monotonic(); spec=model.load()
    context=json.loads((model.ROOT/'tmp/cf01-context.json').read_text(encoding='utf-8')) if args.finish_existing else model.prepare()
    if context['source_sha256']!=model.digest(model.SOURCE): raise ValueError('Build source changed; regenerate both CADs')
    cad,out=Path(context['cad']),Path(context['out']); reports=[]
    cases=[('default',{}),('mechanism_variant',{'bottom_radius':84,'mouth_clearance':8,'lid_clearance':8,'lift_travel':18,
            'base_width':420,'base_height':160,'chamber_wall':26,'chamber_floor':16,'lid_thickness':24,'encoder_gap':1.5,'power_cable_bend':55,
            'brake_disc_radius':32,'brake_clearance':2,'latch_travel':24})]
    if args.finish_existing:
        reports=json.loads((out/'cases-progress.json').read_text(encoding='utf-8'))
        if [c['id'] for c in reports]!=[c[0] for c in cases] or not all(c['passed'] for c in reports): raise ValueError('Both checked CAD cases required')
        for case in reports:
            expected=model.solidcraft_commands(spec,model.parameters(spec,case['overrides']))
            if expected!=json.loads((model.ROOT/case['files']['commands']).read_text(encoding='utf-8'))['commands']: raise ValueError('Geometry recipe changed')
            for kind,sha in case['artifact_sha256'].items():
                if model.digest(model.ROOT/case['files'][kind])!=sha: raise ValueError('Checked artifact changed: '+kind)
        cases=[]
    for name,overrides in cases:
        p=model.parameters(spec,overrides); prefix=cad/(spec['id'] if name=='default' else spec['id']+'_'+name)
        sc,fc=prefix.with_suffix('.sc'),prefix.with_suffix('.FCStd'); commands=out/(name+'.commands.json')
        measured=out/(name+'.solidcraft.json'); validation=out/(name+'.freecad.json'); step=out/(name+'.step')
        model.write(commands,{'source_sha256':model.digest(model.SOURCE),'commands':model.solidcraft_commands(spec,p)})
        print('Building CF01 '+name,flush=True)
        subprocess.run([args.solidcraft_cli,'run',str(commands),'--save',str(sc),'--out',str(step),'--json-out',str(measured),'--quiet'],check=True,cwd=model.ROOT)
        subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_centrifuge_freecad.py'),str(fc),str(validation),json.dumps(overrides),str(step)],check=True,cwd=model.ROOT)
        sm=json.loads(measured.read_text(encoding='utf-8')); fm=json.loads(validation.read_text(encoding='utf-8'))
        checks=compare(sm,fm['geometry'],fm['solidcraft_step_geometry']); good=fm['passed'] and all(c['passed'] for c in checks)
        files={'solidcraft':sc,'freecad':fc,'step':step,'commands':commands,'solidcraft_measurements':measured,'freecad_validation':validation}
        reports.append({'id':name,'overrides':overrides,'passed':good,'body_count':len(checks),'body_comparisons':checks,
                        'pose_samples':len(fm['motion_samples']),'files':{k:str(v.relative_to(model.ROOT)).replace('\\','/') for k,v in files.items()},
                        'service_geometry_checks':fm['service_geometry_checks'],
                        'artifact_sha256':{k:model.digest(v) for k,v in files.items()}})
        model.write(out/'cases-progress.json',reports)
        if not good: raise AssertionError('CF01 comparison failed: '+name)
        print('Passed '+name+': '+str(len(checks))+' bodies; '+str(len(fm['motion_samples']))+' sampled poses',flush=True)
    default=cad/(spec['id']+'.sc'); render=model.ROOT/'renders'/context['revision']; render.mkdir(parents=True,exist_ok=args.finish_existing)
    source=model.expanded(spec,model.parameters(spec)); keep={'MotorStator','MotorRotor','MotorMount','MotorBearingLower','MotorBearingUpper','SpindleShaft','SpindleBearingHousing',
        'EncoderTargetRing','RotationSensor','EncoderBracket','EncoderSignalCable','ParkingBrakeDisc','ParkingCaliper','CaliperSupport','CaliperActuator','BrakePadUpper','BrakePadLower','MotorTerminalBox','MotorPowerLead','SpindleDrive','BrakingResistor'}
    service_view=out/'drive-detail.commands.json'
    model.write(service_view,{'commands':[{'command':'browser.visibility','params':{'items':[b['id'] for b in source['bodies'] if b['id'] not in keep],'visible':False}},
        {'command':'browser.visibility','params':{'folder':'sketches','visible':False}}]})
    lid_view=out/'lid-detail.commands.json'
    model.write(lid_view,{'commands':[{'command':'browser.visibility','params':{'items':[b['id'] for b in source['bodies'] if not(b['component']=='LidGroup' or b['id'].startswith(('Hinge','LidGearbox','LidMotor','LidHoldingBrake','LidDriveSupport','LidLock')))],'visible':False}},
        {'command':'browser.visibility','params':{'folder':'sketches','visible':False}}]})
    def snapshot(view):
        if args.finish_existing and (render/(view+'.png')).exists(): return
        command=[args.solidcraft_cli,'snapshot']
        if view=='drive-detail': command.append(str(service_view))
        if view=='lid-detail': command.append(str(lid_view))
        command.extend(['--in',str(default),'--out',str(render/(view+'.png')),'--width','1400','--height','1100','--no-grid','--no-axes'])
        if view=='drive-detail': command.extend(['--camera',json.dumps({'target':[0,0,95],'yaw':-0.8,'pitch':0.35,'distance':390})])
        elif view=='lid-detail': command.extend(['--view','iso'])
        else: command.extend(['--view',view])
        subprocess.run(command,check=True,cwd=model.ROOT)
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(snapshot,['iso','top','drive-detail','lid-detail']))
    interface=model.ROOT/'interfaces/centrifuge-cf01'; model.write(interface/'request.schema.json',request_schema()); model.write(out/'mock-demo.json',demo())
    p=model.parameters(spec); interfaces={'units':spec['units'],'frames':model.service_frames(spec,p),'power':spec['services']['power'],
        'rotation':spec['services']['rotation'],'encoder_requirements':model.encoder_requirements(spec,p),'qualification':'not_performed'}
    model.write(out/'service-interfaces.json',interfaces)
    model.write(out/'mechanism-interfaces.json',{'source_sha256':model.digest(model.SOURCE),'mechanisms':spec['mechanisms'],
        'requirements':model.mechanisms.requirements(spec,p),'joints':source['joints'],'poses':model.samples(spec,p),'hardware_qualified':False})
    fc_geometry=json.loads((out/'default.freecad.json').read_text(encoding='utf-8'))['geometry']
    steel={b['id'] for b in source['bodies'] if b['material_family']=='steel'}; density=spec['structure']['density_assumption_kg_m3']
    estimates={b['body']:b['volume_mm3']*density/1e9 for b in fc_geometry if b['body'] in steel}
    files=['model/centrifuge-cf01.shared.json','model/centrifuge-cf01.protocol.json','scripts/centrifuge_protocol.py','scripts/centrifuge_model.py','scripts/build_centrifuge.py','scripts/build_centrifuge_freecad.py',
           'scripts/centrifuge_control.py','scripts/centrifuge_mechanisms.py','scripts/robot_spec.py','scripts/freecad/solidcraftbot_freecad.py','scripts/freecad/persist_station_view.py',
           'scripts/freecad/persist_view.py','tests/test_centrifuge.py','interfaces/centrifuge-cf01/request.schema.json']
    result={'format':'solidcraftbot.centrifuge-build/1',**context,'source':'model/centrifuge-cf01.shared.json',
            'source_files_sha256':{f:model.digest(model.ROOT/f) for f in files},'passed':all(r['passed'] for r in reports),'cases':reports,
            'finished_existing_checked_build':args.finish_existing,
            'target_rcf_x_g':spec['rotor']['target_rcf_x_g'],'target_rpm_at_default_bottom_radius':model.rpm_for_rcf(16000,model.parameters(spec)['bottom_radius']),
            'renders':{v:str((render/(v+'.png')).relative_to(model.ROOT)).replace('\\','/') for v in ['iso','top','drive-detail','lid-detail']},
            'mechanisms_file':str((out/'mechanism-interfaces.json').relative_to(model.ROOT)).replace('\\','/'),
            'services_file':str((out/'service-interfaces.json').relative_to(model.ROOT)).replace('\\','/'),
            'steel_layout_estimates':{'density_assumption_kg_m3':density,'body_mass_kg':estimates,'total_represented_steel_kg':sum(estimates.values()),
                'lid_static_gravity_torque_closed_nm':estimates['CommandLid']*9.80665*model.service_frames(spec,p)['hinge'][1]/1000,
                'scope':'Nominal CAD bulk steel only; grade, mass, support, actuator and structural performance unverified'},
            'elapsed_s':time.monotonic()-started,'limitations':spec['limitations']+[
                'Both CADs use evaluated source dimensions; geometry changes require regeneration. FreeCAD motion coordinates remain editable.',
                'Comparison uses volume, center and exact STEP bounding boxes, not full STEP symmetric difference; mesh extent errors are reported separately.',
                '44 discrete poses per case; no continuous swept-volume, complete robot path or dynamic validation.',
                'Only pocket 01 has an explicit lifted tube in CAD; all 12 index positions and the single fixed ejector are represented.',
                'Pairwise mock mass balance is a draft restriction, not a validated dynamic balancing algorithm.',
                'Lid/index setpoints are idealized; synthetic stopping takes 5 s and does not predict real stop time or braking energy.',
                'FreeCAD presentation metadata saved; FreeCAD GUI rendering not verified.'
            ]}
    model.write(out/'build-report.json',result); model.write(model.ROOT/'cad/centrifuge-cf01/shared-build-report.json',result)
    print('CF01 build passed: cad/centrifuge-cf01/shared-build-report.json',flush=True)


if __name__=='__main__': main()
