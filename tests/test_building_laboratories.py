import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_laboratories as laboratories
import building_stack as stack
import lab_room_model as room
import robot_spec as robot


class BuildingLaboratoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = stack.load()
        cls.p = stack.parameters(cls.spec)
        cls.interface = stack.interfaces(cls.spec, cls.p)
        cls.lab = cls.interface['laboratories'][0]
        cls.source = laboratories.read(cls.spec['sources']['laboratories'])
        cls.instance = cls.source['laboratories'][0]
        cls.plan = stack.level_plan(cls.spec, cls.instance['level'])

    def test_sources_contain_references_not_copied_dimensions(self):
        self.assertEqual(set(self.instance), {'id', 'room', 'level', 'area', 'entrance_wall',
                                             'room_source', 'layout_source', 'basis', 'bench_layout'})
        self.assertEqual(self.lab['area'], 'R3_003')
        self.assertEqual(self.lab['level_id'], 'OG3')
        self.assertFalse(self.lab['placement_qualified'])
        self.assertFalse(self.lab['metric_registration_qualified'])

    def test_cf01_bench_uses_the_video_arrangement_about_the_existing_anchor(self):
        import synthetic_workspace
        from export_building_walkthrough_freecad import equipment_link_placements, native_equipment_bindings

        setup = self.instance['bench_layout']
        source = synthetic_workspace.load(ROOT / setup['workspace']['source'])['devices']
        devices = {item['id']: item for item in self.lab['device_instances']}
        anchor = devices[setup['anchor']]
        source_anchor = source[setup['devices'][setup['anchor']]]
        anchor_inverse = robot.inverse(anchor['bound_pose'])
        expected_inverse = robot.inverse(source_anchor['matrix'])
        for name, original in setup['devices'].items():
            with self.subTest(device=name):
                relative = robot.multiply(anchor_inverse, devices[name]['bound_pose'])
                expected = robot.multiply(expected_inverse, source[original]['matrix'])
                self.assertLess(max(abs(a-b) for row, ref in zip(relative, expected)
                                    for a, b in zip(row, ref)), 1e-7)
        self.assertTrue(devices['ArmC']['direct_mount'])
        self.assertEqual(anchor['bound_pose'][2][3], devices['ArmC']['bound_pose'][2][3])
        self.assertEqual(devices['TR01']['bound_pose'], devices['TR01']['standalone_pose'])
        self.assertEqual(devices['ArmC']['park_joints_deg'], setup['park_joints_deg']['ArmC'])
        placements = equipment_link_placements(self.lab, devices['ArmC'])
        for actual, expected in zip(placements['Base_plate'], devices['ArmC']['transform']):
            for a, b in zip(actual, expected):
                self.assertAlmostEqual(a, b)
        self.assertNotEqual(placements['C_tip_lens_ENVELOPE'], placements['Base_plate'])
        supports = {device['supporting_device_id'] for _, device in native_equipment_bindings([self.lab])
                    if 'supporting_device_id' in device}
        self.assertEqual(supports, {'ArmA', 'ArmB'})

    def test_binding_follows_boundary_translation_and_wall_thickness(self):
        shifted = copy.deepcopy(self.plan)
        for point in shifted['vertices'].values():
            point[0] += .01
            point[1] -= .02
        before = laboratories.derive_binding(self.instance, self.plan, self.p, 123)
        after = laboratories.derive_binding(self.instance, shifted, self.p, 456)
        for key in before['bound_parameters_mm']:
            self.assertAlmostEqual(before['bound_parameters_mm'][key], after['bound_parameters_mm'][key])
        self.assertAlmostEqual(after['transform'][0][3]-before['transform'][0][3], .01*self.p['display_scale'])
        self.assertAlmostEqual(after['transform'][1][3]-before['transform'][1][3], -.02*self.p['display_scale'])
        self.assertEqual(after['transform'][2][3], 456)
        thicker = laboratories.derive_binding(self.instance, self.plan,
                                               {**self.p, 'display_thickness': self.p['display_thickness']+20}, 123)
        self.assertAlmostEqual(thicker['bound_parameters_mm']['room_width'], before['bound_parameters_mm']['room_width']-20)

    def test_bounds_and_existing_l01_checks_are_not_relaxed(self):
        model = room.load()
        params = room.parameters(model, self.lab['bound_parameters_mm'])
        expanded = room.expanded(model, params)
        expected = {body['id'] for body in expanded['bodies'] if body['role'] not in laboratories.SHELL_ROLES}
        self.assertEqual(set(self.lab['furniture_body_ids']), {'Lab3003_'+name for name in expected})
        self.assertIn('Lab3003_ConcreteSupport', self.lab['body_ids'])
        self.assertFalse(self.lab['concrete_support_in_f03'])
        self.assertTrue(self.lab['furniture_room_check']['passed'])
        self.assertLessEqual(self.lab['furniture_room_check']['maximum_boundary_deviation_mm'],
                             self.lab['furniture_room_check']['wall_face_tolerance_mm'])
        with self.assertRaisesRegex(ValueError, 'outside exploration range'):
            laboratories.compile_instance(self.instance, self.plan, {**self.p, 'display_scale': self.p['display_scale']/2}, 0)

    def test_default_stools_keep_their_original_numeric_positions(self):
        source = room.load(); params = room.parameters(source); expanded = room.expanded(source, params)
        frames = {frame['id']: frame for frame in expanded['frames']}
        for identity, expected_x, expected_y in [('Stool1', 1550, 6650), ('Stool2', 2300, 6650), ('Stool3', 5000, 6600)]:
            frame = frames['L01.'+identity+'.Seat']
            self.assertAlmostEqual(robot.evaluate(frame['origin'][0], params), expected_x, places=9)
            self.assertAlmostEqual(robot.evaluate(frame['origin'][1], params), expected_y, places=9)
        bound = room.parameters(source, self.lab['bound_parameters_mm'])
        bound_frames = {frame['id']: frame for frame in room.expanded(source, bound)['frames']}
        for identity in ('Stool1', 'Stool2', 'Stool3'):
            offsets=[]
            for selected, context in ((frames, params), (bound_frames, bound)):
                frame=selected['L01.'+identity+'.Seat'];x,y=[robot.evaluate(v,context)for v in frame['origin'][:2]]
                offsets.append(y-room.window_front(context,x))
            self.assertAlmostEqual(*offsets, places=9)

    def test_lost_device_room_and_host_are_rejected(self):
        original=laboratories.read(self.instance['layout_source'])
        changed=copy.deepcopy(original);changed['instances'][0]['host']='UnknownHost'
        with mock.patch.object(laboratories,'read',return_value=changed):
            with self.assertRaisesRegex(ValueError,'loses its declared host'):
                laboratories.compile_instance(self.instance,self.plan,self.p,self.lab['transform'][2][3])
        changed=copy.deepcopy(original);changed['instances'][0]['xyz'][0]=-1
        with mock.patch.object(laboratories,'read',return_value=changed):
            with self.assertRaisesRegex(ValueError,'leaves its destination room'):
                laboratories.compile_instance(self.instance,self.plan,self.p,self.lab['transform'][2][3])

    def test_every_device_has_one_rigid_binding_and_host(self):
        layout = laboratories.read(self.instance['layout_source'])
        devices = self.lab['device_instances']
        self.assertEqual({d['id'] for d in devices}, {d['id'] for d in layout['instances']})
        self.assertEqual(len(devices), len(layout['instances']))
        for device in devices:
            self.assertTrue(device['anchor_in_room'])
            self.assertTrue(device['host_anchor_checked'])
            self.assertFalse(device['geometry_extent_checked'])
            actual = robot.multiply(device['transform'], device['standalone_pose'])
            expected = robot.multiply(self.lab['transform'], device['bound_pose'])
            for row in range(4):
                for col in range(4): self.assertAlmostEqual(actual[row][col], expected[row][col])
            for col in range(3):
                self.assertAlmostEqual(sum(device['transform'][row][col]**2 for row in range(3)), 1)

    def test_joint_frames_and_world_places_refer_to_existing_bodies(self):
        self.assertTrue(self.lab['joints'])
        for frame in self.lab['frames']:
            self.assertEqual(frame['origin'],frame['origin_mm'])
            self.assertTrue(all(type(value) in (int,float)and math.isfinite(value)for value in frame['origin']))
            self.assertIn('source_origin',frame)
        for joint in self.lab['joints']:
            self.assertTrue(set(joint['moving_body_ids']) <= set(self.lab['body_ids']))
            self.assertTrue(all(math.isfinite(v) for v in joint['origin_mm']+joint['axis']))
        places = self.interface['places']
        self.assertTrue(any(p['id'].startswith('PhD3002.') and p['kind'] == 'work_surface' for p in places))
        self.assertTrue(any(p['id'].startswith('Lab3003.') and p['kind'] == 'work_surface' for p in places))
        racks = [p for p in places if p['kind'] == 'rack_slot']
        self.assertEqual(len(racks), 24*len([d for d in self.lab['device_instances'] if d['asset'] == 'tube_rack']))
        self.assertEqual(len({p['id'] for p in places}), len(places))

    def test_office_corridor_lab_connection_comes_from_real_openings(self):
        edges = [edge for edge in self.interface['topology'] if edge['level_id'] == self.lab['level_id']]
        starts = [e for e in edges if e['opening'] == 'D3_002N']
        ends = [e for e in edges if e['opening'] in ('D3_003A', 'D3_003B')]
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(ends), 2)
        self.assertIn('R3_002', starts[0]['areas'])
        for end in ends:
            self.assertIn('R3_003', end['areas'])
            self.assertTrue(set(starts[0]['areas']) & set(end['areas']))
            self.assertFalse(end['passability_qualified'])

    def test_rack_places_use_the_layout_cassette_frame_not_the_transport_deck(self):
        layout_source=laboratories.read(self.instance['layout_source'])
        context=laboratories.layout.parameters(layout_source,room_overrides=self.lab['bound_parameters_mm'])
        for device in layout_source['instances']:
            if device['asset']!='tube_rack':continue
            rack_source=laboratories.layout.instance_source(layout_source,device,context=context)
            module=laboratories.layout.provider('transporter')
            rack=module.expanded(rack_source,module.parameters(rack_source),laboratories.layout.instance_variant(rack_source,device))
            datum=laboratories.layout.cassette_datum(rack_source,device)
            native_local={o['body']:[v-datum[axis]for axis,v in enumerate(o['shape']['origin'])]
                          for o in rack['operations']if o['action']=='create'and o['body'].startswith('B2_Tube')}
            binding=next(d for d in self.lab['device_instances']if d['id']==device['id'])
            for place in self.lab['places']:
                if place.get('rack_instance')!=device['id']:continue
                actual=laboratories.transformed(robot.inverse(binding['world_pose']),place['origin_mm'])
                for value,expected in zip(actual,native_local[place['reference_body_id']]):
                    self.assertAlmostEqual(value,expected,places=7)
                self.assertLess(actual[2],datum[2])

    def test_rack_places_match_checked_native_layout_tube_bases(self):
        report_path=ROOT/'cad/lab-layout-l01/shared-build-report.json'
        if not report_path.exists():self.skipTest('Current checked native L01 report unavailable')
        report=json.loads(report_path.read_text())
        if report.get('source_sha256')!=self.instance['layout_source']['source_sha256']:
            self.skipTest('Current source-bound native L01 report not built yet')
        import export_building_walkthrough_freecad as native
        report=native.checked_report(report_path,'lab')
        geometry={body['body']:body for body in report['layout_validation']['scene_geometry']}
        devices={device['id']:device for device in self.lab['device_instances']}
        for place in self.lab['places']:
            if place['kind']!='rack_slot':continue
            identity=place['rack_instance']+'__'+place['reference_body_id'].removeprefix('B2_')
            self.assertIn(identity,geometry)
            bounds=geometry[identity]['bbox']
            point=[(bounds['min'][axis]+bounds['max'][axis])/2 for axis in (0,1)]+[bounds['min'][2]]
            actual=laboratories.transformed(devices[place['rack_instance']]['transform'],point)
            for value,expected in zip(actual,place['origin_mm']):self.assertAlmostEqual(value,expected,places=6)

    def test_countertop_ice_maker_is_native_only_in_laboratory_3016(self):
        placements = [(lab, item) for lab in self.interface['laboratories']
                      for item in lab.get('native_appliances', [])
                      if item['id'] == 'IceMakerIM01']
        self.assertEqual(len(placements), 1)
        lab, appliance = placements[0]
        self.assertEqual((lab['id'], lab['room'], lab['level_id'], lab['area']),
                         ('Lab3016', '3.016', 'OG3', 'R3_016'))
        self.assertEqual(appliance['variant'], 'countertop')
        self.assertEqual(appliance['support_body_id'], 'Lab3016_WetStation_DripTray')
        self.assertTrue(appliance['body_ids'])
        self.assertEqual(len(appliance['body_ids']), len(set(appliance['body_ids'])))
        self.assertTrue(set(appliance['body_ids']) <= set(lab['body_ids']))
        self.assertFalse(set(appliance['body_ids']) & set(lab['furniture_body_ids']))
        self.assertEqual(lab['device_instances'], [])
        expanded = stack.expanded(self.spec, self.p)
        native_bodies = {body['id'] for body in expanded['bodies']}
        native_creates = {operation['body'] for operation in expanded['operations']
                          if operation['action'] == 'create'}
        self.assertTrue(set(appliance['body_ids']) <= native_bodies & native_creates)

    def test_ice_maker_feet_rest_on_the_actual_drip_tray_inner_floor(self):
        import basic_laboratories
        lab = next(lab for lab in self.interface['laboratories'] if lab['id'] == 'Lab3016')
        appliance = next(item for item in lab.get('native_appliances', [])
                         if item['id'] == 'IceMakerIM01')
        expanded = stack.expanded(self.spec, self.p)
        hollows = [operation['shape'] for operation in expanded['operations']
                   if operation['body'] == appliance['support_body_id']
                   and operation['action'] == 'cut'
                   and operation['shape']['kind'] == 'polygon_prism']
        self.assertEqual(len(hollows), 1)
        hollow = hollows[0]
        polygon = hollow['points']
        self.assertEqual(hollow['plane'], 'XY')
        self.assertAlmostEqual(appliance['support_floor_z_mm'], hollow['offset'])
        self.assertAlmostEqual(appliance['origin_mm'][2], hollow['offset'])
        self.assertEqual(len(appliance['front']), 3)
        for actual, expected in zip(appliance['front'], (1, 0, 0)):
            self.assertAlmostEqual(actual, expected)
        for point in appliance['footprint_mm']:
            self.assertGreaterEqual(laboratories.floor.point_membership(point[:2], polygon), 0)
        pads = [operation['shape'] for operation in expanded['operations']
                if operation['body'] in appliance['body_ids']
                and operation['action'] == 'create' and 'FootPad_' in operation['body']]
        self.assertEqual(len(pads), 4)
        self.assertEqual(len(appliance['foot_centres_mm']), len(pads))
        for point in appliance['foot_centres_mm']:
            self.assertEqual(len(point), 3)
            self.assertTrue(all(math.isfinite(value) for value in point))
            self.assertAlmostEqual(point[2], hollow['offset'])
            pad = next((pad for pad in pads if math.dist(pad['origin'], point) < 1e-6), None)
            self.assertIsNotNone(pad, 'The reported contact must come from a real native foot pad')
            self.assertEqual(pad['kind'], 'cylinder')
            self.assertGreater(laboratories.floor.point_membership(point[:2], polygon), 0)
            clearance = min(basic_laboratories.point_segment(point[:2], a, b)
                            for a, b in zip(polygon, polygon[1:]+polygon[:1]))
            self.assertGreaterEqual(clearance+1e-6, pad['radius'])

    def test_dependency_pins(self):
        paths = stack.source_dependencies(self.spec)
        for path in (laboratories.SCHEMA, ROOT/'scripts/building_laboratories.py',
                     ROOT/self.instance['layout_source']['source']): self.assertIn(path, paths)
        for path in paths: self.assertTrue(path.is_file(), str(path))
        changed = copy.deepcopy(self.source)
        changed['laboratories'][0]['room_source']['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Pinned assembly source changed'):
            laboratories.validate(changed)

    def test_optional_json_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema unavailable')
        jsonschema.validate(self.source, json.loads(laboratories.SCHEMA.read_text()))


if __name__ == '__main__':
    unittest.main()
