"""Concept-stack tests use invented room/atrium polygons, not copied plan data."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_stack as model

try:
    from jsonschema import Draft202012Validator, ValidationError
    from referencing import Registry, Resource
except ImportError:
    Draft202012Validator = None


def invented_plan():
    result = {'format': model.floor.FORMAT, 'id': 'InventedFloor', 'units': {'length': 'relative'}, 'calibration': None, 'vertices': {}, 'walls': [], 'areas': [], 'openings': [],
              'provenance': {'method': 'manual_trace', 'source_kind': 'synthetic_fixture', 'accuracy': 'approximate', 'notes': ['Invented polygons only.']}}
    for name, kind, points in [('ReferenceRoom', 'room', [[0, 0], [2, 0], [2, 1], [0, 1]]),
                               ('Atrium', 'void', [[3, 0], [6, 0], [6, 1], [4, 1], [4, 3], [3, 3]]),
                               ('Unknown', 'unknown', [[0, 2], [1, 2], [1, 3], [0, 3]])]:
        ids = [name+'V'+str(i) for i in range(len(points))]
        result['vertices'].update(zip(ids, points)); refs = []
        for index, (a, b) in enumerate(zip(ids, ids[1:]+ids[:1])):
            wall = name+'W'+str(index); result['walls'].append({'id': wall, 'start': a, 'end': b, 'kind': 'wall'}); refs.append({'wall': wall, 'direction': 1})
        result['areas'].append({'id': name, 'label': name, 'kind': kind, 'boundary': refs, 'confidence': 'approximate'})
    result['openings'] = [{'id': 'Door', 'wall': 'ReferenceRoomW0', 'interval': [.2, .4], 'kind': 'door', 'confidence': 'approximate', 'connection': 'uncertain'}]
    model.floor.validate(result)
    return result


class StackTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(model.SOURCE.read_text()); self.spec.pop('exterior', None); self.spec['sources'].pop('furnishings', None)
        self.spec['presentation_reference']['floorplan_area'] = 'ReferenceRoom'
        self.plan = invented_plan()
        self.ground_plan = copy.deepcopy(self.plan)
        ground_atrium = next(a for a in self.ground_plan['areas'] if a['id'] == 'Atrium')
        ground_atrium.update(id='GroundHall', kind='corridor')
        self.mock_levels = mock.patch.object(model, 'level_plan', side_effect=lambda spec, level: copy.deepcopy(self.ground_plan if level == 'EG' else self.plan))
        self.mock_roof = mock.patch.object(model.roof, 'compile', return_value={'components': [], 'bodies': [], 'operations': [], 'interface': {}})
        self.mock_levels.start(); self.addCleanup(self.mock_levels.stop)
        self.mock_roof.start(); self.addCleanup(self.mock_roof.stop)
        self.reference = {'format': 'solidcraftbot.room-geometry/1', 'units': {'length': 'mm', 'angle': 'deg'},
                          'parameters': {name: {'expression': value, 'unit': 'mm', 'measured_mm': None} for name, value in [('room_width', 20), ('wall_t', .2), ('door_height', 2)]}}
        self.mock_templates = mock.patch.object(model, 'templates', side_effect=lambda spec: (copy.deepcopy(self.plan), copy.deepcopy(self.reference)))
        self.mock_room = mock.patch.object(model.room, 'parameters', side_effect=model.robot.parameters)
        # These small fixtures exercise the original stack projection only.
        # The circulation recipe has its own complete, metre-sized fixtures.
        self.mock_circulation = mock.patch.object(model.circulation, 'compile', return_value={'components': [], 'bodies': [], 'operations': [], 'interface': {'wall_bridge_ids': []}})
        self.mock_templates.start(); self.mock_room.start()
        self.mock_circulation.start(); self.addCleanup(self.mock_circulation.stop)
        self.addCleanup(self.mock_templates.stop); self.addCleanup(self.mock_room.stop)

    def test_experimental_alignment_contract_cannot_silently_deform_floorplans(self):
        spec=copy.deepcopy(self.spec)
        spec['alignment']={'method':'boundary_arclength_harmonic_displacement'}
        with self.assertRaisesRegex(ValueError,'building stack'):
            model.validate(spec)

    def test_five_scoped_instances_and_explicit_assumed_dimensions(self):
        model.validate(self.spec); p = model.parameters(self.spec); data = model.interfaces(self.spec, p)
        self.assertEqual([level['id'] for level in data['levels']], ['KG', 'EG', 'OG1', 'OG2', 'OG3'])
        self.assertEqual([level['z_mm'] for level in data['levels']], [-4250, 0, 4250, 8500, 12750])
        self.assertEqual(data['floor_pitch_mm'], 4250)
        self.assertEqual(p['display_scale'], 10)
        self.assertEqual(data['coordinate_meaning'], {'xy': 'presentation_mm', 'z': 'assumed_mm'})
        self.assertFalse(data['metric_scale_known']); self.assertFalse(data['transport_implemented'])
        self.assertNotIn('bodies', self.spec); self.assertNotIn('vertices', self.spec)

    def test_height_and_slab_variants_update_every_level_and_marker_without_z_copies(self):
        before = copy.deepcopy(self.spec)
        p = model.parameters(self.spec, {'clear_height_mm': 3500, 'slab_thickness_mm': 200}); data = model.interfaces(self.spec, p)
        self.assertEqual([level['z_mm'] for level in data['levels']], [-3700, 0, 3700, 7400, 11100])
        for level in data['levels']:
            self.assertEqual(level['slab_top_mm']-level['slab_bottom_mm'], 200)
            self.assertEqual(level['clear_top_mm']-level['z_mm'], 3500)
        self.assertEqual(data['concept_marker']['depth_mm'], 14600)
        self.assertEqual(model.parameters(model.native_spec(self.spec, p)), p)
        self.assertEqual(self.spec, before)

    def test_xy_scale_tracks_reference_parameter_but_never_becomes_calibration(self):
        first = model.parameters(self.spec)
        self.reference['parameters']['room_width']['expression'] = 40
        second = model.parameters(self.spec)
        self.assertEqual(second['display_scale'], 2*first['display_scale'])
        self.assertEqual(second['floor_pitch_mm'], first['floor_pitch_mm'])
        self.assertFalse(model.interfaces(self.spec, second)['metric_scale_known'])
        self.reference['parameters']['room_width']['unit'] = 'relative'
        with self.assertRaises(ValueError): model.parameters(self.spec)

    def test_exact_nonrectangular_atrium_fill_exists_only_on_ground(self):
        p = model.parameters(self.spec); data = model.interfaces(self.spec, p); expanded = model.expanded(self.spec, p)
        ground = data['ground_fill_probe']; polygon = model.floor.outline(self.plan, 'Atrium')
        self.assertEqual(ground['points_mm'], [[x*p['display_scale'], y*p['display_scale']] for x, y in polygon])
        self.assertEqual(len(ground['points_mm']), 6)
        self.assertEqual(ground['expected_volume_mm3'], 5*p['display_scale']**2*p['slab_thickness_mm'])
        self.assertLess(ground['expected_volume_mm3'], 9*p['display_scale']**2*p['slab_thickness_mm'])
        fills = [b for b in expanded['bodies'] if b['role'] == 'concept_ground_atrium_slab']
        self.assertEqual(fills, [])
        self.assertEqual(ground['expectation'], 'union_filled')
        self.assertIn('EG__Area_GroundHall', ground['target_bodies'])
        self.assertNotIn('target_body', ground)
        self.assertTrue(all('AtriumFloor' not in b['id'] for b in expanded['bodies']))
        self.assertEqual(len(data['atrium_prisms']), 3)
        for probe in data['atrium_prisms']:
            self.assertEqual(probe['points_mm'], ground['points_mm'])
            self.assertTrue(all('AtriumFloor' not in name for name in probe['target_bodies']))

    def test_projected_source_operations_only_change_scope_z_and_declared_door_height(self):
        p = model.parameters(self.spec); base = model.floor.expanded(self.plan, p); result = model.expanded(self.spec, p)
        operations = {op['id']: op for op in result['operations']}
        for index, level in enumerate(self.spec['levels']):
            chosen = self.ground_plan if level['id'] == 'EG' else self.plan
            for original in model.floor.expanded(chosen, p)['operations']:
                current = operations[level['id']+'__'+original['id']]
                a = model.numeric_shape(current['shape'], p); b = model.numeric_shape(original['shape'], p)
                self.assertEqual(a['points'], b['points'])
                self.assertEqual(a['offset'], b['offset']+(index-1)*p['floor_pitch_mm'])
                self.assertEqual(a['depth'], p['door_height_mm'] if original['id'] == 'Opening_Door' else b['depth'])
        names = [body['id'] for body in result['bodies']]
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(any('Area_Unknown' in name for name in names))
        self.assertEqual(result['joints'], [])

    def test_all_opening_probes_are_scoped_translated_and_inside_new_lintel(self):
        p = model.parameters(self.spec); data = model.interfaces(self.spec, p)
        self.assertEqual(len(data['opening_probes']), 5)
        for index, probe in enumerate(data['opening_probes']):
            self.assertTrue(probe['id'].startswith(self.spec['levels'][index]['id']+'__'))
            self.assertGreater(probe['offset_mm'], (index-1)*p['floor_pitch_mm'])
            self.assertLess(probe['offset_mm']+probe['depth_mm'], (index-1)*p['floor_pitch_mm']+p['door_height_mm'])

    def test_marker_is_strictly_inside_atrium_and_separate_from_physical_claims(self):
        p = model.parameters(self.spec); data = model.interfaces(self.spec, p)
        marker = data['concept_marker']; self.assertEqual(marker['status'], 'semantic_visualization_only')
        self.assertTrue(all(model.floor.point_membership(point, data['atrium_polygon_mm']) == 1 for point in marker['points_mm']))
        self.assertEqual(data['marker_body_ids'], ['ConceptExchange'])
        body = next(b for b in model.expanded(self.spec, p)['bodies'] if b['id'] == 'ConceptExchange')
        self.assertEqual(body['role'], 'semantic_exchange_marker'); self.assertLess(body['appearance']['opacity'], 1)
        for name in ['structural_qualified', 'transport_implemented', 'trajectory_implemented', 'hardware_executed', 'fire_safety_qualified']:
            self.assertFalse(data[name])
        self.spec['concept_exchange']['footprint_fraction'] = .9
        with self.assertRaises(ValueError): model.validate(self.spec)

    def test_unknown_keys_pins_qualified_flags_and_other_storeys_are_rejected(self):
        for change in ['extra', 'calibration', 'basement', 'upper_floor', 'qualified', 'limitations']:
            spec = copy.deepcopy(self.spec)
            if change == 'extra': spec['room_definitions'] = []
            elif change == 'calibration': spec['calibration'] = {'scale': 10}
            elif change == 'basement': spec['levels'][0]['id'] = 'Basement'
            elif change == 'upper_floor': spec['atrium']['floor_levels'].append('OG1')
            elif change == 'qualified': spec['qualification']['transport_implemented'] = True
            else: spec['limitations'] = [12]
            with self.subTest(change=change), self.assertRaises(ValueError): model.validate(spec)
        bad = copy.deepcopy(self.spec['sources']['floorplan']); bad['source_sha256'] = '0'*64
        with self.assertRaises(ValueError): model.read(bad)
        bad['source'] = '../outside.json'
        with self.assertRaises(ValueError): model.read(bad)

    def test_bad_parameter_values_source_reference_and_void_selection_are_rejected(self):
        for values in [{'clear_height_mm': True}, {'slab_thickness_mm': float('inf')}, {'display_scale': 2}, {'clear_height_mm': 2000}]:
            with self.subTest(values=values), self.assertRaises(ValueError): model.parameters(self.spec, values)
        for change in ['parameter', 'area', 'void']:
            spec = copy.deepcopy(self.spec)
            if change == 'parameter': spec['presentation_reference']['width_parameter'] = 'missing'
            elif change == 'area': spec['presentation_reference']['floorplan_area'] = 'Missing'
            else: spec['atrium']['area'] = 'ReferenceRoom'
            with self.subTest(change=change), self.assertRaises(ValueError): model.validate(spec)

    def test_static_api_and_shared_primitive_adapter_do_not_add_motion(self):
        p = model.parameters(self.spec)
        self.assertEqual(model.cases(self.spec), [{'id': 'stacked'}])
        self.assertEqual(model.pose(self.spec, p), {})
        with self.assertRaises(ValueError): model.materialize(self.spec, 'moving')
        with mock.patch.object(model.portable, 'solidcraft_commands', wraps=model.portable.solidcraft_commands) as shared:
            commands = model.solidcraft_commands(self.spec, p)
        shared.assert_called_once()
        self.assertFalse(any(c['command'] in {'joint.create', 'joint.drive', 'file.insert_step'} for c in commands))

    @unittest.skipIf(Draft202012Validator is None, 'Optional jsonschema development dependency required')
    def test_schema_is_local_strict_and_keeps_calibration_unknown(self):
        resources = []
        for name in ['assembly-reference.schema.json', 'building-stack.schema.json']:
            path = ROOT/'model'/name; schema = json.loads(path.read_text()); Draft202012Validator.check_schema(schema)
            schema['$id'] = path.as_uri(); resources.append((schema['$id'], Resource.from_contents(schema)))
        validator = Draft202012Validator(schema, registry=Registry().with_resources(resources))
        validator.validate(self.spec)
        for change in ['pin', 'metric', 'motion']:
            bad = copy.deepcopy(self.spec)
            if change == 'pin': del bad['sources']['floorplan']['source_sha256']
            elif change == 'metric': bad['calibration'] = {'scale_mm_per_unit': 10}
            else: bad['qualification']['trajectory_implemented'] = True
            with self.subTest(change=change), self.assertRaises(ValidationError): validator.validate(bad)


class RegisteredFloorSourceTests(unittest.TestCase):
    def test_registered_ground_sources_preserve_their_validated_boundaries(self):
        spec=json.loads(model.SOURCE.read_text())
        for level,key in [('EG','ground_floor'),('KG','basement')]:
            with self.subTest(level=level):
                original=model.ground.load(model.assembly.validate_reference(spec['sources'][key],root=ROOT))
                actual=model.level_plan(spec,level)
                model.floor.validate(actual)
                for field in ('vertices','walls','areas','openings'):
                    self.assertEqual(actual[field],original[field])


if __name__ == '__main__': unittest.main()
