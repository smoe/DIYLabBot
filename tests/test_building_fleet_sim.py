"""World-only first returns and independent collision interval failures."""
import copy
import json
import math
from pathlib import Path
import sys
import random
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_sim as sim


SETTINGS = {'angular_step_deg':2, 'range_mm':2200, 'period_s':.1, 'latency_s':.1}


def own(x=0,y=0,level='EG',z=0,aboard=False,radius=100):
    return {'pose_mm':[x,y,0], 'level':level, 'z_mm':z, 'aboard':aboard, 'radius_mm':radius}


def original_scan(world,vehicle_id,truth,now,lift):
    """Frozen pre-optimization algorithm, independent of the new raw cache."""
    row=truth[vehicle_id];x,y,yaw=row['pose_mm'];cap=world.settings['range_mm']
    others=[p for key,p in truth.items()if key!=vehicle_id and world.visible(row,p,lift)]
    returns=[]
    step=world.settings['angular_step_deg']
    for index in range(round(360/step)):
        angle=math.radians(index*step);heading=yaw+angle;dx,dy=math.cos(heading),math.sin(heading)
        on_floor=abs(row.get('floor_z_mm',row['z_mm'])-row['z_mm'])<1e-6
        distance=world.static[row['level']].ray((x,y),(dx,dy),cap)if on_floor else cap
        sides=tuple(sorted(lift.get('open_sides',())))if lift['doors_open']else()
        landed=(on_floor and row['level']==lift.get('level')and abs(row['z_mm']-lift.get('z_mm',math.inf))<1e-6)
        landing=world.landings.get((row['level'],sides if landed else()),world.landings.get((row['level'],())))
        if landing is not None and on_floor:distance=min(distance,landing.ray((x,y),(dx,dy),cap))
        cabin=world.cabin.get(sides)
        if cabin is not None and(row.get('aboard',False)or abs(row['z_mm']-lift.get('z_mm',math.inf))<1e-6):
            distance=min(distance,cabin.ray((x,y),(dx,dy),cap))
        for peer in others:
            if 'footprint_mm'in peer:
                cx,cy,heading=peer['pose_mm'];c,s=math.cos(heading),math.sin(heading);length,width=peer['footprint_mm']
                ox,oy=(x-cx)*c+(y-cy)*s,-(x-cx)*s+(y-cy)*c
                rx,ry=dx*c+dy*s,-dx*s+dy*c
                measured=sim.ray_box(ox,oy,rx,ry,[-length/2,-width/2,length/2,width/2])
            else:measured=sim.ray_disc(x,y,dx,dy,*peer['pose_mm'][:2],peer['radius_mm'])
            distance=min(distance,measured)
        if distance<cap:returns.append([math.sin(angle)*distance,math.cos(angle)*distance])
    return {'captured_s':now,'returns_local_mm':returns}


