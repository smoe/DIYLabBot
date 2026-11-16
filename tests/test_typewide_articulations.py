"""Type changes apply to placed instances without per-instance UI requests."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_furnishings as furnishings
import furniture_articulation as articulation


def rectangle_plan():
    vertices = {'A': [0, 0], 'B': [10000, 0], 'C': [10000, 10000], 'D': [0, 10000]}
    walls = [{'id': str(i), 'start': a, 'end': b}
             for i, (a, b) in enumerate(zip('ABCD', 'BCDA'))]
    return {'vertices': vertices, 'walls': walls, 'areas': [
        {'id': 'Room', 'boundary': [{'wall': wall['id'], 'direction': 1} for wall in walls]}]}


class TypewideArticulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_path = ROOT/'model/furniture/social.articulations.json'
        cls.ref = {'source': str(cls.source_path.relative_to(ROOT)),
                   'source_sha256': hashlib.sha256(cls.source_path.read_bytes()).hexdigest()}
        cls.source = articulation.read(cls.ref)
        cls.catalog = articulation.validate(cls.source)

    def social_fixture(self, type_id='fridge'):
        identity = {'fridge': 'Fridge', 'microwave': 'Microwave'}[type_id]
        room = {'id': 'Kitchen1008', 'room': '1.008', 'level': 'OG1',
                'template_areas': ['Room'], 'instances': [
                    {'id': identity, 'type': type_id}, {'id': 'Second'+identity, 'type': type_id}]}
        placed = [furnishings.instantiate(self.catalog, type_id, 'Kitchen1008_'+instance['id'],
                   'FixtureRoom', [2000+index*3000, 2000, 0], 0)
                  for index, instance in enumerate(room['instances'])]
        expanded = {key: [item for value in placed for item in value[key]]
                    for key in ('bodies', 'operations')}
        body_ids = [body['id'] for body in expanded['bodies']]
        interface = {'levels': [{'id': 'OG1', 'z_mm': 0}],
                     'furnishings': {'rooms': [{'id': room['id'], 'body_ids': body_ids}]}}
        fixture_source = {'catalog': self.source['catalog'], 'rooms': [room]}
        fixture_ref = {'source': 'fixture/furnishings.json', 'source_sha256': 'f'*64}
        building = {'sources': {'furnishings': fixture_ref}}
        return building, fixture_ref, fixture_source, interface, expanded

    def derive_social(self, profile=None, type_id='fridge'):
        building, fixture_ref, source, interface, expanded = self.social_fixture(type_id)
        original_read = articulation.read
        def read(ref):
            if ref == fixture_ref:
                return source
            if ref == self.ref and profile is not None:
                return profile
            return original_read(ref)
        with mock.patch.object(articulation, 'read', side_effect=read):
            return articulation.compile_objects(self.ref, [], building, {'display_scale': 1},
                interface, expanded, {'OG1': rectangle_plan()}, 1600)

    def test_second_fridge_gets_its_joint_without_an_instance_request(self):
        objects = self.derive_social()
        self.assertEqual({obj['id'] for obj in objects},
                         {'Kitchen1008.Fridge.Door', 'Kitchen1008.SecondFridge.Door'})
        first, second = objects
        self.assertEqual(first['label'], 'Kühlschrank 1.008')
        self.assertEqual(first['duration_s'], 1.2)
        self.assertEqual(first['commands']['open'], {'label': 'Öffnen', 'target_state': 'open'})
        self.assertFalse(set(first['moving_body_ids']) & set(second['moving_body_ids']))
        for obj in objects:
            self.assertEqual(len(obj['moving_body_ids']), 2)
            self.assertEqual(obj['joint']['type'], 'revolute')
            self.assertEqual(obj['states'], {'closed': 0, 'open': 90})

    def test_type_presentation_update_applies_to_both_instances(self):
        source = copy.deepcopy(self.source)
        source['types']['fridge']['Door']['presentation']['duration']['value'] = 2.5
        source['types']['fridge']['Door']['presentation']['commands']['open'] = 'Open door'
        for obj in self.derive_social(source):
            self.assertEqual(obj['duration_s'], 2.5)
            self.assertEqual(obj['commands']['open']['label'], 'Open door')

    def test_second_microwave_gets_preserved_master_presentation_without_requests(self):
        objects = self.derive_social(type_id='microwave')
        self.assertEqual({obj['id'] for obj in objects},
                         {'Kitchen1008.Microwave.Door', 'Kitchen1008.SecondMicrowave.Door'})
        for obj in objects:
            self.assertEqual(obj['label'], 'Mikrowelle 1.008')
            self.assertEqual(obj['duration_s'], 0.8)
            self.assertEqual(obj['joint']['type'], 'revolute')
            self.assertEqual(obj['states'], {'closed': 0, 'open': 90})
            self.assertEqual(obj['commands']['open'], {'label': 'Öffnen', 'target_state': 'open'})
            self.assertEqual(len(obj['moving_body_ids']), 3)
        self.assertFalse(set(objects[0]['moving_body_ids']) & set(objects[1]['moving_body_ids']))
        source = copy.deepcopy(self.source)
        source['types']['microwave']['Door']['presentation']['duration']['value'] = 1.6
        for obj in self.derive_social(source, type_id='microwave'):
            self.assertEqual(obj['duration_s'], 1.6)

    def lab_fixture(self):
        body_ids = ['Lab3003_Cabinet_Door', 'Lab3003_Stool_Seat']
        expanded = {'bodies': [{'id': name} for name in body_ids], 'operations': [
            {'id': body_ids[0], 'body': body_ids[0], 'action': 'create',
             'shape': {'kind': 'box', 'origin': [2000, 2000, 100], 'size': [18, 450, 700]}},
            {'id': body_ids[1], 'body': body_ids[1], 'action': 'create',
             'shape': {'kind': 'cylinder', 'origin': [5000, 5000, 450], 'radius': 200, 'height': 35}},
        ]}
        lab = {'id': 'Lab3003', 'room': '3.003', 'level_id': 'OG3',
               'template_areas': ['Room'], 'furniture_body_ids': body_ids, 'joints': [
                   {'instance_id': 'Cabinet', 'articulation_id': 'Door1', 'type': 'revolute',
                    'origin_mm': [2018, 2000, 100], 'axis': [0, 0, -1], 'front': [1, 0, 0],
                    'limits_deg': [0, 90], 'value': 0, 'moving_body_ids': [body_ids[0]]},
                   {'instance_id': 'Stool', 'articulation_id': 'SeatLift', 'type': 'slider',
                    'origin_mm': [5000, 5000, 0], 'axis': [0, 0, 1], 'front': [0, -1, 0],
                    'limits_mm': [0, 200], 'value': 0, 'moving_body_ids': [body_ids[1]]},
               ]}
        return {'levels': [{'id': 'OG3', 'z_mm': 0}], 'laboratories': [lab]}, expanded

    def derive_lab(self, interface=None, expanded=None):
        if interface is None:
            interface, expanded = self.lab_fixture()
        return articulation.compile_lab_objects(self.ref, interface, expanded,
            {'OG3': rectangle_plan()}, {'display_scale': 1}, 1600)

    def test_lab_door_and_stool_use_recipe_frames_and_type_labels(self):
        door, stool = self.derive_lab()
        self.assertEqual(door['id'], 'Lab3003.Cabinet.Door1')
        self.assertEqual(door['joint']['origin_mm'], [2018, 2000, 100])
        self.assertEqual(door['joint']['axis'], [0, 0, -1])
        self.assertEqual(stool['id'], 'Lab3003.Stool.SeatLift')
        self.assertEqual(stool['joint']['type'], 'prismatic')
        self.assertEqual(stool['joint']['limits_mm'], [0, 200])
        self.assertNotIn('limits_deg', stool['joint'])
        self.assertEqual(stool['states'], {'closed': 0, 'open': 200})
        self.assertEqual(stool['commands']['open']['label'], 'Anheben')
        self.assertEqual(stool['commands']['close']['label'], 'Absenken')
        self.assertTrue(all(value is False for obj in (door, stool) for value in obj['qualification'].values()))

    def test_lab_objects_cannot_claim_missing_or_shared_child_bodies(self):
        interface, expanded = self.lab_fixture()
        for moving in [['UnknownBody'], interface['laboratories'][0]['joints'][0]['moving_body_ids']]:
            broken = copy.deepcopy(interface)
            broken['laboratories'][0]['joints'][1]['moving_body_ids'] = moving
            with self.subTest(moving=moving), self.assertRaises(ValueError):
                self.derive_lab(broken, expanded)

    def test_lab_objects_reject_false_numeric_frames_and_reference_poses(self):
        interface, expanded = self.lab_fixture()
        for key, value in [('axis', [0, 0, True]), ('origin_mm', [0, float('nan'), 0]),
                           ('limits_mm', [0, float('inf')]), ('value', 100)]:
            broken = copy.deepcopy(interface)
            broken['laboratories'][0]['joints'][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.derive_lab(broken, expanded)

    def test_type_templates_cannot_access_attributes_or_nonsemantic_fields(self):
        for label in ['{room.__class__}', '{unknown}', '{room!r}', '{room:>20}']:
            source = copy.deepcopy(self.source)
            source['types']['fridge']['Door']['presentation']['label'] = label
            with self.subTest(label=label), self.assertRaises(ValueError):
                articulation.validate(source)

    def test_type_source_matches_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is unavailable')
        Draft202012Validator(json.loads(articulation.SCHEMA.read_text())).validate(self.source)


if __name__ == '__main__':
    unittest.main()
