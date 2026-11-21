"""Conditional fixed-home maps preserve anonymous scans and unknown obstacles."""
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

import building_fleet_depot as depot
import building_fleet_model as model
from building_fleet_control import Controller
from building_fleet_motion import Path as MotionPath
from building_fleet_sim import SensorWorld


class DepotTests(unittest.TestCase):
    def setUp(self):
        self.homes={'BF01':{'level':'EG','area':'D','pose_mm_rad':[0,0,math.pi/2]},
                    'BF02':{'level':'EG','area':'D','pose_mm_rad':[500,0,math.pi/2]}}
        self.envelope={'length_mm':512,'width_mm':412}
        self.aliases={('EG','D'):'R'}

    def test_only_fixed_surfaces_under_an_own_grant_are_matched(self):
        mapped=depot.FixedHomeMap('BF01',self.homes,self.envelope,self.aliases,25)
        # Own heading +Y makes the nearest adjacent rectangle side local -294.
        self.assertFalse(mapped.matches([0,0,math.pi/2],[-294,0]))
        mapped.set_own_grant({'status':'granted','resource':'R'})
        self.assertTrue(mapped.matches([0,0,math.pi/2],[-294,0]))
        self.assertFalse(mapped.matches([0,0,math.pi/2],[-500,0]))
        self.assertFalse(mapped.matches([0,0,math.pi/2],[-250,0]))
        self.assertFalse(mapped.matches([0,0,math.pi/2],[0,0]))
        with self.assertRaises(ValueError):mapped.set_own_grant({'status':'granted','resource':'R','peer_positions':[]})
        mapped.set_own_grant({'status':'waiting','resource':'R'})
        self.assertFalse(mapped.matches([0,0,math.pi/2],[-294,0]))

    def test_nonowner_must_remain_at_exact_home_and_zero_pva(self):
        states={key:{'level':'EG','pose_mm':home['pose_mm_rad'][:],'footprint_mm':[512,412],
            'velocity_mm_rad_s':[0,0,0],'acceleration_mm_rad_s2':[0,0,0]}for key,home in self.homes.items()}
        polygons={('EG','D'):[[-1000,-1000],[2000,-1000],[2000,2000],[-1000,2000]]}
        self.assertEqual(depot.check_invariant(states,self.homes,polygons,self.aliases,{},85),2)
        states['BF01']['velocity_mm_rad_s']=[0,1,0]
        with self.assertRaises(RuntimeError):depot.check_invariant(states,self.homes,polygons,self.aliases,{},85)
        depot.check_invariant(states,self.homes,polygons,self.aliases,{'R':'BF01'},85)
        states['BF02']['pose_mm'][1]+=.1
        with self.assertRaises(RuntimeError):depot.check_invariant(states,self.homes,polygons,self.aliases,{'R':'BF01'},85)

    def test_all_other_homes_are_checked_between_curve_nodes(self):
        f=depot.floor.F
        curve=depot.floor.motion.Curve([
            {'time_s':0,f[0]:[0,0,math.pi/2],f[1]:[0,300,0],f[2]:[0,0,0]},
            {'time_s':1,f[0]:[0,300,math.pi/2],f[1]:[0,300,0],f[2]:[0,0,0]}])
        proof=depot.fixed_home_curve_proof(curve,'BF01',self.homes,self.envelope,85,'EG')
        self.assertTrue(proof['passed']);self.assertGreater(proof['refinements'],0)
        self.assertGreaterEqual(proof['minimum_distance_lower_bound_mm'],85-1e-6)
        self.homes['BF02']['pose_mm_rad'][0]-=4
        with self.assertRaises(RuntimeError):depot.fixed_home_curve_proof(curve,'BF01',self.homes,self.envelope,85,'EG')

    def test_actual_anonymous_neighbour_scan_launches_only_with_fixed_surface_grant(self):
        source=model.load();sensor=model.resolved_sensor(source)
        world=SensorWorld(sensor,{'EG':[]})
        states={key:{'level':'EG','z_mm':0,'pose_mm':home['pose_mm_rad'][:],'footprint_mm':[512,412]}
                for key,home in self.homes.items()}
        scan=world.scan('BF01',states,0,{'doors_open':False,'level':'KG','z_mm':-4000})
        mapped=depot.FixedHomeMap('BF01',self.homes,self.envelope,self.aliases,25)
        car=Controller(MotionPath([[0,0],[0,3000]]),source,static_return=mapped.matches)
        blocked=car.decide(0,scan)
        self.assertEqual(blocked['reason'],'local_obstacle')
        mapped.set_own_grant({'status':'granted','resource':'R'})
        clear=car.decide(0,scan)
        self.assertGreater(clear['observed_gap_mm'],clear['required_gap_mm'])
        unknown={'captured_s':0,'returns_local_mm':scan['returns_local_mm']+[[0,700]]}
        blocked=car.decide(0,unknown)
        self.assertEqual(blocked['reason'],'local_obstacle')


if __name__=='__main__':unittest.main()
