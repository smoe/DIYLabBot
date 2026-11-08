"""Freeze executed pickup-scene evidence and backend capabilities into a report."""
import json
import math
from pathlib import Path
import re
import shutil
import ast
import centrifuge_robot_pickup as pickup
import centrifuge_model as cf
import robot_spec as robot


def main():
    context=json.loads((cf.ROOT/'tmp/cf01-robot-pickup-context.json').read_text());out=Path(context['out']);cad=Path(context['cad']);renders=Path(context['renders'])
    for name,sha in context['source_hashes'].items():assert cf.digest(cf.ROOT/name)==sha,name
    station=json.loads((out/'native-scene-validation.json').read_text());self_check=json.loads((out/'native-self-and-grip-validation.json').read_text());sc=json.loads((out/'solidcraft-scene-validation.json').read_text());motion=json.loads((out/'native-motion-validation.json').read_text())
    assert station['passed'] and self_check['passed'] and motion['passed']
    trace=json.loads((out/'protocol-transfer-trace.json').read_text());assert trace['passed']
    data=json.loads((out/'trajectory.json').read_text());scene=pickup.load();arm=pickup.arm_source(scene);kin=pickup.Kinematics(arm,scene)
    assert data['scene_sha256']==cf.digest(pickup.SOURCE)
    interpolation=pickup.interpolation_audit(scene,data);assert interpolation['passed']
    review=json.loads((cf.ROOT/'tmp/cf01-bench-visual-review.json').read_text());assert review['passed'] and review['scene_sha256']==data['scene_sha256']
    # Cross-check every stored angle against the original forward-kinematics implementation.
    maximum_fk=0;maximum_orientation=0
    for sample in data['samples']:
        cached=kin.forward(sample['joints_deg']);original=robot.forward(arm,sample['joints_deg'])
        for name,matrix in original.items():
            target=robot.multiply(kin.base,matrix)
            for point in [[0,0,0],[17,23,31]]:maximum_fk=max(maximum_fk,math.dist(robot.transform(cached[name],point),robot.transform(target,point)))
        target=pickup.target_at(scene,cf.load(),cf.parameters(cf.load()),sample['time_s']);residual=kin.residual(sample['joints_deg'],target)
        maximum_orientation=max(maximum_orientation,math.degrees(math.sqrt(sum(v*v for v in residual[3:]))/100))
    assert maximum_fk<1e-7 and maximum_orientation<scene['checks']['tip_orientation_tolerance_deg']
    log=cf.ROOT/'tmp/cf01-robot-pickup-tests.log';text=log.read_text(encoding='utf-8',errors='replace');assert text.rstrip().endswith('OK');tests=int(re.search(r'Ran (\d+) tests',text).group(1));shutil.copy2(log,out/'offline-tests.log')
    visual=json.loads((out/'visualization-mesh-summary.json').read_text());assert visual['bytes']<2_000_000
    macro=cad/'CF01_Robot_Pickup.FCMacro';macro_ast=ast.parse(macro.read_text(encoding='utf-8'));assert any(isinstance(n,ast.Constant) and n.value==str(out/'context.json') for n in ast.walk(macro_ast))
    source_paths=[pickup.SOURCE,cf.SOURCE,pickup.protocol.SOURCE,cf.ROOT/'model/robot.json',*[cf.ROOT/'scripts'/n for n in [
        'centrifuge_robot_pickup.py','build_centrifuge_robot_pickup.py','build_centrifuge_robot_pickup_freecad.py',
        'export_centrifuge_robot_pickup_solidcraft.py','centrifuge_pickup_solidcraft.py','solidcraft_vendor.py','robot_components.py',
        'build_centrifuge_robot_pickup_visual.py','report_centrifuge_robot_pickup.py',
        'check_centrifuge_robot_motion.py','robot_spec.py','lab_transfer_model.py']],
        cf.ROOT/'scripts/templates/centrifuge_robot_pickup.html',cf.ROOT/'scripts/templates/centrifuge_robot_pickup.FCMacro',cf.ROOT/'tests/test_centrifuge_robot_pickup.py']
    batch=json.loads((out/'rack-batch-trace.json').read_text());assert batch['passed'] and batch['order_restored']
    source_paths += [*pickup.workspace.source_dependencies(pickup.workspace.load(pickup.assembly.validate_reference(scene['environment']))),cf.ROOT/'scripts/synthetic_workspace.py',cf.ROOT/'scripts/rack_slots.py',cf.ROOT/'scripts/cf01_rack_batch.py',cf.ROOT/'scripts/furniture_model.py',cf.ROOT/'scripts/centrifuge_control.py',cf.ROOT/'scripts/centrifuge_protocol.py',cf.ROOT/'scripts/centrifuge_model.py',cf.ROOT/'model/cf01-rack-batch.protocol.json',cf.ROOT/'scripts/templates/robot_demo_header.html']
    def relative(p):return str(p.relative_to(cf.ROOT)).replace('\\','/')
    artifacts=[p for folder in [cad,out,renders] for p in folder.iterdir() if p.is_file() and p.name!='robot-pickup-build-report.json']
    result={'format':'solidcraftbot.centrifuge-robot-pickup-build/1',**context,'passed':bool(sc['passed']),
        'source_files_sha256':{relative(p):cf.digest(p) for p in source_paths},
        'workspace':{'source':scene['environment'],'extent':'unbounded','reference_surface_only':True},
        'rack_batch':{'path':relative(out/'rack-batch-trace.json'),'passed':True,'order_restored':True,'sample_count':12,'network_executed':False,'hardware_executed':False,'robot_motion_checked':False},
        'native_input_sha256':{context[k]:cf.digest(context[k]) for k in ['arm_native','centrifuge_native']},
        'artifact_sha256':{relative(p):cf.digest(p) for p in artifacts},
        'trajectory':{'samples':len(data['samples']),'duration_s':data['duration_s'],'joint_count':6,'all_joint_limits_checked':True,
            'max_tip_position_error_mm':data['maximum_tip_position_error_mm'],'max_orientation_error_deg':maximum_orientation,'max_original_fk_difference_mm':maximum_fk,
            'handoff_time_s':scene['checks']['attachment_time_s'],'clear_confirmed_s':scene['checks']['robot_clear_confirmed_s'],'closure_starts_s':scene['checks']['closing_starts_s']},
        'bench_mount':scene['arm_fixture'],'robot_parameters_mm':{k:robot.parameters(arm)[k] for k in scene['robot_parameter_overrides_mm']},
        'transport_requirement':scene['transport_requirement'],'rack':{'capacity':scene['rack']['rows']*scene['rack']['columns'],'handoff_s':scene['checks']['rack_handoff_time_s'],'release_complete_s':scene['checks']['release_complete_time_s'],'nominal_radial_bore_clearance_mm':scene['rack']['bore_radius_mm']-cf.parameters(cf.load())['tube_radius']},
        'joint_interpolation_audit':interpolation,'native_motion_audit':motion,'native_station_clearance':station,'native_self_and_grip':self_check,'solidcraft_snapshots':sc,
        'offline_tests':{'passed':True,'count':tests,'log':relative(out/'offline-tests.log')},'endpoint_protocol_trace':relative(out/'protocol-transfer-trace.json'),
        'files':{'interactive':relative(renders/'cf01-robot-pickup.html'),'freecad_playback':relative(macro),
            'freecad_grasp':relative(cad/'CF01_Robot_Grasp.FCStd'),'freecad_withdrawn':relative(cad/'CF01_Robot_Withdrawn.FCStd'),
            'solidcraft_grasp':relative(cad/'CF01_Robot_Grasp.sc'),'solidcraft_rack_released':relative(cad/'CF01_Robot_RackReleased.sc'),
            'freecad_rack_seated':relative(cad/'CF01_Robot_RackSeated.FCStd'),'freecad_rack_released':relative(cad/'CF01_Robot_RackReleased.FCStd'),'freecad_parametric_arm_variant':relative(cad/'CF01_LongLink_Arm.FCStd'),
            'documentation':'docs/centrifuge-cf01-robot-pickup.md'},
        'visual_review':{**review,'freecad_live_macro_executed':False,'display_mesh':visual},
        'backend_capabilities':{'interactive':'Full coupled six-axis motion, jaw closure, carried tube and supported rack handoff','freecad':'Seven native snapshots, parametric long-link arm variant and generated placement-playback macro; GUI not run',
            'solidcraft':'Two native source-derived review scenes, independently buildable without FreeCAD; frozen poses, no live native handoff motion study'},
        'hardware_connected':False,'robot_frame_calibrated':False,'gripper_qualified':False,'limitations':scene['limitations']+[
            'Adaptive motion audit and native snapshots remain discrete checks, not a continuous swept-volume proof.',
            'SolidCraft keeps original X2/X4 case pieces as rigid assemblies; their source-body mapping and original seam overlaps are recorded separately.',
            'No hardware ROS/SiLA server or physical grasp/sensor/force validation is supplied.']}
    cf.write(out/'robot-pickup-build-report.json',result);cf.write(cf.ROOT/'cad/centrifuge-cf01/robot-pickup-build-report.json',result)
    print(json.dumps({'passed':result['passed'],'revision':context['revision'],'tests':tests,'samples':len(data['samples']),'native_station_poses':len(station['samples']),
        'native_self_and_grip_poses':len(self_check['samples']),'interactive':result['files']['interactive'],'max_orientation_error_deg':maximum_orientation}))


if __name__=='__main__':main()
