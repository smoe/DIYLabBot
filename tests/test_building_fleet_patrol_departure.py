"""Private starter, ordinary resource handover and retained scan integration."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_background as background
import building_fleet_model as model
from building_fleet_control import preparation_digest
from building_fleet_geometry import vehicle_envelope
from building_fleet_motion import Path as Route
from building_fleet_patrol import PatrolWorldRunner


class PatrolDepartureIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Two distinct depot rooms, one canonical corridor, one ordinary FIFO waiter.
        w = self.world = object.__new__(PatrolWorldRunner)
        w.source = model.load()
        w.sensor = model.resolved_sensor(w.source)
        homes = {identity: {'level':'EG', 'area':area, 'pose_mm_rad':[x,y,0.]}
                 for identity, area, x, y in [('leader','A',0.,0.), ('fifo','A',0.,1000.),
                                                ('successor','B',4000.,0.)]}
        w.vehicles = {k: {'driver':None, 'action':None, 'done':False, 'drives':0,
                           'vehicle_id':k, 'home':home, 'level':'EG', 'z_mm':0., 'phase':'home',
                           'pose_mm_rad':home['pose_mm_rad'][:], 'mission_pending':True, 'aboard':False}
                      for k,home in homes.items()}
        w.depot_aliases = {('EG','A'):'corridor', ('EG','B'):'corridor'}
        w.depot_polygons = {('EG','A'):[[-1000.,-900.],[1400.,-900.],[1400.,1700.],[-1000.,1700.]],
                            ('EG','B'):[[3000.,-900.],[5100.,-900.],[5100.,900.],[3000.,900.]]}
        w.depot_invariant_checks = 0
        w.dt, w.now = .05, 0.
        w.progress = w.evidence = None
        w.resource_cursor = w.leg_counter = 0
        w.geometry_checks, w.depot_checks, w.resource_events = [], [], []
        w.route_door_ids = set()
        w.zone_regions = {'EG':[]}
        envelope = vehicle_envelope()
        w.nav = SimpleNamespace(homes=homes, waits={}, envelope=envelope, radius=envelope['radius_mm'],
                                level_z={'EG':0.}, reserve=85., navigation_margin_mm=0., portals={'EG':[]},
                                mesh=SimpleNamespace(manifest={'objects':[]}))
        def spans(level, path):
            return [{'resource':'corridor', 'start_progress_mm':0., 'end_progress_mm':path.length}]
        w.catalog = SimpleNamespace(resources={'corridor':'room'}, spans=spans)
        w.lift = SimpleNamespace(own_grant=lambda identity:{'status':'none'}, schedule=[])
        w.lift_snapshot = w.lift_values = lambda: {}
        w.event = lambda *args: None
        w.static_return = lambda level, phase, identity: w.depot_maps[identity].matches
        w.capture_history = {k:{} for k in homes}
        # Inject the native geometry verdict. The route, both envelope checks,
        # scalar clocks, C2 connector and same-scan braking remain real.
        w.geometry_checker = lambda *args: {'passed':True}
        w._background_preparation = None
        w.configure_background_preparation('c'*64)
        w.enable_private_departures()
        for identity in ('leader','fifo','successor'):
            w.resources.request(identity, 'corridor', 0.)
        lead = w.vehicles['leader']
        path = Route([[0.,0.],[1000.,0.],[1000.,400.],[-1000.,400.],[-1000.,0.],[0.,0.]])
        lead.update(action={'level':'EG', 'terminal':{'kind':'capacity_home'}}, leg_id=1,
                    driver=SimpleNamespace(path=path, mode='driving', goal=path.length, y=0., v=0., a=0.),
                    gate=SimpleNamespace(spans=spans('EG',path)))
        self.action = {'kind':'drive', 'level':'EG', 'points_mm':[[4000.,0.],[6400.,0.]],
                       'corner_trim_mm':100., 'reverse':False, 'prefetch_level':'EG', 'markers':[],
                       'zone_segments':[{'start_index':0,'end_index':1,'velocity_mm_s':300.}],
                       'terminal':{'kind':'lift_wait','mission_id':'mission-successor'}}
        w.planner = SimpleNamespace(states={'successor':{'queue':[{'mission_id':'mission-successor'}],
                    'admission_deferred':False, 'requested':False}},
                    next_action=lambda own, now, grants:copy.deepcopy(self.action))

    def stage(self):
        w = self.world
        self.assertTrue(w.departures.try_depart('successor','corridor'))
        self.assertTrue(w.departures.staged('successor'))
        self.assertTrue(w.geometry_checks and w.depot_checks)
        return w.vehicles['successor']

    def return_leader(self):
        w = self.world
        lead = w.vehicles['leader']
        lead.update(phase='capacity_home', pose_mm_rad=lead['home']['pose_mm_rad'][:])
        lead['driver'].mode = 'arrived'
        lead['driver'].y = lead['driver'].goal
        w.release_resource('leader','corridor',w.now)
        lead['driver'] = None
        self.assertEqual(w.resources.own_grants('successor'),{'status':'granted','resource':'corridor'})

    def step_successor(self,row):
        w = self.world
        now, end = w.now, round(w.now+w.dt,3)
        driver = row['driver']
        driver.decide(now,{'captured_s':now,'returns_local_mm':[]},
                      grant_permits=row['gate'].permit(now),step_end_s=end)
        driver.advance(now,end)
        row['pose_mm_rad'] = driver.pose()
        w.now = end

    def test_observed_release_alone_unlocks_same_mission_and_preserves_fifo(self):
        w = self.world
        row = self.stage()
        manager, driver = w._background_preparation, row['driver']
        self.assertLess(driver.certified_horizon_mm,driver.goal)
        self.assertTrue(row['gate'].permit(w.now))
        request_id = manager.pending_by_vehicle['successor']
        original = copy.deepcopy(manager.jobs[request_id])
        ctx = {'source':w.source, 'nav':w.nav, 'catalog':w.catalog,
               'geometry_checks':w.geometry_checker, 'source_binding':manager.binding}
        response = background.prepare_route(original,ctx)
        # Even a source-valid completion cannot authorize an undrained private request.
        self.assertFalse(manager.accept(response)['accepted'])
        self.assertNotIn('successor',manager.full)
        for _ in range(2):
            self.assertEqual(w.drain_preparation_requests(), [])
            self.assertEqual(manager.jobs[request_id], original)
        initial_horizon = driver.certified_horizon_mm
        for _ in range(240):
            self.step_successor(row)
            self.assertEqual(w.drain_preparation_requests(), [])
            if driver.y > 1 and driver.mode=='waiting':
                break
        self.assertAlmostEqual(driver.y,initial_horizon,places=5)
        self.assertEqual((driver.v,driver.a),(0.,0.))
        self.assertEqual(driver.reason,'await_checked_continuation')
        lead = w.vehicles['leader']
        lead['pose_mm_rad'][0] += 20.
        with self.assertRaises(RuntimeError):
            w.release_resource('leader','corridor',w.now)
        # Mid-leg clear of both rooms still does not retire the leader's return.
        lead['pose_mm_rad'][0] = 2400.
        with self.assertRaises(RuntimeError):
            w.release_resource('leader','corridor',w.now)
        self.assertTrue(w.departures.staged('successor'))
        self.assertEqual(w.drain_preparation_requests(), [])
        self.return_leader()
        self.assertEqual(w.departures.handovers,1)
        self.assertFalse(w.departures.staged('successor'))
        self.assertTrue(row['gate'].permit(w.now))
        self.assertEqual(w.resources.queues['corridor'],['fifo'])
        job, = w.drain_preparation_requests()
        self.assertEqual(job,original)
        self.assertEqual(job['fence']['action_sha256'],preparation_digest(self.action))
        self.assertEqual(w.drain_preparation_requests(),[])
        self.assertTrue(manager.accept(response)['accepted'])
        # Deterministic worker completions in between source steps, identical mission and driver.
        for _ in range(240):
            manager.before_tick()
            for next_job in manager.drain():
                self.assertTrue(manager.accept(background.prepare_route(next_job,ctx))['accepted'])
            self.step_successor(row)
            if driver.y > initial_horizon+1:break
        self.assertGreater(driver.y,initial_horizon+1)
        self.assertIs(driver,row['driver'])
        self.assertEqual(row['action'],self.action)
        self.assertTrue(driver.joined_nominal)
        # Source-clear rest outside both depot polygons admits the waiting FIFO head.
        row.update(driver=None,pose_mm_rad=[6400.,0.,0.])
        w.release_resource('successor','corridor',w.now)
        self.assertEqual(w.resources.owners['corridor'],'fifo')

    def test_bounded_gate_rejects_stale_leader_and_wider_follower_horizon(self):
        w = self.world
        row = self.stage()
        w.vehicles['leader']['leg_id'] += 1
        with self.assertRaisesRegex(RuntimeError,'Private departure'):
            row['gate'].permit(w.now)
        w.vehicles['leader']['leg_id'] -= 1
        original = row['action']
        row['action'] = {**original, 'terminal':{'kind':'home','mission_id':'other'}}
        with self.assertRaises(RuntimeError):
            row['gate'].permit(w.now)
        row['action'] = original
        row['driver'].certified_horizon_mm += 1
        with self.assertRaisesRegex(RuntimeError,'Private departure'):
            row['gate'].permit(w.now)
        self.assertEqual(w.drain_preparation_requests(),[])

    def test_finishing_home_promotes_before_the_leader_action_is_replaced(self):
        w = self.world
        lead = w.vehicles['leader']
        lead['action']['terminal'] = {'kind':'home','mission_id':'home-mission'}
        self.stage()
        driver = lead['driver']
        driver.mode, driver.y = 'arrived', driver.goal
        driver.perception_limit, driver.perception_audit, driver.profile_checks = {}, {}, []
        driver.recorded = []
        # Synthetic completion record along the same immutable leader loop.
        for progress in [0., *driver.path.ends]:
            moving = 0. < progress < driver.goal
            pose, velocity, acceleration = driver.path.pva(progress,50. if moving else 0.,0.)
            driver.recorded.append({'time_s':round(progress/50.,3),'pose_mm_rad':pose,
                                    'velocity_mm_rad_s':velocity,'acceleration_mm_rad_s2':acceleration})
        lead['markers'] = []
        w.driver_checks = []
        results = []
        w.planner.on_action_result = lambda identity, action, result, now:results.append(result)
        w.now = driver.recorded[-1]['time_s']
        w.finish_drive('leader')
        self.assertEqual(results[0]['terminal'],{'kind':'home','mission_id':'home-mission'})
        self.assertIsNone(lead['driver'])
        self.assertIsNone(lead['action'])
        self.assertEqual(w.departures.handovers,1)
        self.assertEqual(w.resources.owners['corridor'],'successor')
        self.assertTrue(w.vehicles['successor']['gate'].permit(w.now))

    def test_vacated_home_surfaces_stay_excluded_across_the_actual_handover(self):
        w = self.world
        leader_map = w.depot_maps['leader']
        leader_map.set_own_grant(w.resources.own_grants('leader'))
        half = w.nav.envelope['length_mm']/2
        observer = [0.,0.,0.]
        successor_home_return = [0.,4000.-half]
        self.assertTrue(leader_map.matches(observer,successor_home_return))
        self.stage()
        w.check_depot_invariant()
        self.assertFalse(leader_map.matches(observer,successor_home_return))
        self.return_leader()
        other_map = w.depot_maps['successor']
        other_map.set_own_grant(w.resources.own_grants('successor'))
        leader_home_return = [0.,half]
        w.now = w.sensor['stale_after_s']
        w.check_depot_invariant()
        self.assertFalse(other_map.matches(observer,leader_home_return))
        w.now += 2*w.dt
        w.check_depot_invariant()
        self.assertTrue(other_map.matches(observer,leader_home_return))
