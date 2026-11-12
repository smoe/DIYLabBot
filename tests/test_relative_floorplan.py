"""Invented geometry only: two rooms and a hall, never a real-plan fixture."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import relative_floorplan as model

try:
    from jsonschema import Draft202012Validator, ValidationError
except ImportError:
    Draft202012Validator = None


def invented():
    vertices = {'a': [0, 0], 'c': [2, 0], 'd': [0, 1], 'e': [1, 1], 'f': [2, 1], 'g': [0, 2], 'h': [1, 2], 'i': [2, 2]}
    endpoints = [('ac', 'a', 'c'), ('cf', 'c', 'f'), ('ef', 'e', 'f'), ('de', 'd', 'e'), ('da', 'd', 'a'),
                 ('eh', 'e', 'h'), ('hg', 'h', 'g'), ('gd', 'g', 'd'), ('fi', 'f', 'i'), ('ih', 'i', 'h')]
    def area(name, label, kind, refs):
        return {'id': name, 'label': label, 'kind': kind, 'boundary': [{'wall': wall, 'direction': direction} for wall, direction in refs], 'confidence': 'approximate'}
    return {'format': model.FORMAT, 'id': 'Invented', 'units': {'length': 'relative'}, 'calibration': None, 'vertices': vertices,
            'walls': [{'id': name, 'start': start, 'end': end, 'kind': 'wall'} for name, start, end in endpoints],
            'areas': [area('Alpha', 'Alpha', 'room', [('de', 1), ('eh', 1), ('hg', 1), ('gd', 1)]),
                      area('Beta', 'Beta', 'room', [('ef', 1), ('fi', 1), ('ih', 1), ('eh', -1)]),
                      area('Hall', 'Hall', 'corridor', [('ac', 1), ('cf', 1), ('ef', -1), ('de', -1), ('da', 1)])],
            'openings': [{'id': 'DoorAlpha', 'wall': 'de', 'interval': [.25, .6], 'kind': 'door', 'confidence': 'clear', 'connection': 'observed'},
                         {'id': 'DoorBeta', 'wall': 'ef', 'interval': [.25, .6], 'kind': 'door', 'confidence': 'approximate', 'connection': 'uncertain'},
                         {'id': 'WindowAlpha', 'wall': 'hg', 'interval': [.3, .7], 'kind': 'window', 'confidence': 'approximate', 'connection': 'uncertain'}],
            'provenance': {'method': 'manual_trace', 'source_kind': 'synthetic_fixture', 'accuracy': 'approximate', 'notes': ['Invented rectangles for tests; no image was used.']}}


class RelativePlanTests(unittest.TestCase):
    def setUp(self):
        self.spec = invented()

    def test_closed_shared_boundaries_and_door_topology_are_derived_once(self):
        model.validate(self.spec)
        result = model.topology(self.spec)
        self.assertEqual(result['unreferenced_walls'], [])
        doors = {value['opening']: value for value in result['connections']}
        self.assertEqual(doors['DoorAlpha']['areas'], ['Alpha', 'Hall'])
        self.assertEqual(doors['DoorBeta']['connection'], 'uncertain')
        self.assertTrue(all(value['passable'] is None for value in doors.values()))
        self.assertEqual(model.outline(self.spec, 'Alpha'), [[0, 1], [1, 1], [1, 2], [0, 2]])

    def test_open_corridor_boundary_is_topology_without_a_physical_display_wall(self):
        wall = next(w for w in self.spec['walls'] if w['id'] == 'eh'); wall['kind'] = 'open_boundary'
        graph = model.topology(self.spec)
        self.assertEqual(next(c for c in graph['connections'] if c['kind'] == 'open_boundary')['areas'], ['Alpha', 'Beta'])
        data = model.expanded(self.spec, model.parameters(self.spec, {'display_scale': 1000}))
        self.assertNotIn('Wall_eh', {body['id'] for body in data['bodies']})

    def test_unknown_and_void_are_not_invented_native_walls_or_floor_slabs(self):
        self.spec['areas'][0]['kind'] = 'unknown'; self.spec['areas'][1]['kind'] = 'void'
        next(w for w in self.spec['walls'] if w['id'] == 'hg')['kind'] = 'unknown'
        self.spec['openings'][1]['kind'] = 'unknown'
        p = model.parameters(self.spec, {'display_scale': 1000}); data = model.expanded(self.spec, p)
        names = {body['id'] for body in data['bodies']}
        self.assertFalse({'Area_Alpha', 'Area_Beta', 'Wall_hg'} & names)
        interface = model.interfaces(self.spec, p)
        self.assertEqual(interface['unmodeled_openings'], ['DoorBeta', 'WindowAlpha'])
        self.assertEqual({p['id'] for p in interface['opening_probes']}, {'DoorAlpha'})
        self.assertNotIn('Opening_DoorBeta', {op['id'] for op in data['operations']})

    def test_duplicate_vertices_walls_and_zero_length_edges_are_rejected(self):
        for change in ('vertex', 'reverse_wall', 'zero_wall', 'wall_id'):
            spec = copy.deepcopy(self.spec)
            if change == 'vertex': spec['vertices']['duplicate'] = [0, 0]
            elif change == 'reverse_wall': spec['walls'].append({'id': 'duplicate', 'start': 'e', 'end': 'd', 'kind': 'wall'})
            elif change == 'zero_wall': spec['walls'][0]['end'] = spec['walls'][0]['start']
            else: spec['walls'].append(copy.deepcopy(spec['walls'][0]))
            with self.subTest(change=change), self.assertRaises(ValueError): model.validate(spec)

    def test_unsplit_t_junction_and_crossing_are_detected_even_at_small_relative_scale(self):
        for scale in (1, .001):
            for change in ('t_node', 'crossing'):
                spec = copy.deepcopy(self.spec)
                if change == 't_node': spec['vertices']['middle'] = [.5, 1]
                else:
                    spec['vertices'].update({'p': [.2, .2], 'q': [.8, .8], 'r': [.2, .8], 's': [.8, .2]})
                    spec['walls'] += [{'id': 'CrossA', 'start': 'p', 'end': 'q', 'kind': 'unknown'}, {'id': 'CrossB', 'start': 'r', 'end': 's', 'kind': 'unknown'}]
                spec['vertices'] = {name: [value*scale for value in point] for name, point in spec['vertices'].items()}
                with self.subTest(scale=scale, change=change), self.assertRaises(ValueError): model.validate(spec)

    def test_clockwise_unordered_boolean_and_nonmanifold_area_loops_are_rejected(self):
        for change in ('clockwise', 'unordered', 'boolean', 'nonmanifold'):
            spec = copy.deepcopy(self.spec); area = spec['areas'][0]
            if change == 'clockwise': area['boundary'] = [{'wall': ref['wall'], 'direction': -ref['direction']} for ref in reversed(area['boundary'])]
            elif change == 'unordered': area['boundary'][0], area['boundary'][1] = area['boundary'][1], area['boundary'][0]
            elif change == 'boolean': area['boundary'][0]['direction'] = True
            else:
                duplicate = copy.deepcopy(area); duplicate['id'] = 'Duplicate'; spec['areas'].append(duplicate)
            with self.subTest(change=change), self.assertRaises(ValueError): model.validate(spec)

    def test_contained_overlapping_area_faces_are_rejected(self):
        self.spec['vertices'].update({'m': [.2, 1.2], 'n': [.4, 1.2], 'o': [.4, 1.4], 'p': [.2, 1.4]})
        for index, (a, b) in enumerate(zip('mnop', 'nopm')):
            self.spec['walls'].append({'id': 'Inner'+str(index), 'start': a, 'end': b, 'kind': 'wall'})
        self.spec['areas'].append({'id': 'Inside', 'label': None, 'kind': 'unknown', 'boundary': [{'wall': 'Inner'+str(i), 'direction': 1} for i in range(4)], 'confidence': 'uncertain'})
        with self.assertRaises(ValueError): model.validate(self.spec)

    def test_unreferenced_uncertain_partition_is_reported_without_forcing_a_room(self):
        self.spec['vertices'].update({'p': [.2, .25], 'q': [.6, .25]})
        self.spec['walls'].append({'id': 'Partial', 'start': 'p', 'end': 'q', 'kind': 'unknown'})
        self.assertEqual(model.topology(self.spec)['unreferenced_walls'], ['Partial'])

    def test_opening_interval_reference_overlap_and_numeric_checks(self):
        for change in ('outside', 'zero', 'overlap', 'boolean', 'nan', 'missing', 'on_open_boundary'):
            spec = copy.deepcopy(self.spec); opening = spec['openings'][0]
            if change == 'outside': opening['interval'] = [-.1, .5]
            elif change == 'zero': opening['interval'] = [.5, .5]
            elif change == 'overlap':
                other = copy.deepcopy(opening); other['id'] = 'Duplicate'; spec['openings'].append(other)
            elif change == 'boolean': opening['interval'][0] = False
            elif change == 'nan': opening['interval'][0] = float('nan')
            elif change == 'missing': opening['wall'] = 'missing'
            else: next(w for w in spec['walls'] if w['id'] == opening['wall'])['kind'] = 'open_boundary'
            with self.subTest(change=change), self.assertRaises(ValueError): model.validate(spec)

    def test_unknown_metric_values_cannot_be_replaced_by_visualization_scale(self):
        for change in ('mm_unit', 'calibration', 'boolean', 'infinite'):
            spec = copy.deepcopy(self.spec)
            if change == 'mm_unit': spec['units']['length'] = 'mm'
            elif change == 'calibration': spec['calibration'] = {'mm_per_unit': 1000}
            elif change == 'boolean': spec['vertices']['a'][0] = True
            else: spec['vertices']['a'][0] = float('inf')
            with self.subTest(change=change), self.assertRaises(ValueError): model.validate(spec)
        self.assertEqual(model.wall_metrics(self.spec)['de'], {'length_relative': 1., 'length_mm': None})
        with self.assertRaises(ValueError): model.metric_geometry(self.spec)
        with self.assertRaises(ValueError): model.parameters(self.spec)
        for values in ({'display_scale': True}, {'display_scale': float('inf')}, {'display_scale': 0}, {'display_scale': 1000, 'real_height': 10}):
            with self.assertRaises(ValueError): model.parameters(self.spec, values)

    def test_preview_materialization_is_static_arbitrary_and_does_not_mutate_source(self):
        before = copy.deepcopy(self.spec)
        preview = model.preview(self.spec, 1000); p = preview['parameters']; data = model.expanded(preview['spec'], p)
        self.assertEqual(model.parameters(preview['spec']), p)
        self.assertEqual(data['joints'], []); self.assertTrue(all(op['shape']['fixed'] for op in data['operations']))
        self.assertEqual(model.cases(self.spec), [{'id': 'overview'}]); self.assertEqual(model.pose(self.spec, p), {})
        model.validate_pose(data, {})
        with self.assertRaises(ValueError): model.validate_pose(data, {'Door': 1})
        with self.assertRaises(ValueError): model.materialize(self.spec, 'walkthrough')
        interface = model.interfaces(self.spec, p)
        self.assertFalse(interface['metric_scale_known']); self.assertFalse(interface['passability_qualified']); self.assertFalse(interface['hardware_executed'])
        self.assertIsNone(interface['real_wall_height_mm']); self.assertTrue(interface['junction_overlap_expected'])
        self.assertEqual(self.spec, before)

    def test_rotated_opening_probes_are_inside_the_target_cut_and_below_synthetic_lintel(self):
        angle = .4; c, s = math.cos(angle), math.sin(angle)
        self.spec['vertices'] = {name: [c*x-s*y+.1, s*x+c*y-.2] for name, (x, y) in self.spec['vertices'].items()}
        p = model.parameters(self.spec, {'display_scale': 1000}); data = model.expanded(self.spec, p)
        operations = {op['id']: op for op in data['operations']}
        for probe in model.interfaces(self.spec, p)['opening_probes']:
            cut = model.numeric_shape(operations['Opening_'+probe['id']]['shape'], p)
            self.assertTrue(all(model.point_membership(point, cut['points']) == 1 for point in probe['points_mm']))
            self.assertGreater(probe['offset_mm'], cut['offset'])
            self.assertLess(probe['offset_mm']+probe['depth_mm'], cut['offset']+cut['depth'])
            self.assertEqual(probe['target_body'], operations['Opening_'+probe['id']]['body'])
            self.assertLess(cut['offset']+cut['depth'], p['display_height'])

    def test_svg_is_vector_only_escaped_source_text_with_no_image_or_source_metadata(self):
        self.spec['areas'][0]['label'] = '<image href="secret"/>'
        self.spec['_source'] = {'path': '/private/original-photo.jpg', 'sha256': 'private_hash'}
        before = copy.deepcopy(self.spec)
        with mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('SVG cannot read any image or file')):
            svg = model.render_svg(self.spec)
        tree = ET.fromstring(svg)
        self.assertNotIn('<image', svg)
        self.assertFalse(any(key.endswith('href') for element in tree.iter() for key in element.attrib))
        self.assertNotIn('original-photo', svg); self.assertNotIn('private_hash', svg)
        self.assertIn('&lt;image', svg); self.assertLess(len(svg.encode()), 15000)
        self.assertEqual(self.spec, before)

    def test_public_provenance_rejects_original_image_reference_fields(self):
        for field in ('image_path', 'image_sha256', 'exif', 'url'):
            spec = copy.deepcopy(self.spec); spec['provenance'][field] = 'private'
            with self.subTest(field=field), self.assertRaises(ValueError): model.validate(spec)

    def test_uncertain_openings_are_orange_and_observed_approximate_doors_green_dashed(self):
        for uncertain in ('none', 'connection', 'confidence', 'kind'):
            spec = copy.deepcopy(self.spec); spec['openings'] = [spec['openings'][0]]
            opening = spec['openings'][0]; opening['confidence'] = 'approximate'
            if uncertain == 'connection': opening['connection'] = 'uncertain'
            elif uncertain == 'confidence': opening['confidence'] = 'uncertain'
            elif uncertain == 'kind': opening['kind'] = 'unknown'
            svg = ET.fromstring(model.render_svg(spec))
            lines = [element for element in svg.iter() if element.tag.endswith('line')]
            self.assertEqual(lines[-1].attrib['stroke'], '#379368' if uncertain == 'none' else '#c38637')
            self.assertIn('stroke-dasharray', lines[-1].attrib)

    def test_concave_corridor_label_keeps_its_text_box_below_a_niche_and_ignores_t_node_bias(self):
        spec = invented()
        points = [[0, 0], [6, 0], [12, 0], [12, 2], [7, 2], [7, 1.3], [5, 1.3], [5, 2], [0, 2]]
        spec['vertices'] = {'v'+str(i): point for i, point in enumerate(points)}
        spec['walls'] = [{'id': 'w'+str(i), 'start': 'v'+str(i), 'end': 'v'+str((i+1) % len(points)), 'kind': 'wall'} for i in range(len(points))]
        spec['walls'].append({'id': 'NicheTop', 'start': 'v4', 'end': 'v7', 'kind': 'wall'})
        spec['areas'] = [
            {'id': 'Hall', 'label': 'Corridor', 'kind': 'corridor', 'boundary': [{'wall': 'w'+str(i), 'direction': 1} for i in range(len(points))], 'confidence': 'approximate'},
            {'id': 'Niche', 'label': 'N', 'kind': 'unknown', 'boundary': [{'wall': 'w5', 'direction': -1}, {'wall': 'w4', 'direction': -1}, {'wall': 'NicheTop', 'direction': 1}, {'wall': 'w6', 'direction': -1}], 'confidence': 'uncertain'}]
        spec['openings'] = []
        def label(value):
            return next(element for element in ET.fromstring(model.render_svg(value)).iter() if element.tag.endswith('text') and element.text == 'Corridor')
        element = label(spec); font = float(element.attrib['font-size']); scale = 900/12
        center = [(float(element.attrib['x'])-40)/scale, 2-(float(element.attrib['y'])-40)/scale]
        half = [(len('Corridor')*font*.65/2+1)/scale, (font*1.2/2+1)/scale]
        polygon = model.outline(spec, 'Hall')
        self.assertLess(center[1]+half[1], 1.3)
        self.assertTrue(all(model.point_membership([center[0]+dx*half[0], center[1]+dy*half[1]], polygon) == 1 for dx in (-1, 1) for dy in (-1, 1)))
        self.assertEqual(element.attrib['dominant-baseline'], 'central')
        # Removing a merely collinear subdivision must not shift the label.
        unsplit = copy.deepcopy(spec); del unsplit['vertices']['v1']
        unsplit['walls'] = [wall for wall in unsplit['walls'] if wall['id'] != 'w1']
        unsplit['walls'][0]['end'] = 'v2'
        unsplit['areas'][0]['boundary'] = [ref for ref in unsplit['areas'][0]['boundary'] if ref['wall'] != 'w1']
        plain = label(unsplit)
        self.assertEqual((element.attrib['x'], element.attrib['y']), (plain.attrib['x'], plain.attrib['y']))

    def test_tiny_numeric_niche_label_stays_visible_at_minimum_readable_size(self):
        spec = invented()
        spec['vertices'] = {'a': [0, 0], 'b': [.052, 0], 'c': [.052, .06], 'd': [0, .06], 'p': [0, 1], 'q': [2, 1]}
        spec['walls'] = [{'id': a+b, 'start': a, 'end': b, 'kind': 'wall'} for a, b in zip('abcd', 'bcda')]
        spec['walls'].append({'id': 'Context', 'start': 'p', 'end': 'q', 'kind': 'unknown'})
        spec['areas'] = [{'id': 'Tiny', 'label': '9.876', 'kind': 'unknown', 'confidence': 'uncertain', 'boundary': [{'wall': name, 'direction': 1} for name in ['ab', 'bc', 'cd', 'da']]}]
        spec['openings'] = []
        element = next(item for item in ET.fromstring(model.render_svg(spec)).iter() if item.tag.endswith('text') and item.text == '9.876')
        self.assertGreaterEqual(float(element.attrib['font-size']), 7)
        self.assertEqual(element.attrib['dominant-baseline'], 'central')

    def test_load_binds_the_exact_json_bytes_and_rejects_a_parse_pin_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'invented.json'; path.write_text(json.dumps(self.spec))
            value = model.load(path)
            self.assertEqual(value['_source']['sha256'], model.digest(path))
            read = Path.read_bytes; changed = False
            def replace_after_read(item):
                nonlocal changed
                raw = read(item)
                if item.resolve() == path.resolve() and not changed:
                    changed = True; path.write_bytes(raw+b'\n')
                return raw
            with mock.patch.object(Path, 'read_bytes', replace_after_read):
                with self.assertRaises(ValueError): model.load(path)

    def test_shared_native_adapter_and_source_dependencies_do_not_read_originals(self):
        with mock.patch.object(model.portable, 'solidcraft_commands', wraps=model.portable.solidcraft_commands) as shared:
            commands = model.solidcraft_commands(self.spec, model.parameters(self.spec, {'display_scale': 1000}))
        shared.assert_called_once()
        self.assertTrue(any(c['command'] == 'solid.extrude' for c in commands))
        self.assertFalse(any(c['command'] in {'joint.create', 'joint.drive', 'file.insert_step'} for c in commands))
        self.assertTrue(all(path.suffix in {'.py', '.json'} for path in model.source_dependencies(self.spec)))

    @unittest.skipIf(Draft202012Validator is None, 'Optional jsonschema development dependency required')
    def test_schema_accepts_invented_data_and_rejects_metric_or_private_fields(self):
        schema = json.loads(model.SCHEMA.read_text()); Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema); validator.validate(self.spec)
        for change in ('metric', 'image', 'direction', 'calibration'):
            spec = copy.deepcopy(self.spec)
            if change == 'metric': spec['units']['length'] = 'mm'
            elif change == 'image': spec['provenance']['image_sha256'] = 'private'
            elif change == 'direction': spec['areas'][0]['boundary'][0]['direction'] = True
            else: spec['calibration'] = {'scale': 1}
            with self.subTest(change=change), self.assertRaises(ValidationError): validator.validate(spec)


if __name__ == '__main__':
    unittest.main()
