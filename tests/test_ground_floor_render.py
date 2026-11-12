"""Compact source geometry, readable source labels and no original-image input."""
import copy
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import relative_floorplan as floor
import render_ground_floor as render
from test_relative_floorplan import invented


def tag(element): return element.tag.rsplit('}', 1)[-1]


def paths(tree):
    """Read the absolute straight segments emitted by the SVG serializer."""
    result = []
    selected = [element for group in tree if group.get('data-layer') in {'walls', 'masks', 'openings'} for element in group]
    for path in selected:
        tokens = re.findall(r'[MHVL]|-?\d+(?:\.\d+)?', path.get('d'))
        cursor = 0; point = None
        while cursor < len(tokens):
            command = tokens[cursor]; cursor += 1
            if command in {'M', 'L'}:
                end = [float(tokens[cursor]), float(tokens[cursor+1])]; cursor += 2
            elif command == 'H':
                end = [float(tokens[cursor]), point[1]]; cursor += 1
            elif command == 'V':
                end = [point[0], float(tokens[cursor])]; cursor += 1
            else:
                raise AssertionError('Unexpected vector command')
            if command != 'M': result.append((point, end, path.get('class')))
            point = end
    return result


def paints(tree):
    css = next(element.text for element in tree if tag(element) == 'style')
    return {name: dict(item.split(':', 1) for item in values.split(';')) for name, values in re.findall(r'\.([a-z]\d+)\{([^}]+)\}', css)}


def faces(tree):
    result = []
    for group in tree:
        if group.get('data-layer') != 'faces': continue
        for path in group:
            tokens = re.findall(r'[MHVLZ]|-?\d+(?:\.\d+)?', path.get('d')); cursor = 0; points = []
            while cursor < len(tokens):
                command = tokens[cursor]; cursor += 1
                if command == 'Z':
                    result.append((points, path.get('class'))); points = []; continue
                if command in {'M', 'L'}:
                    point = [float(tokens[cursor]), float(tokens[cursor+1])]; cursor += 2
                elif command == 'H':
                    point = [float(tokens[cursor]), points[-1][1]]; cursor += 1
                elif command == 'V':
                    point = [points[-1][0], float(tokens[cursor])]; cursor += 1
                else: raise AssertionError('Unexpected closed vector command')
                points.append(point)
    return result


class GroundFloorVectorTests(unittest.TestCase):
    def test_batched_strokes_preserve_coordinates_colors_and_opening_mask_layers(self):
        raw = floor.render_svg(invented()); before = ET.fromstring(raw)
        compact = render.compact_svg(raw); after = ET.fromstring(compact)
        original = [element for element in before.iter() if tag(element) == 'line']
        actual = paths(after)
        styles = paints(after)
        self.assertEqual(len(actual), len(original))
        for expected in original:
            paint = {key: value for key, value in expected.attrib.items() if key not in {'x1', 'y1', 'x2', 'y2'}}
            coords = [float(expected.get(key)) for key in ('x1', 'y1', 'x2', 'y2')]
            index = next((i for i, (a, b, style) in enumerate(actual) if styles[style] == {'fill': 'none', **paint}
                          and all(abs(x-y) <= .0501 for x, y in zip(a+b, coords))), None)
            self.assertIsNotNone(index); actual.pop(index)
        self.assertEqual([e.get('data-layer') for e in after if e.get('data-layer')], ['faces', 'labels', 'walls', 'masks', 'openings'])
        self.assertEqual(before.get('viewBox'), after.get('viewBox'))
        self.assertLess(len(compact.encode()), len(raw.encode())*.75)

    def test_areas_and_all_source_labels_survive_compaction(self):
        raw = floor.render_svg(invented()); a = ET.fromstring(raw); b = ET.fromstring(render.compact_svg(raw))
        self.assertEqual([e.text for e in a.iter() if tag(e) == 'text'], [e.text for e in b.iter() if tag(e) == 'text'])
        original = [e for e in a.iter() if tag(e) == 'polygon']; actual = faces(b); styles = paints(b)
        self.assertEqual(len(original), len(actual))
        for first in original:
            points = [[float(v) for v in p.split(',')] for p in first.get('points').split()]
            index = next((i for i, (other, style) in enumerate(actual) if styles[style] == {'fill': first.get('fill')}
                          and len(points) == len(other) and all(abs(x-y) <= .0501 for p, q in zip(points, other) for x, y in zip(p, q))), None)
            self.assertIsNotNone(index); actual.pop(index)

    def test_resolved_graph_is_loaded_once_without_reading_any_original(self):
        spec = invented(); spec['_source'] = {'path': '/private/original.jpg', 'sha256': 'private_hash'}
        spec['areas'][0]['label'] = '<image href="secret"/>'
        before = copy.deepcopy(spec); loader = types.SimpleNamespace(load=mock.Mock(return_value=spec))
        with mock.patch.dict(sys.modules, {'ground_floor_model': loader}), \
                mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('No original asset input')):
            svg = render.render_svg()
        loader.load.assert_called_once_with()
        self.assertEqual(spec, before)
        tree = ET.fromstring(svg)
        self.assertNotIn('/private', svg); self.assertNotIn('private_hash', svg)
        self.assertIn('&lt;image', svg)
        self.assertFalse({tag(element) for element in tree.iter()} & {'image', 'script', 'foreignObject'})
        self.assertIn('Maßstab unbekannt', ''.join(tree.itertext()))

    def test_embedded_images_external_references_and_nonfinite_vectors_fail(self):
        for content in ('<image/>', '<rect href="private.jpg"/>', '<rect fill="url(private.jpg)"/>',
                        '<line x1="nan" y1="0" x2="1" y2="0" stroke="#000"/>'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                render.compact_svg('<svg viewBox="0 0 10 10">'+content+'</svg>')

    def test_explicit_source_cli_passes_only_a_resolved_graph_to_the_renderer(self):
        spec = invented(); loader = types.SimpleNamespace(load=mock.Mock(return_value=spec))
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules, {'ground_floor_model': loader}):
            output = Path(directory)/'ground.svg'; source = Path(directory)/'input.json'
            render.main(['--source', str(source), '--out', str(output)])
            loader.load.assert_called_once_with(source)
            self.assertEqual(output.read_text(), render.render_svg(spec))

    def test_actual_ground_source_preserves_every_area_and_fits_documentation_budget(self):
        import ground_floor_model
        spec = ground_floor_model.load(); svg = render.render_svg(spec); tree = ET.fromstring(svg)
        self.assertLessEqual(len(svg.encode()), render.BUDGET)
        self.assertLess(len(svg.encode()), 10000)
        self.assertEqual(len(faces(tree)), len(spec['areas']))
        labels = [e.text for e in tree.iter() if tag(e) == 'text']
        self.assertEqual(labels[:-1], [area['label'] or area['id'] for area in spec['areas']])
        self.assertIsNone(spec['calibration'])


if __name__ == '__main__':
    unittest.main()
