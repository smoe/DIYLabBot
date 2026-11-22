"""Read-only camera derivation, optical bindings, and unavailable-source semantics."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import lab_layout_model as layout
import monitor_camera_registry as registry
import robot_cameras
import robot_spec as robot


class CameraRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.equipment = layout.load(validate_builds=False)
        parameters = layout.parameters(cls.equipment)
        # A nontrivial rigid world placement avoids accidentally using lab-local coordinates.
        world = [[0, -1, 0, 20000], [1, 0, 0, 30000], [0, 0, 1, 12750], [0, 0, 0, 1]]
        devices = [{'id': item['id'], 'asset': item['asset'],
                    'world_pose': robot.multiply(world, layout.matrix(item, parameters)),
                    'body_prefix': 'Lab3003_' + item['id'] + '_'}
                   for item in cls.equipment['instances']]
        cls.interface = {'laboratories': [
            {'id': 'Lab3003', 'room': '3.003', 'level_id': 'OG3',
             'layout_source': {'source': 'model/lab-layout-l01.shared.json',
                               'source_sha256': registry.digest(ROOT / 'model/lab-layout-l01.shared.json')},
             'device_instances': devices, 'instances': []},
            {'id': 'BasicLab1001', 'room': '1.001', 'level_id': 'OG1',
             'device_instances': [], 'instances': [
                 {'id': 'Hood', 'layout_kind': 'hood'},
                 {'id': 'Desk', 'layout_kind': 'side'}]}],
            'microscopy': {'id': 'Microscopy3007', 'level_id': 'OG3'},
            'monitor_wall': {'grid_rows': 4, 'grid_columns': 5,
                             'monitors': [{'id': f'FoyerMonitorWall.M{i:02d}'} for i in range(1, 21)]}}
        cls.objects = [
            {'id': 'Lab3003.NanoDrop01.Lid', 'viewpoint': {'eye_mm': [21000, 31000, 14000], 'target_mm': [21000, 32000, 13900]}},
            {'id': 'Lab3003.Qubit01.Lid', 'viewpoint': {'eye_mm': [22000, 31000, 14000], 'target_mm': [22000, 32000, 13900]}},
            {'id': 'Lab3003.Freezer01.Drawer', 'viewpoint': {'eye_mm': [23000, 31000, 14000], 'target_mm': [23000, 32000, 13900]}},
            {'id': 'BasicLab1001.Hood.Sash', 'viewpoint': {'eye_mm': [3000, 4000, 5000], 'target_mm': [3000, 5000, 4900]}}]
        cls.stops = [{'id': 'microscopy', 'anchor': {'kind': 'microscopy', 'station': 'Microscopy3007'},
                      'eye_mm': [24000, 31000, 14000], 'target_mm': [24000, 32000, 13900]}]

    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / 'exports', prefix='camera-registry-test-')
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'source.json'
        self.spec = json.loads(registry.SOURCE.read_text())
        for ref in self.spec['sources'].values():
            ref['source_sha256'] = registry.digest(ROOT / ref['source'])
        self.write_source()
        self.program = {'objects': copy.deepcopy(self.objects), 'stops': copy.deepcopy(self.stops),
                        'levels': [{'id': 'OG3', 'z_mm': 12750}, {'id': 'EG', 'z_mm': 0},
                                   {'id': 'OG1', 'z_mm': 4250}],
                        'source_files_sha256': {self.spec['sources']['walkthrough']['source']:
                                               self.spec['sources']['walkthrough']['source_sha256']}}

    def write_source(self):
        self.source.write_text(json.dumps(self.spec) + '\n')

    def compiled(self, interface=None):
        return registry.compile(self.program, interface or self.interface, self.source)

    def available_startup_ids(self, result):
        return sorted(c['id'] for c in result['cameras'] if c['availability'] == 'available'
                      and c['category'] == 'robot') + sorted(
                          c['id'] for c in result['cameras'] if c['availability'] == 'available'
                          and c['category'] == 'device')

    def test_six_arm_cameras_bind_the_correct_native_camera_body(self):
        result = self.compiled()
        arms = [c for c in result['cameras'] if c['category'] == 'robot']
        self.assertEqual(len(arms), 6)
        for arm in ('ArmA', 'ArmB', 'ArmC'):
            cameras = [c for c in arms if c['device_id'] == 'Lab3003.' + arm]
            self.assertEqual({c['mounted_link'] for c in cameras}, {'L1_Turret', 'L6_BareFlange'})
            item = next(i for i in self.equipment['instances'] if i['id'] == arm)
            spec = robot.expanded(layout.instance_source(self.equipment, item))
            for camera in cameras:
                bodies = {op['body'] for link in spec['links'] if link['id'] == camera['mounted_link']
                          for op in link['recipe'] if op['action'] == 'create'}
                self.assertIn(camera['mount_body_id'].removeprefix('Lab3003_' + arm + '_'), bodies)
                self.assertEqual(camera['reference_joints_deg'], item['joints_deg'])
                self.assertEqual(camera['availability'], 'available')

    def test_optical_eye_matches_source_lens_front_after_instance_fk(self):
        laboratory = self.interface['laboratories'][0]
        for device in laboratory['device_instances']:
            if device['asset'] != 'arm':
                continue
            item = next(i for i in self.equipment['instances'] if i['id'] == device['id'])
            spec = layout.instance_source(self.equipment, item)
            expanded = robot.expanded(spec)
            fk = robot.forward(spec, item['joints_deg'])
            derived = registry.arm_cameras(laboratory, device, item, self.equipment, self.spec['settings'])
            for camera in derived:
                camera_id = camera['id'].split('.')[-1]
                operations = next(link['recipe'] for link in expanded['links'] if link['id'] == camera['mounted_link'])
                lens = next(op['primitive'] for op in operations if op.get('body') == camera_id + '_lens_ENVELOPE')
                p = robot.parameters(spec)
                point = [robot.evaluate(value, p) + axis * robot.evaluate(lens['length'], p)
                         for value, axis in zip(lens['origin'], lens['axis'])]
                expected = robot.transform(robot.multiply(device['world_pose'], fk[camera['mounted_link']]), point)
                for a, b in zip(expected, camera['eye_mm']):
                    self.assertAlmostEqual(a, b, places=8)

    def test_projection_inscribes_the_source_cone_and_keeps_explicit_mm_planes(self):
        for camera in [c for c in self.compiled()['cameras'] if c['category'] == 'robot']:
            item = next(i for i in self.equipment['instances'] if i['id'] == camera['device_id'].split('.')[-1])
            spec = layout.instance_source(self.equipment, item)
            optical = next(c for c in robot_cameras.audit(spec)['cameras'] if c['id'] == camera['id'].split('.')[-1])
            tangent = math.tan(math.radians(camera['fov_y_deg']) / 2)
            corner_radius = optical['cone_range_mm'] * tangent * math.sqrt(1 + (16 / 9) ** 2)
            self.assertAlmostEqual(corner_radius, optical['cone_far_radius_mm'], places=7)
            self.assertEqual(camera['near_mm'], 0.5)
            self.assertEqual(camera['far_mm'], 5000)
            self.assertEqual(camera['clipping_basis'], 'presentation_assumption_not_optical_range')
            forward = [b-a for a, b in zip(camera['eye_mm'], camera['target_mm'])]
            self.assertAlmostEqual(sum(a*b for a, b in zip(forward, camera['up'])), 0, places=7)
            self.assertAlmostEqual(math.hypot(*camera['up']), 1, places=8)

    def test_virtual_overviews_use_separate_clipping_assumptions(self):
        overviews = [c for c in self.compiled()['cameras'] if c['kind'] == 'virtual_overview']
        self.assertTrue(overviews)
        for camera in overviews:
            self.assertEqual(camera['near_mm'], 25)
            self.assertEqual(camera['far_mm'], 180000)
            self.assertEqual(camera['clipping_basis'], 'presentation_assumption_not_optical_range')
        self.spec['settings']['modeled_far_mm'] = self.spec['settings']['near_mm']
        self.write_source()
        with self.assertRaises(ValueError):
            self.compiled()
        self.spec['settings']['modeled_far_mm'] = 5000
        self.spec['settings']['far_mm'] = self.spec['settings']['virtual_near_mm']
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'virtual-overview far clipping plane'):
            self.compiled()

    def test_mosaic_view_distance_is_required_bounded_and_exported_in_mm(self):
        key = 'mosaic_max_view_distance_mm'
        self.assertEqual(self.compiled()['settings'][key], self.spec['settings'][key])
        valid = self.spec['settings'].pop(key)
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'Missing camera-wall schema field'):
            self.compiled()
        for value in (999, 30001, str(valid), True):
            with self.subTest(value=value):
                self.spec['settings'][key] = value
                self.write_source()
                with self.assertRaisesRegex(ValueError, key):
                    self.compiled()
        self.spec['settings'][key] = 10000
        self.write_source()
        self.assertEqual(self.compiled()['settings'][key], 10000)

    def test_static_transporter_has_no_camera_and_disconnected_fleet_has_no_poses(self):
        result = self.compiled()
        tr = next(c for c in result['cameras'] if c['device_id'] == 'Lab3003.TR01')
        self.assertEqual(tr['category'], 'transporter')
        self.assertEqual(tr['availability'], 'no_camera')
        self.assertIsNone(tr['eye_mm'])
        fleet = [c for c in result['cameras'] if c['availability'] == 'not_connected']
        self.assertEqual(len(fleet), 20)
        self.assertEqual([c['device_id'] for c in fleet], ['BF01.BF' + str(n).zfill(2) for n in range(1, 21)])
        for camera in fleet:
            self.assertEqual(camera['category'], 'transporter')
            self.assertEqual(camera['kind'], 'modeled_camera')
            self.assertIsNone(camera['eye_mm'])
            self.assertIsNone(camera['target_mm'])
        self.assertFalse(result['fleet_connected'])
        self.assertFalse(result['message_source_connected'])

    def test_menu_categories_and_room_order_are_derived_deterministically(self):
        interface = copy.deepcopy(self.interface)
        for identity, room in [('GroundA', 'EG 15'), ('GroundB', 'EG 3')]:
            interface['laboratories'].append({'id': identity, 'room': room, 'level_id': 'EG',
                                              'instances': [{'id': 'Hood', 'layout_kind': 'hood'}]})
        cameras = self.compiled(interface)['cameras']
        interface['laboratories'].reverse()
        self.assertEqual(cameras, self.compiled(interface)['cameras'])
        self.assertEqual(list(dict.fromkeys(c['category'] for c in cameras)), ['transporter', 'robot', 'device'])
        self.assertEqual([c['device_id'] for c in cameras[:21]],
                         [f'BF01.BF{n:02d}' for n in range(1, 21)] + ['Lab3003.TR01'])
        devices = [c['location'] for c in cameras if c['category'] == 'device']
        self.assertEqual(devices, ['EG 3', 'EG 15', '1.001'] + ['3.003'] * devices.count('3.003') + ['3.007'])

    def test_bound_hood_and_microscope_are_included_but_racks_and_desks_are_not(self):
        result = self.compiled()
        ids = {c['device_id'] for c in result['cameras']}
        self.assertIn('BasicLab1001.Hood', ids)
        self.assertIn('Microscopy3007', ids)
        self.assertNotIn('BasicLab1001.Desk', ids)
        self.assertFalse(any('Rack' in identity for identity in ids))
        microscopy = next(c for c in result['cameras'] if c['device_id'] == 'Microscopy3007')
        self.assertEqual(microscopy['label'], 'Mikroskop · 3.007')
        self.assertNotIn('Apotome', json.dumps(result, ensure_ascii=False))
        self.assertNotIn('ZEISS', json.dumps(result, ensure_ascii=False))
        self.assertFalse(microscopy['physical_camera'])

    def test_overviews_use_source_viewpoints_and_missing_anchors_are_explicit_gaps(self):
        result = self.compiled()
        nano = next(c for c in result['cameras'] if c['device_id'] == 'Lab3003.NanoDrop01')
        self.assertEqual(nano['eye_mm'], self.objects[0]['viewpoint']['eye_mm'])
        self.assertEqual(nano['target_mm'], self.objects[0]['viewpoint']['target_mm'])
        balance = next(c for c in result['cameras'] if c['device_id'] == 'Lab3003.Balance01')
        self.assertEqual(balance['availability'], 'missing_viewpoint')
        self.assertIsNone(balance['eye_mm'])
        self.assertIn({'device_id': 'Lab3003.Balance01', 'reason': 'missing_viewpoint'}, result['gaps'])

    def test_default_slots_only_use_available_views_and_derivation_is_deterministic(self):
        interface = copy.deepcopy(self.interface)
        for index in range(12):
            identity = f'BasicLabExtra{index:02d}'
            interface['laboratories'].append({'id': identity, 'level_id': 'OG1',
                                              'instances': [{'id': 'Hood', 'layout_kind': 'hood'}]})
            self.program['objects'].append({'id': identity + '.Hood.Sash', 'viewpoint': self.objects[-1]['viewpoint']})
        first, second = self.compiled(interface), self.compiled(interface)
        self.assertEqual(first, second)
        available = self.available_startup_ids(first)
        self.assertGreater(len(available), 20)
        self.assertEqual(first['default_assignments'], available[:20])
        self.assertEqual(len(set(first['default_assignments'])), 20)
        self.assertFalse(first['settings']['history_enabled'])

    def test_default_assignments_follow_wall_size_and_leave_missing_views_unassigned(self):
        result = self.compiled()
        available = self.available_startup_ids(result)
        self.assertLess(len(available), 20)
        self.assertEqual(result['default_assignments'], available + [None] * (20 - len(available)))

        interface = copy.deepcopy(self.interface)
        wall = interface['monitor_wall']
        wall.update(grid_rows=2, grid_columns=2, monitors=wall['monitors'][:4])
        self.assertEqual(self.compiled(interface)['default_assignments'], available[:4])

    def test_changed_pin_and_wrong_program_revision_fail_before_registry_creation(self):
        self.spec['sources']['fleet']['source_sha256'] = '0' * 64
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'overlay fleet pin failed'):
            self.compiled()
        self.spec['sources']['fleet']['source_sha256'] = registry.digest(ROOT / self.spec['sources']['fleet']['source'])
        self.write_source()
        self.program['source_files_sha256'][self.spec['sources']['walkthrough']['source']] = '1' * 64
        with self.assertRaisesRegex(ValueError, 'different source revisions'):
            self.compiled()

    def test_unknown_asset_and_duplicate_instance_are_not_silently_accepted(self):
        interface = copy.deepcopy(self.interface)
        interface['laboratories'][0]['device_instances'].append({'id': 'NewDevice', 'asset': 'new_device'})
        self.assertIn({'device_id': 'Lab3003.NewDevice', 'reason': 'unclassified_asset', 'asset': 'new_device'}, self.compiled(interface)['gaps'])
        interface = copy.deepcopy(self.interface)
        interface['laboratories'][0]['device_instances'].append(copy.deepcopy(interface['laboratories'][0]['device_instances'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate derived camera'):
            self.compiled(interface)

    def test_unsupported_history_and_invalid_source_fields_fail_closed(self):
        self.spec['settings']['history_enabled'] = True
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'history'):
            self.compiled()
        self.spec['settings']['history_enabled'] = False
        self.spec['extra_inventory'] = []
        self.write_source()
        with self.assertRaisesRegex(ValueError, 'Unexpected camera-wall field'):
            self.compiled()

    def test_declared_schema_constraints_are_executed_not_just_snapshotted(self):
        schema = json.loads(registry.SCHEMA.read_text())
        schema['properties']['settings']['properties']['near_mm']['minimum'] = 2
        schema_path = Path(self.directory.name) / 'changed-schema.json'
        schema_path.write_text(json.dumps(schema))
        with patch.object(registry, 'SCHEMA', schema_path):
            with self.assertRaisesRegex(ValueError, 'outside schema bounds.*near_mm'):
                self.compiled()
        schema['unsupported_validation_keyword'] = True
        schema_path.write_text(json.dumps(schema))
        with patch.object(registry, 'SCHEMA', schema_path):
            with self.assertRaisesRegex(ValueError, 'Unsupported camera-wall schema keyword'):
                self.compiled()


if __name__ == '__main__':
    unittest.main()
