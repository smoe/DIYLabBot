"""Exclusive ownership and explicit synthetic lift acknowledgements."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_services as services
import walkthrough_elevator


def fixture():
    """Use the real source timing contract through the existing compiler."""
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root/'model/building-walkthrough.shared.json').read_text())['elevator']
    interface = {'levels':[{'id':'KG','z_mm':-4250,'label':'KG'}, {'id':'EG','z_mm':0,'label':'EG'},
                           {'id':'OG1','z_mm':4250,'label':'OG1'}, {'id':'OG2','z_mm':8500,'label':'OG2'}],
        'circulation':{'elevator':{'id':source['id'], 'cabin_body_ids':['Cabin'], 'cabin_level':'EG',
          'ports':[{'id':level+side,'level_id':level,'side':side,'active':active,
                    'wall':'Outer' if side=='outward' else 'Inner', 'frame_body_id':level+side+'Frame','z_mm':z}
                   for level,z in [('KG',-4250),('EG',0),('OG1',4250),('OG2',8500)]
                   for side,active in [('inward',level in ('KG','EG')),('outward',level not in ('KG','EG'))]]}}}
    plan = {'vertices':{'a':[0,0],'b':[0,20],'c':[20,0],'d':[20,20]},
      'walls':[{'id':'Outer','start':'a','end':'b'},{'id':'Inner','start':'c','end':'d'}],
      'openings':[{'id':'Entry','wall':'Outer','interval':[.25,.75]}]}
    expanded = {'operations':[{'id':'Cabin','body':'Cabin','action':'create','shape':{'kind':'box','origin':[0,0,-20],'size':[2000,1500,2200]}}]}
    _, compiled = walkthrough_elevator.compile(source, {'circulation':{'elevator':{'reference_opening':'Entry'}}},
        {'display_scale':100,'display_thickness':180}, interface, expanded, plan, 1600)
    lanes = services.cabin_lanes({'min':[0,0,0],'max':[2000,1500,2200]}, [512,412], 75)
    return services.LiftService(compiled, source['door_duration']['value'], lanes), source


class ResourceTests(unittest.TestCase):
    def test_fifo_exclusive_and_cannot_hold_and_wait_on_second_resource(self):
        owner = services.ResourceServices({'room':'room','door':'passage'})
        self.assertEqual(owner.request('BF01','room',0)['status'],'granted')
        self.assertEqual(owner.request('BF02','room',1)['status'],'waiting')
        with self.assertRaises(ValueError): owner.request('BF01','door',2)
        with self.assertRaises(ValueError): owner.release('BF02','room',2)
        owner.release('BF01','room',3)
        self.assertEqual(owner.own_grants('BF02'), {'status':'granted','resource':'room'})
        self.assertEqual(owner.events[-1]['wait_s'],2)
        self.assertNotIn('BF01', repr(owner.own_grants('BF02')))

    def test_waiting_places_have_own_grants_and_bounded_admission(self):
        owner = services.ResourceServices({}, {'EG':[[100,200,0]]})
        self.assertEqual(owner.request_waiting_place('BF01','EG')['pose_mm'],[100,200,0])
        self.assertEqual(owner.request_waiting_place('BF02','EG')['status'],'rejected_full')
        owner.release_waiting_place('BF01')
        self.assertEqual(owner.request_waiting_place('BF02','EG')['status'],'granted')

    def test_capacity_is_proven_from_interior_not_requested_two(self):
        both = services.cabin_lanes({'min':[0,0,0],'max':[800,1100,2000]},[512,412],75)
        self.assertEqual(len(both),2)
        one = services.cabin_lanes({'min':[0,0,0],'max':[800,900,2000]},[512,412],75)
        self.assertEqual(len(one),1)
        with self.assertRaises(ValueError): services.cabin_lanes({'min':[0,0,0],'max':[650,900,2000]},[512,412],75)


class LiftAdmissionTests(unittest.TestCase):
    def service(self,capacity=2):
        return services.ResourceServices({}, {level:[[100*i,200,0]for i in range(capacity)]for level in('EG','KG')})

    def test_trip_admission_is_atomic_when_destination_is_full(self):
        owner=self.service(1)
        owner.request_waiting_place('BF02','KG')
        result=owner.admit_lift_trip('BF01','EG','KG',0)
        self.assertEqual(result,{'status':'rejected_full','level':'KG'})
        self.assertNotIn('BF01',owner.wait_holds)
        self.assertNotIn('BF01',owner.exit_wait_holds)
        self.assertNotIn(('EG',0),owner.wait_owners)

    def test_same_side_destination_is_fenced_before_departure(self):
        owner=self.service(1)
        first=owner.admit_lift_trip('BF01','EG','KG',0)
        self.assertEqual(first['status'],'granted')
        self.assertEqual(owner.own_waiting_grants('BF01')['destination']['level'],'KG')
        self.assertEqual(owner.request_waiting_place('BF02','KG')['status'],'rejected_full')
        owner.release_waiting_place('BF01',1)
        self.assertEqual(owner.request_waiting_place('BF02','KG')['status'],'rejected_full')
        promoted=owner.promote_destination_waiting_place('BF01','KG',2)
        self.assertEqual(promoted['slot'],0)
        self.assertNotIn('BF01',owner.exit_wait_holds)
        self.assertEqual(owner.own_waiting_grants('BF01')['start']['level'],'KG')

    def test_opposing_admitted_trips_have_reserved_exits_and_no_peer_payload(self):
        owner=self.service(2)
        a=owner.admit_lift_trip('BF01','EG','KG',0)
        b=owner.admit_lift_trip('BF02','KG','EG',.1)
        self.assertEqual(a['status'],b['status'])
        self.assertEqual(a['status'],'granted')
        self.assertNotIn('BF02',repr(owner.own_waiting_grants('BF01')))
        self.assertNotEqual(owner.wait_holds['BF01'],owner.exit_wait_holds['BF02'])
        before=copy.deepcopy(owner.wait_owners)
        self.assertEqual(owner.admit_lift_trip('BF01','EG','KG',1)['status'],'granted')
        self.assertEqual(before,owner.wait_owners)
        owner.release_waiting_place('BF01',1)
        owner.promote_destination_waiting_place('BF01','KG',2)
        owner.release_waiting_place('BF02',3)
        owner.promote_destination_waiting_place('BF02','EG',4)
        self.assertEqual(owner.admit_lift_trip('BF01','KG','EG',5)['status'],'granted')

    def test_unknown_or_changed_destination_cannot_drop_an_existing_claim(self):
        owner=self.service();owner.admit_lift_trip('BF01','EG','KG',0)
        before=copy.deepcopy(owner.wait_owners)
        with self.assertRaises(ValueError):owner.admit_lift_trip('BF01','KG','EG',1)
        with self.assertRaises(ValueError):owner.promote_destination_waiting_place('BF01','KG',1)
        with self.assertRaises(ValueError):owner.release_waiting_place('BF01',float('nan'))
        self.assertEqual(before,owner.wait_owners)


class LiftTests(unittest.TestCase):
    def advance_to(self, lift, phase, clear=True):
        for _ in range(10000):
            if lift.phase == phase: return
            lift.tick(round(lift.now+.05, 9), clear)
        self.fail('Lift phase did not settle: '+lift.phase)

    def test_boarding_requires_open_active_port_and_own_free_scan(self):
        lift, _ = fixture()
        lift.request('BF01','OG1','EG',0)
        self.assertEqual(lift.board('BF01',True)['status'],'rejected_not_ready')
        self.advance_to(lift,'travelling')
        self.assertFalse(lift.doors_open)
        self.assertEqual(lift.board('BF01',True)['status'],'rejected_not_ready')
        self.advance_to(lift,'boarding')
        self.assertEqual(lift.level,'OG1'); self.assertTrue(lift.doors_open)
        self.assertEqual(lift.board('BF01',False)['status'],'rejected_not_ready')
        self.assertEqual(lift.board('BF01',True)['status'],'accepted')
        with self.assertRaises(ValueError): lift.request('BF02','EG','OG1',lift.now,start_side='outward')

    def test_all_parked_and_clear_line_are_required_before_travel(self):
        lift, source = fixture()
        lift.request('BF01','EG','OG1',0); lift.request('BF02','EG','OG2',0)
        lift.tick(0,True)
        lift.board('BF01',True); lift.park('BF01')
        lift.tick(10,True); self.assertEqual(lift.phase,'boarding')
        lift.board('BF02',True); lift.park('BF02')
        lift.tick(11,False); lift.tick(12,False)
        self.assertEqual(lift.phase,'closing_passengers'); self.assertTrue(lift.doors_open)
        lift.tick(12+source['door_duration']['value']+.01,True)
        self.assertEqual(lift.phase,'travelling'); self.assertFalse(lift.doors_open)
        travel = lift.transition
        self.assertAlmostEqual(travel['end_s']-travel['start_s'],1.875*4250/source['speed']['value'])
        self.assertEqual(travel['to_level'],'OG1')
        self.assertEqual(lift.maximum_occupancy,2)

    def test_directional_collective_stops_only_assigned_destinations(self):
        lift, _ = fixture()
        lift.request('BF01','EG','OG2',0); lift.request('BF02','EG','OG1',0)
        lift.request('BF03','EG','KG',0); lift.tick(0,True)
        self.assertEqual(lift.own_grant('BF03')['status'],'waiting')
        for vehicle in ('BF01','BF02'): lift.board(vehicle,True); lift.park(vehicle)
        self.advance_to(lift,'alighting')
        self.assertEqual(lift.level,'OG1')
        self.assertEqual(lift.exit('BF01',True)['status'],'rejected_not_ready')
        self.assertEqual(lift.exit('BF02',False)['status'],'rejected_not_ready')
        self.assertEqual(lift.exit('BF02',True)['direction'],'forward')
        self.advance_to(lift,'alighting')
        self.assertEqual(lift.level,'OG2'); self.assertEqual(lift.exit('BF01',True)['direction'],'forward')
        self.assertEqual(lift.phase,'idle'); self.assertEqual(lift.own_grant('BF01')['status'],'none')

    def test_same_side_exit_reverse_and_absolute_cabin_binding(self):
        lift, _ = fixture(); lift.request('BF01','OG1','OG2',0)
        self.advance_to(lift,'boarding'); lift.board('BF01',True); lift.park('BF01')
        self.advance_to(lift,'travelling')
        t = copy.deepcopy(lift.transition); lift.tick((t['start_s']+t['end_s'])/2,True)
        self.assertAlmostEqual(lift.z,(4250+8500)/2)
        self.assertAlmostEqual(lift.attached_pose('BF01')[2],lift.z)
        self.advance_to(lift,'alighting')
        self.assertEqual(lift.exit('BF01',True)['direction'],'reverse')
        with self.assertRaises(ValueError): lift.attached_pose('BF01')

    def test_narrow_port_grants_serialize_crossings_without_reducing_cabin_capacity(self):
        lift,_=fixture();lift.request('BF01','EG','OG1',0);lift.request('BF02','EG','OG1',0);lift.tick(0,True)
        self.assertTrue(lift.own_grant('BF01')['boarding_ready'])
        self.assertFalse(lift.own_grant('BF02')['boarding_ready'])
        self.assertEqual(lift.board('BF02',True)['status'],'rejected_not_ready')
        lift.board('BF01',True);lift.park('BF01')
        self.assertTrue(lift.own_grant('BF02')['boarding_ready'])
        lift.board('BF02',True);lift.park('BF02');self.advance_to(lift,'alighting')
        self.assertEqual(lift.maximum_occupancy,2)
        self.assertFalse(lift.own_grant('BF02')['exit_ready'])
        self.assertEqual(lift.exit('BF02',True)['status'],'rejected_not_ready')
        self.assertEqual(lift.exit('BF01',True)['status'],'accepted')
        self.assertTrue(lift.own_grant('BF02')['exit_ready'])
        self.assertEqual(lift.exit('BF02',True)['status'],'accepted')

    def test_door_schedule_keeps_source_duration_when_tick_float_subtracts_low(self):
        lift,source=fixture();lift.request('BF01','EG','OG1',0);lift.tick(0,True)
        lift.board('BF01',True);lift.park('BF01');self.advance_to(lift,'alighting')
        for row in lift.schedule:
            if row['kind']=='doors':self.assertAlmostEqual(row['end_s']-row['start_s'],source['door_duration']['value'],places=8)

    def test_door_observation_and_clock_are_explicit(self):
        lift, _ = fixture()
        with self.assertRaises(ValueError): lift.tick(1,None)
        lift.tick(1,True)
        with self.assertRaises(ValueError): lift.tick(.5,True)


if __name__ == '__main__': unittest.main()
