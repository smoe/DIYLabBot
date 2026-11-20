"""Source ownership, native pose constraints and lift fitting placement."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_stack as stack
import building_walkthrough as walkthrough
import lab_layout_model as layout
import walkthrough_mechanisms as mechanisms
import lift_fittings


class MechanismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = walkthrough.compile()
        cls.objects = {obj['id']: obj for obj in cls.program['objects']}

    def test_every_native_room_leaf_and_its_glazing_move_once(self):
        rooms = [o for o in self.objects.values() if o.get('mechanism') == 'room_door']
        self.assertEqual(len(rooms), 138)
        self.assertNotIn('OG3.D3_009.Door',self.objects)
        self.assertEqual({o['level_id'] for o in rooms}, {'KG', 'EG', 'OG1', 'OG2', 'OG3'})
        basement = [o for o in rooms if o['level_id'] == 'KG']
        self.assertTrue(basement)
        self.assertTrue(all(o['material'] == 'steel' for o in basement))
        bodies = [body for obj in self.objects.values() for body in obj['moving_body_ids']]
        self.assertEqual(len(bodies), len(set(bodies)), 'No body is driven by two unrelated joints')
        for room in rooms:
            self.assertEqual(room['reference_state'], 'open')
            self.assertEqual(room['states'], {'closed': 0, 'open': 90})
            self.assertEqual(abs(room['joint']['axis'][2]), 1)
        window = self.objects['OG3.D3_002N.Door']
        self.assertEqual(len(window['moving_body_ids']), 4, 'Leaf, pane and both rims share their hinge')

    def test_freezer_guard_covers_every_drawer_and_both_command_directions(self):
        prefix = 'Lab3003.Freezer01.'
        door = self.objects[prefix+'OuterDoor']
        guards = door['commands']['close']['requires']
        self.assertEqual({g['object_id'] for g in guards}, {prefix+'Drawer%02d'%i for i in range(1, 7)})
        self.assertTrue(all(g['state'] == 'closed' for g in guards))
        for guard in guards:
            drawer = self.objects[guard['object_id']]
            self.assertEqual(drawer['commands']['open']['requires'], [{'object_id': door['id'], 'state': 'open'}])
            self.assertEqual(drawer['commands']['close']['requires'], [])
        self.assertEqual(self.objects[prefix+'Drawer04']['reference_state'], 'open')

    def test_equipment_reuses_source_joints_and_reference_poses(self):
        source = layout.load(validate_builds=False)
        for item in source['instances']:
            if item['asset'] not in mechanisms.ASSETS:
                continue
            provider = layout.provider(item['asset']); spec = layout.instance_source(source, item)
            p = provider.parameters(spec); expanded = provider.expanded(spec, p)
            reference = provider.pose(spec, p, item.get('pose'))
            for joint in expanded['joints']:
                obj = self.objects['Lab3003.'+item['id']+'.'+joint['id']]
                self.assertEqual(obj['states'][obj['reference_state']], reference[joint['id']])
                self.assertEqual(obj['moving_body_ids'], ['Lab3003_'+item['id']+'_'+b['id'] for b in expanded['bodies'] if b['component'] == joint['child']])
                self.assertEqual(obj['states']['open'], joint.get('limits_deg', joint.get('limits_mm'))[1])
        self.assertEqual(self.objects['Lab3003.NanoDrop01.Hinge']['states']['reference'], 65)
        self.assertEqual(self.objects['Lab3003.Qubit01.Hinge']['states']['reference'], 95)

    def test_technical_accesses_start_closed_without_changing_native_reference(self):
        closed = set()
        for level in ('OG1', 'OG2', 'OG3'):
            for number in ('023', '024', '025', '026', '027'):
                identity = level+'.D3_'+number+'.Door'
                closed.add(identity)
                obj = self.objects[identity]
                self.assertEqual(obj['initial_state'], 'closed')
                self.assertEqual(obj['reference_state'], 'open')
        for identity in ('OG3.D3_002N.Door', 'OG3.D3_003A.Door', 'OG3.D3_003B.Door', 'OG3.D3_002_001.Door'):
            self.assertEqual(self.objects[identity]['initial_state'], 'open')
        for identity, obj in self.objects.items():
            if obj.get('mechanism') == 'room_door' and identity not in closed:
                self.assertEqual(obj['initial_state'], 'open')

    def test_unknown_closed_access_bindings_fail_instead_of_closing_other_rooms(self):
        source = json.loads((walkthrough.ROOT/'model/building-walkthrough.shared.json').read_text())
        for policy in ({'MissingFloor': ['N3_026']}, {'OG3': ['MissingArea']}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                mechanisms.room_doors(source['mechanisms']['room_doors'],
                    {'levels': [], 'exterior': {'door_bindings': {}}}, {'operations': []},
                    {'OG3': {'areas': []}}, {}, 1600, policy)

    def test_lift_has_one_cabin_and_only_active_landing_doors(self):
        lift = self.program['elevator']; cabin = self.objects[lift['object_id']]
        self.assertTrue(all(a < b for a, b in zip(lift['shaft_bounds_mm']['min'], lift['shaft_bounds_mm']['max'])))
        self.assertEqual(cabin['moving_body_ids'].count('BuildingLiftCabin'), 1)
        self.assertIn('LiftControlPanel', cabin['moving_body_ids'])
        self.assertIn('LiftTelephone', cabin['moving_body_ids'])
        doors = [o for o in self.objects.values() if o.get('mechanism') == 'lift_door']
        self.assertEqual(len(doors), 14)
        self.assertEqual(len([o for o in doors if o['parent_object_id'] == cabin['id']]), 4)
        for door in doors:
            self.assertEqual(door['commands']['open']['target_state'], 'open')
            self.assertEqual(door['commands']['close']['target_state'], 'closed')
        for port in lift['ports']:
            self.assertEqual(len(port['door_object_ids']), 4 if port['active'] else 0)
            for name in port['door_object_ids']:
                obj = self.objects[name]
                self.assertEqual(obj['side'], port['side'])
                self.assertTrue(obj['parent_object_id'] == cabin['id'] or obj['port_id'] == port['id'])
        panel, phone = (lift['fittings'][name] for name in ('panel', 'telephone'))
        self.assertEqual(panel['side'], 'southwest'); self.assertEqual(phone['side'], 'northeast')
        self.assertLess(panel['center_mm'][0], phone['center_mm'][0])
        self.assertLess(panel['center_mm'][1], lift['cabin_bounds_mm']['min'][1]+500)
        self.assertEqual(panel['face_normal'], [0,1,0])
        self.assertGreater(phone['center_mm'][1], lift['cabin_bounds_mm']['max'][1]-500)

    def test_new_dependencies_are_pinned(self):
        pins = self.program['source_files_sha256']
        for name in ('scripts/lift_fittings.py', 'scripts/walkthrough_mechanisms.py', 'scripts/lab_equipment.py', 'scripts/instrument_concept.py'):
            self.assertIn(name, pins)


class FittingValidationTests(unittest.TestCase):
    def test_open_cabin_leaves_clear_end_walls_and_controls_for_the_whole_stroke(self):
        source = json.loads((ROOT/'model/building-stack.shared.json').read_text())['circulation']['elevator']['fittings']
        rectangle = [10107.810810810812, 15102.405405405405, 12605.702702702703, 17303.0]
        opening = [15608.10810823892, 16529.729729741622]
        ports = [{'id': 'Ground', 'level_id': 'EG', 'side': 'outward', 'active': True,
                  'plane_x_mm': 9900, 'wall_thickness_mm': 180, 'height_mm': 2150, 'z_mm': 0}]
        result = lift_fittings.compile(source, rectangle, 90, opening, ports, 0, [{'id': 'EG'}])
        shapes = {op['body']: op['shape'] for op in result['operations']}
        def bounds(shape):
            origin=shape['origin']
            if shape['kind']=='box':return origin,[v+w for v,w in zip(origin,shape['size'])]
            axis=shape['axis'];radius=shape['radius'];length=shape['height']
            extent=[radius*(1-v*v)**.5 for v in axis]
            return ([origin[i]+min(0,axis[i]*length)-extent[i]for i in range(3)],
                    [origin[i]+max(0,axis[i]*length)+extent[i]for i in range(3)])
        controls=result['placements']['panel']['body_ids']+['LiftTelephone','LiftTelephoneReceiver','LiftTelephoneReceiverBottom','LiftTelephoneReceiverTop']
        for door in result['door_groups']:
            if door['parent'] != 'cabin': continue
            shape = shapes[door['moving_body_ids'][0]]
            travel = door['joint']['axis'][1]*door['joint']['limits_mm'][1]
            swept_min = shape['origin'][1]+min(0, travel)
            swept_max = shape['origin'][1]+shape['size'][1]+max(0, travel)
            self.assertGreater(swept_min, rectangle[1]+90)
            self.assertLess(swept_max, rectangle[3]-90)
            swept_lo,swept_hi=bounds(shape);swept_lo=list(swept_lo);swept_hi=list(swept_hi)
            swept_lo[1]=swept_min;swept_hi[1]=swept_max
            for body in controls:
                lo,hi=bounds(shapes[body])
                self.assertTrue(any(swept_hi[i]<lo[i] or hi[i]<swept_lo[i] for i in range(3)),body)
            opened = [shape['origin'][1]+travel, shape['origin'][1]+shape['size'][1]+travel]
            self.assertTrue(opened[1] < opening[0] or opened[0] > opening[1])
        changed = copy.deepcopy(source); changed['panel']['entry_end_clearance_mm'] = 20
        with self.assertRaisesRegex(ValueError, 'clear'):
            lift_fittings.compile(changed, rectangle, 90, opening, ports, 0, [{'id': 'EG'}])

    def test_nonfinite_sizes_and_wrong_confirmed_sides_fail(self):
        source = json.loads((ROOT/'model/building-stack.shared.json').read_text())['circulation']['elevator']['fittings']
        for field, value in [('leaf_gap_mm', float('nan')), ('leaf_thickness_mm', -1)]:
            changed = copy.deepcopy(source); changed[field] = value
            with self.assertRaises(ValueError): lift_fittings.validate(changed)
        changed = copy.deepcopy(source); changed['panel']['side'] = 'southeast'
        with self.assertRaises(ValueError): lift_fittings.validate(changed)


if __name__ == '__main__':
    unittest.main()