class ExactScanTests(unittest.TestCase):
    def assert_scan(self,world,truth,now,lift):
        actual=world.scan('BF01',truth,now,lift);expected=original_scan(world,'BF01',truth,now,lift)
        self.assertEqual(json.dumps(actual,separators=(',',':')),json.dumps(expected,separators=(',',':')))
        return actual

    def test_random_full_scans_match_original_with_occlusion_and_lift_visibility(self):
        rng=random.Random(224817)
        world=sim.SensorWorld(SETTINGS,{'EG':[((500,-700),(500,700))],'OG1':[((-600,-600),(-600,600))]},
            cabin_segments_by_sides={():[((1200,-900),(1200,900))],('inward',):[],('outward',):[((-1100,-900),(-1100,900))]},
            landing_segments_by_level_sides={(level,sides):([((700,-800),(700,800))]if not sides else[])
                for level in('EG','OG1')for sides in((),('inward',),('outward',))})
        for frame in range(80):
            level=rng.choice(['EG','OG1']);z=0 if level=='EG'else 4250
            truth={}
            for index in range(20):
                peer_level=level if rng.random()<.7 else('OG1'if level=='EG'else'EG')
                peer_z=z if rng.random()<.75 else(0 if peer_level=='EG'else 4250)+rng.choice([0,1000])
                row=own(rng.uniform(-6000,6000),rng.uniform(-6000,6000),peer_level,peer_z,rng.random()<.3)
                row['pose_mm'][2]=rng.uniform(-20*math.pi,20*math.pi)
                if index%5:row['footprint_mm']=[rng.uniform(100,1800),rng.uniform(100,1500)]
                truth['BF%02d'%(index+1)]=row
            truth['BF01'].update(level=level,z_mm=z,floor_z_mm=z)
            lift={'doors_open':rng.choice([True,False]),'open_sides':[rng.choice(['inward','outward'])],
                  'level':rng.choice(['EG','OG1']),'z_mm':rng.choice([0,4250,2000])}
            self.assert_scan(world,truth,frame*.1,lift)
            self.assert_scan(world,truth,frame*.1+.05,lift)

    def test_whole_rectangle_range_rejection_retains_corners_and_tangencies(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[]});lift={'doors_open':False,'level':'EG','z_mm':1000}
        for origin in(0.,1e9,-1e9):
            for heading in(0.,math.pi/2,math.pi/4,1e-13):
                for offset in(math.nextafter(2456.,-math.inf),2456.,math.nextafter(2456.,math.inf),4000.):
                    truth={'BF01':own(origin,origin),'BF02':own(origin+offset,origin)}
                    truth['BF02'].update(footprint_mm=[512,412]);truth['BF02']['pose_mm'][2]=heading
                    self.assert_scan(world,truth,0,lift)
        truth={'BF01':own(),'BF02':own(4000)};truth['BF02']['footprint_mm']=[9000,10000]
        self.assertTrue(self.assert_scan(world,truth,0,lift)['returns_local_mm'])
        self.assertGreater(world.range_pruned_peers,0)

    def test_dense_beams_preserve_first_returns_after_rectangle_angle_pruning(self):
        rng = random.Random(74786)
        world = sim.SensorWorld({**SETTINGS, 'angular_step_deg': .36, 'range_mm': 12000},
                                {'EG': [((1800, -2500), (1800, 2500))]})
        lift = {'doors_open': False, 'level': 'EG', 'z_mm': 1000}
        for frame in range(24):
            x, y = rng.uniform(-10000, 10000), rng.uniform(-10000, 10000)
            truth = {'BF01': own(x, y)}
            truth['BF01']['pose_mm'][2] = rng.uniform(-20 * math.pi, 20 * math.pi)
            for index in range(12):
                peer = own(x + rng.uniform(-11000, 11000), y + rng.uniform(-11000, 11000))
                peer['pose_mm'][2] = rng.uniform(-20 * math.pi, 20 * math.pi)
                peer['footprint_mm'] = [rng.uniform(150, 1100), rng.uniform(150, 900)]
                truth[str(index)] = peer
            self.assert_scan(world, truth, frame * .1, lift)
        self.assertLess(world.rectangle_rays, 24 * 12 * 1000 // 4)

        for origin in (0., 1e9, -1e9):
            for yaw in (0., math.nextafter(math.tau, 0.), -10 * math.tau, 1e8):
                truth = {'BF01': own(origin, origin), 'enclosing': own(origin + 1, origin + 1)}
                truth['BF01']['pose_mm'][2] = yaw
                truth['enclosing']['footprint_mm'] = [2, 2]
                self.assert_scan(world, truth, 3., lift)
                del truth['enclosing']
                for index, offset in enumerate((math.nextafter(206., 0.), 206.,
                                                math.nextafter(206., math.inf), -206.)):
                    peer = own(origin + 11744, origin + offset)
                    peer['pose_mm'][2] = 1e-13 * index
                    peer['footprint_mm'] = [512, 412]
                    truth['boundary'] = peer
                    self.assert_scan(world, truth, 3.1, lift)

    def test_cache_refreshes_for_nearby_motion_height_doors_and_cabin(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[]},cabin_segments_by_sides={():[((1200,-500),(1200,500))],('inward',):[]},
            landing_segments_by_level_sides={('EG',()):[((500,-500),(500,500))],('EG',('inward',)):[]})
        truth={'BF01':own(),'BF02':own(800)};truth['BF02']['footprint_mm']=[100,100]
        lift={'doors_open':False,'level':'EG','z_mm':0,'open_sides':[]}
        first=self.assert_scan(world,truth,1,lift);self.assert_scan(world,truth,2,lift)
        self.assertEqual(world.raw_cache_hits,1)
        first['returns_local_mm'][0][1]=-999;first['returns_local_mm'].append([999,999])
        fresh=self.assert_scan(world,truth,3,lift);self.assertEqual(fresh['captured_s'],3)
        self.assertNotEqual(fresh['returns_local_mm'][0][1],-999)
        lift.update(doors_open=True,open_sides=['inward']);self.assert_scan(world,truth,4,lift)
        self.assertEqual(world.raw_cache_misses,2)
        truth['BF02']['pose_mm'][0]=900;self.assert_scan(world,truth,5,lift)
        truth['BF02']['z_mm']=4250;self.assert_scan(world,truth,6,lift)
        truth['BF01'].update(aboard=True,z_mm=1000,floor_z_mm=0);self.assert_scan(world,truth,7,lift)
        self.assertEqual(world.raw_cache_misses,5)
        self.assertEqual(world.static_cache_misses,3)
        self.assertEqual(world.static_cache_hits,2)

    def test_far_peer_and_unrelated_lift_travel_do_not_invalidate_raw_geometry(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[]});truth={'BF01':own(),'BF02':own(100000)}
        truth['BF02']['footprint_mm']=[512,412]
        lift={'doors_open':False,'level':'OG1','z_mm':4250,'open_sides':[]}
        self.assert_scan(world,truth,0,lift)
        truth['BF02']['pose_mm'][0]+=100;lift['z_mm']=5000
        self.assert_scan(world,truth,.1,lift);self.assertEqual(world.raw_cache_hits,1)

    def test_mixed_peer_tie_order_and_signed_zero_are_preserved(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[]});lift={'doors_open':False,'level':'EG'}
        truth={'BF01':own(0.),'disc':own(0.,100.),'box':own(50.,0.)};truth['box']['footprint_mm']=[100,100]
        scan=self.assert_scan(world,truth,0,lift)
        self.assertEqual(math.copysign(1,scan['returns_local_mm'][0][1]),-1)
        truth['BF01']['pose_mm'][0]=-0.
        self.assert_scan(world,truth,1,lift);self.assertEqual(world.raw_cache_misses,2)

    def test_cache_is_bounded_and_downstream_noise_stays_fresh(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[]});world._raw_cache_limit=2;world._static_cache_limit=2
        truth={'BF01':own(),'BF02':own(800)};truth['BF02']['footprint_mm']=[100,100]
        lift={'doors_open':False,'level':'EG'};rng1=random.Random(17);rng2=random.Random(17);frames=[]
        def noisy(scan,rng):return [[x+rng.uniform(-1,1),y+rng.uniform(-1,1)]for x,y in scan['returns_local_mm']]
        for frame,x in enumerate([0,0,10,20,0]):
            truth['BF01']['pose_mm'][0]=x;actual=self.assert_scan(world,truth,frame*.1,lift)
            changed=noisy(actual,rng1);self.assertEqual(changed,noisy(original_scan(world,'BF01',truth,frame*.1,lift),rng2));frames.append(changed)
        self.assertNotEqual(frames[0],frames[1]);self.assertEqual(len(world._raw_cache),2)
        self.assertEqual(world.raw_cache_hits,1);self.assertEqual(world.raw_cache_misses,4)
        self.assertEqual(len(world._static_cache),2);self.assertEqual(world.static_cache_misses,4)

    def test_cached_static_part_does_not_freeze_a_current_peer_first_return(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[((1500,-500),(1500,500))]})
        truth={'BF01':own(),'BF02':own(800)};truth['BF02']['footprint_mm']=[100,100]
        lift={'doors_open':False,'level':'EG'}
        self.assertEqual(self.assert_scan(world,truth,0,lift)['returns_local_mm'][0][1],750)
        truth['BF02']['pose_mm'][0]=1000
        self.assertEqual(self.assert_scan(world,truth,.1,lift)['returns_local_mm'][0][1],950)
        del truth['BF02']
        self.assertEqual(self.assert_scan(world,truth,.2,lift)['returns_local_mm'][0][1],1500)
        self.assertEqual(world.raw_cache_misses,3)
        self.assertEqual(world.static_cache_misses,1);self.assertEqual(world.static_cache_hits,2)


