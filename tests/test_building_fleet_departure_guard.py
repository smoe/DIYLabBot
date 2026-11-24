"""Private departure witnesses, retained home surfaces, and grant boundaries."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_departure_guard import GuardedHomeMap, check_departure_invariant


class DepartureGuardTests(unittest.TestCase):
    def setUp(self):
        self.homes = {key:{'level':'EG','area':area,'pose_mm_rad':[x,0,math.pi/2]}
                      for key,x,area in [('A',0,'south'),('B',500,'south'),('C',8000,'north'),('D',8500,'north')]}
        self.aliases = {('EG','south'):'R',('EG','north'):'R'}
        self.rooms = {('EG',area):[(lo,-1000),(hi,-1000),(hi,3000),(lo,3000)]
                      for area,lo,hi in [('south',-1000,2000),('north',7000,10000)]}
        self.ticket = {'vehicle':'A','leader':'C','level':'EG','area':'south','resource':'R',
                       'start_xy':[0,0],'end_xy':[0,2100],'start_yaw':math.pi/2}
        self.states = {key:{'level':'EG','pose_mm':home['pose_mm_rad'][:],'footprint_mm':[512,412],
                             'velocity_mm_rad_s':[0,0,0],'acceleration_mm_rad_s2':[0,0,0]}
                       for key,home in self.homes.items()}
        self.states['A']['pose_mm'][1] = 300
        self.states['A']['velocity_mm_rad_s'][1] = 120

    def test_private_match_uses_only_occupied_own_room_surfaces_and_waiting_token(self):
        m=GuardedHomeMap('A',self.homes,{'length_mm':512,'width_mm':412},self.aliases,25)
        pose=self.homes['A']['pose_mm_rad']
        near,other=[-294,0],[-8294,0]
        m.select_occupied_homes({'C'},'south')
        self.assertFalse(m.matches(pose,near))
        m.set_own_grant({'status':'waiting','resource':'different'})
        self.assertFalse(m.matches(pose,near))
        m.set_own_grant({'status':'waiting','resource':'R'})
        self.assertTrue(m.matches(pose,near))
        self.assertFalse(m.matches(pose,other))
        with self.assertRaises(ValueError):m.select_occupied_homes({'C'},'north')
        with self.assertRaises(ValueError):m.select_occupied_homes({'unknown'},'south')
        index=m.indexes
        m.select_occupied_homes(['C'],('EG','south'))
        self.assertIs(index,m.indexes)
        m.select_occupied_homes({'B','C'},'south')
        self.assertFalse(m.matches(pose,near))
        m.select_occupied_homes({'C'})
        self.assertFalse(m.matches(pose,near))
        m.set_own_grant({'status':'granted','resource':'R'})
        self.assertTrue(m.matches(pose,near))
        self.assertTrue(m.matches(pose,other))
        self.assertFalse(m.matches(pose,[-7794,0]))  # Vacated or quarantined C surface.
        with self.assertRaises(ValueError):m.set_own_grant({'status':'granted','resource':'R','peers':[]})

    def check(self,ticket,owner='C'):
        return check_departure_invariant(self.states,self.homes,self.rooms,self.aliases,{'R':owner},85,ticket)

    def test_only_the_designated_successor_can_move_on_its_straight(self):
        self.assertEqual(self.check(self.ticket),4)
        with self.assertRaises(RuntimeError):self.check(None)
        with self.assertRaises(RuntimeError):self.check(self.ticket,owner='D')
        self.states['B']['velocity_mm_rad_s'][1] = 1
        with self.assertRaises(RuntimeError):self.check(self.ticket)

    def test_wrong_fence_position_heading_derivatives_and_boundary_fail_closed(self):
        for field,value in [('vehicle','C'),('leader','D'),('area','north'),('resource','other'),
                            ('level','KG'),('start_xy',[0,200]),('end_xy',[0,100]),('start_yaw',1.2)]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.check({**self.ticket,field:value})
        for field,value in [('pose_mm',[5,300,math.pi/2]),('pose_mm',[0,300,1.2]),
                            ('velocity_mm_rad_s',[0,-10,0]),('acceleration_mm_rad_s2',[3,0,0]),
                            ('velocity_mm_rad_s',[0,10,.1]),('pose_mm',[0,float('nan'),math.pi/2]),
                            ('level','OG1'),('aboard',True)]:
            original=copy.deepcopy(self.states['A'])
            self.states['A'][field]=value
            with self.subTest(field=field,value=value), self.assertRaises(RuntimeError):self.check(self.ticket)
            self.states['A']=original
        self.states['A']['pose_mm'][1]=2700  # 44 mm body-to-wall, below the 85 mm reserve.
        with self.assertRaises(RuntimeError):self.check({**self.ticket,'end_xy':[0,2800]})


if __name__ == '__main__':
    unittest.main()
