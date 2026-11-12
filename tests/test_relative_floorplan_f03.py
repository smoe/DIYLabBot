"""Semantic regressions for the authorized derived geometry, without the photo."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import relative_floorplan as model


class DerivedFloorTests(unittest.TestCase):
    def setUp(self):
        self.spec = model.load()
        self.topology = model.topology(self.spec)

    def connection(self, opening):
        return next(item for item in self.topology['connections'] if item.get('opening') == opening)

    def test_southern_writing_room_connections_are_internal_side_wall_doors(self):
        for name, neighbor in [('D3_002_003', 'R3_003'), ('D3_002_001', 'R3_001')]:
            connection = self.connection(name)
            self.assertEqual(set(connection['areas']), {'R3_002', neighbor})
            self.assertIsNone(connection['passable'])
        self.assertFalse(self.topology['unreferenced_walls'])

    def test_unresolved_suite_and_north_core_do_not_invent_a_partition_or_door(self):
        areas = {area['id']: area for area in self.spec['areas']}
        self.assertEqual(areas['Suite3_006AB']['kind'], 'unknown')
        self.assertEqual(areas['NorthCore']['kind'], 'unknown')
        self.assertNotIn('R3_006A', areas)
        self.assertNotIn('R3_006B', areas)
        self.assertFalse(any('NorthCore' in item['areas'] for item in self.topology['connections']))
        for index in range(23, 28):
            self.assertEqual(areas['N3_%03d' % index]['kind'], 'unknown')

    def test_open_corridor_boundaries_are_shared_without_extra_doors(self):
        joins = {frozenset(item['areas']) for item in self.topology['connections'] if item['kind'] == 'open_boundary'}
        self.assertEqual(joins, {frozenset(pair) for pair in [('C3_020', 'C3_021'),
                                                           ('C3_020', 'C3_019'), ('C3_018', 'C3_019')]})
        self.assertFalse(self.topology['metric_scale_known'])
        self.assertFalse(self.topology['robot_navigation_qualified'])
        self.assertTrue(all(value['length_mm'] is None for value in model.wall_metrics(self.spec).values()))
        with self.assertRaisesRegex(ValueError, 'calibration'):
            model.metric_geometry(self.spec)

    def test_authorized_preview_is_only_vectors_and_text_without_embedded_original(self):
        svg = ET.fromstring(model.render_svg(self.spec))
        tags = {element.tag.rsplit('}', 1)[-1] for element in svg.iter()}
        self.assertFalse(tags & {'image', 'script', 'foreignObject'})
        self.assertFalse(any('href' in key.lower() for element in svg.iter() for key in element.attrib))
        self.assertIn('3.003', ''.join(svg.itertext()))
        self.assertEqual(set(self.spec['provenance']), {'method', 'source_kind', 'accuracy', 'notes'})


if __name__ == '__main__':
    unittest.main()
