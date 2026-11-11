"""Shared scene placements and actual-arm position screening contracts."""
from pathlib import Path
import copy
import math
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import lab_layout_model as model


class LabLayoutTests(unittest.TestCase):
    def setUp(self):
        self.spec = model.load(validate_builds=False)
        self.items = {i['id']: i for i in self.spec['instances']}

    def test_three_original_arms_and_requested_hosts(self):
        arms = [i for i in self.spec['instances'] if i['asset'] == 'arm']
        self.assertEqual(len(arms), 3)
        self.assertEqual(self.items['ArmA']['host'], self.items['ArmB']['host'])
        self.assertEqual(self.items['ArmA']['host'], 'IslandRight')
        self.assertEqual(self.items['ArmC']['host'], 'LeftBench')
        self.assertEqual(self.items['CF01']['host'], 'LeftBench')
        self.assertEqual(self.items['T01']['asset'], 'tip_collector')

    def test_spacing_moves_bases_and_risers_together(self):
        changed = copy.deepcopy(self.spec)
        changed['parameters']['pair_spacing'] += 100
        a = model.parameters(self.spec)
        b = model.parameters(changed)
        for name, delta in [('ArmA', -50), ('ArmB', 50)]:
            self.assertEqual(model.xyz(self.items[name]['xyz'], b)[1] -
                             model.xyz(self.items[name]['xyz'], a)[1], delta)
        props = {i['id']: i for i in model.primitives(changed)}
        self.assertEqual(props['MountArmA']['xyz'][:2],
                         model.xyz(self.items['ArmA']['xyz'], b)[:2])

    def test_flange_solutions_match_real_forward_kinematics_and_limits(self):
        arm = model.robot.load(model.ROOT / self.spec['assets']['arm']['source'])
        ap = model.robot.parameters(arm)
        p = model.parameters(self.spec)
        results = model.reach_report(self.spec)
        self.assertEqual(len(results), 7)
        for result in results:
            self.assertTrue(result['passed'], result)
            q = result['joint_angles_deg']
            for angle, joint in zip(q, arm['joints']):
                self.assertTrue(joint['limits_deg'][0] <= angle <= joint['limits_deg'][1])
            local = model.robot.transform(
                model.robot.forward(arm, q)[arm['flange_reference']['link']],
                model.xyz(arm['flange_reference']['point'], ap))
            actual = model.robot.transform(model.matrix(self.items[result['arm']], p), local)
            self.assertLess(math.dist(actual, result['target_mm']), 0.01)

    def test_unreachable_target_is_rejected(self):
        self.assertFalse(model.inverse_position_ik(
            self.spec, self.items['ArmA'], [0, 0, 5000])['passed'])

    def test_vehicle_footprint_route_requires_complete_finite_segments(self):
        p=model.parameters(self.spec)
        self.assertEqual(len(model.vehicle_route_points(self.spec,p)),5)
        for field,value in [('waypoints',[]),('waypoints',[[930,0]]),('waypoints',[[0,0],[1,2,3]]),('sample_step_mm',0),('yaw_deg',float('nan'))]:
            changed=copy.deepcopy(self.spec);changed['vehicle_route'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):model.vehicle_route_points(changed,p)

    def test_bench_racks_use_transporter_cassettes(self):
        racks = [i for i in self.spec['instances'] if i['asset'] == 'tube_rack']
        self.assertEqual(len(racks), 3)
        self.assertNotIn('tube_rack', self.spec['assets'])
        self.assertEqual(self.items['TR01']['host'], 'Floor')
        self.assertEqual(model.provider('transporter').parameters(model.instance_source(self.spec,self.items['TR01']))['floor_deck_z'],
                         self.spec['parameters']['vehicle_deck_z'])

    def test_devices_reference_the_catalog_and_cellar_ult_stays_outside_l01(self):
        devices=[i for i in self.spec['instances'] if i['asset'] in model.EQUIPMENT_PROFILES]
        self.assertEqual({i['id'] for i in devices},{'Balance01','Freezer01','Fridge01','WaterBath01','Hood01'})
        self.assertNotIn('cellar_ult_f440n',{i['asset'] for i in self.spec['instances']})
        for item in devices:
            ref=self.spec['assets'][item['asset']]
            self.assertEqual(ref['source'],'model/lab-equipment.shared.json')
            source=model.instance_source(self.spec,item)
            self.assertEqual(source['id'],item['asset'])
            commands=model.equipment_solidcraft_commands(self.spec,item)
            self.assertFalse(any('insert' in c['command'] for c in commands))
            self.assertTrue(any(c['command']=='joint.create' for c in commands))
            self.assertTrue(any(c['command']=='solid.box' for c in commands))
            bodies=[c['params']['body_name'] for c in commands if 'body_name' in c['params']]
            self.assertTrue(all(name.startswith(item['id']+'__') for name in bodies))
        invalid=copy.deepcopy(self.spec)
        invalid['parameters']['Freezer01_width']=500
        with self.assertRaisesRegex(ValueError,'Equipment dimensions must come from the catalog'):
            model.parameters(invalid)

    def test_cold_storage_positions_fill_the_reserved_bay_and_the_right_door_strip(self):
        p=model.parameters(self.spec)
        freezer=model.xyz(self.items['Freezer01']['xyz'],p)
        half=p['Freezer01_width']/2
        bench_end=p['left_depth']-p['window_bench_depth']-p['heating_corner_gap']-p['left_rear_equipment_bay']
        self.assertEqual(freezer[1]-half-bench_end,p['cold_wall_gap'])
        self.assertEqual(freezer[1]+half,p['left_depth']-p['window_bench_depth']-p['heating_corner_gap']-p['cold_wall_gap'])
        self.assertEqual(freezer[0]-p['Freezer01_body_depth'],p['cold_wall_gap'])
        source=model.instance_source(self.spec,self.items['Freezer01'])
        self.assertEqual(model.provider('freezer_minus20').parameters(source)['max_open'],90)
        fridge=model.xyz(self.items['Fridge01']['xyz'],p)
        self.assertEqual(fridge[0]+p['Fridge01_body_depth'],p['room_width']-p['cold_wall_gap'])
        self.assertEqual(fridge[1]+p['Fridge01_width']/2,p['perimeter_start_y']+p['right_front_equipment_bay']-p['cold_wall_gap'])
        self.assertEqual(self.items['Fridge01']['yaw_deg'],270)
        self.assertEqual(p['right_front_equipment_bay'],0)
        self.assertEqual(self.items['Balance01']['host'],'IslandLeft')

    def test_station_group_and_existing_transfer_waypoints_translate_together(self):
        import json
        historical=copy.deepcopy(self.spec)
        historical['parameters']['left_station_shift_y']=0
        a,b=model.parameters(historical),model.parameters(self.spec)
        moved={'ArmC','CF01','TR01','RackCF'}
        for name,item in self.items.items():
            if item['asset'] in model.EQUIPMENT_PROFILES:continue
            before=model.xyz(item['xyz'],a);after=model.xyz(item['xyz'],b)
            self.assertEqual([after[i]-before[i] for i in range(3)],[0,b['left_station_shift_y'] if name in moved else 0,0])
        # Check the geometric references independently of the separate runtime
        # protocol implementation, which has its own versioned tests.
        source=json.loads((model.ROOT/'model/lab-transfer-l01.protocol.json').read_text())
        for key in ('transit_tcp_mm','cf_pre_tcp_mm','cf_side_tcp_mm'):
            before=model.xyz(source['path'][key],a);after=model.xyz(source['path'][key],b)
            self.assertAlmostEqual(after[1]-before[1],b['left_station_shift_y'])
            self.assertEqual(before[::2],after[::2])


