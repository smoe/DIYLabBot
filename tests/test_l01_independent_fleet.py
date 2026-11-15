"""Independent clocks, explicit observations, parallel leases and native evidence."""
import copy,json,math,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import l01_independent_fleet as fleet

class IndependentSourceTests(unittest.TestCase):
    def test_guards_and_existing_limits_cannot_be_relaxed(self):
        source=json.loads(fleet.SOURCE.read_text());fleet.validate_config(source)
        for key in source['guards']:
            bad=copy.deepcopy(source);bad['guards'][key]=False
            with self.assertRaises(ValueError):fleet.validate_config(bad)
        for key,value in [('minimum_added_clearance_mm',14),('workspace_interval_step_s',float('nan'))]:
            bad=copy.deepcopy(source);bad[key]=value
            with self.assertRaises(ValueError):fleet.validate_config(bad)
    def test_time_never_substitutes_for_a_positive_workplace_observation(self):
        events=[{'station':'CF01','time_s':0,'status':'occupied','evidence':'synthetic_demo_fixture'}]
        self.assertFalse(fleet.person_clear_observed(events,'CF01',1e12))
        events.append({'station':'CF01','time_s':300,'status':'person_clear','evidence':'synthetic_demo_fixture'})
        self.assertFalse(fleet.person_clear_observed(events,'CF01',299.999));self.assertTrue(fleet.person_clear_observed(events,'CF01',300))
        events.append({'station':'CF01','time_s':301,'status':'unknown','evidence':'synthetic_demo_fixture'})
        self.assertFalse(fleet.person_clear_observed(events,'CF01',302))
    def test_only_numerically_equivalent_resting_frames_are_canonicalized(self):
        a=fleet.as_point(0,[1000.,2000.,1.],[0.,0.,0.],[0.,0.,0.])
        b=fleet.as_point(1,[math.nextafter(1000.,math.inf),2000.,1.],[0.,0.,0.],[0.,0.,0.])
        points=[a];fleet.append_point(points,b);self.assertEqual(points[-1][fleet.F[0]],a[fleet.F[0]])
        c=fleet.as_point(2,[1000.001,2000.,1.],[0.,0.,0.],[0.,0.,0.]);fleet.append_point(points,c)
        self.assertEqual(points[-1][fleet.F[0]][0],1000.001)
        d=fleet.as_point(3,[math.nextafter(1000.001,math.inf),2000.,1.],[.01,0.,0.],[0.,0.,0.]);fleet.append_point(points,d)
        self.assertNotEqual(points[-1][fleet.F[0]][0],points[-2][fleet.F[0]][0])
    def test_conflicting_observations_are_rejected(self):
        source=json.loads(fleet.SOURCE.read_text());source['workplace_observations'].append(copy.deepcopy(source['workplace_observations'][0]))
        with self.assertRaises(ValueError):fleet.validate_config(source)

class IndependentProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=fleet.OUT/'independent-fleet.json'
        if not path.exists():raise unittest.SkipTest('Build the independent fleet and its native evidence locally')
        cls.r=json.loads(path.read_text());fleet.floor.verify(cls.r['source_files_sha256']);cls.base=json.loads((ROOT/'cad/tr01-workcell/shared-build-report.json').read_text());cls.program=json.loads((ROOT/cls.base['files']['program']).read_text());cls.curves=[fleet.floor.motion.Curve([fleet.as_point(*p) for p in v['points']]) for v in cls.r['traffic']['trajectories']]
        cls.kin={a:fleet.serial.workcell.actor_source(cls.program['definition'],a)[2] for a in cls.program['actors']}
    def test_new_occupation_during_an_active_job_aborts_generation(self):
        events=copy.deepcopy(self.r['workplace_observations']);events.append({'time_s':1,'station':'DNA','status':'occupied','evidence':'synthetic_demo_fixture'})
        with self.assertRaisesRegex(ValueError,'invalidates an active station job'):fleet.compile_program(observations=events)
    def test_departure_and_arrival_do_not_wait_for_the_other_two(self):
        r=self.r;departures=[t['load_complete'] for t in r['tracks']];self.assertEqual(len(set(departures)),3)
        first_unload=min(j['start_s'] for j in r['jobs'] if j['direction']=='unload');self.assertLess(first_unload,max(t['arrival_s'] for t in r['tracks']))
        self.assertLess(min(departures),max(j['end_s'] for j in r['jobs'] if j['direction']=='load'))
        self.assertLess(r['duration_s'],r['statistics']['serial_duration_s'])
    def test_parallel_arms_and_driving_are_actual_overlapping_intervals(self):
        r=self.r;arms=[p for p in r['phases'] if p['kind']=='arm'];samples=[p['start_s']+.001 for p in arms];maximum=max(sum(p['start_s']<=t<p['start_s']+p['duration_s'] for p in arms) for t in samples);self.assertEqual(maximum,3)
        found=False
        for a in arms:
            for i,tr in enumerate(r['tracks']):
                if tr['id']==a['vehicle']:continue
                for p in tr['phases']:
                    if p['kind']!='traffic':continue
                    start=max(a['start_s'],p['start_s']);end=min(a['start_s']+a['duration_s'],p['start_s']+p['duration_s'])
                    if end>start and max(fleet.floor.extrema(self.curves[i],start,end,order=1)['max'][:2])>1e-5:found=True
        self.assertTrue(found)
    def test_person_clear_and_exclusive_resources_cover_every_job(self):
        for j in self.r['jobs']:
            if j['direction']=='unload':
                outbound=next(k for k in self.r['jobs'] if k['station']==j['station'] and k['direction']=='load');self.assertLessEqual(outbound['end_s'],j['start_s'])
            self.assertTrue(fleet.person_clear_observed(self.r['workplace_observations'],j['station'],j['start_s']))
            for other in self.r['jobs']:
                if other is j or min(j['end_s'],other['end_s'])<=max(j['start_s'],other['start_s']):continue
                self.assertNotEqual(j['actor'],other['actor']);self.assertNotEqual(j['area'],other['area'])
        cf=next(j for j in self.r['jobs'] if j['station']=='CF01' and j['direction']=='load');self.assertEqual(cf['start_s'],300)
        for p in self.r['phases']:
            if p['kind'] not in ('dock','arm'):continue
            area=self.program['definition']['stations'][p['station']]['work_area'];lease=p['state']['benches'][area];self.assertEqual(lease['vehicle'],p['vehicle']);self.assertTrue(lease['person_clear'])
    def test_opposing_traffic_reuses_anonymous_scan_and_yield_rule(self):
        events=[e for t in self.r['traffic']['trajectories'] for e in t['events']];self.assertTrue(any(e['event']=='local_yield_and_reroute' for e in events));self.assertTrue(all(e['peer_data_used'] is False for e in events));self.assertFalse(self.r['traffic']['shared_positions'])
        for tr in self.r['traffic']['trajectories']:
            for k in ('linear','angular','carried_points'):
                for name,limit in fleet.floor.load()['limits'][k].items():self.assertLessEqual(tr['dynamics'][k][name],limit*(1+1e-8))
    def test_reference_docking_and_cargo_handoffs_preserve_world_poses(self):
        ids=[m['id'] for m in self.r['missions']];F=fleet.F
        def cargo(owner,q,car):
            if owner['type']=='bench':return owner['matrix']
            if owner['type']=='car':return fleet.serial.mm(fleet.serial.placement([*car[:2],0],car[2]),owner['attachment'])
            return fleet.serial.mm(self.kin[owner['actor']].tool([math.degrees(v) for v in q]),owner['attachment'])
        for track in self.r['tracks']:
            i=ids.index(track['id']);parts=track['phases']
            for n,p in enumerate(parts):
                if p['kind']=='dock':
                    ref=fleet.floor.motion.Curve(fleet.floor.canonical(self.program['approaches'][p['station']]['points']))
                    for u in (.17,.37,.79):
                        actual=self.curves[i].evaluate(p['start_s']+p['duration_s']*u)[F[0]];wanted=ref.evaluate(p['duration_s']*(1-u if p['reverse'] else u))[F[0]];wanted[2]+=p['yaw_offset'];self.assertLess(math.dist(actual,wanted),1e-5)
                if p['kind']!='arm' or p['part']!='loaded':continue
                actor=p['actor'];ref=self.program['stations'][p['station']]['transfers'][p['direction']]['loaded'];before=parts[n-1]['state'];after=parts[n+2]['state'];start=p['start_s'];end=start+p['duration_s']
                a=cargo(before['owners'][i],before['joints'][actor],self.curves[i].evaluate(start)[F[0]]);b=cargo(p['state']['owners'][i],ref['points'][0][F[0]],self.curves[i].evaluate(start)[F[0]])
                c=cargo(p['state']['owners'][i],ref['points'][-1][F[0]],self.curves[i].evaluate(end)[F[0]]);d=cargo(after['owners'][i],after['joints'][actor],self.curves[i].evaluate(end)[F[0]])
                for x,y in ((a,b),(c,d)):self.assertLess(max(abs(x[k][j]-y[k][j]) for k in range(4) for j in range(4)),.001)
    def test_complete_fresh_native_proof_covers_all_three_new_routes(self):
        result=fleet.validated();proof=json.loads((fleet.OUT/'independent-fleet-clearance.json').read_text());self.assertEqual(proof['program_sha256'],self.r['program_sha256']);self.assertTrue(proof['passed']);self.assertTrue(all(r['passed'] for r in proof['native']['routes']));self.assertEqual(len(proof['native']['routes']),3);self.assertTrue(all(v['passed'] and v['moving_episodes'] for v in proof['post_export_motion'].values()))
        self.assertGreaterEqual(proof['summary']['minimum_added_obstacle_clearance_mm'],15)
        for i in range(3):
            leaves=sorted((p for p in proof['intervals'] if p['kind']=='car_person' and p['vehicles']==[i]),key=lambda p:p['start_s']);self.assertEqual(leaves[0]['start_s'],0);self.assertAlmostEqual(leaves[-1]['end_s'],result['duration_s']);self.assertTrue(all(abs(a['end_s']-b['start_s'])<1e-8 for a,b in zip(leaves,leaves[1:])))

class NativeContextTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        import render_tr01_workcell as render
        self.render=render;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.context=self.root/'exports/worktrees/fixture';out=self.context/'exports/tr01-workcell';out.mkdir(parents=True)
        for name in render.PRESENTATION_SOURCES+('scripts/check_l01_independent_fleet_freecad.py','model/robot.json'):
            for tree in (self.root,self.context):
                p=tree/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'checked source')
        (out/'independent-fleet.json').write_text(json.dumps({'program_sha256':'checked','source_files_sha256':{'model/robot.json':render.file_digest(self.root/'model/robot.json'),'cad/lab-layout-l01/shared-build-report.json':'original namespace'}}))
        (out/'daylight-shell.json').write_text(json.dumps({'source_files_sha256':{}}));self.proof={'passed':True,'program_sha256':'checked','checker_sha256':render.file_digest(self.root/'scripts/check_l01_independent_fleet_freecad.py')};(out/'independent-fleet-clearance.json').write_text(json.dumps(self.proof))
    def test_generated_index_aliases_are_preserved_while_leading_sources_match(self):
        self.assertEqual(self.render.checked_native_context(self.context,self.root),self.context)
    def test_changed_geometry_source_or_presentation_is_not_delegated(self):
        (self.root/'model/robot.json').write_text('changed')
        with self.assertRaisesRegex(ValueError,'not source-equivalent'):self.render.checked_native_context(self.context,self.root)
        (self.root/'model/robot.json').write_bytes(b'checked source');(self.context/'scripts/tr01_workcell_player.html').write_text('changed')
        with self.assertRaisesRegex(ValueError,'presentation differs'):self.render.checked_native_context(self.context,self.root)
    def test_failed_native_proof_is_not_delegated(self):
        self.proof['passed']=False;(self.context/'exports/tr01-workcell/independent-fleet-clearance.json').write_text(json.dumps(self.proof))
        with self.assertRaisesRegex(ValueError,'proof required'):self.render.checked_native_context(self.context,self.root)

if __name__=='__main__':unittest.main()
