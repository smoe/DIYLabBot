"""Vector proposal contracts; no photograph, CAD runtime or original fixture."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_stack as model
import render_building_stack_section as section


def elements(tree, role):
    return [element for element in tree.iter() if element.get('data-role') == role]


def invented(clear=3600., slab=180.):
    pitch = clear+slab
    levels = [{'id': 'Level'+str(i), 'label': 'EG*' if i == 0 else 'Ebene '+str(i),
               'z_mm': i*pitch, 'slab_bottom_mm': i*pitch-slab,
               'slab_top_mm': i*pitch, 'clear_top_mm': i*pitch+clear,
               'atrium_floor_filled': i == 0} for i in range(4)]
    extent = {'from_level': 'KG', 'to_level': levels[-1]['id']}
    roof_z = levels[-1]['clear_top_mm']+slab
    return {'levels': levels,
            'clear_height_mm': clear, 'slab_thickness_mm': slab, 'floor_pitch_mm': pitch,
            'x_bounds_mm': [0., 10000.], 'atrium_x_bounds_mm': [4000., 6000.],
            'y_bounds_mm': [0., 20000.], 'atrium_y_bounds_mm': [8000., 12000.],
            'concept_marker': {'points_mm': [[4200., 8400.], [5800., 8400.], [5800., 11600.], [4200., 11600.]],
                               'offset_mm': 0., 'depth_mm': 3*pitch+clear},
            'template_id': 'Invented', 'template_source': 'model/invented.json',
            'ground_floor': {'id': 'InventedGround', 'source': 'model/invented-ground.json'},
            'roof': {'roof_z_mm': roof_z, 'slab_bottom_mm': roof_z-slab, 'slab_top_mm': roof_z,
                     'barrel': {'axis': 'X', 'profile_axis': 'Y', 'center_cross_mm': 10000., 'crown_z_mm': roof_z+1300,
                                'footprint_points_mm': [[3000., 7000.], [7000., 7000.], [7000., 13000.], [3000., 13000.]],
                                'profile_points_mm': [[6800., roof_z+300], [10000., roof_z+1300], [13200., roof_z+300]]},
                     'covered_area_ids': ['AtriumTest', 'HallA', 'HallB', 'HallC', 'HallD'],
                     'covered_corridor_area_ids': ['HallA', 'HallB', 'HallC', 'HallD'],
                     'guard': {'height_mm': 1100}},
            'circulation': {'served_extent': extent, 'elevator': {
                'served_extent': extent,
                'sides': {'outward': {'label': 'außen / links zum Flur', 'wall': 'OutsideWall'},
                          'inward': {'label': 'innen / rechts zum Kernbereich', 'wall': 'InsideWall'}},
                'doors_by_level': {level['id']: ['outward', 'inward'] if i == 0 else ['outward'] for i, level in enumerate(levels)},
                'deferred_stops': [{'id': 'KG', 'label': 'KG (geplant)', 'elevation_mm': None,
                                    'status': 'awaiting_plan', 'sides': ['inward']}]},
                'stairs': [{'id': 'RightStair', 'area': 'InventedRightCore', 'classification': 'internal', 'served_extent': extent,
                            'planned_connectors': [{'id': 'RightStair_KG_Ground', 'from_level': 'KG', 'to_level': levels[0]['id'],
                                                    'z0_mm': None, 'z1_mm': None, 'body_id': None, 'status': 'awaiting_plan'}]}],
                'external_stairs': [{'id': 'OuterStair', 'area': 'InventedExternalCore', 'classification': 'external_metal',
                                     'served_extent': {'from_level': levels[0]['id'], 'to_level': 'ROOF'}}]}}


class BuildingStackSectionTests(unittest.TestCase):
    def test_real_stack_has_one_filled_atrium_and_only_upper_openings(self):
        spec = model.load(); view = model.interfaces(spec, model.parameters(spec))
        tree = ET.fromstring(section.render_svg(spec))
        levels = {element.get('data-level'): element for element in tree.iter() if element.get('data-level')}
        self.assertEqual(set(levels), {level['id'] for level in view['levels']})
        for source in view['levels']:
            actual = levels[source['id']]
            self.assertEqual(float(actual.get('data-z-mm')), source['z_mm'])
            self.assertEqual(len(elements(actual, 'atrium-floor')), int(source['atrium_floor_filled']))
            self.assertEqual(len(elements(actual, 'atrium-opening')), int(source['id'].startswith('OG')))
        self.assertEqual(len(elements(tree, 'atrium-floor')), 1)
        self.assertEqual(len(elements(tree, 'atrium-opening')), 3)
        self.assertEqual(len(elements(tree, 'exchange-arrow')), 2)
        self.assertEqual(len(elements(tree, 'roof-slab')), 2)
        self.assertEqual(len(elements(tree, 'glass-roof-profile')), 1)
        self.assertEqual(len(elements(tree, 'glass-roof-eaves')), 1)

    def test_height_dimensions_and_slab_geometry_follow_evaluated_assumptions(self):
        view = invented(); tree = ET.fromstring(section._render(view))
        labels = ''.join(tree.itertext())
        self.assertIn('3,6 m lichte Höhe', labels)
        self.assertIn('3,78 m Geschossteilung', labels)
        self.assertIn('Platte 180 mm', labels)
        clear = elements(tree, 'clear-height')[0]
        pitch = elements(tree, 'floor-pitch')[0]
        self.assertEqual(float(clear.get('data-to-mm'))-float(clear.get('data-from-mm')), 3600.)
        self.assertEqual(float(pitch.get('data-to-mm'))-float(pitch.get('data-from-mm')), 3780.)
        groups = [element for element in tree.iter() if element.get('data-level')]
        floors = [elements(group, 'slab')[0] for group in groups]
        pixel_pitch = float(floors[0].get('y'))-float(floors[1].get('y'))
        pixel_slab = float(floors[0].get('height'))
        self.assertAlmostEqual(pixel_slab/pixel_pitch, 180/3780, delta=1e-5)
        zone = elements(tree, 'concept-volume')[0]
        self.assertLess(float(zone.get('x')), 210+850*.5)
        self.assertGreater(float(zone.get('x'))+float(zone.get('width')), 210+850*.5)

    def test_yz_projection_keeps_atrium_void_and_extended_glazing_separate(self):
        view = invented(); tree = ET.fromstring(section._render(view))
        self.assertEqual(tree.get('data-horizontal-axis'), 'Y')
        self.assertEqual(elements(tree, 'glass-roof-profile')[0].get('data-profile-axis'), 'Y')
        self.assertIn('Y/Z-Prinzipprojektion', ''.join(tree.itertext()))
        self.assertIn('Glas über Atrium und 4 Fluren', ''.join(tree.itertext()))
        self.assertGreater(float(elements(tree, 'slab')[0].get('width')), float(elements(tree, 'roof-slab')[0].get('width')))
        self.assertEqual(len(elements(tree, 'slab')), 8)
        changed = copy.deepcopy(view)
        changed['x_bounds_mm'] = [-8000., 45000.]; changed['atrium_x_bounds_mm'] = [-4000., 30000.]
        for point in changed['concept_marker']['points_mm']: point[0] *= 4
        other = ET.fromstring(section._render(changed))
        for role in ('slab', 'roof-slab', 'concept-volume', 'glass-roof-profile'):
            self.assertEqual([e.attrib for e in elements(tree, role)], [e.attrib for e in elements(other, role)])
        for key, value in [('axis', 'Y'), ('profile_axis', 'X')]:
            changed = copy.deepcopy(view); changed['roof']['barrel'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): section._render(changed)
        changed = copy.deepcopy(view); changed['roof']['covered_corridor_area_ids'].pop()
        with self.assertRaisesRegex(ValueError, 'four distinct source corridors'):
            section._render(changed)

    def test_default_load_occurs_once_and_only_the_public_interface_is_rendered(self):
        private = {'_source': {'path': '/private/original.jpg', 'sha256': 'private_hash'}}
        with mock.patch.object(model, 'load', return_value=private) as load, \
                mock.patch.object(model, 'parameters', return_value={}), \
                mock.patch.object(model, 'interfaces', return_value=invented()) as interface:
            svg = section.render_svg()
        load.assert_called_once_with()
        interface.assert_called_once_with(private, {})
        self.assertNotIn('/private', svg); self.assertNotIn('private_hash', svg)

    def test_door_table_follows_source_policy_and_marks_basement_height_assumed(self):
        spec = model.load(); view = model.interfaces(spec, model.parameters(spec))
        tree = ET.fromstring(section.render_svg(spec))
        policy = elements(tree, 'lift-door-policy')[0]
        rows = {element.get('data-lift-stop'): element for element in policy.iter() if element.get('data-lift-stop')}
        elevator = view['circulation']['elevator']
        expected = {**elevator['doors_by_level'], 'KG': ['inward']}
        self.assertEqual(set(rows), set(expected))
        for name, sides in expected.items():
            self.assertEqual(rows[name].get('data-door-sides').split(), sides)
        self.assertEqual(rows['KG'].get('data-elevation-basis'), 'assumed')
        self.assertIn('KG', {element.get('data-level') for element in tree.iter()})
        self.assertEqual(elevator['deferred_stops'], [])
        labels = ''.join(policy.itertext())
        self.assertIn('KG-Höhe vorläufig angenommen', labels)
        self.assertIn('1 rechter Treppenkern', labels)
        self.assertIn('R3_028', labels)
        self.assertIn('Außentreppe EG → Dach', labels)
        self.assertFalse(any('data-level' in element.attrib or 'data-z-mm' in element.attrib for element in policy.iter()))

    def test_changed_policy_changes_only_its_table_and_retains_atrium_geometry(self):
        original = invented(); changed = copy.deepcopy(original)
        changed['circulation']['elevator']['doors_by_level']['Level1'] = ['inward']
        changed['circulation']['elevator']['sides']['inward']['wall'] = 'DifferentInsideWall'
        a = ET.fromstring(section._render(original)); b = ET.fromstring(section._render(changed))
        row = next(element for element in b.iter() if element.get('data-lift-stop') == 'Level1')
        self.assertEqual(row.get('data-door-sides'), 'inward')
        self.assertIn('DifferentInsideWall', ''.join(elements(b, 'lift-door-policy')[0].itertext()))
        for role in ('concept-volume', 'atrium-floor', 'atrium-opening', 'exchange-arrow', 'slab', 'roof-slab', 'glass-roof-profile', 'glass-roof-eaves'):
            self.assertEqual([element.attrib for element in elements(a, role)], [element.attrib for element in elements(b, role)])

    def test_unknown_basement_height_cannot_silently_become_a_drawn_level(self):
        for value in (0, -4000, False):
            view = invented(); view['circulation']['elevator']['deferred_stops'][0]['elevation_mm'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'no known elevation'):
                section._render(view)
        view = invented(); view['circulation']['elevator']['doors_by_level']['KG'] = ['inward']
        with self.assertRaisesRegex(ValueError, 'exactly the drawn storeys'):
            section._render(view)

    def test_only_one_stair_is_accepted_and_its_source_reference_is_reflected(self):
        view = invented()
        view['circulation']['stairs'][0]['area'] = 'DifferentRightCore'
        tree = ET.fromstring(section._render(view))
        note = elements(tree, 'stair-extent')[0]
        self.assertEqual(note.get('data-area'), 'DifferentRightCore')
        self.assertIn('1 rechter Treppenkern', ''.join(note.itertext()))
        view['circulation']['stairs'].append(copy.deepcopy(view['circulation']['stairs'][0]))
        with self.assertRaisesRegex(ValueError, 'Exactly one right stair'):
            section._render(view)
        view['circulation']['stairs'] = []
        with self.assertRaisesRegex(ValueError, 'Exactly one right stair'):
            section._render(view)

    def test_planned_stair_basement_link_cannot_acquire_a_height_or_body(self):
        for key, value in [('z0_mm', 0), ('z1_mm', 0), ('body_id', 'BasementSolid')]:
            view = invented(); view['circulation']['stairs'][0]['planned_connectors'][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'planned without elevation or geometry'):
                section._render(view)
        view = invented(); view['circulation']['elevator']['served_extent'] = {'from_level': 'KG', 'to_level': 'Level2'}
        with self.assertRaisesRegex(ValueError, 'source-served extent'):
            section._render(view)

    def test_own_ground_source_glass_roof_and_external_stair_are_explicit_and_separate(self):
        view = invented(); tree = ET.fromstring(section._render(view)); labels = ''.join(tree.itertext())
        self.assertIn('EG InventedGround', labels)
        self.assertNotIn('Erdgeschoss später korrigieren', labels)
        self.assertIn('geschlossenes Glasgewölbe', labels)
        self.assertIn('1 interner Treppenkern', labels)
        self.assertIn('1 äußere Metalltreppe: Dach → EG*', labels)
        self.assertEqual({e.get('data-level') for e in tree.iter() if e.get('data-level')}, {level['id'] for level in view['levels']})
        profile = elements(tree, 'glass-roof-profile')[0]
        self.assertEqual(float(profile.get('data-roof-z-mm')), view['roof']['roof_z_mm'])
        self.assertEqual(float(profile.get('data-crown-z-mm')), view['roof']['barrel']['crown_z_mm'])
        self.assertEqual(profile.get('d').count('L')+1, len(view['roof']['barrel']['profile_points_mm']))
        eaves = elements(tree, 'glass-roof-eaves')[0]
        self.assertEqual(eaves.get('d').count('M'), 2)
        self.assertEqual(eaves.get('d').count('V'), 2)
        for key, value in [('slab_bottom_mm', 0), ('slab_top_mm', 0)]:
            changed = copy.deepcopy(view); changed['roof'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'above the last clear ceiling'):
                section._render(changed)
        changed = copy.deepcopy(view); changed['circulation']['external_stairs'][0]['served_extent']['from_level'] = 'KG'
        with self.assertRaisesRegex(ValueError, 'external metal stair'):
            section._render(changed)

    def test_escaped_vector_only_output_is_compact_and_explicitly_unqualified(self):
        view = invented(); view['template_id'] = '<image href="secret"/>'
        view['levels'][0]['label'] = '<script>secret</script>'
        before = copy.deepcopy(view)
        with mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('No image input')):
            svg = section._render(view)
        tree = ET.fromstring(svg)
        self.assertLess(len(svg.encode('utf-8')), 11000)
        self.assertEqual(view, before)
        self.assertEqual(tree.get('viewBox'), '0 0 1500 1000')
        self.assertFalse(any(element.tag.rsplit('}', 1)[-1] in {'image', 'script', 'foreignObject'} for element in tree.iter()))
        self.assertFalse(any(key.endswith('href') for element in tree.iter() for key in element.attrib))
        labels = ''.join(tree.itertext())
        for expected in ('XY nicht kalibriert', 'Sicherheit sind nicht qualifiziert', 'Keller nicht modelliert',
                         'keine Schutzwirkung', 'Raumkennungen sind Vorlagenreferenzen'):
            self.assertIn(expected, labels)
        self.assertIn('&lt;image', svg)
        self.assertFalse(any(element.get('class-') for element in tree.iter()))

    def test_inconsistent_or_nonfinite_evaluated_geometry_is_rejected(self):
        for key, value in [('floor_pitch_mm', 4000.), ('clear_height_mm', float('nan')),
                           ('slab_thickness_mm', True)]:
            view = invented(); view[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                section._render(view)

    def test_current_source_figure_fits_gallery_budget_and_cli_writes_svg(self):
        svg = section.render_svg()
        self.assertLess(len(svg.encode('utf-8')), 11000)
        self.assertIn('4 m lichte Höhe', ''.join(ET.fromstring(svg).itertext()))
        self.assertIn('4,25 m Geschossteilung', ''.join(ET.fromstring(svg).itertext()))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'section.svg'
            section.main(['--out', str(output)])
            self.assertEqual(output.read_text(encoding='utf-8'), svg)


if __name__ == '__main__':
    unittest.main()