class LabLayoutNativeEvidenceTests(unittest.TestCase):
    def test_installed_appliances_and_native_cad_instances_have_current_evidence(self):
        import json
        path=model.ROOT/'cad/lab-layout-l01/shared-build-report.json'
        if not path.exists():self.skipTest('Build the current L01 layout for native evidence')
        report=json.loads(path.read_text())
        if report['source_sha256']!=model.digest(model.SOURCE):self.skipTest('Current L01 layout has not been built locally')
        self.assertTrue(report['passed'])
        for name,checksum in report['source_files_sha256'].items():
            self.assertEqual(model.digest(model.ROOT/name),checksum,name)
        for name,checksum in report['artifact_sha256'].items():
            self.assertEqual(model.digest(model.ROOT/report['files'][name]),checksum)
        native=report['layout_validation']
        self.assertEqual(native['invalid_objects'],[])
        self.assertEqual(len(native['equipment_body_metrics']),87)
        self.assertEqual(len(report['equipment_body_comparisons']),87)
        self.assertTrue(all(c['passed'] for c in report['equipment_body_comparisons']))
        self.assertTrue(all(c['passed'] for c in native['equipment_placement']))
        self.assertEqual({c['instance'] for c in native['equipment_access']},{'Balance01','Freezer01','Fridge01','WaterBath01','Hood01'})
        self.assertEqual(sum(len(c['samples']) for c in native['equipment_access']),171)
        for device in native['equipment_access']:
            self.assertTrue(device['passed'])
            self.assertTrue(all(c['passed'] for c in device['samples']))
        fridge=next(c for c in native['equipment_access'] if c['instance']=='Fridge01')
        approaches=[p for sample in fridge['samples'] for p in sample['access_probes'] if p['id'].endswith('.aisle_approach')]
        self.assertEqual(len(approaches),15)
        self.assertTrue(all(p['passed'] for p in approaches))
        self.assertTrue(all(p['obstruction_mm']<1e-6 for p in approaches if p['accessible']))
        for group in ('native_arm_models','native_equipment_models'):
            self.assertEqual(len(report[group]),3 if group=='native_arm_models' else 5)
            for asset in report[group].values():self.assertEqual(model.digest(model.ROOT/asset['path']),asset['sha256'])
        self.assertEqual(set(report['native_station_models']),{'CF01'})
        self.assertTrue(all(c['passed'] for c in report['arm_rigid_placement_checks']))
        for entry in report['arm_rigid_metric_derivations']:
            self.assertIn('_housing_Part',entry['body'])
            self.assertEqual(model.digest(model.ROOT/entry['local_metrics']),entry['local_metrics_sha256'])
        self.assertEqual(report['direct_world_measurements_complete'],not report['arm_rigid_metric_derivations'])


if __name__ == '__main__':
    unittest.main()
