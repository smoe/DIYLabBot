"""Own-state/controller timing regressions; no world state is passed to a car."""
import copy
import bisect
import random
from types import MethodType
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_control as control
import building_fleet_model as model
import building_fleet_motion as motion
F=control.F


def reference_project_ahead(car,point,lookahead_mm=None,maximum_lateral_mm=None):
    """Preserved original arithmetic/order; the new lateral hint is ignored."""
    end=car.goal if lookahead_mm is None else min(car.goal,car.y+lookahead_mm)
    best=(math.inf,car.y);samples=car.path.samples
    ends=[row[1]for row in samples];first=max(0,bisect.bisect_left(ends,car.y)-1)
    for a,b,pa,pb in samples[first:]:
        if a>end+1e-9:break
        if b<car.y-1e-9:continue
        left=max(a,car.y);right=min(b,end)
        if right<left:continue
        p=car.path.evaluate(left)[0][:2];q=car.path.evaluate(right)[0][:2]
        delta=[q[k]-p[k]for k in range(2)];norm=sum(v*v for v in delta)
        u=max(0.,min(1.,sum((point[k]-p[k])*delta[k]for k in range(2))/norm))if norm else 0.
        distance=math.hypot(*(point[k]-p[k]-u*delta[k]for k in range(2)))
        if distance<best[0]:best=distance,left+u*(right-left)
    return best


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=model.load()

    def controller(self,path=None,**kwargs):
        return control.Controller(path or motion.Path([[0,0],[6000,0]]),self.source,**kwargs)

    def test_positive_speed_plan_end_advances_leftover_time(self):
        c=self.controller();c.y=100.;c.v=300.;c.a=0
        # End at 23 ms inside a 50 ms integration tick, then keep cruising.
        curve=control.floor.motion.Curve([control.local.point(0,0,300,0),control.local.point(.023,6.9,300,0)])
        c.set_plan(curve,0,'driving','speed_change');c.advance(0,.05)
        self.assertAlmostEqual(c.y,115.,places=8)
        self.assertAlmostEqual(c.v,300.,places=8)
        self.assertEqual(c.mode,'driving')
        self.assertIsNone(c.plan)
        records=c.recorded[1:]
        self.assertTrue(all(b['pose_mm_rad'][0]>a['pose_mm_rad'][0]for a,b in zip(records,records[1:])))
        c.advance(.05,.1)
        self.assertAlmostEqual(c.y,130.,places=8)

    def test_missing_scan_and_stale_scan_do_not_launch(self):
        c=self.controller();c.decide(0,None);c.advance(0,.05)
        self.assertEqual(c.y,0)
        self.assertEqual(c.mode,'waiting')
        c.decide(.05,{'captured_s':0.,'returns_local_mm':[]})
        for tick in range(1,20):
            start=tick*.05;c.advance(start,start+.05);c.decide(start+.05,None)
        self.assertEqual(c.y,0)
        self.assertEqual(c.mode,'waiting')
        self.assertEqual(c.reason,'scan_missing_or_stale')

    def test_peer_identifiers_and_world_poses_are_rejected(self):
        for extra in ['vehicle_id','peer_positions','world_pose']:
            c=self.controller();scan={'captured_s':0.,'returns_local_mm':[],extra:'forbidden'}
            with self.assertRaises(ValueError):c.decide(0,scan)

    def test_own_capture_pose_is_used_for_static_map_matching(self):
        used=[];c=self.controller(static_return=lambda pose,ray:used.append((pose,ray))or True)
        c.recorded=[{'time_s':0.,'pose_mm_rad':[100,200,math.pi/2],
                     'velocity_mm_rad_s':[0,0,0],'acceleration_mm_rad_s2':[0,0,0]},
                    {'time_s':.1,'pose_mm_rad':[100,250,math.pi/2],
                     'velocity_mm_rad_s':[0,0,0],'acceleration_mm_rad_s2':[0,0,0]}]
        c.record_times=[0.,.1];c.now=.1
        c._observed_gap({'captured_s':0.,'returns_local_mm':[[0,100]]},.1)
        self.assertEqual(used[0][0],[100,200,math.pi/2])
        with self.assertRaises(ValueError):c.own_pose_at(.2)
    def run_controller(self,c,obstacle=None,maximum_s=120):
        for tick in range(round(maximum_s/.05)+1):
            now=round(tick*.05,3);scan=None
            if tick%2==0 and now>=.1:
                captured=round(now-.1,3);pose=c.own_pose_at(captured);rays=[]
                world=obstacle(captured)if obstacle else None
                if world is not None:
                    dx,dy=world[0]-pose[0],world[1]-pose[1]
                    if math.hypot(dx,dy)<=c.settings['range_mm']:
                        rays=[[-math.sin(pose[2])*dx+math.cos(pose[2])*dy,
                               math.cos(pose[2])*dx+math.sin(pose[2])*dy]]
                scan={'captured_s':captured,'returns_local_mm':rays}
            c.decide(now,scan)
            if c.mode=='arrived':return c
            c.advance(now,round(now+.05,3))
        self.fail('Own bounded mission failed to finish')

    def assert_bounded_recording(self,c):
        curve=control.floor.motion.Curve(control.floor.canonical(c.recorded))
        actual=motion.episode_dynamics(curve,c.radius)
        for kind,limits in [('linear',c.limits),('angular',c.angular)]:
            for key,value in actual[kind].items():self.assertLessEqual(value,limits[key]*(1+1e-6),(kind,key,value))
        self.assertTrue(all(abs(p['time_s']*1000-round(p['time_s']*1000))<1e-8 for p in c.recorded))
        # Rest observations are explicit functional/protective holds. Apply the
        # shared no-stop criterion only to each uninterrupted moving episode.
        episodes=[];current=[]
        for a,b in zip(c.recorded,c.recorded[1:]):
            moving=any(abs(v)>1e-8 for p in(a,b)for v in p['velocity_mm_rad_s'][:2])or math.dist(a['pose_mm_rad'][:2],b['pose_mm_rad'][:2])>1e-9
            if moving:
                if not current:current=[a]
                current.append(b)
            elif current:episodes.append(current);current=[]
        if current:episodes.append(current)
        for points in episodes:
            result=control.floor.no_stop(control.floor.motion.Curve(control.floor.canonical(points)))
            self.assertTrue(result['passed'],result)
        return actual

    def test_corner_uses_checked_nominal_clock_without_waypoint_stop(self):
        c=self.controller(motion.Path([[0,0],[3000,0],[3000,3000]]),zone_caps=[(0,300)])
        self.run_controller(c)
        actual=self.assert_bounded_recording(c)
        self.assertEqual(c.mode,'arrived');self.assertEqual(c.stops,0)
        self.assertLessEqual(actual['linear']['velocity'],300*(1+1e-6))
        self.assertTrue(c.nominal_clock_proof['dynamics']['angular']['jerk']<=c.angular['jerk'])

    def test_obstacle_bounded_braking_fresh_free_and_resume(self):
        c=self.controller(zone_caps=[(0,300)])
        self.run_controller(c,lambda time:[2500,0]if time<8 else None)
        self.assert_bounded_recording(c)
        stops=[e for e in c.events if e['event']=='protective_stop']
        resumed=[e for e in c.events if e['event']=='resumed']
        self.assertTrue(stops);self.assertGreaterEqual(len(resumed),2)
        self.assertGreaterEqual(resumed[-1]['time_s'],8+c.settings['latency_s']+c.settings['clear_observation_s']-1e-8)
        self.assertTrue(all(e['clear_observation_s']>=c.settings['clear_observation_s']-1e-8 for e in resumed))
        stopped=[p for p in c.recorded if p.get('hold_reason')=='local_obstacle'and math.hypot(*p['velocity_mm_rad_s'][:2])<1e-8]
        self.assertTrue(stopped)
        self.assertLess(stopped[0]['pose_mm_rad'][0]+c.radius+c.settings['clearance_mm'],2500)

    def test_future_projection_does_not_choose_a_nearer_past_loop_branch(self):
        path=motion.Path([[0,0],[3000,0],[3000,1000],[0,1000]],trim_mm=10)
        c=self.controller(path);c.y=path.ends[-2]+200
        world=[1000,100]
        self.assertLess(path.project(world)[1],c.y)
        self.assertGreater(c.project_ahead(world)[1],c.y)

    def test_waiting_clearance_uses_launch_cap_and_opposing_cap(self):
        c=self.controller(zone_caps=[(0,300)])
        result=c.decide(0,{'captured_s':0.,'returns_local_mm':[]})
        reaction=c.settings['period_s']+c.settings['latency_s']+c.settings['stale_after_s']
        # Any stop from 300 needs at least v/A seconds and v²/(2A) distance,
        # even before the jerk restriction. The opposing vehicle may use its
        # zone cap despite this car still being at rest.
        expected=c.settings['clearance_mm']+300**2/(2*c.limits['acceleration'])+600*reaction+300*(300/c.limits['acceleration'])
        self.assertGreaterEqual(result['required_gap_mm'],expected-1e-8)
        self.assertEqual(c.v,0)

    def test_stale_peer_metadata_and_nonfinite_vectors_are_rejected(self):
        c=self.controller()
        with self.assertRaises(ValueError):c._observed_gap({'captured_s':0.,'returns_local_mm':[],'vehicle_id':'foreign'},1.)
        with self.assertRaises(ValueError):c.decide(0,{'captured_s':0.,'returns_local_mm':[[0,float('nan')]]})
        self.assertIsNone(c.last_scan)

    def test_parallel_box_surface_is_not_a_disc_false_positive(self):
        c=self.controller()
        empty,_=c._observed_gap({'captured_s':0.,'returns_local_mm':[]},0.)
        parallel,_=c._observed_gap({'captured_s':0.,'returns_local_mm':[[394.,1000.]]},0.)
        front,_=c._observed_gap({'captured_s':0.,'returns_local_mm':[[0.,1000.]]},0.)
        self.assertEqual(parallel,empty)
        self.assertLess(front,parallel)

    def test_unwrapped_initial_heading_is_equivalent_and_requires_rest(self):
        c=self.controller();c.align_initial_heading(2*math.pi)
        self.assertAlmostEqual(c.pose()[2],2*math.pi)
        self.assertAlmostEqual(c.recorded[0]['pose_mm_rad'][2],2*math.pi)
        with self.assertRaises(ValueError):c.align_initial_heading(math.pi/2)
        c.v=1.
        with self.assertRaises(ValueError):c.align_initial_heading(2*math.pi)

    def test_supplied_clock_origin_rest_dimensions_and_foreign_fields_fail_closed(self):
        path=motion.Path([[0,0],[6000,0]])
        program=motion.compile_motion(path,self.source)
        changed=copy.deepcopy(program);changed['scalar_clock'][0][F[0]][0]=1.
        with self.assertRaises(ValueError):self.controller(path,motion_program=changed)
        changed=copy.deepcopy(program);changed['scalar_clock'][-1][F[1]][0]=1.
        with self.assertRaises(ValueError):self.controller(path,motion_program=changed)
        changed=copy.deepcopy(program)
        for point in changed['scalar_clock']:
            for field in F[:3]:point[field].append(0.)
        with self.assertRaises(ValueError):self.controller(path,motion_program=changed)
        changed=copy.deepcopy(program);changed['peer_positions']=[[1,2]]
        with self.assertRaises(ValueError):self.controller(path,motion_program=changed)

    def test_pose_preserves_current_unwrapped_winding_after_a_loop(self):
        c=control.Controller.__new__(control.Controller)
        c.path=motion.Path([[0,0],[2000,0],[2000,2000],[0,2000],[0,0],[2000,0]])
        c.y=c.path.length;c.heading_offset=0.
        c.recorded=[{'pose_mm_rad':[1999,0,2*math.pi-.001]}]
        self.assertAlmostEqual(c.pose()[2],2*math.pi)

    def test_projection_matches_original_random_loops_reverse_and_clipped_boundaries(self):
        rng=random.Random(20261121)
        routes=[[[0,0],[3000,0]],[[0,0],[1500,0],[1500,1500],[0,1500],[0,0],[1000,0]],
                [[1e9,-1e9],[1e9+2000,-1e9],[1e9+2000,-1e9+1500],[1e9,-1e9+1500]]]
        for route in routes:
            path=motion.Path(route,trim_mm=75);car=control.Controller.__new__(control.Controller)
            car.path=path;car.goal=path.length
            edge=path.samples[len(path.samples)//2][0]
            progresses=[0.,path.length*.21,edge,math.nextafter(edge,-math.inf),math.nextafter(edge,math.inf),path.length]
            for progress in progresses:
                car.y=progress;car.heading_offset=math.pi if rng.random()<.5 else 0.
                xy=path.evaluate(progress)[0][:2]
                points=[[xy[0]+rng.uniform(-2500,2500),xy[1]+rng.uniform(-2500,2500)]for _ in range(8)]
                points.extend([path.samples[0][2],path.samples[-1][3],xy,
                    [math.nextafter(xy[0],math.inf),math.nextafter(xy[1],-math.inf)]])
                for lookahead in(None,0.,19.125,800.,1e7):
                    for point in points:
                        expected=reference_project_ahead(car,point,lookahead)
                        self.assertEqual(car.project_ahead(point,lookahead),expected,(route,progress,lookahead,point))
                        limited=car.project_ahead(point,lookahead,400.)
                        self.assertEqual(limited,expected if expected[0]<=400 else(math.inf,progress))

    def test_projection_reuses_full_samples_and_only_evaluates_clipped_endpoints(self):
        path=motion.Path([[0,0],[3000,0],[3000,2000]],trim_mm=125)
        car=control.Controller.__new__(control.Controller);car.path=path;car.goal=path.length;car.y=123.456
        original=path.evaluate;calls=[]
        def counted(value):calls.append(value);return original(value)
        path.evaluate=counted
        for i in range(180):car.project_ahead([i*10.,1000.],2200.)
        self.assertEqual(len(calls),2,'Only the two window-clipped endpoints need Path.evaluate')
        car.y+=.001;car.project_ahead([1,1000],2200.)
        self.assertEqual(len(calls),4,'Own progress invalidates the exact future-window cache')
        with self.assertRaises(ValueError):car.project_ahead([0,0],2200.,float('nan'))

    def test_projection_keeps_observed_gaps_and_actual_decisions_identical(self):
        car=self.controller(zone_caps=[(0,300)]);legacy=copy.deepcopy(car)
        legacy.project_ahead=MethodType(reference_project_ahead,legacy)
        for tick in range(60):
            now=round(tick*.05,3);captured=max(0.,round(now-.1,3))
            # An unknown forward return triggers the same bounded stop; later
            # disappearance must retain the same fresh-clear restart clock.
            rays=[[0.,700.]]if .85<=now<1.4 else[]
            scan={'captured_s':captured,'returns_local_mm':rays}
            self.assertEqual(car.decide(now,scan),legacy.decide(now,copy.deepcopy(scan)))
            self.assertEqual(car.advance(now,round(now+.05,3)),legacy.advance(now,round(now+.05,3)))
        self.assertEqual(car.events,legacy.events);self.assertEqual(car.recorded,legacy.recorded)
        # Full beam sets on curved/reversed geometry retain the same observed
        # gap even when the optional lateral broad phase discards far returns.
        car.path=motion.Path([[0,0],[2500,0],[2500,2000],[500,2000]],trim_mm=125)
        car.goal=car.path.length;car.y=car.path.length*.4;car.heading_offset=math.pi
        car.recorded=[{'pose_mm_rad':car.path.evaluate(car.y)[0]}];car.record_times=[0.]
        pose=car.pose();car.own_pose_at=lambda at:pose[:]
        legacy=copy.copy(car);legacy.project_ahead=MethodType(reference_project_ahead,legacy)
        vectors=[[1800*math.sin(math.radians(i)),1800*math.cos(math.radians(i))]for i in range(0,360,2)]
        self.assertEqual(car._observed_gap({'captured_s':0.,'returns_local_mm':vectors},0.),
                         legacy._observed_gap({'captured_s':0.,'returns_local_mm':vectors},0.))

    def test_sensor_range_negative_time_and_reduced_radius_rejected(self):
        c=self.controller()
        with self.assertRaises(ValueError):c._observed_gap({'captured_s':-1.,'returns_local_mm':[]},0.)
        with self.assertRaises(ValueError):c._observed_gap({'captured_s':0.,'returns_local_mm':[[0.,3000.]]},0.)
        with self.assertRaises(ValueError):self.controller(radius_mm=1.)



if __name__=='__main__':unittest.main()