class SensorTests(unittest.TestCase):
    def test_ray_bounds_preserve_closed_edges_corner_tangencies_and_range_types(self):
        segments = [((0, 0), (0, 1)), ((0, 1), (1, 1)), ((-4, 0), (-4, -2)),
                    ((-1, -1), (0, 0)), ((3, 2), (3, 2))]
        diagonal = math.sqrt(.5)
        directions = [(1., 0.), (-1., 0.), (0., 1.), (-0., -1.), (0., 0.),
                      (1., 1e-15), (diagonal, diagonal), (-diagonal, diagonal),
                      (diagonal, -diagonal), (-diagonal, -diagonal)]
        for geometry in (segments, [segments[-1]], []):
            index = sim.SegmentIndex(geometry, 1.)
            unpruned = sim.SegmentIndex(geometry, 1.)
            unpruned._ray_bounds = (-math.inf, -math.inf, math.inf, math.inf)
            for x in (-7., -4., -1e-10, 0., 1., math.nextafter(1., math.inf), 8.):
                for y in (-5., -2., 0., 1., 4.):
                    for direction in directions:
                        for cap in (0, -0., 1e-12, 1., math.sqrt(2), 4., 12.):
                            expected = unpruned.ray((x, y), direction, cap)
                            result = index.ray((x, y), direction, cap)
                            self.assertEqual((type(result), float(result).hex()),
                                             (type(expected), float(expected).hex()))

    def test_far_ray_skips_indexed_cells_but_an_incoming_ray_hits(self):
        class CountingCells(dict):
            visits = 0
            def get(self, *args):
                self.visits += 1
                return super().get(*args)

        index = sim.SegmentIndex([((0., 0.), (0., 1.))], 1.)
        index.cells = CountingCells(index.cells)
        self.assertEqual(index.ray((-100., .5), (1., 0.), 5.), 5.)
        self.assertEqual(index.cells.visits, 0)
        self.assertEqual(index.ray((-100., .5), (1., 0.), 101.), 100.)
        self.assertGreater(index.cells.visits, 0)

    def test_first_return_is_anonymous_and_static_wall_occludes_vehicle(self):
        world = sim.SensorWorld(SETTINGS, {'EG':[((500,-500),(500,500))]})
        truth = {'BF01':own(), 'BF02':own(1000)}
        scan = world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})
        self.assertEqual(set(scan), {'captured_s','returns_local_mm'})
        self.assertEqual(scan['returns_local_mm'][0], [0,500])
        self.assertNotIn('BF02',repr(scan)); self.assertNotIn('radius',repr(scan))
        del truth['BF02']
        self.assertEqual(scan,world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'}))

    def test_dynamic_first_return_replaces_farther_wall(self):
        world = sim.SensorWorld(SETTINGS, {'EG':[((1500,-500),(1500,500))]})
        scan = world.scan('BF01',{'BF01':own(),'BF02':own(800)},0,{'doors_open':True,'level':'EG'})
        self.assertAlmostEqual(scan['returns_local_mm'][0][1],700)

    def test_full_oriented_footprint_avoids_false_disc_overlap_on_parallel_lanes(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[]})
        truth={'BF01':own(),'BF02':own(1000,y=600,radius=math.hypot(256,206))}
        truth['BF02']['footprint_mm']=[512,412]
        scan=world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})
        self.assertFalse(any(abs(side)<394 and forward>0 for side,forward in scan['returns_local_mm']))
        truth['BF02']['pose_mm']=[1000,0,math.pi/2]
        scan=world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})
        self.assertAlmostEqual(scan['returns_local_mm'][0][1],1000-206)
        self.assertEqual(world.statistics()['disc_fixture_ray_tests'],0)

    def test_floor_height_and_closed_cabin_hide_other_vehicle(self):
        world = sim.SensorWorld(SETTINGS, {'EG':[]})
        truth = {'BF01':own(), 'BF02':own(800,aboard=True)}
        self.assertEqual(world.scan('BF01',truth,0,{'doors_open':False,'level':'EG'})['returns_local_mm'],[])
        self.assertTrue(world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})['returns_local_mm'])
        truth['BF02']['z_mm'] = 4250
        self.assertEqual(world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})['returns_local_mm'],[])
        truth['BF02'] = own(800,level='OG1')
        self.assertEqual(world.scan('BF01',truth,0,{'doors_open':True,'level':'EG'})['returns_local_mm'],[])

    def test_landing_doors_occlude_without_cabin_and_open_only_aligned_active_side(self):
        world=sim.SensorWorld(SETTINGS,{'EG':[],'OG1':[]},
            landing_segments_by_level_sides={('EG',()):[((500,-500),(500,500))],
                ('EG',('inward',)):[],('OG1',()):[((700,-500),(700,500))],
                ('OG1',('outward',)):[]})
        truth={'BF01':own(),'BF02':own(1000)}
        def ahead(lift):return world.scan('BF01',truth,0,lift)['returns_local_mm'][0][1]
        self.assertEqual(ahead({'doors_open':True,'open_sides':['outward'],'level':'OG1','z_mm':4250}),500)
        self.assertEqual(ahead({'doors_open':False,'open_sides':[],'level':'EG','z_mm':0}),500)
        self.assertEqual(ahead({'doors_open':True,'open_sides':['inward'],'level':'EG','z_mm':0}),900)
        # An open-door flag at a different absolute height never erases the
        # closed landing door at the vehicle's actual floor.
        self.assertEqual(ahead({'doors_open':True,'open_sides':['inward'],'level':'EG','z_mm':4250}),500)

    def test_orientation_is_own_and_ray_index_matches_unindexed_geometry(self):
        segments = [((500,-500),(500,500)),((-600,-500),(-600,500)),((-500,500),(500,500))]
        index = sim.SegmentIndex(segments,200)
        for degrees in range(0,360,2):
            angle = math.radians(degrees); direction = [math.cos(angle),math.sin(angle)]
            expected = min(2200,*[sim.ray_segment(0,0,*direction,*segment) for segment in segments])
            self.assertAlmostEqual(index.ray([0,0],direction,2200),expected)
        world = sim.SensorWorld(SETTINGS,{'EG':[((-500,500),(500,500))]})
        pose = own(); pose['pose_mm'][2] = math.pi/2
        self.assertAlmostEqual(world.scan('BF01',{'BF01':pose},0,{'doors_open':True,'level':'EG'})['returns_local_mm'][0][1],500)


