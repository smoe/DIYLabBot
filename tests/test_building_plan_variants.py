"""Owner corrections retain the raw trace, other storeys and protected cores."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_stack as stack
import relative_floorplan as floor
import build_building_stack as evidence


class PlanVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(stack.SOURCE.read_text())
        cls.plan = stack.templates(cls.source)[0]

    def test_only_og3_loses_the_erroneous_right_door(self):
        for level in ('OG1', 'OG2', 'OG3'):
            plan = stack.apply_plan_variants(self.source, self.plan, level)
            names = {opening['id'] for opening in plan['openings']}
            self.assertIn('D3_002_001', names)
            self.assertIn('D3_002N', names)
            self.assertEqual('D3_002_003' in names, level != 'OG3')

    def test_restroom_areas_boundaries_and_doors_remain_as_drawn(self):
        protected = {'R3_011', 'R3_012', 'CoreGap'}
        areas = {area['id']: area for area in self.plan['areas'] if area['id'] in protected}
        boundaries = {edge['wall'] for area in areas.values() for edge in area['boundary']}
        walls = {wall['id']: wall for wall in self.plan['walls'] if wall['id'] in boundaries}
        openings = {opening['id']: opening for opening in self.plan['openings'] if opening['wall'] in boundaries}
        for level in ('OG1', 'OG2', 'OG3'):
            with self.subTest(level=level):
                plan = stack.apply_plan_variants(self.source, self.plan, level)
                self.assertEqual({area['id']: area for area in plan['areas'] if area['id'] in protected}, areas)
                self.assertEqual({wall['id']: wall for wall in plan['walls'] if wall['id'] in boundaries}, walls)
                self.assertEqual({opening['id']: opening for opening in plan['openings'] if opening['wall'] in boundaries}, openings)

    def test_only_confirmed_kernbereich_opposite_3002_is_opened_on_upper_floors(self):
        before = copy.deepcopy(self.plan)
        variant = next(item for item in self.source['plan_variants'] if item['id'] == 'AtriumAccess')
        self.assertEqual(variant['area_overrides'], {'NorthCore': {'kind': 'corridor', 'label': 'Kernbereich'}})
        self.assertEqual(variant['wall_overrides'], {'W063': 'open_boundary', 'W065': 'open_boundary'})
        self.assertEqual(variant['disabled_openings'], [])
        areas = {area['id']: area for area in before['areas']}
        polygons = {name: floor.outline(before, areas[name]) for name in ('R3_002', 'Atrium', 'NorthCore')}
        bounds = {name: ([min(point[i] for point in points) for i in (0, 1)],
                         [max(point[i] for point in points) for i in (0, 1)])
                  for name, points in polygons.items()}
        self.assertLess(bounds['R3_002'][1][1], bounds['Atrium'][0][1])
        self.assertGreaterEqual(bounds['NorthCore'][0][1], bounds['Atrium'][1][1])
        self.assertLess(max(bounds['R3_002'][0][0], bounds['NorthCore'][0][0]),
                        min(bounds['R3_002'][1][0], bounds['NorthCore'][1][0]))
        for level in ('OG1', 'OG2', 'OG3'):
            plan = stack.apply_plan_variants(self.source, self.plan, level)
            floor.validate(plan)
            self.assertEqual(plan['vertices'], before['vertices'])
            self.assertEqual(next(area for area in plan['areas'] if area['id'] == 'Atrium'),
                             next(area for area in before['areas'] if area['id'] == 'Atrium'))
            self.assertEqual(next(area for area in plan['areas'] if area['id'] == 'NorthCore'),
                             {**areas['NorthCore'], 'kind': 'corridor', 'label': 'Kernbereich'})
            for name in ('LiftCore', 'R3_028'):
                self.assertEqual(next(area for area in plan['areas'] if area['id'] == name), areas[name])
            for name in ('W063', 'W065'):
                self.assertEqual(next(wall['kind'] for wall in plan['walls'] if wall['id'] == name), 'open_boundary')
            for name in ('W062', 'W079'):
                self.assertEqual(next(wall for wall in plan['walls'] if wall['id'] == name),
                                 next(wall for wall in before['walls'] if wall['id'] == name))
            self.assertIn('D3_012', {opening['id'] for opening in plan['openings']})
        self.assertEqual(self.plan, before, 'The canonical source must remain unchanged')

    def test_no_variant_is_applied_to_eg_or_kg(self):
        for level in ('EG', 'KG'):
            self.assertIs(stack.apply_plan_variants(self.source, self.plan, level), self.plan)

    def test_guarded_source_anchor_is_level_bound_and_references_actual_edges(self):
        p = stack.parameters(self.source)
        plans = {level: stack.apply_plan_variants(self.source, self.plan, level) for level in ('OG1', 'OG2', 'OG3')}
        anchors = stack.atrium_access_anchors(self.source, self.plan, plans, p)
        self.assertEqual(set(anchors), {'OG1', 'OG2', 'OG3'})
        self.assertEqual(self.source['atrium_access']['corridor_area'], 'C3_021')
        for anchor in anchors.values():
            self.assertEqual(set(anchor['area_refs']), {'NorthCore'})
            self.assertEqual(set(anchor['entry_boundary_ids']), {'W063'})
            self.assertEqual(set(anchor['guard_boundary_ids']), {'W065'})
        unsafe = copy.deepcopy(self.source)
        unsafe['exterior']['guard_boundaries'].remove('W065')
        with self.assertRaisesRegex(ValueError, 'requires the common railing'):
            stack.validate_atrium_access(unsafe, self.plan)

    def test_invalid_unknown_conflicting_or_core_modifications_are_rejected(self):
        changes = [
            lambda spec: spec['plan_variants'][0]['levels'].append('EG'),
            lambda spec: spec['plan_variants'][0]['area_overrides'].update({'Atrium': {'kind': 'corridor', 'label': 'Filled'}}),
            lambda spec: spec['plan_variants'][0]['wall_overrides'].update({'W052': 'open_boundary'}),
            lambda spec: spec['plan_variants'][1]['disabled_openings'].append('MissingDoor'),
            lambda spec: spec['plan_variants'].append(copy.deepcopy(spec['plan_variants'][0])),
        ]
        for change in changes:
            spec = copy.deepcopy(self.source)
            change(spec)
            with self.assertRaises(ValueError):
                stack.validate_plan_variants(spec, self.plan)

    def test_closed_opening_witness_requires_positive_material_in_retained_wall(self):
        probe = {'id': 'ClosedDoor', 'target_body': 'OG3__Wall_W070', 'points_mm': [[0, 0], [10, 0], [10, 2], [0, 2]],
                 'offset_mm': 0, 'depth_mm': 30, 'expectation': 'filled', 'expected_volume_mm3': 600}
        contract = {'levels': [{'wall_bodies': ['OG3__Wall_W070']}], 'opening_closure_probes': [probe]}
        record = evidence.opening_closure_probe_specs(contract)[0]
        self.assertEqual(record['expected'], {'OG3__Wall_W070': 600})
        contract['levels'][0]['wall_bodies'] = []
        with self.assertRaisesRegex(ValueError, 'retained wall'):
            evidence.opening_closure_probe_specs(contract)


if __name__ == '__main__':
    unittest.main()
