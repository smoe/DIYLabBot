"""Mission-bound bay admission and observed role transitions without CAD."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_model as model
from building_fleet_services import ResourceServices
from building_fleet_runner import WorldRunner,ResourceGate
from building_fleet_dispatch import Dispatcher


def waiting(capacity=2):
    return {level:[[1000.,1000.*i,0.]for i in range(capacity)]for level in('KG','EG','OG1','OG2','OG3')}


def complete_trip(service,vehicle,mid,start,end,now):
    booking=service.book_mission(vehicle,mid,start,end,now)
    if booking is None:raise AssertionError('Fixture trip is not admitted')
    service.mark_mission_boarded(vehicle,mid,now+1)
    service.release_waiting_place(vehicle,now+1)
    service.promote_destination_waiting_place(vehicle,end,now+2)
    return booking


def runner_stub(service):
    world=object.__new__(WorldRunner);world.source=model.load()
    homes={'BF%02d'%i:{'level':'EG','area':'R0_004','slot':i}for i in range(1,21)}
    world.dispatcher=Dispatcher(world.source,homes);world.resources=service
    world.nav=SimpleNamespace(waits=service.waiting_places,homes=homes)
    world.planner=SimpleNamespace(states={v:{'queue':[],'completed':set()}for v in homes})
    world.vehicles={v:{'mission_pending':False,'aboard':False,'level':'EG'}for v in homes}
    world.downlink=SimpleNamespace(emit=lambda *args:None)
    return world


class BookingTests(unittest.TestCase):
    def test_atomic_binding_precedes_mission_and_survives_source_release(self):
        service=ResourceServices({},waiting(1));world=runner_stub(service)
        result=world.request_mission('BF01','EG',0)
        mission=world.dispatcher.missions[result['mission_id']]
        if mission['goal']['level']=='EG':
            world.vehicles['BF01']['mission_pending']=False
            world.planner.states['BF01']['queue']=[mission]
            result=world.request_mission('BF01','EG',.1);mission=world.dispatcher.missions[result['mission_id']]
        booking=service.bookings[mission['booking_id']]
        self.assertEqual(booking['mission_id'],mission['mission_id'])
        self.assertLessEqual(booking['created_s'],mission['assigned_s'])
        with self.assertRaises(ValueError):service.release_waiting_place('BF01',1)
        with self.assertRaises(ValueError):service.promote_destination_waiting_place('BF01',booking['to_level'],1)
        service.mark_mission_boarded('BF01',mission['mission_id'],2)
        service.release_waiting_place('BF01',2)
        self.assertEqual(service.own_waiting_grants('BF01')['destination']['role'],'destination')
        self.assertEqual(service.request_waiting_place('BF02',booking['to_level'])['status'],'rejected_full')
        service.promote_destination_waiting_place('BF01',booking['to_level'],3)
        self.assertEqual(service.bookings[mission['booking_id']]['state'],'arrived')

    def test_one_conditional_destination_activates_only_after_body_clear(self):
        service=ResourceServices({},waiting())
        first=service.book_mission('BF01','m1','EG','KG',0)
        self.assertFalse(service.can_book_mission('BF01','KG','OG1','arrival'))
        service.mark_mission_boarded('BF01','m1',1);service.release_waiting_place('BF01',1)
        next_trip=service.book_mission('BF01','m2','KG','OG1',2,'arrival')
        self.assertEqual(next_trip['start'],first['destination'])
        self.assertEqual(next_trip['state'],'conditional')
        own=service.own_waiting_grants('BF01')
        self.assertEqual(own['destination']['booking_id'],first['booking_id'])
        self.assertEqual(own['lookahead_destination']['booking_id'],next_trip['booking_id'])
        self.assertIsNone(service.book_mission('BF01','m3','KG','OG2',2,'arrival'))
        with self.assertRaises(ValueError):service.require_mission_booking('BF01','m2','KG','OG1')
        service.promote_destination_waiting_place('BF01','KG',3)
        self.assertEqual(service.require_mission_booking('BF01','m2','KG','OG1')['state'],'active')
        self.assertEqual(service.own_waiting_grants('BF01')['lookahead_destination'],{'status':'none'})
        self.assertEqual([e['event']for e in service.waiting_events[-3:]],
            ['waiting_promoted','waiting_role_activated','waiting_bound'])
        self.assertEqual([e['event']for e in service.booking_events[-2:]],['booking_arrived','booking_activated'])
        self.assertNotIn('BF02',repr(own))

    def test_return_lookahead_cannot_reuse_the_current_source_key(self):
        service=ResourceServices({},waiting(1))
        service.book_mission('BF01','m1','EG','KG',0)
        # Even an early external request cannot share two physical roles.
        self.assertIsNone(service.book_mission('BF01','m2','KG','EG',.1,'arrival'))
        service.mark_mission_boarded('BF01','m1',1)
        self.assertIsNone(service.book_mission('BF01','m2','KG','EG',1,'arrival'))
        service.release_waiting_place('BF01',1)
        self.assertIsNotNone(service.book_mission('BF01','m2','KG','EG',2,'arrival'))

    def test_identity_and_physical_owner_cannot_be_forged(self):
        service=ResourceServices({},waiting());booking=service.book_mission('BF01','m1','EG','KG',0)
        with self.assertRaises(ValueError):service.book_mission('BF02','m1','EG','KG',1)
        key=(booking['destination']['level'],booking['destination']['slot'])
        service.wait_owners[key]='BF02'
        with self.assertRaises(ValueError):service.require_mission_booking('BF01','m1','EG','KG')


class AdmissionCycleTests(unittest.TestCase):
    def test_nine_current_holders_filter_to_free_destination_and_progress(self):
        service=ResourceServices({},waiting());n=0
        # Eight non-EG current holders, reached by real bound role transitions.
        for level in('KG','OG1','OG2','OG3'):
            for _ in range(2):
                n+=1;complete_trip(service,'BF%02d'%n,'old-'+str(n),'EG',level,n*3)
        complete_trip(service,'BF01','old-9','KG','EG',30)
        complete_trip(service,'BF09','old-10','EG','KG',33)
        self.assertEqual(len(service.wait_holds),9)
        free=[k for k in [(l,i)for l in waiting()for i in range(2)]if k not in service.wait_owners]
        self.assertEqual(len(free),1);self.assertEqual(free[0][0],'EG')
        world=runner_stub(service)
        for identity,key in service.wait_holds.items():world.vehicles[identity]['level']=key[0]
        # Every non-EG target is full. Coverage priority must not issue one of
        # those destinations and then strand its owner waiting for capacity.
        result=world.request_mission('BF02','KG',40)
        mission=world.dispatcher.missions[result['mission_id']]
        self.assertEqual(mission['goal']['level'],'EG')
        self.assertIsNotNone(mission['booking_id'])
        self.assertEqual(len(service.wait_owners),10)
        # Actual boarding frees KG; the source remains fenced until this point.
        service.mark_mission_boarded('BF02',mission['mission_id'],41)
        service.release_waiting_place('BF02',41)
        service.promote_destination_waiting_place('BF02','EG',42)
        world.planner.states['BF01']['queue']=[{'mission_id':'local','goal':{'kind':'inspection_pass','level':'EG'}}]
        second=world.request_mission('BF01','EG',43)
        second_mission=world.dispatcher.missions[second['mission_id']]
        self.assertEqual(second_mission['goal']['level'],'KG')
        self.assertEqual(len(world.dispatcher.missions),2)

    def test_full_destinations_do_not_issue_a_foreign_mission_or_mutate_rng(self):
        service=ResourceServices({},waiting(1));world=runner_stub(service)
        for i,level in enumerate(('KG','OG1','OG2','OG3'),2):service.request_waiting_place('BF%02d'%i,level)
        world.planner.states['BF01']['queue']=[{'mission_id':'local','goal':{'kind':'inspection_pass','level':'EG'}}]
        before=world.dispatcher.random.getstate()
        self.assertEqual(world.request_mission('BF01','EG',0),{'status':'pending_admission'})
        self.assertEqual(world.dispatcher.missions,{})
        self.assertEqual(world.dispatcher.random.getstate(),before)
        self.assertEqual(service.wait_owners,{(level,0):'BF%02d'%i for i,level in enumerate(('KG','OG1','OG2','OG3'),2)})

    def test_aboard_lookahead_uses_incoming_floor_and_one_foreign_boundary(self):
        service=ResourceServices({},waiting());world=runner_stub(service)
        incoming=service.book_mission('BF01','incoming','EG','KG',0)
        service.mark_mission_boarded('BF01','incoming',1);service.release_waiting_place('BF01',1)
        world.vehicles['BF01'].update(aboard=True,level='EG')
        world.lift=SimpleNamespace(own_grant=lambda v:{'destination_port':'KG.in'},ports={'KG.in':{'level_id':'KG'}})
        world.planner.states['BF01']['queue']=[{'mission_id':'incoming','goal':{'kind':'inspection_pass','level':'KG'}}]
        result=world.request_mission('BF01','EG',2)
        issued=world.dispatcher.missions[result['mission_id']]
        self.assertEqual(issued['source_level'],'KG')
        self.assertNotEqual(issued['goal']['level'],'KG')
        self.assertEqual(service.bookings[issued['booking_id']]['source_role'],'arrival')
        world.vehicles['BF01']['mission_pending']=False
        world.planner.states['BF01']['queue'].append(issued)
        self.assertEqual(world.request_mission('BF01','EG',3),{'status':'already_queued_foreign'})
        self.assertEqual(len(world.dispatcher.missions),1)

    def test_home_bound_body_clear_cannot_drop_a_newly_rebound_source(self):
        service=ResourceServices({},waiting());world=runner_stub(service)
        complete_trip(service,'BF01','arrived','KG','EG',0)
        world.vehicles['BF01']['action']={'terminal':{'kind':'capacity_home'}}
        self.assertEqual(world.request_mission('BF01','EG',3),{'status':'pending_admission'})
        self.assertEqual(world.dispatcher.missions,{})
        service.release_waiting_place('BF01',4)
        world.vehicles['BF01']['action']=None
        self.assertEqual(world.request_mission('BF01','EG',5)['status'],'pending')

    def test_return_home_is_queued_behind_local_inspection_without_provisional_rest(self):
        world=runner_stub(ResourceServices({},waiting()))
        world.dispatcher.visits={key:1 for key in world.dispatcher.targets}
        world.planner.states['BF01']['queue']=[{'mission_id':'local','goal':{'kind':'inspection_pass','level':'EG'}}]
        result=world.request_mission('BF01','EG',600)
        issued=world.dispatcher.missions[result['mission_id']]
        self.assertEqual(issued['goal']['kind'],'home')
        self.assertEqual(issued['source_level'],'EG');self.assertIsNone(issued['booking_id'])


class ParkedBayTests(unittest.TestCase):
    def world(self):
        service=ResourceServices({'landing':'passage'},waiting())
        service.book_mission('BF01','m1','EG','KG',0)
        service.request('BF01','landing',0)
        world=runner_stub(service);world.now=1.;world.depot_aliases={};world.resource_events=[];world.bay_parking_events=[]
        world.drain_resource_events=lambda:None
        world.lift=SimpleNamespace(own_grant=lambda identity:{'status':'none'})
        grant=service.own_waiting_grants('BF01')['start']
        world.vehicles['BF01']['pose_mm_rad']=grant['pose_mm'][:]
        driver=SimpleNamespace(path=SimpleNamespace(pva=lambda *args:([0,0,0],[0.,0.,0.],[0.,0.,0.])),y=0.,v=0.,a=0.)
        return world,driver

    def test_bay_stays_fenced_while_corridor_token_is_released_and_reacquired(self):
        world,driver=self.world();before=copy.deepcopy(world.resources.wait_owners)
        world.park_waiting_bay('BF01',driver)
        self.assertNotIn('BF01',world.resources.holds)
        self.assertEqual(before,world.resources.wait_owners)
        self.assertEqual(world.bay_parking_events[0]['released_resource'],'landing')
        world.catalog=SimpleNamespace(spans=lambda level,path:[{'resource':'landing','start_progress_mm':0.,'end_progress_mm':1000.}])
        driver.settings={'range_mm':2200}
        gate=ResourceGate(world,'BF01',driver,'EG')
        self.assertTrue(gate.permit(2))
        self.assertEqual(world.resources.holds,{'BF01':'landing'})

    def test_neither_wrong_pose_nor_nonzero_pva_can_release_token(self):
        world,driver=self.world();world.vehicles['BF01']['pose_mm_rad'][0]+=1
        with self.assertRaises(RuntimeError):world.park_waiting_bay('BF01',driver)
        self.assertEqual(world.resources.holds,{'BF01':'landing'})
        world,driver=self.world();driver.path.pva=lambda *args:([0,0,0],[.1,0.,0.],[0.,0.,0.])
        with self.assertRaises(RuntimeError):world.park_waiting_bay('BF01',driver)
        self.assertEqual(world.resources.holds,{'BF01':'landing'})


if __name__=='__main__':unittest.main()
