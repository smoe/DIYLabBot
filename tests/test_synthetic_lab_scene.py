"""Referenced instrument placement, frozen CAD commands and scene evidence."""
import copy
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import instrument_concept
import centrifuge_robot_pickup as pickup
import robot_spec as robot
import synthetic_lab_scene as model
import synthetic_workspace as workspace


class SyntheticLabPlacementTests(unittest.TestCase):
    def setUp(self):
        self.spatial = workspace.load()
        self.entries = model.instrument_instances(self.spatial)

    def test_existing_three_devices_and_bank_have_not_moved(self):
        expected = {'Arm': [-330, 80, 0], 'CF01': [0, 0, 0], 'Rack': [-260, -280, 0]}
        for identity, position in expected.items():
            self.assertEqual([self.spatial['devices'][identity]['matrix'][i][3] for i in range(3)], position)
        self.assertEqual(len(self.spatial['bench']['bodies']), 1)

    def test_instruments_use_the_same_source_and_identity_as_the_logical_profiles(self):
        for entry, profile in zip(self.entries, ['nanodrop-manual', 'qubit-4-manual']):
            original = json.loads((ROOT/'model'/(profile+'.synthetic.json')).read_text())
            self.assertEqual(entry['instance']['id'], original['instrument']['id'])
            self.assertEqual(entry['instance']['host'], original['workspace']['frame'])
            source = instrument_concept.SOURCES[entry['spec']['family']]
            self.assertEqual(entry['instance']['source']['source_sha256'], robot.digest(source))
            self.assertEqual(entry['spec'], instrument_concept.load(source))
            self.assertFalse({'geometry', 'bodies', 'parameters'} & set(entry['instance']))

    def test_bank_frame_and_instrument_hinge_are_composed_once(self):
        entry = self.entries[0]
        matrix = entry['instance']['matrix']
        self.assertEqual([matrix[i][3] for i in range(3)], [-445, -137.5, 0])
        # A left quarter-turn in the bench's right-handed XY plane.
        self.assertAlmostEqual(matrix[0][0], 0)
        self.assertAlmostEqual(matrix[1][0], 1)
        self.assertAlmostEqual(matrix[0][1], -1)
        p = entry['parameters']
        local_hinge = [p['sample_x'], p['hinge_y'], p['hinge_z']]
        self.assertEqual(robot.transform(model.component_matrix(entry, 'Frame'), local_hinge),
                         robot.transform(matrix, local_hinge))
        for angle in [0, 35, p['max_open']]:
            for a, b in zip(robot.transform(model.component_matrix(entry, 'MovingArm', angle), local_hinge),
                            robot.transform(matrix, local_hinge)):
                self.assertAlmostEqual(a, b)

    def test_model_names_and_parameters_do_not_collide_with_each_other_or_the_arm(self):
        body_sets, parameter_sets = [], []
        for entry in self.entries:
            commands, manifest = model.frozen_commands(entry)
            self.assertFalse(any(c['command'].startswith('joint.') for c in commands))
            body_sets.append({n for b in manifest for n in b['names']})
            parameter_sets.append({c['params']['name'] for c in commands if c['command'] == 'parameters.add'})
            self.assertTrue(all(c['params']['grounded'] for c in commands if c['command'] == 'component.create'))
            self.assertEqual(len([c for c in commands if c['command'] == 'occurrence.move']), 2)
            expressions = [c['params']['expression'] for c in commands if c['command'] == 'parameters.add']
            self.assertFalse(any(re.search(r'\b(width|depth|base_h|sample_z)\b', e) for e in expressions))
        self.assertFalse(body_sets[0] & body_sets[1])
        self.assertFalse(parameter_sets[0] & parameter_sets[1])
        self.assertFalse(parameter_sets[0] & set(robot.load()['parameters']))

    def test_missing_device_or_wrong_model_family_is_rejected(self):
        spatial = copy.deepcopy(self.spatial)
        del spatial['devices']['SYN.Qubit401']
        with self.assertRaisesRegex(ValueError, 'requires NanoDrop and Qubit'):
            model.instrument_instances(spatial)
        spatial = copy.deepcopy(self.spatial)
        spatial['devices']['SYN.Qubit401']['source'] = spatial['devices']['SYN.NanoDrop01']['source']
        with self.assertRaisesRegex(ValueError, 'does not match'):
            model.instrument_instances(spatial)

    def test_bad_model_pin_is_rejected_before_geometry_build(self):
        spatial = copy.deepcopy(self.spatial)
        spatial['devices']['SYN.NanoDrop01']['source']['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Pinned assembly source changed'):
            model.instrument_instances(spatial)

    def test_both_sample_interfaces_and_vertical_approaches_are_reachable(self):
        scene = pickup.load()
        kin = pickup.Kinematics(pickup.arm_source(scene), scene)
        report = model.instrument_reachability(scene, self.entries)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['checks']), 4)
        for check in report['checks']:
            entry = next(e for e in self.entries if e['instance']['id'] == check['instance'])
            surface = robot.transform(entry['instance']['matrix'], instrument_concept.interfaces(
                entry['spec'], entry['parameters'])['sample_surface'])
            expected = surface[:2]+[surface[2]+check['height_above_surface_mm']]
            actual = kin.tool(check['joints_deg'])
            for i in range(3):
                self.assertAlmostEqual(actual[i][3], expected[i], delta=0.01)
                self.assertAlmostEqual(actual[i][2], [0, 0, -1][i], delta=0.0001)
            self.assertTrue(check['within_joint_limits'])

    def test_an_unreachable_instrument_is_rejected(self):
        entries = copy.deepcopy(self.entries)
        entries[0]['instance']['matrix'][0][3] += 10000
        with self.assertRaisesRegex(ValueError, 'No accurate constrained IK solution'):
            model.instrument_reachability(pickup.load(), entries)


