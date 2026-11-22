"""Independent conditional-bay and provisional-rest checks, without CAD claims."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).resolve().parent)]
import building_fleet_checks as checks
from test_building_fleet_checks import point,trajectory


def waiting(event,at,level='EG',slot=0,role='start',booking='B1',mission='M1'):
    return {'event':event,'time_s':at,'vehicle_id':'BF01','level':level,'slot':slot,
            'role':role,'booking_id':booking,'mission_id':mission}


def navigation():
    return NS(waits={level:[[0.,0.,0.]]for level in('EG','OG1')},
        waiting_bay_polygons={level:[[[-10.,-10.],[10.,-10.],[10.,10.],[-10.,10.]]]for level in('EG','OG1')},
        envelope={'length_mm':4,'width_mm':4},radius=math.sqrt(8),reserve=1,
        homes={'BF01':{'level':'EG','pose_mm_rad':[1000.,0.,0.]}})


def trip_chain():
    return [waiting('waiting_granted',0),
            waiting('waiting_granted',0,'OG1',role='destination'),
            waiting('waiting_released',1),
            waiting('waiting_granted',1.1,role='lookahead_destination',booking='B2',mission='M2'),
            waiting('waiting_promoted',3,'OG1'),
            waiting('waiting_role_activated',3,role='destination',booking='B2',mission='M2'),
            waiting('waiting_bound',3,'OG1',booking='B2',mission='M2'),
            waiting('waiting_released',5,'OG1',booking='B2',mission='M2'),
            waiting('waiting_promoted',7,booking='B2',mission='M2'),
            waiting('waiting_released',8,booking='B2',mission='M2')]


def parked_program(released='R'):
    return {'duration_s':4,'waiting_events':[waiting('waiting_granted',0),waiting('waiting_released',4)],
            'bay_parking_events':[{'event':'waiting_bay_parked','vehicle_id':'BF01','time_s':2,
                'level':'EG','slot':0,'booking_id':'B1','released_resource':released,
                'pose_mm_rad':[0.,0.,0.],'velocity_mm_rad_s':[0.,0.,0.],'acceleration_mm_rad_s2':[0.,0.,0.],
                'condition':'exclusive_current_bay_at_exact_source_pose_and_rest; every_other_curve_excludes_occupied_bay'}]}


class CapacityChecks(unittest.TestCase):
    def test_original_assignment_booking_fixture_also_passes_physical_role_replay(self):
        from test_building_fleet_assignment_checks import fixture
        program,trajectories,nav,_=fixture()
        self.assertTrue(checks.check_waiting_history(program['waiting_events'],program['duration_s'],nav,
                                                    {t.identity for t in trajectories})['passed'])

    def test_role_chain_activates_only_after_actual_arrival_promotion(self):
        rows=trip_chain();nav=navigation()
        proof=checks.check_waiting_history(rows,8,nav,{'BF01'})
        self.assertTrue(proof['passed'])
        bad=copy.deepcopy(rows);bad[4],bad[5]=bad[5],bad[4]
        with self.assertRaisesRegex(ValueError,'source promotion'):checks.check_waiting_history(bad,8,nav,{'BF01'})
        bad=copy.deepcopy(rows);bad[6]['mission_id']='forged'
        # The booking checker independently binds the newly named source;
        # releasing under the real next mission cannot drop the forgery here.
        with self.assertRaisesRegex(ValueError,'exact own grant'):checks.check_waiting_history(bad,8,nav,{'BF01'})

    def test_conditional_lookahead_and_unmatched_arrival_are_not_occupancy_grants(self):
        nav=navigation();rows=trip_chain()
        for a,b in((2.,2.5),(4.,4.5)):
            car=trajectory('BF01',[point(a,0),point(b,0)],mode='hold',hold_reason='resource_wait',hold_condition='own grant')
            with self.assertRaisesRegex(ValueError,'without its own live grant'):
                checks.check_waiting_occupancy([car],nav,rows,8)
        car=trajectory('BF01',[point(6.5,0),point(7,0)],mode='hold',hold_reason='lift_wait',
                       hold_condition='own exit',lift_phase='alighting',port_id='EG.in')
        request={'vehicle_id':'BF01','booking_id':'B2','mission_id':'M2','destination_port':'EG.in',
                 'requested_s':4.,'exited_s':7.,'destination_waiting_bay':{'level':'EG','slot':0}}
        self.assertTrue(checks.check_waiting_occupancy([car],nav,rows,8,lift_requests=[request])['passed'])
        request['booking_id']='forged'
        with self.assertRaisesRegex(ValueError,'without its own live grant'):
            checks.check_waiting_occupancy([car],nav,rows,8,lift_requests=[request])

    def test_exact_parked_bay_releases_only_its_corridor_token_during_rest(self):
        nav=navigation();car=trajectory('BF01',[point(2,0),point(4,0)],mode='hold',
            hold_reason='capacity_wait',hold_condition='own_admissible_successor_assignment')
        program=parked_program();catalog={'resources':{'R':'passage'},'regions':[
            {'level':'EG','resource':'R','polygon':[[-20,-20],[20,-20],[20,20],[-20,20]]}],
            'room_polygons':[],'room_guard_mm':0}
        tokens={('BF01','R'):[(0,2)]}
        self.assertTrue(checks.check_waiting_occupancy([car],nav,program['waiting_events'],4)['passed'])
        proof,parked=checks.check_capacity_parking(program,[car],nav,catalog,tokens)
        self.assertEqual(proof['capacity_hold_episodes'],1)
        with self.assertRaisesRegex(ValueError,'exclusive resource'):
            checks.check_resource_occupancy([car],catalog,tokens,nav.homes)
        self.assertTrue(checks.check_resource_occupancy([car],catalog,tokens,nav.homes,parked_bays=parked)['passed'])
        car.episodes[0]['hold_condition']='a prettier scene'
        with self.assertRaisesRegex(ValueError,'actual source assignment/admission'):
            checks.check_capacity_parking(program,[car],nav,catalog,tokens)
        car.episodes[0]['hold_condition']='own_admissible_successor_assignment'
        bad=copy.deepcopy(program);bad['bay_parking_events'][0]['pose_mm_rad'][0]=1
        with self.assertRaisesRegex(ValueError,'actual exported own PVA'):
            checks.check_capacity_parking(bad,[car],nav,catalog,tokens)
        bad=copy.deepcopy(program);bad['bay_parking_events'][0]['released_resource']='unknown'
        with self.assertRaisesRegex(ValueError,'token grant/release'):
            checks.check_capacity_parking(bad,[car],nav,catalog,tokens)

    def test_departure_and_other_vehicle_still_need_real_exclusive_permissions(self):
        nav=navigation();program=parked_program();catalog={'resources':{'R':'passage'},'regions':[
            {'level':'EG','resource':'R','polygon':[[-20,-20],[20,-20],[20,20],[-20,20]]}],
            'room_polygons':[],'room_guard_mm':0}
        parked_car=trajectory('BF01',[point(2,0),point(4,0)],mode='hold',
            hold_reason='capacity_wait',hold_condition='own_admissible_successor_assignment')
        other=trajectory('BF02',[point(2,-100,vx=100),point(4,100,vx=100)])
        with self.assertRaisesRegex(ValueError,'without its own live grant'):
            checks.check_waiting_occupancy([parked_car,other],nav,program['waiting_events'],4)
        moving=trajectory('BF01',[point(2,0),point(4,100)],mode='driving')
        _,parked=checks.check_capacity_parking(program,[moving],nav,catalog,{('BF01','R'):[(0,2)]})
        self.assertFalse(parked)
        with self.assertRaisesRegex(ValueError,'exclusive resource'):
            checks.check_resource_occupancy([moving],catalog,{('BF01','R'):[(0,2)]},nav.homes,parked_bays=parked)

    def test_capacity_home_is_exact_provisional_home_and_releases_old_arrival(self):
        nav=navigation();program={'duration_s':4,'waiting_events':[],'bay_parking_events':[]}
        car=trajectory('BF01',[point(2,1000),point(4,1000)],mode='hold',
                       hold_reason='capacity_home',hold_condition='own_admissible_successor_assignment')
        self.assertEqual(checks.check_capacity_parking(program,[car],nav,{'resources':{}},{})[0]['capacity_hold_episodes'],1)
        program['waiting_events']=[waiting('waiting_granted',0),waiting('waiting_released',3)]
        with self.assertRaisesRegex(ValueError,'retained its old arrival bay'):
            checks.check_capacity_parking(program,[car],nav,{'resources':{}},{})
        program['waiting_events']=[];car.episodes[0]['points'][0]['pose_mm_rad'][0]+=1
        with self.assertRaisesRegex(ValueError,'exact own source home'):
            checks.check_capacity_parking(program,[car],nav,{'resources':{}},{})


if __name__=='__main__':unittest.main()
