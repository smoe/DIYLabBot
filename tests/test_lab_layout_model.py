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

    def test_bench_racks_use_transporter_cassettes(self):
        racks = [i for i in self.spec['instances'] if i['asset'] == 'tube_rack']
        self.assertEqual(len(racks), 3)
        self.assertNotIn('tube_rack', self.spec['assets'])
        self.assertEqual(self.items['TR01']['host'], 'Floor')
        self.assertEqual(self.items['TR01']['overrides']['floor_deck_z'],
                         self.spec['parameters']['vehicle_deck_z'])


if __name__ == '__main__':
    unittest.main()