class AuditorTests(unittest.TestCase):
    def curve(self,start,end,velocity):
        import tr01_floor_motion as floor
        points=[{'time_s':t,'pose_mm_rad':pose,'velocity_mm_rad_s':velocity,'acceleration_mm_rad_s2':[0,0,0]}
                for t,pose in((0,start),(.05,end))]
        return floor.motion.Curve(floor.canonical(points))

    def test_actual_polynomial_axis_bound_certifies_parallel_home_gap_88(self):
        radius=math.hypot(256,206);previous={'BF01':own(radius=radius),'BF02':own(500,radius=radius)}
        for row in previous.values():row['footprint_mm']=[512,412];row['pose_mm'][2]=math.pi/2
        current=copy.deepcopy(previous);current['BF01']['pose_mm'][1]=15
        curves={'BF01':self.curve(previous['BF01']['pose_mm'],current['BF01']['pose_mm'],[0,300,0]),
                'BF02':self.curve(previous['BF02']['pose_mm'],current['BF02']['pose_mm'],[0,0,0])}
        bounds={'BF01':{'linear_mm_s':300,'yaw_rad_s':0},'BF02':{'linear_mm_s':0,'yaw_rad_s':0}}
        auditor=sim.IntervalAuditor(85,{'EG':[]})
        auditor.audit(previous,current,.05,bounds,curves=curves,start_s=0,end_s=.05)
        self.assertAlmostEqual(auditor.minima['vehicle_vehicle'],88)
        self.assertGreater(auditor.refined_intervals,0)

    def test_actual_polynomial_refinement_keeps_static_reserve_85(self):
        radius=math.hypot(256,206);previous={'BF01':own(radius=radius)}
        previous['BF01']['footprint_mm']=[512,412];previous['BF01']['pose_mm'][2]=math.pi/2
        current=copy.deepcopy(previous);current['BF01']['pose_mm'][1]=15
        curve=self.curve(previous['BF01']['pose_mm'],current['BF01']['pose_mm'],[0,300,0])
        auditor=sim.IntervalAuditor(85,{'EG':[((294,-500),(294,500))]})
        auditor.audit(previous,current,.05,{'BF01':{'linear_mm_s':300,'yaw_rad_s':0}},curves={'BF01':curve},start_s=0,end_s=.05)
        self.assertGreaterEqual(auditor.minima['vehicle_static'],85)

    def test_true_midinterval_collision_remains_a_failure_with_curve_input(self):
        previous={'BF01':own(-300,radius=math.hypot(50,50)),'BF02':own(0,150,radius=math.hypot(50,50))}
        for row in previous.values():row['footprint_mm']=[100,100]
        current=copy.deepcopy(previous);current['BF01']['pose_mm'][0]=300
        curves={'BF01':self.curve(previous['BF01']['pose_mm'],current['BF01']['pose_mm'],[12000,0,0]),
                'BF02':self.curve(previous['BF02']['pose_mm'],current['BF02']['pose_mm'],[0,0,0])}
        auditor=sim.IntervalAuditor(75,{'EG':[]})
        with self.assertRaisesRegex(RuntimeError,'actual pair'):
            auditor.audit(previous,current,.05,{'BF01':12000,'BF02':0},curves=curves,start_s=0,end_s=.05)

    def test_nested_footprints_have_zero_separation_in_both_orders(self):
        small=sim.footprint({'pose_mm':[0,0,0],'footprint_mm':[100,100]})
        large=sim.footprint({'pose_mm':[0,0,0],'footprint_mm':[1000,1000]})
        self.assertEqual(sim.polygon_distance(small,large),0)
        self.assertEqual(sim.polygon_distance(large,small),0)

    def test_motion_bound_detects_midinterval_contact_despite_safe_endpoints(self):
        # A fast vehicle could approach and return between these equal poses.
        previous = {'BF01':own(), 'BF02':own(500)}
        auditor = sim.IntervalAuditor(75,{'EG':[]})
        with self.assertRaisesRegex(RuntimeError,'pair interval'):
            auditor.audit(previous,copy.deepcopy(previous),1,{'BF01':400,'BF02':400})

    def test_safe_pair_has_conservative_finite_bound(self):
        previous = {'BF01':own(), 'BF02':own(1000)}
        current = {'BF01':own(10), 'BF02':own(990)}
        auditor = sim.IntervalAuditor(75,{'EG':[]})
        auditor.audit(previous,current,.05,{'BF01':200,'BF02':200})
        self.assertAlmostEqual(auditor.minima['vehicle_vehicle'],770)
        self.assertGreaterEqual(auditor.minima['vehicle_static'],75)

    def test_static_contact_and_unbounded_motion_fail(self):
        previous = {'BF01':own(0)}; current = {'BF01':own(10)}
        auditor = sim.IntervalAuditor(75,{'EG':[((180,-500),(180,500))]})
        with self.assertRaisesRegex(RuntimeError,'static interval'):
            auditor.audit(previous,current,.05,{'BF01':200})
        with self.assertRaisesRegex(ValueError,'displacement'):
            auditor.audit(previous,current,.05,{'BF01':10})

    def test_floor_transition_requires_cabin(self):
        previous = {'BF01':own()}; current = {'BF01':own(level='OG1',z=4250)}
        auditor = sim.IntervalAuditor(75,{'EG':[],'OG1':[]})
        with self.assertRaisesRegex(ValueError,'outside the cabin'):
            auditor.audit(previous,current,.05,{'BF01':0})

    def test_narrow_phase_needs_explicit_angular_bound_and_retains_reserve(self):
        previous = {'BF01':own(), 'BF02':own(y=487)}
        for row in previous.values():
            row['radius_mm'] = math.hypot(512,412)/2
            row['footprint_mm'] = [512,412]
        current = copy.deepcopy(previous)
        auditor = sim.IntervalAuditor(75,{'EG':[]})
        with self.assertRaises(RuntimeError): auditor.audit(previous,current,.05,{'BF01':0,'BF02':0})
        auditor = sim.IntervalAuditor(75,{'EG':[]})
        bounds = {'BF01':{'linear_mm_s':0,'yaw_rad_s':0},'BF02':{'linear_mm_s':0,'yaw_rad_s':0}}
        auditor.audit(previous,current,.05,bounds)
        self.assertAlmostEqual(auditor.minima['vehicle_vehicle'],75)
        self.assertEqual(auditor.oriented_fallbacks,1)
        bounds['BF01']['yaw_rad_s'] = 1
        with self.assertRaises(RuntimeError): auditor.audit(previous,current,.05,bounds)

    def test_static_rectangle_fallback_checks_yaw_motion(self):
        previous = {'BF01':own(radius=math.hypot(512,412)/2)}
        previous['BF01']['footprint_mm'] = [512,412]
        current = copy.deepcopy(previous)
        auditor = sim.IntervalAuditor(75,{'EG':[((-1000,300),(1000,300))]})
        auditor.audit(previous,current,.05,{'BF01':{'linear_mm_s':0,'yaw_rad_s':0}})
        self.assertAlmostEqual(auditor.minima['vehicle_static'],94)
        current['BF01']['pose_mm'][2] = .1
        with self.assertRaisesRegex(ValueError,'angular bound'):
            auditor.audit(previous,current,.05,{'BF01':{'linear_mm_s':0,'yaw_rad_s':0}})

    def test_endpoint_cache_reuses_only_exact_geometry_and_keeps_interval_bound(self):
        row = dict(own(), footprint_mm=[512,412])
        auditor = sim.IntervalAuditor(75, {'EG': [((-1000,300),(1000,300))]})
        index = auditor.static['EG']
        with patch.object(sim, 'polygon_segment_distance', wraps=sim.polygon_segment_distance) as measure:
            self.assertEqual(auditor.static_rectangle_bound(index,row,row,0,0,.05),94)
            self.assertEqual(auditor.static_rectangle_bound(index,row,row,10,0,.05),93.75)
            self.assertEqual(measure.call_count,1)
            moved = copy.deepcopy(row)
            moved['pose_mm'][1] = 1e-8
            self.assertLess(auditor.static_rectangle_bound(index,moved,moved,0,0,.05),94)
            self.assertEqual(measure.call_count,2)
            index.segments = (((-1000,200),(1000,200)),)
            self.assertEqual(auditor.static_rectangle_bound(index,row,row,0,0,.05),0)
            self.assertGreater(measure.call_count,2)



