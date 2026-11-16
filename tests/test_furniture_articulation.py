"""Additive browser articulation contracts; no native CAD execution."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_stack as stack
import building_walkthrough as walkthrough
import furniture_articulation as articulation
import relative_floorplan as floor


class ArticulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(walkthrough.SOURCE.read_text())
        cls.art = articulation.read(cls.spec['articulation_source'])
        cls.building = stack.load(); cls.p = stack.parameters(cls.building)
        cls.interface = stack.interfaces(cls.building, cls.p)
        cls.expanded = stack.expanded(cls.building, cls.p)
        cls.plans = {v['id']: stack.level_plan(cls.building, v['id']) for v in cls.interface['levels']}
        cls.objects = cls.derive(cls.spec['objects'])

    @classmethod
    def derive(cls, requests):
        return articulation.compile_objects(cls.spec['articulation_source'], requests, cls.building, cls.p,
            cls.interface, cls.expanded, cls.plans, cls.spec['settings']['eye_height_mm'])

    def test_only_door_and_handle_move(self):
        room = next(v for v in self.interface['furnishings']['rooms'] if v['id'] == 'Kitchen1008')
        obj = self.objects[0]
        self.assertEqual(set(obj['moving_body_ids']), set(room['fridge_door_body_ids']))
        self.assertEqual(len(obj['moving_body_ids']), 2)
        self.assertFalse(any('Penguin' in n or 'Shelf' in n or 'Shell' in n for n in obj['moving_body_ids']))
        self.assertTrue(all(value is False for value in obj['qualification'].values()))

    def test_microwave_leaf_window_and_handle_move_independently_of_case(self):
        obj = next(v for v in self.objects if v['id'] == 'Kitchen1008.Microwave.Door')
        self.assertEqual(set(obj['moving_body_ids']),
            {'Kitchen1008_Microwave_'+part for part in ('Door', 'Window', 'Handle')})
        self.assertEqual(obj['states'], {'closed': 0, 'open': 90})
        hinge = obj['joint']['origin_mm']
        handle = next(v['shape'] for v in self.expanded['operations']
                      if v['id'] == 'Kitchen1008_Microwave_Handle')
        delta = [sum(p[i] for p in handle['points'])/4-hinge[i] for i in (0, 1)]
        opened = [-delta[1], delta[0]]
        self.assertGreater(sum(opened[i]*obj['front'][i] for i in (0, 1)),
                           sum(delta[i]*obj['front'][i] for i in (0, 1)))
        self.assertTrue(any(v['action'] == 'cut' and v['body'] == 'Kitchen1008_Microwave_Case'
                            for v in self.expanded['operations']))
        self.assertTrue(all(value is False for value in obj['qualification'].values()))

    def test_hinge_is_the_ordered_top_left_footprint_vertex(self):
        obj = self.objects[0]
        operation = next(o for o in self.expanded['operations'] if o['id'] == 'Kitchen1008_Fridge_Door')
        shape = operation['shape']; points = shape['points']
        self.assertGreater(floor.signed_area(points), 0)
        self.assertEqual(obj['joint']['origin_mm'], points[3]+[shape['offset']])
        delta = [points[3][i]-points[0][i] for i in (0, 1)]
        self.assertEqual(obj['front'][:2], [v/math.hypot(*delta) for v in delta])
        self.assertEqual(obj['joint']['axis'], [0, 0, 1])

    def test_positive_rotation_moves_handle_outward(self):
        obj = self.objects[0]; hinge = obj['joint']['origin_mm']
        shape = next(o['shape'] for o in self.expanded['operations'] if o['id'] == 'Kitchen1008_Fridge_Handle')
        center = [sum(pt[i] for pt in shape['points'])/4 for i in (0, 1)]
        delta = [center[i]-hinge[i] for i in (0, 1)]
        opened = [-delta[1], delta[0]]
        self.assertGreater(sum(opened[i]*obj['front'][i] for i in (0, 1)),
                           sum(delta[i]*obj['front'][i] for i in (0, 1)))
        self.assertEqual(obj['states'][obj['reference_state']], 0)

    def test_object_view_stays_in_source_kitchen(self):
        obj = self.objects[0]; plan = self.plans[obj['level_id']]
        eye = [v/self.p['display_scale'] for v in obj['viewpoint']['eye_mm'][:2]]
        room = next(v for v in self.interface['furnishings']['rooms'] if v['id'] == 'Kitchen1008')
        self.assertTrue(any(floor.point_membership(eye, floor.outline(plan, name)) == 1 for name in room['template_areas']))
        self.assertEqual(obj['viewpoint']['eye_mm'][2], 4250+self.spec['settings']['eye_height_mm'])

    def test_false_pins_parts_and_qualification_are_rejected(self):
        for mutate in (
            lambda s: s['catalog'].update(source_sha256='0'*64),
            lambda s: s['types']['fridge']['Door']['moving_parts'].append('UnknownPart'),
            lambda s: s['types']['fridge']['Door']['qualification'].update(native_articulation=True),
            lambda s: s['types']['fridge']['Door']['hinge'].update(part='Shell'),
        ):
            source = copy.deepcopy(self.art); mutate(source)
            with self.subTest(source=source), self.assertRaises(ValueError): articulation.validate(source)

    def test_unknown_object_references_are_rejected(self):
        for key in ('room', 'instance', 'articulation'):
            requests = copy.deepcopy(self.spec['objects']); requests[0][key] = 'Unknown'
            requests[0]['id'] = '.'.join(requests[0][k] for k in ('room', 'instance', 'articulation'))
            with self.subTest(reference=key), self.assertRaises(ValueError): self.derive(requests)

    def malformed_joint_sources(self):
        for field, key in [('axis', 0), ('axis', 2), ('front', 0), ('front', 1),
                           ('limits_deg', 0), ('states', 'closed')]:
            for value in (False, True, None, '0', float('nan'), float('inf'), -float('inf')):
                source = copy.deepcopy(self.art)
                source['types']['fridge']['Door'][field][key] = value
                yield field, key, value, source

    def test_joint_numbers_reject_boolean_nonfinite_and_nonnumeric_values(self):
        for field, key, value, source in self.malformed_joint_sources():
            with self.subTest(field=field, key=key, value=value), self.assertRaises(ValueError):
                articulation.validate(source)

    def test_schema_rejects_the_same_malformed_joint_numbers(self):
        try: from jsonschema import Draft202012Validator, ValidationError
        except ImportError: self.skipTest('jsonschema is unavailable')
        validator = Draft202012Validator(json.loads(articulation.SCHEMA.read_text()))
        for field, key, value, source in self.malformed_joint_sources():
            with self.subTest(field=field, key=key, value=value), self.assertRaises(ValidationError):
                validator.validate(source)

    def test_object_view_cannot_leave_kitchen_even_with_valid_parameter(self):
        requests = copy.deepcopy(self.spec['objects']); requests[0]['view_distance']['value'] = 3000
        with self.assertRaisesRegex(ValueError, 'outside kitchen'): self.derive(requests)

    def test_typed_assumptions_and_duplicate_objects_are_rejected(self):
        for field, value in [('duration', -1), ('duration', float('nan')), ('view_distance', True), ('view_distance', 10000)]:
            requests = copy.deepcopy(self.spec['objects']); requests[0][field]['value'] = value
            with self.subTest(field=field,value=value), self.assertRaises(ValueError): articulation.validate_requests(requests)
        with self.assertRaises(ValueError): articulation.validate_requests(self.spec['objects']*2)

    def test_articulation_preserves_native_dependencies_and_files(self):
        paths = stack.source_dependencies(self.building)
        self.assertNotIn(Path(articulation.__file__), paths)
        self.assertNotIn(ROOT/self.spec['articulation_source']['source'], paths)
        pins = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        self.derive(self.spec['objects'])
        for path, before in pins.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before, str(path))

    def test_sources_match_schemas(self):
        try: from jsonschema import Draft202012Validator
        except ImportError: self.skipTest('jsonschema is unavailable; runtime contract validation is exercised')
        for source, schema in [(self.art, articulation.SCHEMA), (self.spec, walkthrough.SCHEMA)]:
            Draft202012Validator(json.loads(schema.read_text())).validate(source)


if __name__ == '__main__': unittest.main()
