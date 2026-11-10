"""Source reuse, tool frames and native evidence for the analytical concept."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import analytics_concept as model
import robot_spec as robot


class AnalyticalConceptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec, cls.spatial = model.load()
        cls.states = model.arm_states(cls.spec, cls.spatial)

    def test_two_additional_arms_reuse_one_variant_and_keep_cf01_context(self):
        arms = [d for d in self.spatial['devices'].values() if d['asset'] == 'arm']
        self.assertEqual(len(arms), 2)
        self.assertEqual(arms[0]['source'], arms[1]['source'])
        self.assertEqual(arms[0]['overrides'], arms[1]['overrides'])
        self.assertEqual(arms[0]['source']['source'], 'model/robot.json')
        self.assertEqual(self.spec['context']['device_ids'], ['Arm', 'CF01', 'Rack'])
        self.assertEqual(set(self.spec['arm_tasks']), {a['id'] for a in arms})
        for item in self.spatial['devices'].values():
            self.assertFalse({'geometry', 'bodies', 'joints'} & set(item))

    def test_original_dilution_assay_and_passive_holder_roles_are_separate(self):
        devices = self.spatial['devices']
        cases = {i: devices[i]['source']['case'] for i in ['QC.Originals', 'QC.Dilutions', 'QC.Assays']}
        self.assertEqual(len(set(cases.values())), 3)
        self.assertEqual(devices['QC.SourceNest']['source'], devices['QC.DestinationNest']['source'])
        self.assertNotEqual(devices['QC.SourceNest']['matrix'], devices['QC.DestinationNest']['matrix'])
        source = model.kit_load()
        self.assertTrue(source['cases']['originals']['closed'])
        self.assertFalse(source['cases']['workpiece']['closed'])

    def test_tool_targets_resolve_once_and_both_poses_respect_joint_limits(self):
        for identity, state in self.states.items():
            self.assertTrue(state['passed'])
            self.assertLess(state['position_error_mm'], .01)
            for q, (lo, hi) in zip(state['joints_deg'], state['limits_deg']):
                self.assertLessEqual(lo, q)
                self.assertLessEqual(q, hi)
            world = robot.transform(state['flange_matrix'], [0, 0, state['tool_length_mm']])
            for actual, intended in zip(world, state['target_mm']):
                self.assertAlmostEqual(actual, intended, delta=.01)
            for i in range(3):
                self.assertAlmostEqual(state['tcp_matrix'][i][2], [0, 0, -1][i], delta=1e-4)

    def test_pipette_drawn_tip_ends_at_its_declared_tcp(self):
        parts, frames = model.kit_parts(model.kit_load(), 'pipette')
        tip = next(p['shape'] for p in parts if p['id'] == 'PipetteTip')
        self.assertAlmostEqual(tip['origin'][2]+tip['height'], frames['tcp'][2])
        self.assertTrue(any(p['id'] == 'DosingActuatorEnvelope' for p in parts))

    def test_mount_dimensions_derive_from_the_original_arm_base(self):
        parts, _ = model.kit_parts(model.kit_load(), 'riser')
        arm = robot.load()
        base = next(op['primitive'] for link in robot.expanded(arm)['links'] for op in link['recipe']
                    if op.get('body') == 'Base_plate' and op['action'] == 'create')
        for axis in (0, 1):
            width = robot.evaluate(base['size'][axis], robot.parameters(arm))
            minimum = min(p['shape']['origin'][axis] for p in parts)
            maximum = max(p['shape']['origin'][axis]+p['shape']['size'][axis] for p in parts)
            self.assertAlmostEqual(minimum, -width/2)
            self.assertAlmostEqual(maximum, width/2)

    def test_frozen_arm_names_and_parameters_cannot_collide(self):
        body_sets, parameter_sets = [], []
        for identity, state in self.states.items():
            commands, manifest = model.arm_commands(self.spatial['devices'][identity], state, {})
            self.assertFalse(any(c['command'].startswith('joint.') for c in commands))
            body_sets.append({n for b in manifest for n in b['names']})
            parameter_sets.append({c['params']['name'] for c in commands if c['command'] == 'parameters.add'})
            self.assertEqual(len([c for c in commands if c['command'] == 'occurrence.move']), 7)
        self.assertFalse(body_sets[0] & body_sets[1])
        self.assertFalse(parameter_sets[0] & parameter_sets[1])

    def test_bad_pins_and_unsupported_scene_fields_are_rejected(self):
        real_read = model.read
        bad = copy.deepcopy(self.spec)
        bad['workspace']['source_sha256'] = '0'*64
        with patch.object(model, 'read', side_effect=lambda path: bad if Path(path) == model.SOURCE else real_read(path)):
            with self.assertRaisesRegex(ValueError, 'Pinned assembly source changed'):
                model.load()
        bad = {**self.spec, 'coordinated_motion_verified': True}
        with patch.object(model, 'read', return_value=bad):
            with self.assertRaisesRegex(ValueError, 'Unsupported analytical scene fields'):
                model.load()

    def test_invalid_fixture_dimensions_and_units_are_rejected(self):
        for change in [('units', {'length': 'm', 'angle': 'deg'}), ('cases', {'bad': {'operation': 'unknown'}})]:
            bad = copy.deepcopy(model.kit_load())
            bad[change[0]] = change[1]
            with patch.object(model, 'read', return_value=bad):
                with self.assertRaises(ValueError):
                    model.kit_load()


class AnalyticalNativeEvidenceTests(unittest.TestCase):
    def test_current_native_models_and_geometry_evidence(self):
        path = ROOT/'cad/two-arm-analytics/shared-build-report.json'
        if not path.exists():
            self.skipTest('Generate the two-arm analytical concept for native evidence')
        report = model.read(path)
        self.assertTrue(report['passed'])
        self.assertEqual(report['source_sha256'], robot.digest(model.SOURCE))
        for path, checksum in report['source_files_sha256'].items():
            self.assertEqual(robot.digest(ROOT/path), checksum, path)
        for kind, checksum in report['artifact_sha256'].items():
            self.assertEqual(robot.digest(ROOT/report['files'][kind]), checksum)
        self.assertFalse(report['geometry_validation']['collisions'])
        self.assertTrue(all(s['passed'] for s in report['geometry_validation']['support_checks']))
        self.assertTrue(all(c['passed'] for c in report['instance_cross_cad']))
        self.assertEqual({i for i in report['arm_states']}, {'QC.Handle', 'QC.Pipette'})
        self.assertTrue({'Arm', 'CF01', 'Rack', 'QC.Handle', 'QC.Pipette'} <= set(report['geometry_validation']['instance_metrics']))


if __name__ == '__main__':
    unittest.main()