class ExactStaticEndpointTests(unittest.TestCase):
    def original(self,index,row):
        polygon=sim.footprint(row)
        return min((sim.polygon_segment_distance(polygon,*segment)for segment in index.segments),default=math.inf)

    def assert_exact(self,index,row):
        expected=self.original(index,row)
        actual=sim.IntervalAuditor._static_endpoint_distance(index,row)
        self.assertEqual(actual.hex(),expected.hex())

    def test_random_rotated_rectangles_match_every_original_segment_distance(self):
        rng=random.Random(811240)
        for cell in(47.,500.,2300.):
            segments=[((rng.uniform(-12000,12000),rng.uniform(-12000,12000)),
                       (rng.uniform(-12000,12000),rng.uniform(-12000,12000)))for _ in range(55)]
            index=sim.SegmentIndex(segments,cell)
            for _ in range(24):
                row=dict(own(rng.uniform(-15000,15000),rng.uniform(-15000,15000)),
                    footprint_mm=[rng.uniform(1,1800),rng.uniform(1,1200)])
                row['pose_mm'][2]=rng.uniform(-12*math.pi,12*math.pi)
                self.assert_exact(index,row)

    def test_closed_grid_edges_contacts_long_segments_and_large_translations(self):
        for offset in(0.,1e9,-1e9):
            for yaw in(0.,math.pi/2,math.pi/4,-.000000001):
                row=dict(own(offset,offset),footprint_mm=[512.,412.]);row['pose_mm'][2]=yaw
                corners=sim.footprint(row)
                segments=[((offset-20000,offset+700),(offset+20000,offset+700)),
                    (corners[0],corners[1]),((offset+5000,offset-5000),(offset+5000,offset+5000))]
                for shift in(-1e-8,0.,1e-8):
                    moved=[((a[0],a[1]+shift),(b[0],b[1]+shift))for a,b in segments]
                    self.assert_exact(sim.SegmentIndex(moved),row)

    def test_local_query_omits_far_work_and_retains_exact_cached_value(self):
        row=dict(own(),footprint_mm=[512,412])
        segments=[((-1000,300),(1000,300))]+[
            ((50000+100*i,50000),(50000+100*i,50200))for i in range(400)]
        index=sim.SegmentIndex(segments)
        expected=self.original(index,row)
        with patch.object(sim,'polygon_segment_distance',wraps=sim.polygon_segment_distance)as measure:
            self.assertEqual(sim.IntervalAuditor._static_endpoint_distance(index,row),expected)
            self.assertLess(measure.call_count,10)
            count=measure.call_count
            self.assertEqual(sim.IntervalAuditor._static_endpoint_distance(index,row),expected)
            self.assertEqual(measure.call_count,count)
        # Original ray/match consumers keep their exact read-only interface.
        self.assertEqual(index.ray((0,0),(0,1),1000),300.)
        self.assertTrue(index.matches((0,300),.001))

    def test_empty_and_distant_geometry_expand_or_use_complete_fallback(self):
        row=dict(own(),footprint_mm=[512,412])
        for segments in([], [((1e7,1e7),(1e7+1000,1e7))],
                         [((5000,-5000),(5000,5000)),((-5000,-5000),(-5000,5000))]):
            self.assert_exact(sim.SegmentIndex(segments),row)

    def test_frozen_membership_and_replaced_sources_cannot_reuse_a_stale_gap(self):
        row=dict(own(),footprint_mm=[512,412]);index=sim.SegmentIndex([((-1000,300),(1000,300))])
        self.assertEqual(sim.IntervalAuditor._static_endpoint_distance(index,row),94.)
        with self.assertRaises(TypeError):index.cells[0,0]=()
        cell=next(iter(index.cells))
        with self.assertRaises(TypeError):index.cells[cell][0]=9
        index.cells={};self.assert_exact(index,row)
        index.segments=(((-1000,200),(1000,200)),);self.assert_exact(index,row)
        self.assertEqual(sim.IntervalAuditor._static_endpoint_distance(index,row),0.)
        index.cell=0.;self.assert_exact(index,row)

    def test_rounded_degenerate_polygon_keeps_original_primitive_semantics(self):
        row=dict(own(1e30,1e30),footprint_mm=[512,412])
        self.assert_exact(sim.SegmentIndex([((0.,0.),(1.,1.))]),row)


