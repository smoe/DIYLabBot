"""Cross-frame/native placement and source-driven lift regression checks."""
import base64
import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import export_building_walkthrough_freecad as mesh
import walkthrough_elevator as lift


class SourceLiftTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'FixtureLift', 'speed': {'value': 1000, 'unit': 'mm/s',
                        'range': [100, 3000], 'basis': 'presentation_assumption'}}
        self.plan = {'vertices': {'a': [0, 0], 'b': [0, 10], 'c': [10, 0], 'd': [10, 10]},
            'walls': [{'id': 'Outer', 'start': 'a', 'end': 'b'}, {'id': 'Inner', 'start': 'c', 'end': 'd'}],
            'openings': [{'id': 'Entry', 'wall': 'Outer', 'interval': [.25, .75]}]}
        self.interface = {'levels': [{'id': 'EG', 'z_mm': 0, 'label': 'Ground'},
                                     {'id': 'Upper', 'z_mm': 7100, 'label': 'Upper'}],
            'circulation': {'elevator': {'id': 'FixtureLift', 'cabin_body_ids': ['OnlyCabin'],
                'cabin_level': 'EG', 'ports': [
                    {'id': 'GroundOuter', 'level_id': 'EG', 'side': 'outward', 'active': True,
                     'wall': 'Outer', 'frame_body_id': 'GroundFrame', 'z_mm': 0},
                    {'id': 'UpperInner', 'level_id': 'Upper', 'side': 'inward', 'active': False,
                     'wall': 'Inner', 'frame_body_id': None, 'z_mm': 7100},
                    {'id': 'UpperOuter', 'level_id': 'Upper', 'side': 'outward', 'active': True,
                     'wall': 'Outer', 'frame_body_id': 'UpperFrame', 'z_mm': 7100}]}}}
        self.building = {'circulation': {'elevator': {'reference_opening': 'Entry'}}}
        self.expanded = {'operations': [{'id': 'CabinOuter', 'body': 'OnlyCabin', 'action': 'create',
            'shape': {'kind': 'box', 'origin': [1, 1, -2], 'size': [8, 8, 2200]}}]}
        self.parameters = {'display_scale': 100, 'display_thickness': 18}

    def compile(self):
        return lift.compile(self.source, self.building, self.parameters, self.interface,
                            self.expanded, self.plan, 1600)

    def test_stops_ports_and_one_cabin_come_from_the_interface(self):
        obj, config = self.compile()
        self.assertEqual(obj['states'], {'EG': 0, 'Upper': 7100})
        self.assertEqual(obj['moving_body_ids'], ['OnlyCabin'])
        self.assertEqual(config['ports'][1]['trigger_body_ids'], [])
        self.assertEqual(config['ports'][2]['cabin_entry_mm'][2], 8700)
        self.assertFalse(config['lift_operation_implemented'])

    def test_floor_change_updates_travel_and_destination_without_copied_heights(self):
        old, _ = self.compile()
        self.interface['levels'][1]['z_mm'] = 9600
        for port in self.interface['circulation']['elevator']['ports'][1:]:
            port['z_mm'] = 9600
        new, config = self.compile()
        self.assertGreater(new['duration_s'], old['duration_s'])
        self.assertEqual(new['joint']['limits_mm'], [0, 9600])
        self.assertEqual(config['ports'][2]['exit_eye_mm'][2], 11200)
        self.assertAlmostEqual(new['duration_s'], 1.875*9600/1000)

    def test_ambiguous_cabins_and_missing_active_stop_are_rejected(self):
        self.interface['circulation']['elevator']['cabin_body_ids'].append('SecondCabin')
        with self.assertRaisesRegex(ValueError, 'Exactly one'):
            self.compile()
        self.interface['circulation']['elevator']['cabin_body_ids'].pop()
        self.interface['circulation']['elevator']['ports'][-1]['active'] = False
        with self.assertRaisesRegex(ValueError, 'active port'):
            self.compile()


class NativeRoomPlacementTests(unittest.TestCase):
    def scene(self, name, x):
        builder = mesh.MeshBuilder()
        builder.add(name, [(x, 0, 0), (x+1, 0, 0), (x, 1, 0)], [(0, 1, 2)],
                    {'color': [1, 1, 1], 'opacity': 1}, role='fixture')
        return {**builder.result(), 'native_body_count': 1, 'native_face_count': 1,
                'coordinate_frame': 'building_presentation', 'units': 'mm', 'up_axis': 'Z', 'handedness': 'right',
                'linear_tessellation_deflection_mm': 1, 'equipment_instances': [], 'auxiliary_instances': [], 'equipment_placement_checks': []}

    def test_combination_preserves_bodies_and_indices_in_one_world_frame(self):
        result = mesh.combine_scenes(self.scene('Building', 10), self.scene('LabDevice', 20))
        indices = struct.unpack('<6I', base64.b64decode(result['indices_base64']))
        self.assertEqual(indices, (0, 1, 2, 3, 4, 5))
        self.assertEqual(result['groups'][1]['index_start'], 3)
        self.assertEqual(result['native_body_count'], 2)
        local = self.scene('LabDevice', 20)
        local['coordinate_frame'] = 'l01_local'
        with self.assertRaisesRegex(ValueError, 'same building frame'):
            mesh.combine_scenes(self.scene('Building', 10), local)

    def test_native_positions_normals_and_bounds_share_one_rigid_transform(self):
        transform = [[0, -1, 0, 100], [1, 0, 0, 200], [0, 0, 1, 12750], [0, 0, 0, 1]]
        mesh.validate_rigid(transform)
        self.assertEqual(mesh.rigid_point(transform, [3, 4, 5]), (96, 203, 12755))
        self.assertEqual(mesh.rigid_point(transform, [1, 0, 0], vector=True), (0, 1, 0))
        bounds = mesh.rigid_bounds(transform, {'min': [0, 0, 0], 'max': [2, 4, 5]})
        self.assertEqual(bounds, {'min': [96, 200, 12750], 'max': [100, 202, 12755]})
        scaled = copy.deepcopy(transform)
        scaled[0][1] = -2
        with self.assertRaisesRegex(ValueError, 'scale or shear'):
            mesh.validate_rigid(scaled)

    def test_outside_native_device_or_lost_host_blocks_the_export(self):
        laboratories = [{'id': 'Lab', 'interior_polygon_mm': [[0, 0], [10, 0], [10, 10], [0, 10]],
                         'device_instances': [{'id': 'Device', 'host': 'Bench', 'host_anchor_checked': True}]}]
        groups = [{'laboratory_id': 'Lab', 'instance_id': 'Device',
                   'bounds_mm': {'min': [1, 1, 900], 'max': [9, 9, 1200]}}]
        self.assertTrue(mesh.equipment_placement_checks(groups, laboratories, 0)[0]['passed'])
        groups[0]['bounds_mm']['max'][0] = 11
        with self.assertRaisesRegex(ValueError, 'loses room or host'):
            mesh.equipment_placement_checks(groups, laboratories, 0)
        groups[0]['bounds_mm']['max'][0] = 9
        laboratories[0]['device_instances'][0]['host_anchor_checked'] = False
        with self.assertRaisesRegex(ValueError, 'loses room or host'):
            mesh.equipment_placement_checks(groups, laboratories, 0)


if __name__ == '__main__':
    unittest.main()
