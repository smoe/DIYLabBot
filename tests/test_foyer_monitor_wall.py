"""Shared monitor placement and negative source-drift/geometry contracts."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_stack as stack
import building_furnishings as furniture
import foyer_monitor_wall as model
import microscope_model as bounds
import relative_floorplan as floor


class MonitorWallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = stack.load()
        cls.p = stack.parameters(cls.spec)
        cls.plans = {'EG':stack.level_plan(cls.spec, 'EG')}
        cls.levels = [{'id':'EG', 'z_mm':0, 'clear_top_mm':cls.p['clear_height_mm']}]
        cls.ref = cls.spec['sources']['monitor_wall']
        cls.source = furniture.read(cls.ref)
        cls.result = model.compile(cls.ref, cls.plans, cls.p, cls.levels)

    def compile_changed(self, changes):
        original = furniture.read
        source = copy.deepcopy(self.source)
        for key, values in changes.items():
            if isinstance(values, dict):source[key].update(values)
            else:source[key] = values
        with patch.object(furniture, 'read', side_effect=lambda ref:source if ref==self.ref else original(ref)):
            return model.compile(self.ref, self.plans, self.p, self.levels)

    def test_twenty_complete_native_instances_with_front_frames_and_level(self):
        result = self.result
        v = result['interface']
        self.assertEqual((v['level_id'], v['area'], v['wall'], v['scale']), ('EG','R0_019','W052',1))
        self.assertEqual((v['grid_rows'],v['grid_columns']),(4,5))
        self.assertEqual([m['id'] for m in v['monitors']], [f'FoyerMonitorWall.M{i:02}' for i in range(1,21)])
        self.assertEqual(len(set(v['body_ids'])),60)
        self.assertTrue(all(body['level_id']=='EG' and body['room_id']=='R0_019' for body in result['bodies']))
        self.assertTrue(all(group['grounded'] for group in result['components']))
        self.assertEqual(result['joints'], [])
        for monitor in v['monitors']:
            self.assertEqual(len(monitor['body_ids']),3)
            frame=monitor['screen_frame']
            self.assertEqual(frame['normal'],[0.,-1.,0])
            self.assertEqual((frame['width_mm'],frame['height_mm']),(508,298))
            cross=[frame['x_axis'][1]*frame['y_axis'][2]-frame['x_axis'][2]*frame['y_axis'][1],
                   frame['x_axis'][2]*frame['y_axis'][0]-frame['x_axis'][0]*frame['y_axis'][2],
                   frame['x_axis'][0]*frame['y_axis'][1]-frame['x_axis'][1]*frame['y_axis'][0]]
            self.assertEqual(cross,frame['normal'])

    def test_grid_and_inherited_origin_are_derived_without_room_scaling(self):
        v=self.result['interface']
        self.assertEqual((v['grid_width_mm'],v['grid_height_mm']),(2860,1440))
        self.assertAlmostEqual(v['wall_end_margin_mm'],(v['wall_length_mm']-v['grid_width_mm'])/2)
        self.assertGreaterEqual(v['wall_end_margin_mm'],100)
        boxes=[bounds.shape_bounds(op['shape']) for op in self.result['operations'] if op['body'].endswith('_MonitorCase')]
        self.assertEqual(min(box['min'][2] for box in boxes),1100)
        self.assertEqual(max(box['max'][2] for box in boxes),2540)
        for box in boxes:
            self.assertEqual([round(box['max'][i]-box['min'][i],6) for i in range(3)],[540,22,330])
        origins=[monitor['screen_frame']['origin_mm'] for monitor in v['monitors']]
        left, plane, top=origins[0]
        for index, origin in enumerate(origins):
            row, column=divmod(index,5)
            self.assertEqual(origin,[left+580*column,plane,top-370*row])

    def test_viewpoint_is_in_the_foyer_and_targets_a_reachable_screen(self):
        v = self.result['interface']
        eye, target = (v['viewpoint'][key] for key in ('eye_mm', 'target_mm'))
        self.assertEqual(target,v['monitors'][7]['screen_frame']['origin_mm'])
        plan = self.plans['EG']
        area = next(a for a in plan['areas'] if a['id'] == v['area'])
        polygon = [[n*self.p['display_scale'] for n in xy] for xy in floor.outline(plan,area)]
        self.assertEqual(floor.point_membership(eye[:2],polygon),1)
        spec = json.loads((ROOT/'model/building-walkthrough.shared.json').read_bytes())
        reach = spec['interaction']['reach']['value']
        for monitor in v['monitors']:
            frame = monitor['screen_frame']
            x,y,z = frame['origin_mm']
            for dx in (-frame['width_mm']/2,frame['width_mm']/2):
                for dz in (-frame['height_mm']/2,frame['height_mm']/2):
                    self.assertLess(math.dist(eye,[x+dx,y,z+dz]),reach)

    def test_original_three_by_three_grid_compiles(self):
        wall = self.compile_changed({'grid':{'rows':3,'columns':3}})['interface']
        self.assertEqual((wall['grid_rows'],wall['grid_columns']),(3,3))
        self.assertEqual((len(wall['monitors']),len(wall['body_ids'])),(9,27))

    def test_native_bounds_cover_every_instance_and_detect_foreign_collision(self):
        geometry=[{'body':op['body'],'bbox':bounds.shape_bounds(op['shape'])} for op in self.result['operations']]
        v=self.result['interface']
        self.assertTrue(all(check['passed'] for check in model.native_bounds_checks(v,geometry)))
        bad=copy.deepcopy(geometry)
        bad.append({'body':'ForeignDoor','bbox':copy.deepcopy(geometry[0]['bbox'])})
        self.assertFalse(model.native_bounds_checks(v,bad)[-1]['passed'])
        with self.assertRaisesRegex(ValueError,'complete'):
            model.native_bounds_checks(v,geometry[:-1])

    def test_invalid_grid_anchor_or_mounting_height_fails_closed(self):
        for changes in ({'anchor':{'wall':'W062'}},{'anchor':{'fraction':0}},
                        {'grid':{'rows':0}},{'grid':{'columns':True}},{'grid':{'columns':4.5}},
                        {'grid':{'horizontal_gap_mm':float('nan')}},
                        {'grid':{'vertical_gap_mm':-1}},{'grid':{'case_bottom_mm':2001}}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.compile_changed(changes)

    def test_grid_must_leave_wall_end_margin_and_fit_below_ceiling(self):
        for changes in ({'anchor':{'fraction':.49}},{'grid':{'columns':6}}):
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'wall-end margin'):
                self.compile_changed(changes)
        with self.assertRaisesRegex(ValueError,'storey height'):
            self.compile_changed({'grid':{'rows':9}})

    def test_wall_mount_must_reach_source_wall_without_entering_it(self):
        altered=copy.deepcopy(self.source)
        altered['monitor_type']['parts'][0]['shape']['origin'][1]=-31
        with self.assertRaisesRegex(ValueError,'span exactly'):
            model.validate(altered)

    def test_changed_source_pin_prevents_geometry(self):
        altered={**self.ref,'source_sha256':'0'*64}
        with self.assertRaises(ValueError):model.compile(altered,self.plans,self.p,self.levels)

    def test_existing_catalog_is_unchanged_and_dependency_chain_is_complete(self):
        path=ROOT/self.source['catalog']['source']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),self.source['catalog']['source_sha256'])
        catalog=json.loads(path.read_text())
        self.assertNotIn('wall_monitor',catalog['types'])
        self.assertIn(ROOT/'scripts/foyer_monitor_wall.py',stack.source_dependencies(self.spec))
        self.assertIn(model.SCHEMA,model.dependencies(self.ref))


if __name__=='__main__':unittest.main()
