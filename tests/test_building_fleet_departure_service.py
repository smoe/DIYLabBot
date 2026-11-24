"""Service-level reservation and fairness checks for live depot departures."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_departure_service import DepartureResourceServices


class DepartureServiceTests(unittest.TestCase):
    def test_departure_nomination_is_bound_to_the_active_holder_and_existing_request(self):
        service=DepartureResourceServices({'room':'room','bay':'room','door':'passage'})
        for resource,vehicles in [('room',('A','B','C')),('bay',('D','E'))]:
            for i, vehicle in enumerate(vehicles):
                service.request(vehicle,resource,i)
        self.assertFalse(service.reserve_departure_successor('B','room','A',2))
        service.enable_depot_departures(['room'])
        with self.assertRaises(ValueError):service.enable_depot_departures(['bay'])
        with self.assertRaises(ValueError):service.enable_depot_departures(['door'])
        for vehicle,resource,leader,now in [('B','room','C',2),('D','room','A',2),
                                           ('E','bay','D',2),('B','room','A',0),('A','room','A',2)]:
            self.assertFalse(service.reserve_departure_successor(vehicle,resource,leader,now))
        self.assertTrue(service.reserve_departure_successor('C','room','A',2))
        self.assertTrue(service.reserve_departure_successor('C','room','A',3))
        self.assertFalse(service.reserve_departure_successor('B','room','A',3))
        self.assertEqual(dict(service.departure_successors),{'room':'C'})
        with self.assertRaises(TypeError):service.departure_successors['room']='B'
        self.assertEqual(service.request('C','room',3),{'status':'waiting','resource':'room'})
        self.assertEqual(service.queues['room'],['B','C'])
        with self.assertRaises(ValueError):service.release('C','room',3)
        self.assertEqual(service.owners,{'room':'A','bay':'D'})
        self.assertEqual([e['vehicle_id'] for e in service.events],['A','D'])

    def test_one_promoted_turn_preserves_fifo_waiters_and_mission_bookings(self):
        service=DepartureResourceServices({'room':'room'},{'EG':[[0,0,0]],'KG':[[0,0,0]]})
        service.enable_depot_departures(['room'])
        service.book_mission('D','mission-D','EG','KG',0)
        booking=service.own_waiting_grants('D')
        for i,vehicle in enumerate('ABCDE'):
            service.request(vehicle,'room',i)
        self.assertTrue(service.reserve_departure_successor('D','room','A',4))
        service.release('A','room',5)
        self.assertEqual(service.queues['room'],list('BCE'))
        self.assertEqual(service.departure_successors,{})
        self.assertEqual(service.own_grants('D'),{'status':'granted','resource':'room'})
        self.assertEqual(service.own_waiting_grants('D'),booking)
        self.assertFalse(service.reserve_departure_successor('E','room','D',6))
        service.release('D','room',7)
        self.assertEqual(service.queues['room'],list('CE'))
        self.assertTrue(service.reserve_departure_successor('E','room','B',8))
        service.release('B','room',9)
        service.release('E','room',10)
        self.assertEqual(service.owners,{'room':'C'})
        self.assertEqual([e['vehicle_id'] for e in service.events],list('ADBEC'))
        self.assertEqual([e['wait_s'] for e in service.events],[0,2,6,5,8])
        self.assertEqual(service.own_waiting_grants('D'),booking)


if __name__ == "__main__":
    unittest.main()