class ExactPairEndpointTests(unittest.TestCase):
    def row(self,x=0.,y=0.,yaw=0.,length=512,width=412):
        result=dict(own(x,y,radius=math.hypot(length,width)/2),footprint_mm=[length,width])
        result['pose_mm'][2]=yaw
        return result

    def test_random_orientations_and_large_translations_keep_exact_original_hex(self):
        rng=random.Random(138005)
        auditor=sim.IntervalAuditor(85,{'EG':[]})
        for _ in range(120):
            origin=rng.choice([0.,1e9,-1e9])
            rows=[self.row(origin+rng.uniform(-3000,3000),origin+rng.uniform(-3000,3000),
                rng.uniform(-40*math.pi,40*math.pi),rng.uniform(10,2000),rng.uniform(10,1500))for _ in range(2)]
            expected=sim.polygon_distance(*[sim.footprint(row)for row in rows])
            self.assertEqual(auditor._pair_endpoint_distance(*rows).hex(),expected.hex())
            self.assertEqual(auditor._pair_endpoint_distance(*rows).hex(),expected.hex())
            reverse=sim.polygon_distance(*[sim.footprint(row)for row in reversed(rows)])
            self.assertEqual(auditor._pair_endpoint_distance(*reversed(rows)).hex(),reverse.hex())

    def test_repeated_pairs_reuse_geometry_and_shared_endpoints_reuse_corners(self):
        auditor=sim.IntervalAuditor(85,{'EG':[]});a,b,c=self.row(),self.row(1000),self.row(2000)
        with patch.object(sim,'polygon_distance',wraps=sim.polygon_distance)as distance:
            with patch.object(sim,'footprint',wraps=sim.footprint)as shape:
                auditor._pair_endpoint_distance(a,b);auditor._pair_endpoint_distance(a,b)
                self.assertEqual(distance.call_count,1);self.assertEqual(shape.call_count,2)
                auditor._pair_endpoint_distance(a,c);auditor._pair_endpoint_distance(b,c)
                self.assertEqual(distance.call_count,3);self.assertEqual(shape.call_count,3)

    def test_typed_signed_zero_tiny_pose_and_changed_shape_do_not_alias(self):
        auditor=sim.IntervalAuditor(85,{'EG':[]});a,b=self.row(),self.row(1000.)
        with patch.object(sim,'polygon_distance',wraps=sim.polygon_distance)as distance:
            auditor._pair_endpoint_distance(a,b)
            a['pose_mm'][0]=-0.;auditor._pair_endpoint_distance(a,b)
            a['pose_mm'][0]=0;auditor._pair_endpoint_distance(a,b)
            a['pose_mm'][0]=math.nextafter(0.,math.inf);auditor._pair_endpoint_distance(a,b)
            b['footprint_mm'][0]=512.;auditor._pair_endpoint_distance(a,b)
            b['footprint_mm'][0]=math.nextafter(512.,math.inf);auditor._pair_endpoint_distance(a,b)
            self.assertEqual(distance.call_count,6)
        b['footprint_mm'][0]=-512
        with self.assertRaises(ValueError):auditor._pair_endpoint_distance(a,b)

    def test_geometry_definition_changes_invalidate_both_pure_caches(self):
        auditor=sim.IntervalAuditor(85,{'EG':[]});a,b=self.row(),self.row(1000.)
        original=auditor._pair_endpoint_distance(a,b)
        with patch.object(sim,'polygon_distance',return_value=original+1)as changed:
            self.assertEqual(auditor._pair_endpoint_distance(a,b),original+1)
            changed.assert_called_once()
        self.assertEqual(auditor._pair_endpoint_distance(a,b),original)

    def test_pair_and_corner_storage_is_bounded_and_eviction_recomputes(self):
        auditor=sim.IntervalAuditor(85,{'EG':[]});a=self.row()
        with patch.object(sim,'polygon_distance',wraps=sim.polygon_distance)as distance:
            for i in range(2055):auditor._pair_endpoint_distance(a,self.row(1000.+i))
            self.assertEqual(len(auditor._pair_endpoint_distances),2048)
            self.assertLessEqual(len(auditor._endpoint_footprints),2048)
            distance.reset_mock()
            auditor._pair_endpoint_distance(a,self.row(3054.));self.assertEqual(distance.call_count,0)
            auditor._pair_endpoint_distance(a,self.row(1000.));self.assertEqual(distance.call_count,1)

    def test_current_angular_bound_and_actual_moving_contact_still_fail(self):
        a,b=self.row(),self.row(y=487.)
        previous={'BF01':a,'BF02':b};current=copy.deepcopy(previous)
        zero={identity:{'linear_mm_s':0.,'yaw_rad_s':0.}for identity in previous}
        auditor=sim.IntervalAuditor(75,{'EG':[]})
        auditor.audit(previous,current,.05,zero)
        self.assertEqual(auditor.minima['vehicle_vehicle'],75.)
        angular=copy.deepcopy(zero);angular['BF01']['yaw_rad_s']=1.
        with self.assertRaisesRegex(RuntimeError,'pair interval'):auditor.audit(previous,current,.05,angular)
        current['BF02']['pose_mm'][1]=420.
        moving=copy.deepcopy(zero);moving['BF02']['linear_mm_s']=1340.
        with self.assertRaisesRegex(RuntimeError,'pair interval'):auditor.audit(previous,current,.05,moving)
        # Floor and height gates remain current even for geometrically cached
        # endpoints; they are deliberately absent from this pure planar key.
        current=copy.deepcopy(previous);previous['BF02']['z_mm']=current['BF02']['z_mm']=4250.
        auditor.audit(previous,current,.05,zero)


