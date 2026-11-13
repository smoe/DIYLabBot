import copy,json,math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import l01_fleet_handoffs as fleet

class FleetHandoffs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=fleet.derive();cls.program=json.loads((fleet.ROOT/cls.result['workcell_report']['files']['program']).read_text());cls.kin={name:fleet.workcell.actor_source(cls.program['definition'],name)[2] for name in cls.program['actors']}
    def cargo_matrix(self,state,i):
        owner=state['owners'][i]
        if owner['type']=='bench':return owner['matrix']
        if owner['type']=='car':return fleet.mm(fleet.placement([*state['cars'][i][:2],0],state['cars'][i][2]),owner['attachment'])
        return fleet.mm(self.kin[owner['actor']].tool([math.degrees(v) for v in state['joints'][owner['actor']]]),owner['attachment'])
    def test_each_mission_loads_then_delivers_to_its_distinct_station(self):
        r=self.result;self.assertEqual(len(r['events']),36);self.assertEqual(len(set(r['cargo_ids'].values())),3)
        for i,m in enumerate(r['missions']):
            phases=[p for p in r['phases'] if p['kind']=='arm' and p['part']=='loaded' and p['vehicle']==m['id']]
            self.assertEqual([(p['direction'],p['station']) for p in phases],[('load',m['from']),('unload',m['to'])])
            self.assertEqual(r['phases'][0]['state']['owners'][i]['station'],m['from']);self.assertEqual(r['phases'][-1]['state']['owners'][i]['station'],m['to'])
    def test_exclusive_lease_and_waiting_vehicles_through_all_handoffs(self):
        r=self.result;areas=self.program['definition']['stations']
        for phase in r['phases']:
            state=phase['state']
            self.assertLessEqual(sum(o['type']=='arm' for o in state['owners']),1)
            if phase['kind'] in ('dock','arm'):
                lease=state['benches'][areas[phase['station']]['work_area']];self.assertTrue(lease['person_clear']);self.assertEqual(lease['vehicle'],phase['vehicle']);self.assertEqual(lease['status'],'reserved')
            if phase['kind']=='traffic':
                self.assertTrue(all(o['type']=='car' for o in state['owners']));self.assertEqual(state['covers'],[True]*3);self.assertTrue(all(v['status']=='closed' for v in state['benches'].values()))
                for actor,q in state['joints'].items():self.assertLess(max(abs(a-math.radians(b)) for a,b in zip(q,self.program['actors'][actor]['park'])),1e-6)
    def test_owner_changes_and_phase_boundaries_preserve_pose(self):
        r=self.result;traffic=fleet.traffic.validated_result();ids=[m['id'] for m in r['missions']]
        for phase,next_phase in zip(r['phases'],r['phases'][1:]):
            state=copy.deepcopy(phase['state'])
            if phase['kind']=='dock':
                i=ids.index(phase['vehicle']);p=self.program['approaches'][phase['station']]['points'][0 if phase['reverse'] else -1]['pose_mm_rad'];state['cars'][i]=[p[0],p[1],p[2]+phase['yaw_offset']]
            elif phase['kind']=='arm':state['joints'][phase['actor']]=self.program['stations'][phase['station']]['transfers'][phase['direction']][phase['part']]['points'][-1][fleet.F[0]]
            elif phase['kind']=='traffic':state['cars']=[v['pose_mm_rad'] for v in traffic['frames'][-1]['vehicles']]
            for i in range(3):
                a=self.cargo_matrix(state,i);b=self.cargo_matrix(next_phase['state'],i);self.assertLess(max(abs(a[k][j]-b[k][j]) for k in range(4) for j in range(4)),.001)
                self.assertLess(math.dist(state['cars'][i][:2],next_phase['state']['cars'][i][:2]),1e-6)
    def test_effects_follow_named_observations_not_the_wait_interval(self):
        phases=self.result['phases'];events=self.result['events'];ids=[m['id'] for m in self.result['missions']]
        for phase,next_phase in zip(phases,phases[1:]):
            if phase['kind']!='event':continue
            event=next(e for e in events if e['event']==phase['event'] and e['vehicle']==phase['vehicle'] and abs(e['time_s']-phase['start_s']-phase['duration_s'])<1e-7)
            self.assertEqual(event['evidence'],'synthetic_demo_fixture');i=ids.index(phase['vehicle']);before=phase['state'];after=next_phase['state']
            if phase['event']=='person_clear_and_exclusive_work_area_reserved':
                area=self.program['definition']['stations'][phase['station']]['work_area'];self.assertFalse(before['benches'][area]['person_clear']);self.assertTrue(after['benches'][area]['person_clear'])
            elif phase['event']=='grip_and_cargo_identity_confirmed':self.assertNotEqual(before['owners'][i]['type'],'arm');self.assertEqual(after['owners'][i]['type'],'arm')
            elif phase['event']=='placement_and_cargo_identity_confirmed':self.assertEqual(before['owners'][i]['type'],'arm');self.assertNotEqual(after['owners'][i]['type'],'arm')
            elif phase['event']=='cover_removed_and_person_outside_arm_envelope':self.assertTrue(before['covers'][i]);self.assertFalse(after['covers'][i])
    def test_reused_motion_and_additional_obstacle_proof_are_pinned(self):
        r=fleet.validated();self.assertGreaterEqual(r['clearance_summary']['minimum_added_obstacle_clearance_mm'],15);self.assertEqual(r['clearance_summary']['added_obstacle_checks'],30)
        self.assertIn('discrete',r['clearance_summary']['original_static_arm_proof'])
        self.assertAlmostEqual(sum(p['duration_s'] for p in r['phases']),r['duration_s'],places=9)
        self.assertAlmostEqual(r['traffic_end_s']-r['traffic_start_s'],fleet.traffic.validated_result()['duration_s'],places=9)
if __name__=='__main__':unittest.main()
