"""Referenced atrium profile on inner stairs; no physical guard qualification."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_circulation as circulation
import building_guards as guards
import building_stack as stack
from test_building_circulation import fixture


def clipped_area(points, low, high):
    """Independent polygon/rectangle section check for portable rail prisms."""
    polygon = [list(point) for point in points]
    for axis, boundary, greater in [(0, low[0], True), (0, high[0], False),
                                    (1, low[1], True), (1, high[1], False)]:
        output = []
        for a, b in zip(polygon, polygon[1:]+polygon[:1]):
            ain = a[axis] >= boundary if greater else a[axis] <= boundary
            bin = b[axis] >= boundary if greater else b[axis] <= boundary
            if ain: output.append(a)
            if ain != bin:
                fraction = (boundary-a[axis])/(b[axis]-a[axis])
                output.append([a[i]+fraction*(b[i]-a[i]) for i in (0, 1)])
        polygon = output
        if not polygon: return 0
    return abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(polygon, polygon[1:]+polygon[:1])))/2


def prism_box_overlap(shape, box):
    axes = (0, 1) if shape['plane'] == 'XY' else (0, 2)
    extrusion = 2 if shape['plane'] == 'XY' else 1
    low = box['origin']; high = [a+b for a,b in zip(low, box['size'])]
    thickness = max(0, min(shape['offset']+shape['depth'], high[extrusion])-
                    max(shape['offset'], low[extrusion]))
    return thickness*clipped_area(shape['points'], [low[i] for i in axes], [high[i] for i in axes])


class StairGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.plan, cls.p, cls.levels = fixture()
        cls.profile = guards.profile_from_exterior(json.loads(stack.SOURCE.read_text())['exterior'])
        cls.legacy = circulation.compile(cls.source, cls.plan, cls.p, cls.levels)
        cls.source['stairs']['guard_profile_ref'] = '#/exterior'
        cls.source['stairs']['instances'][0]['top_guard_wall'] = 'EastWellW0'
        cls.result = cls.build()
        cls.view = cls.result['interface']

    @classmethod
    def build(cls, source=None, profile=None):
        return circulation.compile(source or cls.source, cls.plan, cls.p, cls.levels,
                                   guard_profile=cls.profile if profile is None else profile)

    def test_reference_is_explicit_and_existing_geometry_is_unchanged(self):
        ids = set(self.view['guard_body_ids'])
        self.assertTrue(ids)
        self.assertEqual(self.result['components'], self.legacy['components'])
        self.assertEqual([b for b in self.result['bodies'] if b['id'] not in ids], self.legacy['bodies'])
        self.assertEqual([o for o in self.result['operations'] if o['body'] not in ids], self.legacy['operations'])
        self.assertEqual(self.view['stairs'][0]['body_ids'], self.legacy['interface']['stairs'][0]['body_ids'])
        self.assertEqual(len(self.view['stairs'][0]['body_ids']), 4)
        self.assertEqual(self.view['guard_profile_ref'], '#/exterior')
        self.assertFalse(self.view['guard_safety_qualified'])
        self.assertFalse(self.view['headroom_qualified'])
        self.assertFalse(self.view['egress_qualified'])

    def test_all_four_intervals_have_only_the_two_inner_flights_and_gap_edges(self):
        groups = self.view['guard_groups']
        self.assertEqual(len(groups), 24)
        intervals = [(level['id'], upper['id']) for level, upper in zip(self.levels, self.levels[1:])]
        self.assertEqual({(g['from_level'], g['to_level']) for g in groups}, set(intervals))
        self.assertEqual({g['kind'] for g in groups},
                         {'FirstInner', 'FirstTop', 'MidGap', 'ReturnInner', 'ReturnTop', 'UpperGap'})
        for lower, upper in intervals:
            selected = {g['kind']: g for g in groups if (g['from_level'], g['to_level']) == (lower, upper)}
            first, first_top, middle, returning, return_top, top = (selected[k] for k in
                ('FirstInner', 'FirstTop', 'MidGap', 'ReturnInner', 'ReturnTop', 'UpperGap'))
            self.assertEqual(first['end_mm'], first_top['start_mm'])
            self.assertEqual(first_top['end_mm'], middle['start_mm'])
            self.assertEqual(middle['end_mm'], returning['start_mm'])
            self.assertEqual(returning['end_mm'], return_top['start_mm'])
            self.assertEqual(return_top['end_mm'], top['start_mm'])
            for flight in (first, returning):
                a, b = flight['start_mm'], flight['end_mm']
                self.assertEqual(a[1], b[1])
                self.assertNotEqual(a[0], b[0])
                self.assertLess(a[2], b[2])
            for landing in (first_top, middle, return_top, top):
                a, b = landing['start_mm'], landing['end_mm']
                self.assertEqual(a[2], b[2])
            for landing in (middle, top):
                self.assertEqual(landing['start_mm'][0], landing['end_mm'][0])
        self.assertFalse(any(g['kind'] == 'LowerGap' for g in groups))

    def test_landing_rails_cover_the_central_void_without_crossing_walking_lanes(self):
        stair = self.view['stairs'][0]
        rect = stair['interior_rectangle_mm']
        y0, y1 = min(p[1] for p in rect), max(p[1] for p in rect)
        lane = stair['connectors'][0]['lane_width_mm']; post = self.profile['post_mm']
        for group in self.view['guard_groups']:
            if group['kind'] not in {'MidGap', 'UpperGap'}: continue
            ys = sorted((group['start_mm'][1], group['end_mm'][1]))
            if group.get('wall_termination'):
                self.assertAlmostEqual(ys[0]-post/2, self.p['display_thickness']/2)
            else:
                self.assertAlmostEqual(ys[0], y0+lane-post/2)
                self.assertGreater(ys[0]-post/2, y0)
            self.assertAlmostEqual(ys[1], y1-lane+post/2)
            self.assertLess(ys[1]+post/2, y1)

    def test_only_topmost_unused_flight_is_closed_flush_to_referenced_wall(self):
        terminated = [g for g in self.view['guard_groups'] if 'wall_termination' in g]
        self.assertEqual(len(terminated), 1)
        group = terminated[0]; wall = group['wall_termination']
        self.assertEqual((group['kind'], group['to_level']), ('UpperGap', 'OG3'))
        self.assertEqual(wall['wall_body_id'], 'OG3__Wall_EastWellW0')
        shape = next(o['shape'] for o in self.result['operations']
                     if o['body'] == wall['terminal_post_body_id'])
        face = self.p['display_thickness']/2
        self.assertAlmostEqual(min(v[1] for v in shape['points']), face)
        self.assertAlmostEqual(group['end_mm'][1]-self.profile['post_mm']/2, face)
        self.assertEqual(wall['interior_face_y_mm'], face)
        post = next(p for p in self.view['guard_posts'] if p['body_id'] == wall['terminal_post_body_id'])
        self.assertEqual(post['support_body_id'], 'OG3__Area_EastWell')
        self.assertAlmostEqual(post['support_z_mm'], self.levels[-1]['z_mm'])

    def test_wall_extension_preserves_every_other_guard_and_all_existing_geometry(self):
        source = copy.deepcopy(self.source)
        source['stairs']['instances'][0].pop('top_guard_wall')
        previous = self.build(source=source)
        group = next(g for g in self.view['guard_groups'] if 'wall_termination' in g)
        changed = set(group['body_ids'])
        for key in ('bodies', 'operations'):
            field = 'id' if key == 'bodies' else 'body'
            self.assertEqual([v for v in self.result[key] if v[field] not in changed],
                             [v for v in previous[key] if v[field] not in changed])
        for current, old in zip(self.view['guard_groups'], previous['interface']['guard_groups']):
            if current['id'] != group['id']: self.assertEqual(current, old)
        # A wider synthetic stair can require another post on the extension;
        # the existing clearance geometry still applies to all current guards.
        def geometry(probes):
            return [{k:v for k,v in p.items() if k != 'target_bodies'} for p in probes]
        self.assertEqual(geometry(self.view['guard_clearance_probes']),
                         geometry(previous['interface']['guard_clearance_probes']))

    def test_wall_termination_tracks_source_wall_position_and_thickness(self):
        plan = copy.deepcopy(self.plan); parameters = dict(self.p)
        for vertex in plan['vertices'].values(): vertex[1] += 2
        parameters['display_thickness'] = 240
        result = circulation.compile(self.source, plan, parameters, self.levels, guard_profile=self.profile)
        group = next(g for g in result['interface']['guard_groups'] if 'wall_termination' in g)
        expected_face = 2*parameters['display_scale']+parameters['display_thickness']/2
        self.assertAlmostEqual(group['end_mm'][1]-self.profile['post_mm']/2, expected_face)

    def test_wall_termination_rejects_missing_wrong_side_or_non_wall_references(self):
        for wall in ('DoesNotExist', 'LiftBoxW3', 'EastWellW1', 'EastWellW2'):
            source = copy.deepcopy(self.source); source['stairs']['instances'][0]['top_guard_wall'] = wall
            with self.subTest(wall=wall), self.assertRaises(ValueError): self.build(source=source)
        source = copy.deepcopy(self.source); source['stairs'].pop('guard_profile_ref')
        with self.assertRaisesRegex(ValueError, 'requires the referenced guard profile'):
            circulation.validate_source(source)

    def test_shared_corner_posts_are_single_bodies_and_members_stay_in_the_stair_component(self):
        bodies = self.result['bodies']; identifiers = [b['id'] for b in bodies]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        posts = self.view['guard_posts']
        self.assertEqual(len(posts), len({p['body_id'] for p in posts}))
        self.assertEqual(len(posts), len({tuple(p['base_mm']) for p in posts}))
        guard_ids = set(self.view['guard_body_ids'])
        self.assertTrue(all(b['component'] == 'EastStair' for b in bodies if b['id'] in guard_ids))
        groups = self.view['guard_groups']
        first = groups[0]; middle = groups[1]
        self.assertTrue(set(first['body_ids']) & set(middle['body_ids']))
        for identifier in guard_ids:
            self.assertEqual(sum(o['action'] == 'create' and o['body'] == identifier
                                 for o in self.result['operations']), 1)

    def test_new_members_use_portable_prisms_and_sloped_rails_follow_source_pitch(self):
        operations = {o['body']: o for o in self.result['operations'] if o['body'] in set(self.view['guard_body_ids'])}
        for group in self.view['guard_groups']:
            a, b = group['start_mm'], group['end_mm']
            handrail = operations[group['id']+'_Handrail']['shape']
            self.assertEqual(handrail['kind'], 'polygon_prism')
            if group['kind'] in {'FirstInner', 'ReturnInner'}:
                self.assertEqual(handrail['plane'], 'XZ')
                points = handrail['points']
                xlo, xhi = min(p[0] for p in points), max(p[0] for p in points)
                lo = [xlo, min(p[1] for p in points if p[0] == xlo)]
                hi = [xhi, min(p[1] for p in points if p[0] == xhi)]
                slope = (b[2]-a[2])/(b[0]-a[0])
                self.assertAlmostEqual((hi[1]-lo[1])/(hi[0]-lo[0]), slope)
            else:
                self.assertEqual(handrail['plane'], 'XY')

    def test_post_spacing_is_bounded_on_the_actual_sloped_segments(self):
        posts = {p['body_id']:p for p in self.view['guard_posts']}
        for group in self.view['guard_groups']:
            ordered = [posts[name]['top_mm'] for name in group['post_body_ids']]
            self.assertGreaterEqual(len(ordered), 2)
            for a, b in zip(ordered, ordered[1:]):
                self.assertLessEqual(math.dist(a, b), self.profile['max_post_spacing_mm']+1e-7)

    def test_guard_only_clearance_probes_leave_lane_centres_and_landings_open(self):
        probes = self.view['guard_clearance_probes']; identifiers = set(self.view['guard_body_ids'])
        self.assertEqual(len(probes), 16)
        footprints = []
        for operation in self.result['operations']:
            if operation['body'] not in identifiers: continue
            shape = operation['shape']
            if shape['plane'] == 'XY':
                xs = [v[0] for v in shape['points']]; ys = [v[1] for v in shape['points']]
                footprints.append((min(xs), min(ys), max(xs), max(ys)))
            else:
                xs = [v[0] for v in shape['points']]
                footprints.append((min(xs), shape['offset'], max(xs), shape['offset']+shape['depth']))
        for probe in probes:
            self.assertEqual(probe['scope'], 'new_guard_members_only')
            self.assertEqual(set(probe['target_bodies']), identifiers)
            self.assertEqual(probe['expectation'], 'empty')
            xs = [v[0] for v in probe['points_mm']]; ys = [v[1] for v in probe['points_mm']]
            low = [min(xs), min(ys)]; high = [max(xs), max(ys)]
            self.assertLess(low[0], high[0]); self.assertLess(low[1], high[1])
            for x0,y0,x1,y1 in footprints:
                self.assertEqual(max(0, min(high[0],x1)-max(low[0],x0))*
                    max(0, min(high[1],y1)-max(low[1],y0)), 0)

    def test_all_non_post_members_stay_outside_existing_step_and_landing_material(self):
        identifiers = set(self.view['guard_body_ids'])-{p['body_id'] for p in self.view['guard_posts']}
        stairs = set(self.legacy['interface']['stairs'][0]['body_ids'])
        supports = [o['shape'] for o in self.legacy['operations']
                    if o['body'] in stairs and o['action'] in {'create', 'join'}]
        for operation in self.result['operations']:
            if operation['body'] not in identifiers: continue
            for support in supports:
                self.assertLessEqual(prism_box_overlap(operation['shape'], support), 1e-5,
                                     (operation['body'], support))

    def test_attachment_witnesses_are_positive_and_target_posts_and_existing_supports(self):
        posts = self.view['guard_posts']; witnesses = {w['id']: w for w in self.view['guard_attachment_witnesses']}
        self.assertEqual(len(witnesses), len(posts))
        old_bodies = {b['id'] for b in self.legacy['bodies']}
        floors = {level['id']+'__Area_EastWell' for level in self.levels}
        connector_ops = {}
        for operation in self.legacy['operations']:
            if operation['action'] in {'create', 'join'} and operation['shape']['kind'] == 'box':
                connector_ops.setdefault(operation['body'], []).append(operation['shape'])
        for post in posts:
            witness = witnesses[post['attachment_probe_id']]
            support = post['support_body_id']
            self.assertIn(support, old_bodies | floors)
            self.assertEqual(set(witness['target_bodies']), {post['body_id'], support})
            self.assertGreater(witness['depth_mm'], 0)
            self.assertTrue(all(v > 0 for v in witness['expected_volumes_mm3'].values()))
            self.assertLess(witness['offset_mm'], post['reference_pitch_z_mm'])
            self.assertAlmostEqual(post['base_mm'][2], post['support_z_mm']-
                                   self.p['slab_thickness_mm']*self.source['stairs']['join_slab_fraction'])
            if support in floors:
                connector = self.view['stairs'][0]['connectors'][0]
                self.assertGreater(min(p[0] for p in witness['points_mm']), connector['entry_x_mm'])
            else:
                # Every attachment corner is supported by the union of the
                # original step/landing boxes, independently of the guard recipe.
                points = [(x,y,z) for x,y in witness['points_mm'] for z in
                          (witness['offset_mm'], witness['offset_mm']+witness['depth_mm'])]
                self.assertTrue(all(any(all(shape['origin'][i]-1e-7 <= point[i] <=
                    shape['origin'][i]+shape['size'][i]+1e-7 for i in range(3))
                    for shape in connector_ops[support]) for point in points), post)

    def test_explicit_reference_requires_a_valid_profile_and_fit(self):
        with self.assertRaisesRegex(ValueError, 'supplied explicitly'):
            circulation.compile(self.source, self.plan, self.p, self.levels)
        changed = copy.deepcopy(self.source); changed['stairs']['guard_profile_ref'] = '#/roof/guard'
        with self.assertRaisesRegex(ValueError, 'existing exterior atrium'):
            self.build(source=changed)
        for field, value in [('post_mm', True), ('height_mm', float('nan')), ('post_mm', 1000)]:
            profile = copy.deepcopy(self.profile); profile[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): self.build(profile=profile)
        changed = copy.deepcopy(self.source); changed['stairs']['risers_per_flight'] = 2
        changed['stairs']['instances'][0].pop('top_guard_wall')
        with self.assertRaisesRegex(ValueError, 'nosing-line'):
            self.build(source=changed)


class ActualStairGuardProfileTests(unittest.TestCase):
    def test_active_source_references_the_same_profile_for_stairs_and_atrium(self):
        spec = stack.load()
        self.assertEqual(spec['circulation']['stairs']['guard_profile_ref'], '#/exterior')
        before = stack.expanded(spec, stack.parameters(spec))
        changed = copy.deepcopy(spec); changed['exterior']['guard_height_mm'] += 100
        after = stack.expanded(changed, stack.parameters(changed))
        def depth(data, identifier):
            return next(o['shape']['depth'] for o in data['operations'] if o['body'] == identifier)
        for name in ['AtriumGuard_OG1_W065_Post0', 'EastStair_KG_EG_Guard_FirstInner_Post0']:
            self.assertAlmostEqual(depth(after, name)-depth(before, name), 100)
        old = {b['id']:b for b in before['bodies']}
        for body in after['bodies']:
            self.assertEqual(body['appearance'], old[body['id']]['appearance'])


if __name__ == '__main__': unittest.main()
