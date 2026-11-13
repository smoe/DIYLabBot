"""Source projection and static placement checks; native CAD runs are separate."""
import copy
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import kit_storage_model as model

try:
    from jsonschema import Draft202012Validator, ValidationError
    from referencing import Registry, Resource
except ImportError:
    Draft202012Validator = None


def bbox_fixture(spec, p):
    """Synthetic measurement fixture for negative guards, not native evidence."""
    result = {}
    for operation in model.expanded(spec, p)['operations']:
        if operation['action'] == 'cut':
            continue
        shape = model.numeric_shape(operation['shape'], p); low = shape['origin']
        if shape['kind'] == 'box':
            high = [a+b for a, b in zip(low, shape['size'])]
        else:
            x, y, z = low; r = shape['radius']; low = [x-r, y-r, z]; high = [x+r, y+r, z+shape['height']]
        if operation['action'] == 'join':
            old = result[operation['body']]['bbox']
            low = [min(a, b) for a, b in zip(low, old['min'])]; high = [max(a, b) for a, b in zip(high, old['max'])]
        result[operation['body']] = {'body': operation['body'], 'bbox': {'min': low, 'max': high}}
    return list(result.values())


class StorageModelTests(unittest.TestCase):
    def setUp(self):
        self.spec = model.load(); self.p = model.parameters(self.spec)

    def test_four_layers_reference_existing_sources_without_copied_kit_definitions(self):
        self.assertEqual(set(self.spec['sources']), {'environment', 'furniture', 'furnishings', 'kit'})
        self.assertEqual(model.read(self.spec['sources']['environment'])['geometry'], 'none')
        self.assertEqual(model.read(self.spec['sources']['furniture'])['types']['reference_worktop']['recipe'], 'box_envelope')
        raw = model.SOURCE.read_text()
        selected = model.selected_carrier(self.spec)
        for item in selected['module']['materials']:
            self.assertNotIn('"'+item['material_id']+'"', raw)
        self.assertEqual(set(json.loads(raw)['parameters']), set(model.DRIVING))
        self.assertNotIn('bodies', json.loads(raw))

    def test_explicit_interface_selects_exactly_one_complete_closed_rna_carrier(self):
        selected = model.selected_carrier(self.spec); contract = model.interfaces(self.spec, self.p)
        self.assertEqual(len(selected['body_ids']), 17)
        self.assertEqual(set(contract['source_body_map'].values()), set(selected['body_ids']))
        self.assertNotIn('ReferenceFloor', contract['source_body_map'].values())
        self.assertFalse(any(body.startswith('DNA_') for body in contract['source_body_map'].values()))
        self.assertEqual(contract['carrier']['module_id'], 'RNA')
        self.assertEqual(contract['carrier']['source_case'], 'stored')

    def test_both_static_cases_preserve_carrier_content_and_source_body_identities(self):
        views = [model.interfaces(model.materialize(self.spec, case['id']), self.p) for case in model.cases(self.spec)]
        self.assertEqual([v['active_location_id'] for v in views], ['S01.Shelf01', 'S01.Handover01'])
        self.assertEqual(views[0]['carrier'], views[1]['carrier'])
        self.assertEqual(views[0]['source_body_map'], views[1]['source_body_map'])
        contents = views[0]['carrier']['symbolic_contents']
        self.assertEqual(len(contents), 9)
        self.assertEqual(len({v['id'] for v in contents}), 9)
        self.assertEqual(len({v['material_id'] for v in contents}), 9)
        collection = next(v for v in contents if 'collection_tube' in v['roles'])
        self.assertEqual(set(collection['roles']), {'collection_tube', 'gdna_collection_tube'})
        self.assertTrue(all(v['status'] == 'symbolic_unobserved' for v in contents))

    def test_projected_geometry_is_the_exact_source_recipe_with_only_one_translation(self):
        for case in model.cases(self.spec):
            spec = model.materialize(self.spec, case['id']); p = model.parameters(spec)
            selected = model.selected_carrier(spec); data = model.expanded(spec, p); contract = data['interfaces']
            prefix = spec['carrier']['body_prefix']; delta = contract['instance_translation_mm']
            actual = {op['id']: op for op in data['operations']}
            for source in selected['source']['operations']:
                if source['body'] not in selected['body_ids']:
                    continue
                current = actual[prefix+source['id']]
                a = model.numeric_shape(current['shape'], p); b = model.numeric_shape(source['shape'], selected['p'])
                self.assertEqual(current['action'], source['action'])
                for x, y, shift in zip(a.pop('origin'), b.pop('origin'), delta):
                    self.assertAlmostEqual(x, y+shift)
                self.assertEqual(a, b)
            self.assertEqual(len(data['bodies']), 22)
            self.assertEqual(data['joints'], [])

    def test_frames_and_clearance_probes_use_the_same_translation_as_geometry(self):
        for case in model.cases(self.spec):
            spec = model.materialize(self.spec, case['id']); contract = model.interfaces(spec, self.p)
            source = model.selected_carrier(spec)['contract']; shift = contract['instance_translation_mm']
            self.assertEqual(len(contract['frames']), 4); self.assertEqual(len(contract['native_clearance_probes']), 8)
            for frame in contract['frames'].values():
                original = source['frames'][frame['source_frame_id']]
                self.assertEqual(frame['axes'], original['axes'])
                self.assertEqual(frame['origin_mm'], [a+b for a, b in zip(original['origin_mm'], shift)])
            originals = {p['id']: p for p in source['native_clearance_probes']}
            for probe in contract['native_clearance_probes']:
                original = originals[probe['source_probe_id']]
                self.assertEqual(probe['origin_mm'], [a+b for a, b in zip(original['origin_mm'], shift)])
                self.assertEqual(probe['size_mm'], original['size_mm'])
                self.assertEqual(probe['minimum_clearance_mm'], original['minimum_clearance_mm'])
                self.assertIn(probe['frame_id'], contract['frames'])

    def test_asymmetric_front_and_rear_margins_preserve_their_meaning_at_both_places(self):
        for front, back in [(25, 15), (10, 25)]:
            p = model.parameters(self.spec, {'shelf_margin_front': front, 'shelf_margin_back': back})
            for case in model.cases(self.spec):
                spec = model.materialize(self.spec, case['id']); contract = model.interfaces(spec, p)
                for location in contract['locations'].values():
                    box = location['support_bbox_mm']; footprint = location['footprint_bbox_mm']
                    self.assertAlmostEqual(footprint['min'][1]-box['min'][1], front)
                    self.assertAlmostEqual(box['max'][1]-footprint['max'][1], back)
                support = contract['support']; self.assertEqual(support['footprint_bbox_mm']['min'][2], support['contact_z_mm'])
                self.assertTrue(all(row['passed'] for row in model.check_interface_geometry(spec, p, bbox_fixture(spec, p))))

    def test_native_parameter_closure_is_derived_in_memory_and_tracks_variants(self):
        original = copy.deepcopy(self.spec)
        p = model.parameters(self.spec, {'shelf_margin_x': 30, 'support_top': 220})
        native = model.native_spec(self.spec, p)
        self.assertEqual(self.spec, original)
        self.assertEqual(set(native['parameters']), set(model.DRIVING) | set(model.DERIVED))
        for name in model.DERIVED:
            self.assertEqual(native['parameters'][name]['expression'], p[name])
        self.assertEqual(model.interfaces(self.spec, p)['locations']['source']['support_bbox_mm']['max'][2], 220)
        self.assertTrue(all(row['passed'] for row in model.check_interface_geometry(native, p, bbox_fixture(native, p))))
        native['parameters']['carrier_width']['expression'] += 1
        with self.assertRaises(ValueError):
            model.parameters(native)

    def test_native_placement_guards_detect_missing_or_shifted_carrier_support_and_guides(self):
        for case in model.cases(self.spec):
            spec = model.materialize(self.spec, case['id']); measurements = bbox_fixture(spec, self.p)
            checks = model.check_interface_geometry(spec, self.p, measurements)
            self.assertEqual(len(checks), 22); self.assertEqual(len({c['id'] for c in checks}), 22)
            self.assertTrue(all(c['passed'] for c in checks))
            for body in ['Carrier01_RNA_Container', 'Carrier01_RNA_Lid', 'ShelfSupport', 'HandoverSupport', 'NestGuideBack']:
                changed = copy.deepcopy(measurements); item = next(row for row in changed if row['body'] == body)
                item['bbox']['min'][1] += 1; item['bbox']['max'][1] += 1
                with self.subTest(case=case['id'], body=body):
                    self.assertFalse(all(c['passed'] for c in model.check_interface_geometry(spec, self.p, changed)))
            with self.assertRaises(ValueError):
                model.check_interface_geometry(spec, self.p, measurements[1:])

    def test_carrier_floor_is_fully_within_its_selected_support_and_guides_are_supported(self):
        for case in model.cases(self.spec):
            contract = model.interfaces(model.materialize(self.spec, case['id']), self.p)
            support = contract['support']; location = next(v for v in contract['locations'].values() if v['id'] == support['location_id'])
            self.assertEqual(support['contact_z_mm'], location['support_bbox_mm']['max'][2])
            for axis in (0, 1):
                self.assertGreaterEqual(support['footprint_bbox_mm']['min'][axis], location['support_bbox_mm']['min'][axis])
                self.assertLessEqual(support['footprint_bbox_mm']['max'][axis], location['support_bbox_mm']['max'][axis])
            handover = contract['locations']['handover']['support_bbox_mm']
            for guide in contract['nest']['guide_bboxes_mm'].values():
                self.assertEqual(guide['min'][2], handover['max'][2])
                for axis in (0, 1):
                    self.assertGreater(guide['min'][axis], handover['min'][axis])
                    self.assertLess(guide['max'][axis], handover['max'][axis])

    def test_wrong_module_pose_reference_pin_and_colliding_identities_are_rejected(self):
        for change in ['module', 'pose', 'pin', 'place_id', 'content_id']:
            spec = copy.deepcopy(self.spec)
            if change == 'module': spec['carrier']['module_id'] = 'DNA'
            elif change == 'pose': spec['carrier']['source_case'] = 'open'
            elif change == 'pin': spec['sources']['kit']['source_sha256'] = '0'*64
            elif change == 'place_id': spec['locations']['handover']['id'] = spec['locations']['source']['id']
            else: spec['locations']['source']['id'] = spec['carrier']['id']+'.Content01'
            with self.subTest(change=change), self.assertRaises(ValueError):
                model.validate(spec)

    def test_invalid_parameters_and_coupled_guide_limits_are_rejected(self):
        for values in [{'unknown': 1}, {'support_top': True}, {'place_gap': float('nan')}, {'nest_clearance': 0}, {'carrier_width': 230}]:
            with self.subTest(values=values), self.assertRaises(ValueError): model.parameters(self.spec, values)
        for name, value in [('nest_guide_h', 28), ('nest_clearance', 1), ('shelf_margin_x', 6), ('support_top', 10)]:
            bad = copy.deepcopy(self.spec); bad['parameters'][name]['expression'] = value; bad['parameters'][name]['range'] = [value, value]
            with self.subTest(coupled=name), self.assertRaises(ValueError): model.parameters(bad)

    def test_unsupported_furnishings_and_unsupported_footprints_are_rejected(self):
        original = model.read; reference = self.spec['sources']['furnishings']; furniture = original(reference)
        for change in ['too_small', 'same_place', 'rotation', 'third_place']:
            altered = copy.deepcopy(furniture)
            if change == 'too_small': altered['instances'][0]['bindings']['width'] = 100
            elif change == 'same_place': altered['instances'][1]['xyz'][1] = 0
            elif change == 'rotation': altered['instances'][0]['yaw_deg'] = 90
            else: altered['instances'].append(copy.deepcopy(altered['instances'][0]))
            with mock.patch.object(model, 'read', side_effect=lambda ref: copy.deepcopy(altered) if ref == reference else original(ref)):
                with self.subTest(change=change), self.assertRaises(ValueError): model.validate(self.spec)

    def test_static_case_api_rejects_fake_joint_motion(self):
        for case in model.cases(self.spec):
            spec = model.materialize(self.spec, case['id']); expanded = model.expanded(spec, self.p)
            self.assertEqual(model.pose(spec, self.p), {})
            self.assertEqual(model.samples(spec, self.p), [{'id': case['id'], 'values_mm': {}}])
            model.validate_pose(expanded, {})
            with self.assertRaises(ValueError): model.validate_pose(expanded, {'Rail': 1})
        with self.assertRaises(ValueError): model.materialize(self.spec, 'moving')
        with self.assertRaises(ValueError): model.pose(self.spec, self.p, 'handover')

    def test_runtime_projection_is_byte_bound_immutable_and_has_no_store_effects(self):
        before = copy.deepcopy(self.spec)
        with mock.patch.object(sqlite3, 'connect', side_effect=AssertionError('No journal')), mock.patch.object(socket, 'socket', side_effect=AssertionError('No network')), mock.patch.object(subprocess, 'run', side_effect=AssertionError('No device')):
            first = model.runtime_definition(self.spec)
            second = model.runtime_definition(model.materialize(self.spec, 'handover'))
        self.assertEqual(first, second); self.assertEqual(self.spec, before)
        self.assertEqual(first['route'], [first['locations'][role]['id'] for role in ('source', 'handover', 'source')])
        self.assertTrue(all(model.digest(ROOT/path) == sha for path, sha in first['source_files_sha256'].items()))
        first['carrier']['symbolic_contents'][0]['material_id'] = 'changed'
        self.assertNotEqual(first, model.runtime_definition(self.spec))
        bad = copy.deepcopy(self.spec); bad['parameters']['shelf_margin_x']['expression'] = 30
        with self.assertRaises(ValueError): model.runtime_definition(bad)
        bad = copy.deepcopy(self.spec); bad['_source']['sha256'] = '0'*64
        with self.assertRaises(ValueError): model.runtime_definition(bad)

    def test_quantities_real_measurements_and_qualification_claims_are_rejected(self):
        for change in ['stock', 'measured_dimensions', 'trajectory_implemented', 'grasp_qualified', 'shelf_load_qualified']:
            bad = copy.deepcopy(self.spec)
            if change == 'stock': bad['stock'] = {'quantity': 1}
            elif change == 'measured_dimensions': bad[change] = {'width_mm': 260}
            else: bad['qualification'][change] = True
            with self.subTest(change=change), self.assertRaises(ValueError): model.validate(bad)

    def test_commands_use_the_shared_adapter_and_dependencies_preserve_cad_independence(self):
        with mock.patch.object(model.portable, 'solidcraft_commands', wraps=model.portable.solidcraft_commands) as shared:
            commands = model.solidcraft_commands(self.spec, self.p)
        shared.assert_called_once()
        self.assertFalse(any(c['command'] in {'joint.create', 'joint.drive'} for c in commands))
        names = [str(path.relative_to(ROOT)) for path in model.source_dependencies(self.spec)]
        self.assertIn(self.spec['sources']['furnishings']['source'], names)
        self.assertIn('scripts/extraction_kit_station.py', names)
        self.assertFalse(any('glassware' in path or path.endswith(('.FCStd', '.sc', '.step')) for path in names))

    @unittest.skipIf(Draft202012Validator is None, 'Optional jsonschema development dependency required')
    def test_both_leading_sources_validate_with_local_schemas(self):
        resources = []; schemas = {}
        for name in ['assembly-reference.schema.json', 'room-geometry.schema.json', 'furnishings.schema.json', 'kit-storage-s01.schema.json']:
            path = ROOT/'model'/name; schema = json.loads(path.read_text()); Draft202012Validator.check_schema(schema)
            schema['$id'] = path.as_uri(); resources.append((schema['$id'], Resource.from_contents(schema))); schemas[name] = schema
        registry = Registry().with_resources(resources)
        validator = Draft202012Validator(schemas['kit-storage-s01.schema.json'], registry=registry)
        raw = json.loads(model.SOURCE.read_text()); validator.validate(raw)
        Draft202012Validator(schemas['furnishings.schema.json'], registry=registry).validate(model.read(self.spec['sources']['furnishings']))
        for change in ['pin', 'measured', 'derived_copy']:
            bad = copy.deepcopy(raw)
            if change == 'pin': del bad['sources']['kit']['source_sha256']
            elif change == 'measured': bad['measured_dimensions'] = {'width_mm': 220}
            else: bad['parameters']['carrier_width'] = {'expression': 220, 'unit': 'mm', 'range': [220, 220], 'description': 'copy'}
            with self.subTest(change=change), self.assertRaises(ValidationError): validator.validate(bad)


if __name__ == '__main__':
    unittest.main()
