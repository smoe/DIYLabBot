from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_dispatch import Dispatcher
import building_fleet_model as model


class DispatchTests(unittest.TestCase):
    def make(self, seed=None):
        s = model.load()
        if seed is not None:
            s['missions']['seed'] = seed
        return Dispatcher(s, {'BF'+str(i).zfill(2): {'level':'EG','area':'R0_004','slot':i}
                              for i in range(1,21)})

    def run_sequence(self, seed=None):
        d = self.make(seed)
        jobs = [d.assign('BF'+str(i).zfill(2), 'EG', 0) for i in range(1,21)]
        for j in jobs:
            d.acknowledge(j['vehicle_id'], j['mission_id'])
            self.assertTrue(d.receive_completion(j['vehicle_id'], j['mission_id']))
            self.assertFalse(d.receive_completion(j['vehicle_id'], j['mission_id']))
        self.assertTrue(all(row['visits'] >= 1 for row in d.coverage()))
        self.assertEqual(d.assign('BF01','KG',600)['goal']['kind'], 'home')
        return jobs

    def test_deterministic_coverage_without_truth(self):
        self.assertEqual(self.run_sequence(), self.run_sequence())
        self.assertNotEqual(self.run_sequence(1), self.run_sequence(2))

    def test_full_lift_waiting_uses_same_floor(self):
        d = self.make()
        for _ in range(20):
            self.assertEqual(d.assign('BF01','OG1',0,False)['goal']['level'], 'OG1')
        with self.assertRaises(RuntimeError):
            d.assign('BF01','EG',7201)

    def test_only_acknowledged_own_jobs_count(self):
        d = self.make()
        job = d.assign('BF01','EG',0)
        with self.assertRaises(ValueError):
            d.receive_completion('BF01',job['mission_id'])
        with self.assertRaises(ValueError):
            d.acknowledge('BF02',job['mission_id'])
        self.assertFalse(any(row['visits'] for row in d.coverage()))

if __name__ == '__main__':unittest.main()
