"""All confirmed laboratory exits open into their actual adjacent corridor."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_doors as doors
import building_stack as building
import relative_floorplan as floor
import walkthrough_mechanisms as mechanisms


class LaboratoryCorridorDoorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((ROOT/'model/building-stack.shared.json').read_text())
        cls.parameters = building.parameters(cls.spec)
        cls.policy, cls.catalog = doors.load(cls.spec['exterior']['doors'])
        cls.plans = {level: building.level_plan(cls.spec, level) for level in ('EG', 'OG1', 'OG2', 'OG3')}
        source = json.loads((ROOT/'model/furnishings/building-laboratories.json').read_text())
        cls.rooms = {(item['level'], item['area']) for item in source['laboratories']+source['basic_laboratories']}
        cls.targets = []
        for level, plan in cls.plans.items():
            for opening in plan['openings']:
                if opening['kind'] != 'door':
                    continue
                adjacent = [a for a in plan['areas'] if any(e['wall'] == opening['wall'] for e in a['boundary'])]
                labs = [a for a in adjacent if (level, a['id']) in cls.rooms]
                corridors = [a for a in adjacent if a['kind'] == 'corridor']
                if labs and corridors:
                    cls.targets.append((level, plan, opening, labs[0], corridors[0]))

    def selection(self, level, plan, opening, policy=None):
        return doors.select(policy or self.policy, plan, self.plans['OG3'], level, opening)

    def test_every_lab_exit_and_only_lab_exits_receive_the_rule(self):
        self.assertEqual(len(self.rooms), 15)
        self.assertEqual(len(self.targets), 27)
        self.assertEqual({(level, lab['id']) for level, _, _, lab, _ in self.targets}, self.rooms)
        expected = {(level, opening['id']) for level, _, opening, _, _ in self.targets}
        legacy = copy.deepcopy(self.policy)
        legacy.pop('laboratory_corridor_rule')
        for level, plan in self.plans.items():
            for opening in plan['openings']:
                if opening['kind'] != 'door':
                    continue
                selected = self.selection(level, plan, opening)
                if (level, opening['id']) in expected:
                    self.assertIn('laboratory_corridor', selected)
                else:
                    self.assertEqual(selected, self.selection(level, plan, opening, legacy))

    def test_open_leaf_and_intermediate_positions_are_outside_the_lab(self):
        scale = self.parameters['display_scale']
        for level, plan, opening, lab, corridor in self.targets:
            with self.subTest(level=level, opening=opening['id']):
                selected = self.selection(level, plan, opening)
                frame = doors.handed_frame(plan, opening, selected['pose'], scale)
                wall = next(w for w in plan['walls'] if w['id'] == opening['wall'])
                a, b = [plan['vertices'][wall[k]] for k in ('start', 'end')]
                hinge = [(a[i]+opening['interval'][0]*(b[i]-a[i]))*scale for i in (0, 1)]
                self.assertEqual(frame['hinge_mm'], hinge)
                width = math.dist(a, b)*(opening['interval'][1]-opening['interval'][0])*scale
                middle = [(a[i]+sum(opening['interval'])/2*(b[i]-a[i])) for i in (0, 1)]
                # A short step away from the wall must enter the corridor and
                # leave the laboratory, independently of polygon winding.
                sample = [middle[i]+frame['opening_axis'][i]*1e-5 for i in (0, 1)]
                self.assertEqual(floor.point_membership(sample, floor.outline(plan, corridor)), 1)
                self.assertEqual(floor.point_membership(sample, floor.outline(plan, lab)), -1)
                selected['placement'] = frame
                selected['level_id'] = level
                pieces = doors.geometry(self.catalog, selected, 'Leaf', hinge, frame['closed_axis'],
                                        frame['opening_axis'], width, self.parameters['door_height_mm'], 0,
                                        self.spec['exterior'])
                profile = json.loads((ROOT/'model/building-walkthrough.shared.json').read_text())['mechanisms']['room_doors']
                interface = {'levels': [{'id': level, 'label': level}],
                             'exterior': {'door_bindings': {level+'__'+opening['id']: selected}}}
                control = mechanisms.room_doors(profile, interface, pieces, {level: plan}, self.parameters, 1600)[0]
                self.assertEqual(set(control['moving_body_ids']), {b['id'] for b in pieces['bodies']})
                self.assertEqual(control['laboratory_corridor'], {'laboratory': lab['id'], 'corridor': corridor['id']})
                opened = frame['opening_axis']
                sign = control['joint']['axis'][2]
                for angle in (0, 5, 30, 60, 90):
                    theta = math.radians(sign*(angle-90))
                    actual = [math.cos(theta)*opened[0]-math.sin(theta)*opened[1],
                              math.sin(theta)*opened[0]+math.cos(theta)*opened[1]]
                    out = sum(actual[i]*opened[i] for i in (0, 1))
                    self.assertAlmostEqual(out, math.sin(math.radians(angle)), places=10)
                    if angle == 0:
                        for i in (0, 1):
                            self.assertAlmostEqual(actual[i], frame['closed_axis'][i], places=10)

    def test_area_order_and_winding_do_not_reverse_the_opening(self):
        for level, plan, opening, _, _ in self.targets:
            expected = self.selection(level, plan, opening)['pose']
            other = copy.deepcopy(plan)
            other['areas'].reverse()
            for area in other['areas']:
                area['boundary'] = [{**e, 'direction': -e['direction']} for e in reversed(area['boundary'])]
            self.assertEqual(self.selection(level, other, opening)['pose'], expected)

    def test_stale_assignments_and_conflicting_pose_are_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy['laboratory_corridor_rule']['room_assignments']['source_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            doors.validate(policy, self.catalog)
        level, plan, opening, lab, _ = self.targets[0]
        policy = copy.deepcopy(self.policy)
        selected = self.selection(level, plan, opening)
        policy['opening_overrides'].append({'level_id': level, 'opening_id': opening['id'],
            'type': selected['type'], 'material': selected['material'], 'basis': 'Conflicting test fixture',
            'pose': {**selected['pose'], 'opens_into': lab['id']}})
        with self.assertRaisesRegex(ValueError, 'conflicts with outward'):
            self.selection(level, plan, opening, policy)


if __name__ == '__main__':
    unittest.main()
