"""Source-owned seminar furniture, placement evidence and film contracts."""
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
import building_walkthrough as walkthrough
import building_furnishings as furniture
import building_seminar as seminar
import building_exterior as exterior
import microscope_model as primitive_bounds
import relative_floorplan as floor
import wall_worktops
import tube_carrier_model as portable


def dot(first, second):
    return sum(a*b for a,b in zip(first,second))


class SeminarGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Loading the whole stack also expands every other room. This suite
        # exercises the independent compiler against the real registered EG.
        cls.stack = json.loads(stack.SOURCE.read_text())
        cls.p = stack.parameters(cls.stack)
        cls.plan = stack.level_plan(cls.stack,'EG')
        cls.levels = [{'id':'EG','z_mm':0,'clear_top_mm':cls.p['clear_height_mm']}]
        cls.ref = cls.stack['sources']['seminar_room']
        cls.source = furniture.read(cls.ref)
        cls.catalog = furniture.read(cls.source['catalog'])
        ground = next(i for i, level in enumerate(cls.stack['levels']) if level['id']=='EG')
        all_levels = [{'id':level['id'],'z_mm':(i-ground)*cls.p['floor_pitch_mm'],
                       'clear_top_mm':(i-ground)*cls.p['floor_pitch_mm']+cls.p['clear_height_mm']}
                      for i,level in enumerate(cls.stack['levels'])]
        plans = {level['id']:stack.level_plan(cls.stack,level['id']) for level in all_levels}
        cls.doors = exterior.compile(cls.stack['exterior'],plans,cls.p,all_levels)
        cls.result = seminar.compile(cls.ref,cls.plan,cls.p,cls.levels,door_geometry=cls.doors)
        cls.interface = cls.result['interface']
        cls.shapes = {op['body']:op['shape'] for op in cls.result['operations'] if op['action']=='create'}
        cls.content_ids = {cls.interface['screen_body_id'],cls.interface['screen_frame_body_id'],
                           *cls.interface['screen_mount_body_ids'],*cls.interface['projector_body_ids']}
        for row in cls.interface['rows']:
            cls.content_ids.update(row['table_body_ids'])
            for chair in row['chairs']:cls.content_ids.update(chair['body_ids'])
        cls.content_shapes = {name:shape for name,shape in cls.shapes.items() if name in cls.content_ids}

    def changed(self, source):
        original = furniture.read
        with patch.object(furniture,'read',side_effect=lambda ref:source if ref==self.ref else original(ref)):
            return seminar.compile(self.ref,self.plan,self.p,self.levels,door_geometry=self.doors)

    def test_three_filled_rows_use_complete_two_seat_catalogue_desks(self):
        view = self.interface
        self.assertEqual((view['id'],view['area_id'],view['level_id'],view['scale']),
                         ('SeminarEG10','R0_010','EG',1))
        self.assertEqual(len(view['rows']),3)
        self.assertEqual([row['index'] for row in view['rows']],[1,2,3])
        chair_parts = furniture.parts_for(self.catalog,'dining_chair')
        covered = []
        for row in view['rows']:
            self.assertEqual(row['catalog_type'],'desk')
            self.assertEqual(row['desk_count'],4)
            self.assertEqual(len(row['tables']),row['desk_count'])
            self.assertEqual(len(row['chairs']),2*row['desk_count'])
            self.assertEqual(row['tabletop_body_ids'],[table['tabletop_body_id'] for table in row['tables']])
            for table in row['tables']:
                desk_parts = furniture.parts_for(self.catalog,'desk',table['parameter_overrides_mm'])
                self.assertEqual(table['body_ids'],[table['id']+'_'+part['body'] for part in desk_parts])
                self.assertIn(table['tabletop_body_id'],table['body_ids'])
                self.assertEqual(len(table['chairs']),2)
            covered += row['table_body_ids']
            for chair in row['chairs']:
                self.assertEqual(chair['catalog_type'],'dining_chair')
                self.assertEqual(chair['body_ids'],[chair['id']+'_'+part['body'] for part in chair_parts])
                covered += chair['body_ids']
        covered += [view['screen_body_id'],view['screen_frame_body_id'],*view['screen_mount_body_ids'],
                    *view['projector_body_ids']]
        self.assertEqual(len(covered),len(set(covered)))
        self.assertEqual(set(covered),self.content_ids)
        window_ids = set(view.get('window_front',{}).get('body_ids',[]))
        self.assertEqual(set(covered)|window_ids,set(view['body_ids']))
        self.assertEqual(set(view['body_ids']),{body['id'] for body in self.result['bodies']})
        self.assertTrue(all(body['level_id']=='EG' and body['room_id']=='R0_010' for body in self.result['bodies']))
        self.assertTrue(all(group['grounded'] for group in self.result['components'] if not group['id'].startswith('SeminarEG10_Window')))
        for key in ('dimensions_measured','mounting_qualified','optical_qualified','hardware_qualified'):
            self.assertIs(view[key],False)

    def test_tables_and_seats_keep_catalog_dimensions_and_face_the_screen(self):
        view = self.interface; normal = view['screen_frame']['normal']
        seating = self.source['seating']; dimensions = seating['desk_overrides_mm']
        depths = []
        for row in view['rows']:
            for table in row['tables']:
                resolved = table['dimensions_mm']['length']
                self.assertGreaterEqual(resolved,seating['desk_length_min_mm'])
                self.assertLessEqual(resolved,seating['desk_length_max_mm'])
                self.assertEqual(table['dimensions_mm']['depth'],dimensions['depth'])
                self.assertEqual(table['dimensions_mm']['height'],dimensions['height'])
                top = self.shapes[table['tabletop_body_id']]
                lengths = sorted(math.dist(a,b) for a,b in zip(top['points'],top['points'][1:]+top['points'][:1]))
                for actual,expected in zip(lengths,sorted([resolved,dimensions['depth']]*2)):
                    self.assertAlmostEqual(actual,expected,places=7)
                self.assertAlmostEqual(top['offset']+top['depth']-view['floor_z_mm'],dimensions['height'])
                seats = table['chairs']
                self.assertAlmostEqual(math.dist(seats[0]['centre_mm'],seats[1]['centre_mm']),seating['chair_spacing_mm'])
                for chair in seats:
                    self.assertEqual(chair['facing'],row['table_facing'])
                    offset = [chair['centre_mm'][i]-table['centre_mm'][i] for i in (0,1)]
                    self.assertAlmostEqual(dot(offset,normal[:2]),seating['chair_setback_mm'])
                    seat = self.shapes[chair['id']+'_Seat']
                    self.assertTrue(all(abs(math.dist(a,b)-440)<1e-7 for a,b in
                                        zip(seat['points'],seat['points'][1:]+seat['points'][:1])))
                    self.assertAlmostEqual(seat['offset']-view['floor_z_mm'],440)
            depths.append(dot(row['table_centre_mm'][:2],normal[:2]))
            self.assertEqual(row['table_facing'],[-value for value in normal])
        self.assertTrue(all(b>a for a,b in zip(depths,depths[1:])))
        self.assertTrue(all(abs(b-a-seating['row_pitch_mm'])<1e-7 for a,b in zip(depths,depths[1:])))
        self.assertAlmostEqual(view['row_pitch_clearance_mm'],180)

    def test_screen_frame_and_projector_evidence_reference_actual_native_parts(self):
        view = self.interface; screen = view['screen_frame']; shape = self.shapes[view['screen_body_id']]
        self.assertEqual(screen['y_axis'],[0,0,1])
        for axis in ('x_axis','y_axis','normal'):self.assertAlmostEqual(math.hypot(*screen[axis]),1)
        cross = [screen['x_axis'][1],-screen['x_axis'][0],0]
        self.assertTrue(all(abs(a-b)<1e-9 for a,b in zip(cross,screen['normal'])))
        self.assertEqual((screen['width_mm'],screen['height_mm']),
                         (self.source['screen']['width_mm'],self.source['screen']['height_mm']))
        centre = [sum(point[i] for point in shape['points'])/4 for i in (0,1)]
        expected = [centre[i]+screen['normal'][i]*self.source['screen']['surface_depth_mm']/2 for i in (0,1)]
        expected += [shape['offset']+shape['depth']/2]
        self.assertLess(math.dist(screen['origin_mm'],expected),1e-7)
        projector = view['projector']; lens = self.shapes[projector['lens_body_id']]
        self.assertEqual(lens['origin'],projector['lens_origin_mm'])
        self.assertEqual(lens['axis'],projector['lens_axis'])
        aim = [a-b for a,b in zip(screen['origin_mm'],lens['origin'])]
        direction = [value/math.hypot(*aim) for value in aim]
        self.assertTrue(all(abs(a-b)<1e-9 for a,b in zip(direction,lens['axis'])))
        self.assertLess(lens['axis'][2],0)
        stem = self.shapes[projector['mount_body_ids'][0]]
        plate = self.shapes[projector['ceiling_plate_body_id']]
        self.assertAlmostEqual(stem['origin'][2],projector['stem_bottom_z_mm'])
        self.assertAlmostEqual(stem['origin'][2]+stem['height'],plate['offset'])
        self.assertAlmostEqual(plate['offset']+plate['depth'],view['ceiling_z_mm'])
        self.assertEqual(projector['ceiling_contact_z_mm'],view['ceiling_z_mm'])

    def test_source_placement_stays_inside_room_and_floor_ceiling_interval(self):
        view = self.interface; polygon = view['room_interior_polygon_mm']
        self.assertGreaterEqual(len(polygon),3)
        for identity,shape in self.content_shapes.items():
            box = primitive_bounds.shape_bounds(shape)
            self.assertGreaterEqual(box['min'][2],view['floor_z_mm']-1e-7,identity)
            self.assertLessEqual(box['max'][2],view['ceiling_z_mm']+1e-7,identity)
            for x in (box['min'][0],box['max'][0]):
                for y in (box['min'][1],box['max'][1]):
                    self.assertGreaterEqual(floor.point_membership([x,y],polygon),0,identity)
        self.assertEqual(floor.point_membership(view['viewpoint']['eye_mm'][:2],polygon),1)
        self.assertGreaterEqual(view['viewpoint_clearance_mm'],self.source['viewpoint']['clearance_mm'])
        self.assertGreaterEqual(view['screen_wall_end_margin_mm'],100)

    def test_rows_fill_the_available_span_and_preserve_the_real_door(self):
        seating = self.source['seating']
        for row in self.interface['rows']:
            length = sum(table['dimensions_mm']['length'] for table in row['tables'])
            self.assertAlmostEqual(length+(row['desk_count']-1)*seating['table_gap_mm'],row['fitted_span_mm'])
            self.assertGreater(row['fitted_span_mm'],5500)
            self.assertEqual(row['door_side_clearance_mm'],1500)
            self.assertEqual(row['window_margin_mm'],100)
            # The native desktop endpoints cover the fitted world interval;
            # catalogue height/depth stay unchanged while length is resolved.
            points=[point for identity in row['tabletop_body_ids'] for point in self.shapes[identity]['points']]
            right=[-v for v in self.interface['screen_frame']['x_axis'][:2]]
            actual=max(dot(point,right) for point in points)-min(dot(point,right) for point in points)
            self.assertAlmostEqual(actual,row['fitted_span_mm'])
        door=self.interface['door_checks']
        self.assertEqual(door['opening_id'],'D0_010')
        self.assertTrue(door['current_open_pose_checked'])
        self.assertGreater(door['minimum_sweep_clearance_mm'],seating['door_sweep_margin_mm'])
        self.assertGreater(door['minimum_current_pose_gap_mm'],0)
        self.assertFalse(door['egress_qualified'])
        self.assertEqual(door['current_leaf_body_id'],self.doors['interface']['door_bindings']['EG__D0_010']['leaf_body_id'])
        area=next(a for a in self.plan['areas'] if a['id']=='R0_010')
        corridor_edges=[]
        for name in ('EW090','EW098'):
            a,tangent,inward,length=wall_worktops.wall_frame(self.plan,area,name,self.p)
            start=[a[i]+inward[i]*self.p['display_thickness']/2 for i in (0,1)]
            end=[start[i]+tangent[i]*length for i in (0,1)];corridor_edges.append((start,end))
        floor_furniture=[shape for name,shape in self.content_shapes.items() if '_Row' in name]
        actual_gap=min(seminar.point_segment_distance(point,a,b) for shape in floor_furniture
                       for point in shape['points'] for a,b in corridor_edges)
        self.assertGreaterEqual(actual_gap,1500-1e-6,'Native furniture preserves the real normal-distance strip')
        self.assertLess(actual_gap,1800,'The fitted rows reach approximately the requested strip')

    def test_unsupported_fit_and_actual_door_obstructions_fail_closed(self):
        changed=copy.deepcopy(self.source)
        changed['seating'].update(desk_length_min_mm=1400,desk_length_max_mm=1400)
        with self.assertRaisesRegex(ValueError,'tiling'):self.changed(changed)
        changed=copy.deepcopy(self.source);changed['seating']['door_side_clearance_mm']=1800
        fitted=self.changed(changed)['interface']
        self.assertTrue(all(row['door_side_clearance_mm']==1800 for row in fitted['rows']))
        self.assertTrue(all(new['fitted_span_mm']<old['fitted_span_mm'] for new,old in zip(fitted['rows'],self.interface['rows'])))
        bad=copy.deepcopy(self.doors)
        binding=bad['interface']['door_bindings']['EG__D0_010'];shape=next(op['shape'] for op in bad['operations'] if op['body']==binding['leaf_body_id'] and op['action']=='create')
        shape['points']=[p[:] for p in self.shapes[self.interface['rows'][2]['tabletop_body_id']]['points']]
        with self.assertRaisesRegex(ValueError,'door swing|open room door'):
            seminar.compile(self.ref,self.plan,self.p,self.levels,door_geometry=bad)

    def test_ceiling_height_moves_the_projector_without_rescaling_the_seats(self):
        levels = copy.deepcopy(self.levels); levels[0]['clear_top_mm'] += 250
        result = seminar.compile(self.ref,self.plan,self.p,levels)['interface']
        self.assertAlmostEqual(result['projector']['ceiling_contact_z_mm']-self.interface['ceiling_z_mm'],250)
        self.assertAlmostEqual(result['projector']['stem_bottom_z_mm']-self.interface['projector']['stem_bottom_z_mm'],250)
        self.assertEqual([row['table_centre_mm'] for row in result['rows']],
                         [row['table_centre_mm'] for row in self.interface['rows']])

    def test_declared_scalar_ranges_do_not_admit_overlapping_rows(self):
        changed = copy.deepcopy(self.source)
        changed['seating'].update(row_pitch_mm=1200,chair_setback_mm=800)
        # These individually legal dimensions put a 45-mm chair back through
        # the following desktop over its full 35-mm top thickness.
        seminar.validate(changed)
        with self.assertRaisesRegex(ValueError,'overlap'):self.changed(changed)

    def test_invalid_source_opening_or_stale_catalog_pin_fails_closed(self):
        for section,name,value in (('seating','rows',2),('screen','width_mm',float('nan')),
                                   ('anchor','fraction',False),('viewpoint','clearance_mm',0)):
            changed = copy.deepcopy(self.source);changed[section][name] = value
            with self.subTest(section=section,name=name),self.assertRaises(ValueError):self.changed(changed)
        changed = copy.deepcopy(self.source);changed['catalog']['source_sha256'] = '0'*64
        with self.assertRaises(ValueError):self.changed(changed)
        plan = copy.deepcopy(self.plan)
        plan['openings'].append({'id':'ScreenWindow','wall':self.source['anchor']['wall'],'kind':'window'})
        with self.assertRaisesRegex(ValueError,'opening'):seminar.compile(self.ref,plan,self.p,self.levels)

    def test_portable_commands_cover_every_semantic_body_and_keep_source_pins(self):
        class Provider:
            SOURCE = ROOT/'model/furnishings/seminar-eg10.json'
            expanded = staticmethod(lambda *_:{**self.result,
                'bodies':[body for body in self.result['bodies'] if body['id'] in self.content_ids],
                'operations':[op for op in self.result['operations'] if op['body'] in self.content_ids], 'joints':[]})
            pose = staticmethod(lambda *_:{})
            samples = staticmethod(lambda *_:[])
        commands = portable.solidcraft_commands(stack.native_spec(self.stack,self.p),self.p,Provider)
        created = [command['params']['body_name'] for command in commands if 'body_name' in command['params']]
        self.assertEqual(len(created),len(set(created)))
        self.assertEqual(set(created),self.content_ids)
        self.assertTrue(all(op['shape']['kind'] in {'polygon_prism','cylinder','sphere','cone','box'}
                            for op in self.result['operations']))
        dependencies = {path.resolve() for path in seminar.dependencies(self.ref)}
        self.assertTrue({(ROOT/name).resolve() for name in ('scripts/building_seminar.py',
            'model/furnishings/seminar-eg10.json','model/seminar-room.schema.json',
            'model/furniture/social.catalog.json')} <= dependencies)
        self.assertEqual(hashlib.sha256((ROOT/self.source['catalog']['source']).read_bytes()).hexdigest(),
                         self.source['catalog']['source_sha256'])
        from jsonschema import Draft202012Validator
        Draft202012Validator(json.loads(seminar.SCHEMA.read_text())).validate(self.source)


class SeminarFilmSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads((ROOT/'model/building-walkthrough.shared.json').read_text())

    def test_film_and_viewpoint_are_explicit_source_metadata(self):
        film = self.source['seminar_film']
        self.assertEqual(set(film),{'title','source_url','video_url'})
        self.assertTrue(film['title'].strip())
        stop = next(stop for stop in self.source['stops'] if stop['id'] == 'seminar')
        self.assertEqual((stop['scene'],stop['level_id']),('building','EG'))
        self.assertEqual(stop['anchor'],{'kind':'seminar','room':'SeminarEG10'})
        walkthrough.validate(self.source)

    def test_film_metadata_rejects_undeclared_fields_and_unbound_urls(self):
        for field,value in (('title',' '),('source_url','https://example.org/wiki/File:film.webm'),
                            ('video_url','http://upload.wikimedia.org/wikipedia/commons/film.webm'),
                            ('video_url','https://upload.wikimedia.org/wikipedia/commons/film.webm?tracking=1'),
                            ('video_url','https://user@upload.wikimedia.org/wikipedia/commons/film.webm'),
                            ('video_url','https://upload.wikimedia.org.evil.example/wikipedia/commons/film.webm')):
            changed = copy.deepcopy(self.source)
            changed['seminar_film'][field] = value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                walkthrough.validate(changed)
        changed = copy.deepcopy(self.source)
        changed['seminar_film']['autoplay'] = True
        with self.assertRaises(ValueError):walkthrough.validate(changed)


if __name__ == '__main__':unittest.main()
