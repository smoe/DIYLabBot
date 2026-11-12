"""Synthetic roof topology, circular geometry and fail-closed assumptions."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_roof as roof


class BuildingRoofTests(unittest.TestCase):
    def fixture(self):
        vertices = {f'P{x}_{y}': [x, y] for x in range(5) for y in range(4)}
        walls = {}; areas = []; by_pair = {}
        for y in range(3):
            for x in range(4):
                names = [f'P{x}_{y}', f'P{x+1}_{y}', f'P{x+1}_{y+1}', f'P{x}_{y+1}']; boundary = []
                for a, b in zip(names, names[1:]+names[:1]):
                    pair = tuple(sorted((a, b)))
                    if pair not in by_pair:
                        name = 'W'+str(len(walls)); by_pair[pair] = name
                        walls[name] = {'id': name, 'start': a, 'end': b, 'kind': 'wall'}
                    name = by_pair[pair]
                    boundary.append({'wall': name, 'direction': 1 if walls[name]['start'] == a else -1})
                name = 'Atrium' if (x, y) == (2, 1) else 'ExternalStair' if (x, y) == (0, 1) else f'Area{x}_{y}'
                areas.append({'id': name, 'kind': 'void' if name == 'Atrium' else 'corridor' if name in {'Area1_1','Area2_2','Area3_1'} else 'room', 'boundary': boundary})
        gap_wall = by_pair[tuple(sorted(('P1_1', 'P1_2')))]
        plan = {'vertices': vertices, 'walls': list(walls.values()), 'areas': areas,
                'openings': [{'id': 'RoofAccess', 'wall': gap_wall, 'interval': [.25, .75]}]}
        source = {'id': 'BuildingRoof', 'status': 'illustrative_unqualified', 'atrium_area': 'Atrium', 'guard_gap_opening': 'RoofAccess',
                  'opaque_area_ids': [a['id'] for a in areas if a['id'] not in {'Atrium', 'ExternalStair'}],
                  'glass_area_ids':['Atrium','Area1_1','Area2_2','Area3_1'],
                  'local_opaque_access':{'area':'Area1_1','opening':'RoofAccess','depth_parameter':'slab_thickness_mm','status':'illustrative_unqualified'},
                  'barrel': {'axis':'X','profile_segments':64,'max_sagitta_fraction_of_glass_thickness':.25,'rise_mm': 250, 'riser_mm': 100, 'overhang_mm': 100, 'glass_thickness_mm': 10, 'color': '#91cfe5', 'opacity': .35},
                  'guard': {'height_mm': 1100, 'post_width_mm': 40, 'rail_width_mm': 35, 'max_post_spacing_mm': 1000, 'color': '#777f85'}}
        return source, plan, {'display_scale': 1000, 'slab_thickness_mm': 250,'display_thickness':200}, [{'clear_top_mm': 16750}]

    def test_outer_contour_keeps_notch_and_excludes_hole_and_shared_edges(self):
        source, plan, p, levels = self.fixture(); result = roof.compile(source, plan, p, levels); interface = result['interface']
        contour = interface['source_outer_contour']; names = {edge['wall'] for edge in contour}
        atrium = next(a for a in plan['areas'] if a['id'] == 'Atrium')
        self.assertFalse(names & {ref['wall'] for ref in atrium['boundary']})
        self.assertTrue(any([1000, 1000] in edge['points_mm'] for edge in contour))
        self.assertEqual(interface['guard_gap']['opening'], 'RoofAccess')
        self.assertEqual(len(interface['opaque_body_ids']), len(set(source['opaque_area_ids'])-set(source['glass_area_ids']))+1)

    def test_true_cylinders_define_the_curved_hollow_roof_and_eaves(self):
        source, plan, p, levels = self.fixture(); result = roof.compile(source, plan, p, levels); interface = result['interface']; barrel = interface['barrel']
        operations = [op for op in result['operations'] if op['body'] == interface['glass_body_id']]
        self.assertEqual([op['shape']['kind'] for op in operations[:3]], ['cylinder', 'cylinder', 'box'])
        self.assertEqual([op['action'] for op in operations[:3]], ['create', 'cut', 'cut'])
        self.assertEqual(operations[0]['shape']['axis'], [1, 0, 0])
        self.assertEqual(operations[1]['shape']['radius'], barrel['radius_mm']-10)
        self.assertEqual(interface['roof_z_mm'], 17000)
        self.assertEqual(barrel['crown_z_mm'], 17350)
        self.assertEqual(barrel['axis'],'X');self.assertEqual(barrel['profile_axis'],'Y')
        self.assertEqual(interface['covered_corridor_area_ids'],['Area1_1','Area2_2','Area3_1'])
        self.assertAlmostEqual(barrel['profile_points_mm'][0][1], barrel['edge_z_mm'])
        self.assertAlmostEqual(barrel['profile_points_mm'][32][1], barrel['crown_z_mm'])
        self.assertTrue(all(math.isclose((x-barrel['center_cross_mm'])**2+(z-barrel['center_z_mm'])**2, barrel['radius_mm']**2, rel_tol=1e-12) for x, z in barrel['profile_points_mm']))
        self.assertGreater(len(interface['eave_support_probes']), 0)
        self.assertTrue(all(probe['expectation'] == 'union_filled' and probe['target_bodies'] == interface['opaque_body_ids'] for probe in interface['eave_support_probes']))
        self.assertEqual(interface['glass_interior_probe']['expectation'], 'empty')
        self.assertEqual(len(interface['material_probes']), 3)
        self.assertEqual(interface['glass_body_ids'],['RoofBarrelGlass','RoofGlassSkirt'])
        self.assertLessEqual(barrel['skirt_max_sagitta_mm'],barrel['glass_thickness_mm']*barrel['skirt_max_sagitta_fraction'])
        skirt=[op for op in result['operations']if op['body']=='RoofGlassSkirt']
        self.assertEqual([op['action']for op in skirt],['create','cut','cut'])
        self.assertEqual(skirt[-1]['shape']['plane'],'YZ')
        self.assertEqual(interface['glass_interior_probe']['target_bodies'],interface['glass_body_ids'])
        self.assertFalse(interface['structural_qualified'])

    def test_guard_gap_is_source_bound_and_all_geometry_is_separate_roof_group(self):
        source, plan, p, levels = self.fixture(); result = roof.compile(source, plan, p, levels); interface = result['interface']
        self.assertEqual(result['components'], [{'id': 'BuildingRoof', 'grounded': True}])
        self.assertTrue(all(body['component'] == 'BuildingRoof' for body in result['bodies']))
        self.assertEqual(len({op['id'] for op in result['operations']}), len(result['operations']))
        gap = next(probe for probe in interface['empty_probes'] if probe['id'] == 'RoofGuard_ExternalStairGap')
        self.assertEqual(gap['target_bodies'], interface['guard_body_ids'])
        self.assertEqual(interface['guard']['height_mm'], 1100)
        self.assertTrue(all(op['shape']['kind'] == 'polygon_prism' for op in result['operations'] if op['body'] in interface['guard_body_ids']))

    def test_invalid_reference_curvature_and_assumptions_fail_closed(self):
        source, plan, p, levels = self.fixture()
        for change in [lambda s: s['barrel'].update(glass_thickness_mm=1000), lambda s: s['guard'].update(height_mm=float('nan')),
                       lambda s: s.update(guard_gap_opening='Missing'), lambda s: s['opaque_area_ids'].append('Atrium')]:
            changed = copy.deepcopy(source); change(changed)
            with self.assertRaises(ValueError): roof.compile(changed, plan, p, levels)
        for modify in [lambda s:s['barrel'].update(axis='Y'),lambda s:s['barrel'].update(profile_segments=2),lambda s:s['barrel'].update(max_sagitta_fraction_of_glass_thickness=.9),lambda s:s['glass_area_ids'].remove('Area3_1')]:
            changed=copy.deepcopy(source);modify(changed)
            with self.assertRaises(ValueError):roof.compile(changed,plan,p,levels)

    def test_source_translation_moves_curvature_and_contour_without_copied_coordinates(self):
        source, plan, p, levels = self.fixture(); original = copy.deepcopy(plan); first = roof.compile(source, plan, p, levels)
        self.assertEqual(plan, original)
        shifted = copy.deepcopy(plan)
        shifted['vertices'] = {key: [point[0]+7, point[1]+11] for key, point in shifted['vertices'].items()}
        second = roof.compile(source, shifted, p, levels)
        a = first['interface']['barrel']; b = second['interface']['barrel']
        self.assertAlmostEqual(b['center_cross_mm']-a['center_cross_mm'], 11000)
        self.assertAlmostEqual(b['center_z_mm'], a['center_z_mm'])
        self.assertEqual(b['y_bounds_mm'], [value+11000 for value in a['y_bounds_mm']])
        self.assertEqual([edge['wall'] for edge in first['interface']['source_outer_contour']], [edge['wall'] for edge in second['interface']['source_outer_contour']])
    def test_union_mask_keeps_offices_outside_and_cuts_bbox_excess(self):
        source,plan,p,levels=self.fixture();result=roof.compile(source,plan,p,levels);view=result['interface'];mask=view['footprint_points_mm']
        self.assertAlmostEqual(roof.floor.signed_area(mask),4_000_000)
        self.assertLess(roof.floor.signed_area(mask),(max(v[0]for v in mask)-min(v[0]for v in mask))*(max(v[1]for v in mask)-min(v[1]for v in mask)))
        office=[3500,2500]
        self.assertEqual(roof.floor.point_membership(office,view['barrel']['glazing_footprint_points_mm']),-1)
        self.assertTrue(any(roof.floor.point_membership(office,op['shape']['points'])==1 for op in result['operations']if op['body']==view['glass_body_id']and '_Mask_'in op['id']))
        self.assertEqual({probe['area_id']for probe in view['corridor_coverage_probes']},{'Area1_1','Area2_2','Area3_1'})
        self.assertTrue(all(probe['target_body']==view['glass_body_id']for probe in view['corridor_coverage_probes']))

    def test_local_access_is_a_bounded_exception_not_a_corridor_roof(self):
        source,plan,p,levels=self.fixture();result=roof.compile(source,plan,p,levels);view=result['interface'];deck=view['local_access_deck']
        self.assertEqual(deck['body_id'],'RoofSlab_Area1_1')
        self.assertLess(deck['expected_volume_mm3'],1_000_000*p['slab_thickness_mm']/4)
        ops=[op for op in result['operations']if op['body']==deck['body_id']]
        self.assertEqual(len(ops),1);self.assertEqual(ops[0]['shape']['points'],deck['points_mm'])
        exceptions=view['local_opaque_exceptions'];self.assertEqual(len(exceptions),1)
        self.assertEqual(exceptions[0]['source_opening'],'RoofAccess')
        self.assertTrue(all(deck['body_id']not in probe['target_bodies']for probe in view['aperture_coverage_probes']))
        self.assertEqual(len(view['aperture_coverage_probes']),len(source['glass_area_ids']))

    def test_facet_budget_rejects_coarse_skirt_at_unchanged_glass_thickness(self):
        source,plan,p,levels=self.fixture();source['barrel']['profile_segments']=16;source['barrel']['max_sagitta_fraction_of_glass_thickness']=.00001
        with self.assertRaisesRegex(ValueError,'faceting'):roof.compile(source,plan,p,levels)



if __name__ == '__main__':
    unittest.main()
