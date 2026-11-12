"""Registration tests use invented polygons, never copied photograph geometry."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import ground_floor_model as model
from test_building_stack import invented_plan
REFERENCE_FUNCTION = model.reference_plan


def source():
    plan = invented_plan()
    raw = copy.deepcopy(plan); raw['format'] = model.FORMAT
    raw['reference_floorplan'] = {'source': 'model/fixture.json', 'source_sha256': 'a'*64}
    raw['registration'] = copy.deepcopy(model.REGISTRATION)
    raw['vertices']['ReferenceRoomV0'] = {'reference_vertex': 'ReferenceRoomV0'}
    return raw, plan


class GroundFloorTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.reference = source()
        patcher = mock.patch.object(model, 'reference_plan', return_value=self.reference)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_reference_vertices_resolve_once_and_literals_are_not_rotated_again(self):
        original = copy.deepcopy(self.raw); plan = model.resolve(self.raw)
        self.assertEqual(plan['vertices'], self.reference['vertices'])
        self.assertEqual(plan['format'], model.floor.FORMAT)
        self.assertNotIn('registration', plan); self.assertNotIn('reference_floorplan', plan)
        self.assertEqual(self.raw, original)
        plan['vertices']['ReferenceRoomV0'][0] = 42
        self.assertEqual(self.reference['vertices']['ReferenceRoomV0'], [0, 0])

    def test_unknown_reference_registration_and_extra_metadata_are_rejected(self):
        for change in ['vertex', 'rotation', 'apply', 'metric', 'extra', 'nested']:
            raw = copy.deepcopy(self.raw)
            if change == 'vertex': raw['vertices']['ReferenceRoomV0']['reference_vertex'] = 'Absent'
            elif change == 'rotation': raw['registration']['orientation_deg'] = 0
            elif change == 'apply': raw['registration']['applied_to_literals'] = False
            elif change == 'metric': raw['registration']['metric_scale_known'] = True
            elif change == 'extra': raw['photograph'] = '/private/original.jpg'
            else: raw['vertices']['ReferenceRoomV0']['image'] = 'not permitted'
            with self.subTest(change=change), self.assertRaises(ValueError): model.resolve(raw)

    def test_invalid_topology_and_nonfinite_coordinates_still_use_relative_validator(self):
        for value in [[float('nan'), 0], [True, 0], [0, 0, 1]]:
            raw = copy.deepcopy(self.raw); raw['vertices']['ReferenceRoomV0'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): model.resolve(raw)
        raw = copy.deepcopy(self.raw); raw['areas'][0]['boundary'].pop()
        with self.assertRaises(ValueError): model.resolve(raw)

    def test_load_pins_exact_raw_bytes_and_drift_blocks_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'source.json'; raw = json.dumps(self.raw).encode(); path.write_bytes(raw)
            plan = model.load(path)
            self.assertEqual(plan['_source']['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(model.registration(plan), model.REGISTRATION)
            path.write_bytes(raw+b'\n')
            with self.assertRaises(ValueError): model.raw_source(plan)

    def test_pin_and_path_guards_use_the_shared_reference_loader(self):
        for reference in [
            {'source': 'model/floor-f03.shared.json', 'source_sha256': '0'*64},
            {'source': '../outside.json', 'source_sha256': '0'*64},
            {'source': 'model/floor-f03.shared.json'},
        ]:
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                REFERENCE_FUNCTION(reference)

    def test_schema_accepts_literals_or_references_but_no_metric_or_original_image_fields(self):
        try:
            from jsonschema import Draft202012Validator, ValidationError
            from referencing import Registry, Resource
        except ImportError: self.skipTest('Optional jsonschema dependency required')
        resources = []
        for name in ['assembly-reference.schema.json', 'relative-floorplan.schema.json', 'ground-floor.schema.json']:
            path = ROOT/'model'/name; schema = json.loads(path.read_text()); Draft202012Validator.check_schema(schema)
            schema['$id'] = path.as_uri(); resources.append((schema['$id'], Resource.from_contents(schema)))
        validator = Draft202012Validator(schema, registry=Registry().with_resources(resources)); validator.validate(self.raw)
        for mutation in [{'registration': {**self.raw['registration'], 'applied_to_literals': False}}, {'image_path': 'original.jpg'}, {'calibration': {'scale': 20}}]:
            bad = {**self.raw, **mutation}
            with self.assertRaises(ValidationError): validator.validate(bad)


if __name__ == '__main__': unittest.main()