class ExactPolygonDistanceTests(unittest.TestCase):
    def polygon(self,x=0.,y=0.,yaw=0.,length=512.,width=412.):
        return sim.footprint(dict(own(x,y),pose_mm=[x,y,yaw],footprint_mm=[length,width]))

    def test_random_ordered_vertices_equal_uncached_hex_and_mutation_is_observed(self):
        rng=random.Random(761004)
        for _ in range(100):
            offset=rng.choice([0.,1e9,-1e9])
            polygons=[self.polygon(offset+rng.uniform(-3000,3000),offset+rng.uniform(-3000,3000),
                rng.uniform(-20*math.pi,20*math.pi),rng.uniform(10,3000),rng.uniform(10,2000))for _ in range(2)]
            expected=sim._polygon_distance_uncached(*polygons)
            self.assertEqual(sim.polygon_distance(*polygons).hex(),expected.hex())
            self.assertEqual(sim.polygon_distance(*polygons).hex(),expected.hex())
            reverse=sim._polygon_distance_uncached(*reversed(polygons))
            self.assertEqual(sim.polygon_distance(*reversed(polygons)).hex(),reverse.hex())
        a,b=self.polygon(),self.polygon(1000.)
        original=sim.polygon_distance(a,b)
        b[0]=(b[0][0]+.01,b[0][1])
        self.assertEqual(sim.polygon_distance(a,b).hex(),sim._polygon_distance_uncached(a,b).hex())
        self.assertGreaterEqual(sim.polygon_distance(a,b),original)

    def test_signed_zero_numeric_type_order_and_one_ulp_inputs_have_separate_entries(self):
        a=[[0.,0.],[1.,0.],[1.,1.],[0.,1.]];b=[[4.,0.],[5.,0.],[5.,1.],[4.,1.]]
        with patch.object(sim,'_polygon_distance_uncached',wraps=sim._polygon_distance_uncached)as original:
            sim.polygon_distance(a,b);sim.polygon_distance(a,b);self.assertEqual(original.call_count,1)
            a[0][0]=-0.;sim.polygon_distance(a,b)
            a[0][0]=0;sim.polygon_distance(a,b)
            a[0][0]=math.nextafter(0.,math.inf);sim.polygon_distance(a,b)
            sim.polygon_distance(b,a)
            self.assertEqual(original.call_count,5)

    def test_primitive_replacement_cannot_reuse_old_distance(self):
        a,b=self.polygon(),self.polygon(1000.)
        original=sim.polygon_distance(a,b)
        with patch.object(sim,'polygon_segment_distance',return_value=3.):
            self.assertEqual(sim.polygon_distance(a,b),3.)
        self.assertEqual(sim.polygon_distance(a,b),original)

    def test_unusual_numeric_types_and_nonfinite_vertices_use_original_each_time(self):
        from fractions import Fraction
        a=[[Fraction(0),Fraction(0)],[Fraction(1),Fraction(0)],[Fraction(0),Fraction(1)]]
        b=self.polygon(1000.)
        for polygon in(a,[[0.,0.],[math.nan,0.],[0.,1.]],[[0.,0.],[math.inf,0.],[0.,1.]]):
            expected=sim._polygon_distance_uncached(polygon,b)
            with patch.object(sim,'_polygon_distance_uncached',wraps=sim._polygon_distance_uncached)as original:
                self.assertEqual(sim.polygon_distance(polygon,b).hex(),expected.hex())
                self.assertEqual(sim.polygon_distance(polygon,b).hex(),expected.hex())
                self.assertEqual(original.call_count,2)

    def test_bounded_lru_and_unchanged_polygon_skip_original_computation(self):
        room=[[-10000.,-10000.],[10000.,-10000.],[10000.,10000.],[-10000.,10000.]]
        with patch.object(sim,'_polygon_distance_uncached',wraps=sim._polygon_distance_uncached)as original:
            for i in range(2055):sim.polygon_distance(self.polygon(float(i)),room)
            self.assertEqual(len(sim._POLYGON_DISTANCE_CACHE),2048)
            original.reset_mock()
            sim.polygon_distance(self.polygon(2054.),room);self.assertEqual(original.call_count,0)
            sim.polygon_distance(self.polygon(0.),room);self.assertEqual(original.call_count,1)

    def test_depot_owner_rest_and_velocity_checks_still_run_on_cached_geometry(self):
        import building_fleet_depot as depot
        room={('EG','garage'):[[-2000.,-2000.],[2000.,-2000.],[2000.,2000.],[-2000.,2000.]]}
        aliases={('EG','garage'):'own-resource'}
        homes={'BF01':{'level':'EG','pose_mm_rad':[0.,0.,0.]},'BF02':{'level':'EG','pose_mm_rad':[1000.,0.,0.]}}
        states={identity:{**dict(own(*home['pose_mm_rad'][:2]),footprint_mm=[512,412]),
            'velocity_mm_rad_s':[0.,0.,0.],'acceleration_mm_rad_s2':[0.,0.,0.]}for identity,home in homes.items()}
        states['BF01']['pose_mm'][0]=100.;states['BF01']['velocity_mm_rad_s'][0]=10.
        with patch.object(sim,'_polygon_distance_uncached',wraps=sim._polygon_distance_uncached)as original:
            self.assertEqual(depot.check_invariant(states,homes,room,aliases,{'own-resource':'BF01'},85),2)
            self.assertEqual(original.call_count,2);original.reset_mock()
            self.assertEqual(depot.check_invariant(states,homes,room,aliases,{'own-resource':'BF01'},85),2)
            self.assertEqual(original.call_count,0)
            with self.assertRaisesRegex(RuntimeError,'depot map invariant'):
                depot.check_invariant(states,homes,room,aliases,{'own-resource':'BF02'},85)
            self.assertEqual(original.call_count,0)
            states['BF02']['velocity_mm_rad_s'][0]=1.
            with self.assertRaisesRegex(RuntimeError,'depot map invariant'):
                depot.check_invariant(states,homes,room,aliases,{'own-resource':'BF01'},85)
            self.assertEqual(original.call_count,0)


if __name__ == '__main__': unittest.main()