class SyntheticLabBuildEvidenceTests(unittest.TestCase):
    def test_both_cads_and_added_device_clearances_match_current_sources(self):
        path = ROOT/'cad/synthetic-lab-scene/shared-build-report.json'
        if not path.exists():
            self.skipTest('Build the synthetic laboratory scene to inspect native CAD evidence')
        report = json.loads(path.read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(report['workspace_sha256'], robot.digest(workspace.SOURCE))
        for path, checksum in report['source_files_sha256'].items():
            self.assertEqual(robot.digest(ROOT/path), checksum, path)
        for snapshot in report['snapshots']:
            self.assertTrue(snapshot['passed'])
            self.assertEqual({c['instance'] for c in snapshot['instance_cross_cad']},
                             {'BenchSurface', 'Arm', 'CF01', 'Rack', 'SYN.NanoDrop01', 'SYN.Qubit401'})
            self.assertFalse(snapshot['geometry_validation']['new_instrument_interferences'])
            self.assertTrue(all(s['passed'] for s in snapshot['geometry_validation']['support_checks']))
            for kind, checksum in snapshot['artifact_sha256'].items():
                self.assertEqual(robot.digest(ROOT/snapshot['files'][kind]), checksum)
        self.assertTrue(report['instrument_reachability']['passed'])
        motion = report['instrument_motion_validation']
        self.assertTrue(motion['passed'])
        self.assertFalse(motion['collisions'])
        trajectory_path=ROOT/report['cf01_trajectory']['path']
        self.assertEqual(robot.digest(trajectory_path),report['cf01_trajectory']['sha256'])
        trajectory=json.loads(trajectory_path.read_text())
        self.assertEqual(trajectory['scene_sha256'],robot.digest(pickup.SOURCE))
        self.assertEqual(trajectory['duration_s'],pickup.load()['timeline'][-1]['time_s'])
        self.assertEqual(motion['cf01_path_samples'],len(trajectory['samples']))
        self.assertEqual(motion['approach_configurations'], 2)
        nd = model.instrument_instances()[0]
        self.assertEqual(motion['nanodrop_hinge_angles_deg'][0], 0)
        self.assertEqual(motion['nanodrop_hinge_angles_deg'][-1], nd['parameters']['max_open'])
        self.assertLessEqual(max(b-a for a, b in zip(motion['nanodrop_hinge_angles_deg'],
                                                   motion['nanodrop_hinge_angles_deg'][1:])), 5)
        self.assertGreaterEqual(motion['minimum_nanodrop_lever_arm_distance_lower_bound_mm'],
                                pickup.load()['checks']['minimum_robot_equipment_clearance_mm'])
        self.assertEqual(len(report['approach_geometry_checks']), 2)
        for check in report['approach_geometry_checks']:
            self.assertTrue(check['passed'])
            self.assertFalse(check['approach_robot_interferences'])
            self.assertFalse(check['new_instrument_interferences'])
            self.assertEqual(robot.digest(ROOT/check['freecad']), check['artifact_sha256'])
        if report.get('core_source_equivalence'):
            original_path = ROOT/report['core_source_equivalence']['construction_commands']
            original = json.loads((original_path.parent/'solidcraft-scene-validation.json').read_text())
            scene = pickup.load()
            trajectory = pickup.trajectory(scene)
            scene['arm_fixture']['position_mm'][0] += 5
            with self.assertRaisesRegex(ValueError, 'Core pose changed'):
                model.verify_core_geometry(original, scene, trajectory, [('Grasp', scene['checks']['attachment_time_s']), ('RackReleased', trajectory['duration_s'])])


if __name__ == '__main__':
    unittest.main()
