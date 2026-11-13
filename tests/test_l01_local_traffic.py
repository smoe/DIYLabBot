import copy,math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import l01_local_traffic as traffic

class LocalTraffic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=traffic.simulate()
    def test_three_finish_with_interval_clearance_and_native_pose_coverage(self):
        r=self.result;self.assertTrue(r['all_arrived']);self.assertFalse(r['shared_positions']);self.assertTrue(r['native_pose_coverage']['passed'])
        self.assertGreater(r['clearance']['car_person_clearance_lower_mm'],75);self.assertGreater(r['clearance']['car_car_clearance_lower_mm'],75)
        self.assertTrue(any(all(v['velocity_mm_s']>10 for v in f['vehicles']) for f in r['frames']))
        self.assertTrue(all(t['stops_for_observation']>=1 for t in r['trajectories']))
        for trajectory in r['trajectories']:
            self.assertLessEqual(trajectory['dynamics']['velocity'],200)
            self.assertLessEqual(trajectory['dynamics']['acceleration'],100)
            self.assertLessEqual(trajectory['dynamics']['jerk'],200)
        for frame in r['frames']:
            for v in frame['vehicles']:
                self.assertGreaterEqual(v['y_mm'],1200);self.assertLessEqual(v['y_mm'],5250)
    def test_first_return_hides_farther_vehicle_and_has_no_identity(self):
        settings=self.result['settings']['sensor'];world=traffic.SensorWorld(settings,0,[])
        scan=world.scan(0,[(0,800,100),(0,1500,100)],0)
        self.assertEqual(set(scan),{'captured_s','returns_local_mm'})
        self.assertAlmostEqual(scan['returns_local_mm'][0][1],700)
        self.assertTrue(all(p[1]<900 for p in scan['returns_local_mm']))
        self.assertEqual(scan,world.scan(0,[(0,1500,100),(0,800,100)],0))
    def test_scan_dropout_brakes_and_preserves_separation(self):
        r=traffic.simulate(dropout=(2,10))
        self.assertTrue(r['all_arrived'])
        self.assertTrue(any(v['mode']=='braking' and v['reason']=='scan_missing_or_stale' for f in r['frames'] for v in f['vehicles']))
        self.assertTrue(any(4<f['time_s']<9 and all(abs(v['velocity_mm_s'])<1e-6 for v in f['vehicles']) for f in r['frames']))
        self.assertGreater(r['clearance']['car_person_clearance_lower_mm'],0)
    def test_opposing_local_controllers_stop_without_priority_exchange(self):
        s,m=traffic.load();cfg={**s['sensor'],**s['controller'],'desired_speed_mm_s':s['desired_speed_mm_s']}
        limits={k:v*.98 for k,v in m['limits']['linear'].items()};radius=self.result['radius_mm']
        a=traffic.LocalController(0,10000,cfg,limits,radius);b=traffic.LocalController(0,10000,cfg,limits,radius)
        world=traffic.SensorWorld(s['sensor'],0,[]);pending=[[],[]];minimum=math.inf;step=.05
        for tick in range(401):
            now=tick*step;centres=[a.y,2400-b.y]
            if tick%2==0:
                sa=world.scan(centres[0],[(0,centres[1],radius)],now)
                sb=world.scan(centres[1],[(0,centres[0],radius)],now);sb['returns_local_mm']=[[-x,-y] for x,y in sb['returns_local_mm']]
                for queue,scan in zip(pending,[sa,sb]):queue.append((now+.1,scan))
            for controller,queue in zip([a,b],pending):
                scan=None
                while queue and queue[0][0]<=now+1e-9:scan=queue.pop(0)[1]
                controller.decide(now,scan)
            minimum=min(minimum,centres[1]-centres[0]-2*radius)
            a.advance(now,now+step);b.advance(now,now+step)
        self.assertGreater(minimum,75);self.assertAlmostEqual(a.v,0,places=5);self.assertAlmostEqual(b.v,0,places=5)
        self.assertNotEqual(a.mode,'arrived');self.assertNotEqual(b.mode,'arrived')
if __name__=='__main__':unittest.main()
