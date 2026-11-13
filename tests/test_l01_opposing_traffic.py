import copy,json,math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import l01_opposing_traffic as traffic

class OpposingTraffic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=traffic.simulate();cls.source,cls.base,cls.motion=traffic.load()
    def test_distinct_station_missions_complete_and_head_on_is_resolved_locally(self):
        r=self.result;self.assertTrue(r['all_arrived']);self.assertFalse(r['shared_positions']);self.assertEqual({t['station'] for t in r['trajectories']},{'DNA','CF01','QC'})
        events=[e for t in r['trajectories'] for e in t['events']];self.assertEqual(len(events),1);self.assertEqual(events[0]['vehicle'],'TR02');self.assertFalse(events[0]['peer_data_used'])
        curves=[traffic.floor.motion.Curve([{'time_s':p[0],traffic.F[0]:p[1],traffic.F[1]:p[2],traffic.F[2]:p[3]} for p in t['points']]) for t in r['trajectories']]
        encounter=events[0]['time_s']/2
        self.assertGreater(curves[0].evaluate(encounter)[traffic.F[1]][1],0)
        self.assertLess(curves[1].evaluate(encounter)[traffic.F[1]][1],0)
        self.assertTrue(any(all(v['velocity_mm_s']>.5 for v in frame['vehicles']) for frame in r['frames']))
        for t in r['trajectories']:
            xy=self.motion['stations'][t['station']]['park_xy_mm'];self.assertLess(math.dist(t['points'][-1][1][:2],xy),1e-6)
    def test_occupied_bench_and_moving_obstacle_clearance_with_polynomial_limits(self):
        r=self.result;self.assertGreater(r['clearance']['bench_clearance_lower_mm'],0)
        for k in ('car_car_clearance_lower_mm','car_person_clearance_lower_mm'):self.assertGreater(r['clearance'][k],75)
        for t in r['trajectories']:
            for category in ('linear','angular','carried_points'):
                for name,value in t['dynamics'][category].items():self.assertLessEqual(value,self.motion['limits'][category][name])
    def test_rear_obstruction_and_stale_scan_do_not_authorize_retreat(self):
        s,base,motion=self.source,self.base,self.motion;path=traffic.RingPath(motion);cfg={**base['sensor'],**base['controller'],'desired_speed_mm_s':base['desired_speed_mm_s']};limits={k:v*.98 for k,v in motion['limits']['linear'].items()};radius=self.result['radius_mm'];c=traffic.MissionController({'id':'Test','from':'DNA','to':'QC','initial_direction':-1},path,motion,cfg,limits,radius,s['encounter_rule']);world=traffic.RangeWorld(base['sensor'],[]);start=c.progress
        for tick in range(61):
            now=tick*.05;discs=[(path.lanes['left'],1900,radius),(path.lanes['left'],3500,radius)];raw=world.scan(c.pose(),discs,now);c.decide(now,c.observe(raw,c.progress));c.advance(now,now+.05)
        self.assertEqual(len(c.events),1);self.assertEqual(c.direction,1);self.assertAlmostEqual(c.progress,start)
        for tick in range(61,81):c.decide(tick*.05,None);c.advance(tick*.05,(tick+1)*.05)
        self.assertAlmostEqual(c.progress,start);self.assertEqual(c.driver.reason,'scan_missing_or_stale')
        for tick in range(81,121):
            now=tick*.05;raw=world.scan(c.pose(),[(path.lanes['left'],1900,radius)],now);c.decide(now,c.observe(raw,c.progress));c.advance(now,now+.05)
        self.assertGreater(c.progress,start+1)
    def test_no_unplanned_interior_stop_after_export(self):
        for trajectory in self.result['trajectories']:
            points=[{'time_s':p[0],traffic.F[0]:p[1],traffic.F[1]:p[2],traffic.F[2]:p[3]} for p in trajectory['points']]
            curve=traffic.floor.motion.Curve(points);check=traffic.floor.no_stop(curve)
            unexpected=[failure for failure in check['failures'] if 'u' in failure and 1e-7<failure['u']<1-1e-7]
            self.assertEqual(unexpected,[],trajectory['id'])
            # Constant intervals are the controller's explicit observation/goal holds.
            # Curved transit knots have positive speed instead of an imposed pause.
            for p in points:
                if abs(p[traffic.F[1]][2])>1e-6:self.assertGreater(math.hypot(*p[traffic.F[1]][:2]),1e-6)
    def test_native_reference_error_bounds_original_curve(self):
        t=self.result['trajectories'][1];points=[{'time_s':p[0],traffic.F[0]:p[1],traffic.F[1]:p[2],traffic.F[2]:p[3]} for p in t['points']];reduced,bound=traffic.reduced_native_reference(points,self.result['radius_mm']);a=traffic.floor.motion.Curve(points);b=traffic.floor.motion.Curve(reduced)
        self.assertLess(len(reduced),len(points)/10)
        for i in range(101):
            now=a.times[-1]*i/100;p=a.evaluate(now)[traffic.F[0]];q=b.evaluate(now)[traffic.F[0]];error=math.dist(p[:2],q[:2])+self.result['radius_mm']*min(2,abs(p[2]-q[2]));self.assertLessEqual(error,bound)
if __name__=='__main__':unittest.main()
