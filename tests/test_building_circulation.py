"""Invented lift/wells verify the shared recipe, policy and geometric witnesses."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_stack as stack
import building_circulation as model
import relative_floorplan as floor


def fixture():
    plan = {'format': floor.FORMAT, 'id': 'CirculationFixture', 'units': {'length': 'relative'}, 'calibration': None, 'vertices': {}, 'walls': [], 'areas': [], 'openings': [],
            'provenance': {'method': 'manual_trace', 'source_kind': 'synthetic_fixture', 'accuracy': 'approximate', 'notes': ['Invented test polygons only.']}}
    vertex_ids = {}; edge_ids = {}
    def area(name, kind, points):
        vertices = []
        for point in points:
            key = tuple(point)
            if key not in vertex_ids:
                identifier = 'V'+str(len(vertex_ids)); vertex_ids[key] = identifier; plan['vertices'][identifier] = list(point)
            vertices.append(vertex_ids[key])
        refs = []
        for index, (a, b) in enumerate(zip(vertices, vertices[1:]+vertices[:1])):
            key = frozenset((a, b))
            if key not in edge_ids:
                wall = {'id': name+'W'+str(index), 'start': a, 'end': b, 'kind': 'wall'}; edge_ids[key] = wall; plan['walls'].append(wall)
            wall = edge_ids[key]; refs.append({'wall': wall['id'], 'direction': 1 if wall['start'] == a else -1})
        plan['areas'].append({'id': name, 'label': name, 'kind': kind, 'confidence': 'approximate', 'boundary': refs})
    area('LiftBox', 'unknown', [[0, 0], [4, 0], [4, 4], [0, 4]])
    plan['walls'][0]['kind'] = 'unknown'
    area('Core', 'unknown', [[4, 0], [5, 0], [5, 4], [4, 4]])
    area('WestWell', 'stairwell', [[6, 0], [12, 0], [12, 4], [7, 4]])
    area('WestCorridor', 'corridor', [[12,0],[13,0],[13,4],[12,4]])
    area('EastWell', 'stairwell', [[14, 0], [20, 0], [20, 4], [14, 4]])
    area('EastCorridor', 'corridor', [[20,0],[21,0],[21,4],[20,4]])
    area('Reference', 'room', [[0, 6], [2, 6], [2, 8], [0, 8]])
    area('Atrium', 'void', [[6, 6], [10, 6], [10, 10], [6, 10]])
    for identifier, wall, kind in [('LiftAnchor', 'LiftBoxW3', 'unknown'), ('WestDoor', 'WestWellW1', 'door'), ('EastDoor', 'EastWellW1', 'door')]:
        plan['openings'].append({'id': identifier, 'wall': wall, 'interval': [.25, .5], 'kind': kind, 'confidence': 'uncertain' if kind == 'unknown' else 'approximate', 'connection': 'uncertain'})
    floor.validate(plan)
    source = json.loads(stack.SOURCE.read_text())['circulation']
    source['elevator'].update(area='LiftBox', reference_opening='LiftAnchor')
    source['elevator']['sides']['outward']['wall'] = 'LiftBoxW3'; source['elevator']['sides']['inward']['wall'] = 'LiftBoxW1'
    source['stairs']['instances'] = [{'id': 'EastStair', 'area': 'EastWell', 'entry_opening': 'EastDoor'}]
    source['external_stair'].update(area='WestWell',entry_opening='WestDoor',ground_area='GroundSupport',ground_exit_neighbor='GroundSupport')
    p = {'display_scale': 1000., 'display_thickness': 200., 'slab_thickness_mm': 250., 'door_height_mm': 2100., 'clear_height_mm': 4000., 'floor_pitch_mm': 4250., 'display_height': 4000., 'display_floor_depth': 250.}
    levels = [{'id': name, 'z_mm': (index-1)*p['floor_pitch_mm'], 'clear_top_mm': (index-1)*p['floor_pitch_mm']+p['clear_height_mm']} for index, name in enumerate(['KG', 'EG', 'OG1', 'OG2', 'OG3'])]
    return source, plan, p, levels


def box_bounds(operation):
    shape = operation['shape']; return shape['origin'], [a+b for a, b in zip(shape['origin'], shape['size'])]


def overlap(a, b):
    lo, hi = a; low, high = b
    result = 1.
    for i in range(3): result *= max(0, min(hi[i], high[i])-max(lo[i], low[i]))
    return result


def probe_bounds(probe):
    points = probe['points_mm']; return [min(p[0] for p in points), min(p[1] for p in points), probe['offset_mm']], [max(p[0] for p in points), max(p[1] for p in points), probe['offset_mm']+probe['depth_mm']]


class CirculationTests(unittest.TestCase):
    def setUp(self): self.source, self.plan, self.p, self.levels = fixture()
    def build(self): return model.compile(self.source, self.plan, self.p, self.levels)

    def test_confirmed_door_policy_one_cabin_and_basement_geometry(self):
        result = self.build(); view = result['interface']; lift = view['elevator']
        self.assertEqual(lift['doors_by_level'], {'KG': ['inward'], 'EG': ['outward', 'inward'], 'OG1': ['outward'], 'OG2': ['outward'], 'OG3': ['outward']})
        self.assertEqual(len(lift['cabin_body_ids']), 1); self.assertEqual(lift['cabin_level'], 'EG')
        self.assertEqual(len(view['door_probes']), 6); self.assertEqual(len(view['closed_door_probes']), 4)
        self.assertEqual(lift['deferred_stops'], [])
        self.assertTrue(any('KG' in body['id'] for body in result['bodies']))
        self.assertTrue(any(port['level_id'] == 'KG' for port in lift['ports']))
        self.assertTrue(view['basement_geometry_implemented'])

    def test_six_visible_door_frames_match_only_active_faces_and_stay_outside_probes(self):
        result = self.build(); view = result['interface']; lift = view['elevator']
        self.assertEqual(len(lift['door_frame_body_ids']), 6)
        for port in lift['ports']:
            self.assertEqual(port['frame_body_id'] is not None, port['active'])
        for probe in view['door_probes']:
            frame = next(target for target in probe['target_bodies'] if target in lift['door_frame_body_ids'])
            self.assertIn(frame, view['detail_visibility_ids'])
            for operation in result['operations']:
                if operation['body'] == frame:
                    self.assertEqual(overlap(probe_bounds(probe), box_bounds(operation)), 0)

    def test_all_stair_and_doorframe_joins_have_positive_connected_overlap(self):
        result = self.build()
        targets = {b['id'] for b in result['bodies'] if b['role'] in {'concept_continuous_stair', 'concept_lift_door_frame'}}
        self.assertEqual(sum(b['role'] == 'concept_continuous_stair' for b in result['bodies']), 4)
        for target in targets:
            pieces = []
            for operation in result['operations']:
                if operation['body'] != target: continue
                current = box_bounds(operation)
                if not pieces: self.assertEqual(operation['action'], 'create')
                else:
                    self.assertEqual(operation['action'], 'join')
                    self.assertTrue(any(overlap(current, prior) > 1e-6 for prior in pieces), target)
                pieces.append(current)

    def test_contacts_use_full_probe_volume_inside_both_landing_and_connector(self):
        result = self.build(); view = result['interface']
        self.assertEqual(len(view['connection_witnesses']), 24)
        by_body = {}
        for operation in result['operations']:
            if operation['shape']['kind'] == 'box' and operation['action'] in {'create', 'join'}: by_body.setdefault(operation['body'], []).append(box_bounds(operation))
        for witness in [w for w in view['connection_witnesses'] if w.get('system') != 'external_metal']:
            volume = floor.signed_area(witness['points_mm'])*witness['depth_mm']; bounds = probe_bounds(witness)
            self.assertEqual(witness['expectation'], 'filled')
            for target, expected in witness['expected_volumes_mm3'].items():
                self.assertAlmostEqual(expected, volume)
                if '__Area_' in target:
                    level_id, area_id = target.split('__Area_'); z = next(level['z_mm'] for level in self.levels if level['id'] == level_id)
                    self.assertGreaterEqual(bounds[0][2], z-self.p['slab_thickness_mm']); self.assertLessEqual(bounds[1][2], z)
                    polygon = [[v*self.p['display_scale'] for v in point] for point in floor.outline(self.plan, area_id)]
                    self.assertTrue(all(floor.point_membership(p, polygon) == 1 for p in witness['points_mm']))
                else:
                    self.assertTrue(any(abs(overlap(bounds, box)-volume) < 1e-5 for box in by_body[target]), target)

    def test_slab_holes_preserve_entry_landings_and_lowest_floor(self):
        result = self.build(); view = result['interface']; self.assertEqual(len(view['slab_hole_probes']), 4)
        for stair in view['stairs']:
            for level in self.levels:
                original = level['id']+'__Area_'+stair['area']
                self.assertIn(original, view['detail_visibility_ids']); self.assertNotIn(original, view['body_ids'])
            self.assertEqual(len(stair['connectors']), 4)
            for connector in stair['connectors']:
                hole = next(p for p in view['slab_hole_probes'] if p['id'] == connector['id']+'_SlabHole')
                self.assertFalse(hole['target_body'].startswith('KG__'))
                self.assertLess(max(p[0] for p in hole['points_mm']), connector['entry_x_mm'])
                self.assertEqual(connector['risers'], 24)
                self.assertEqual(connector['z1_mm']-connector['z0_mm'], self.p['floor_pitch_mm'])

    def test_only_known_deduplicated_boundary_walls_receive_slab_height_bridges(self):
        result = self.build(); view = result['interface']; ids = view['wall_bridge_ids']
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(any('LiftBoxW0' in name for name in ids))
        for operation in result['operations']:
            if operation['body'] in ids:
                self.assertEqual(operation['shape']['depth'], self.p['slab_thickness_mm'])
                self.assertIn(operation['shape']['offset'], [level['clear_top_mm'] for level in self.levels[:-1]])
        self.assertTrue(set(ids) <= set(view['body_ids']))

    def test_height_variant_updates_connectors_and_continuous_shaft_without_new_stops(self):
        self.p.update(clear_height_mm=3500, slab_thickness_mm=300, floor_pitch_mm=3800)
        for index, level in enumerate(self.levels): level.update(z_mm=(index-1)*3800, clear_top_mm=(index-1)*3800+3500)
        result = self.build(); view = result['interface']
        for stair in view['stairs']:
            self.assertEqual([c['z1_mm'] for c in stair['connectors']], [0, 3800, 7600, 11400])
        self.assertTrue(all(w['depth_mm'] == 18700 for w in view['shaft_witnesses']))
        self.assertEqual(view['elevator']['deferred_stops'], [])

    def test_unknown_source_space_and_opening_are_not_rewritten_or_qualified(self):
        source, plan = copy.deepcopy(self.source), copy.deepcopy(self.plan)
        result = self.build()
        self.assertEqual(self.source, source); self.assertEqual(self.plan, plan)
        self.assertEqual(next(o for o in self.plan['openings'] if o['id'] == 'LiftAnchor')['kind'], 'unknown')
        self.assertEqual(next(a for a in self.plan['areas'] if a['id'] == 'Core')['kind'], 'unknown')
        self.assertFalse(result['interface']['elevator']['operation_implemented'])
        self.assertFalse(result['interface']['headroom_qualified']); self.assertFalse(result['interface']['egress_qualified'])

    def test_invalid_policy_kg_guess_side_reference_and_nonfitting_recipe_fail(self):
        for change in ['policy', 'kg', 'side', 'fit', 'count', 'extra', 'second_stair', 'external_same', 'extent']:
            source = copy.deepcopy(self.source)
            if change == 'policy': source['elevator']['default_sides'] = ['inward']
            elif change == 'kg': source['elevator']['stop_overrides']['KG'] = ['outward']
            elif change == 'side': source['elevator']['sides']['inward']['wall'] = 'LiftBoxW2'
            elif change == 'fit': source['stairs']['wall_margin_factor'] = 100
            elif change == 'count': source['stairs']['risers_per_flight'] = True
            elif change == 'second_stair': source['stairs']['instances'].append({'id': 'WestStair', 'area': 'WestWell', 'entry_opening': 'WestDoor'})
            elif change == 'external_same': source['external_stair']['area'] = 'EastWell'
            elif change == 'extent': source['served_extent']['from_level'] = 'EG'
            else: source['rail_drive'] = {}
            with self.subTest(change=change), self.assertRaises(ValueError): model.compile(source, self.plan, self.p, self.levels)

    def test_stack_integration_preserves_source_floor_ids_and_separates_blue_marker(self):
        spec = json.loads(stack.SOURCE.read_text()); spec.pop('exterior', None); spec.pop('alignment', None); spec['sources'].pop('furnishings', None); spec['circulation'] = copy.deepcopy(self.source); spec['presentation_reference']['floorplan_area'] = 'Reference'
        reference = {'parameters': {name: {'expression': value, 'unit': 'mm'} for name, value in [('room_width', 2000), ('wall_t', 200), ('door_height', 2100)]}}
        ground = copy.deepcopy(self.plan)
        next(a for a in ground['areas'] if a['id'] == 'WestWell')['id'] = 'GroundSupport'
        with mock.patch.object(stack, 'templates', return_value=(self.plan, reference)), mock.patch.object(stack, 'level_plan', side_effect=lambda spec,level: ground if level == 'EG' else self.plan), mock.patch.object(stack.ground,'source_dependencies',return_value=[]), mock.patch.object(stack.roof,'compile',return_value={'components':[],'bodies':[],'operations':[],'interface':{}}), mock.patch.object(stack.room, 'parameters', side_effect=stack.robot.parameters):
            p = stack.parameters(spec); data = stack.interfaces(spec, p); expanded = stack.expanded(spec, p)
        ids = {b['id'] for b in expanded['bodies']}
        self.assertTrue(set(data['circulation']['body_ids']) <= ids)
        self.assertTrue(set(data['circulation']['detail_visibility_ids']) <= ids)
        self.assertTrue(set(data['circulation']['wall_bridge_ids']) <= set(data['wall_visibility_ids']))
        self.assertEqual(data['marker_body_ids'], ['ConceptExchange'])
        self.assertNotIn('ConceptExchange', data['circulation']['body_ids'])
        self.assertIn('OG1__Area_EastWell', ids)
        self.assertTrue(any(op['body'] == 'OG1__Area_EastWell' and op['action'] == 'cut' for op in expanded['operations']))
        self.assertNotIn('OG1__Area_WestWell', ids)
        self.assertFalse(any(op['body'] == 'OG1__Area_WestWell' and op['action'] == 'cut' for op in expanded['operations']))
        self.assertTrue(any(path.name == 'building_circulation.py' for path in stack.source_dependencies(stack.load())))

    def test_one_separate_stair_has_a_modeled_basement_link(self):
        result = self.build(); view = result['interface']; self.assertEqual(len(view['stairs']), 1)
        stair = view['stairs'][0]
        self.assertEqual(stair['id'], 'EastStair'); self.assertEqual(stair['component_id'], 'EastStair')
        self.assertEqual(view['elevator']['component_id'], 'BuildingLift')
        self.assertEqual(stair['served_extent'], {'from_level': 'KG', 'to_level': 'OG3'})
        self.assertEqual(view['elevator']['served_extent'], stair['served_extent'])
        self.assertEqual(stair['planned_connectors'], [])
        self.assertEqual(stair['connectors'][0]['from_level'], 'KG')
        self.assertEqual(stair['connectors'][0]['to_level'], 'EG')
        self.assertEqual(len(view['external_stairs']), 1)
        self.assertEqual(view['external_stairs'][0]['area'], 'WestWell')
        self.assertFalse(any(body['id'].startswith('WestStair') for body in result['bodies']))
        by_id = {b['id']: b for b in result['bodies']}
        self.assertTrue(all(by_id[name]['component'] == 'BuildingLift' for name in view['elevator']['shaft_body_ids']+view['elevator']['cabin_body_ids']+view['elevator']['door_frame_body_ids']))
        self.assertTrue(all(by_id[name]['component'] == 'EastStair' for name in stair['body_ids']))
        self.assertEqual({component['id'] for component in result['components']}, {'BuildingLift', 'EastStair', 'ExternalFireStair'})

    def test_external_metal_stair_has_four_lightweight_intervals_and_no_basement(self):
        result = self.build(); view = result['interface']; external = view['external_stairs'][0]
        self.assertEqual(external['component_id'], 'ExternalFireStair')
        self.assertEqual(external['served_extent'], {'from_level': 'EG', 'to_level': 'ROOF'})
        self.assertEqual([(c['from_level'], c['to_level']) for c in external['connectors']], [('EG','OG1'),('OG1','OG2'),('OG2','OG3'),('OG3','ROOF')])
        self.assertEqual(external['connectors'][-1]['z1_mm'], self.levels[-1]['clear_top_mm']+self.p['slab_thickness_mm'])
        self.assertEqual(external['planned_connectors'], [])
        self.assertTrue(all(c['slab_hole_probe_id'] is None for c in external['connectors']))
        self.assertEqual(len(external['landing_body_ids']), 5)
        self.assertEqual(external['access_floor_area'], 'WestCorridor')
        self.assertEqual(len(view['external_access_witnesses']),4)
        self.assertTrue(any('RoofSlab_WestCorridor' in probe['target_bodies'] for probe in view['external_access_witnesses']))
        internal_ids = set(view['stairs'][0]['body_ids'])
        self.assertFalse(internal_ids & set(external['body_ids']))
        self.assertFalse(any('__Area_WestWell' in p['target_bodies'] for p in view['slab_hole_probes']))
        for connector in external['connectors']:
            ops = [op for op in result['operations'] if op['body'] == connector['body_id']]
            self.assertEqual(sum(op['shape']['kind'] == 'polygon_prism' and op['shape']['plane'] == 'XZ' for op in ops), 4)
            treads = [op['shape'] for op in ops if '_Tread_' in op['id'] or 'Tread_' in op['id']]
            self.assertEqual(len(treads), 24)
            self.assertTrue(all(shape['size'][2] == self.source['external_stair']['tread_thickness_mm'] for shape in treads))
            self.assertTrue(all(op['action'] == ('create' if index == 0 else 'join') for index,op in enumerate(ops)))

    def test_external_contacts_are_wholly_inside_actual_metal_primitives(self):
        result = self.build(); witnesses = [p for p in result['interface']['connection_witnesses'] if p.get('system') == 'external_metal']
        self.assertEqual(len(witnesses), 12)
        def contains(shape, point):
            if shape['kind'] == 'box':
                return all(a-1e-7 <= value <= a+length+1e-7 for value,a,length in zip(point,shape['origin'],shape['size']))
            return shape['offset']-1e-7 <= point[1] <= shape['offset']+shape['depth']+1e-7 and floor.point_membership([point[0],point[2]],shape['points']) >= 0
        for witness in witnesses:
            vertices = [[x,y,z] for x,y in witness['points_mm'] for z in [witness['offset_mm'],witness['offset_mm']+witness['depth_mm']]]
            for target,volume in witness['expected_volumes_mm3'].items():
                shapes = [op['shape'] for op in result['operations'] if op['body'] == target]
                self.assertTrue(any(all(contains(shape,point) for point in vertices) for shape in shapes), witness['id']+' '+target)
                self.assertAlmostEqual(volume, floor.signed_area(witness['points_mm'])*witness['depth_mm'])

    def test_registered_ground_core_drift_is_rejected_before_geometry(self):
        ground = copy.deepcopy(self.plan)
        # Renaming the external ground area is a source-level EG change; cores stay shared.
        next(a for a in ground['areas'] if a['id'] == 'WestWell')['id'] = 'GroundSupport'
        vertex = next(a for a in ground['areas'] if a['id'] == 'EastWell')['boundary'][0]
        wall = next(w for w in ground['walls'] if w['id'] == vertex['wall'])
        ground['vertices'][wall['start']][0] += .01
        with self.assertRaisesRegex(ValueError, 'core outline'):
            model.compile(self.source,self.plan,self.p,self.levels,ground_plan=ground)

    def test_lift_numeric_geometry_is_independent_of_which_stair_template_is_selected(self):
        first = self.build()
        alternative = copy.deepcopy(self.source)
        alternative['stairs']['instances'] = [{'id': 'WestStair', 'area': 'WestWell', 'entry_opening': 'WestDoor'}]
        alternative['external_stair'].update(area='EastWell',entry_opening='EastDoor')
        second = model.compile(alternative, self.plan, self.p, self.levels)
        def lift_geometry(result):
            ids = {b['id'] for b in result['bodies'] if b['component'] == 'BuildingLift'}
            return {op['id']: op for op in result['operations'] if op['body'] in ids}
        self.assertEqual(lift_geometry(first), lift_geometry(second))


if __name__ == '__main__': unittest.main()
