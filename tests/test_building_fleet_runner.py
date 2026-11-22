"""Static base graph splicing and runtime boundaries, without CAD dependency."""
import copy
import gzip
import json
import math
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_runner import intersections,splice_hub_paths,RouteGraph,WorldRunner,EvidenceWriter,compile_program
import building_fleet_runner as runner
from building_fleet_routes import reverse_centreline


class SpliceTests(unittest.TestCase):
    def test_common_corridor_is_spliced_before_hub_without_u_turn(self):
        a=[[0,0],[1000,0],[3000,0],[4000,0]]
        b=[[1000,1000],[1000,0],[2000,0],[4000,0]]
        self.assertEqual(splice_hub_paths(a,b),[[0,0],[1000,0],[1000,1000]])

    def test_crossing_segments_create_only_existing_subsegments(self):
        a=[[0,0],[2000,0],[4000,0]]
        b=[[1000,1000],[1000,-1000],[4000,0]]
        self.assertEqual(splice_hub_paths(a,b),[[0,0],[1000,0],[1000,1000]])
        self.assertEqual(len(intersections([0,0],[10,0],[5,0],[15,0])),2)

    def test_disconnected_or_different_hubs_are_rejected(self):
        with self.assertRaises(ValueError):splice_hub_paths([[0,0],[1,0]],[[0,1],[1,1]])


class FakeNavigation:
    def __init__(self):
        self.waits={'EG':[[4000,0,0]]};self.homes={};self.inspections={};self._route_cache={}
    def route(self,level,start,end):
        row={'level':level,'points_mm':[list(start),list(end)],'resources':[],'zone_segments':[],
             'portal_certificates':[],'curve_qualified':False}
        self._route_cache[level,tuple(start),tuple(end)]=row
        self._route_cache[level,tuple(end),tuple(start)]=reverse_centreline(row)
        return copy.deepcopy(row)
    def _own_right(self,row):return copy.deepcopy(row)


class StaticGraphTests(unittest.TestCase):
    def test_catalog_cannot_expand_after_world_begins(self):
        graph=RouteGraph(FakeNavigation());graph.add_endpoint('EG',[0,0]);graph.add_endpoint('EG',[1000,0]);graph.prepare()
        self.assertEqual(graph.route('EG',[0,0],[1000,0])['points_mm'],[[0,0],[1000,0]])
        with self.assertRaises(ValueError):graph.add_endpoint('EG',[2000,100])
        with self.assertRaises(ValueError):graph.route('EG',[2000,100],[1000,0])
        self.assertEqual(len(graph.base_routes()),4)


class RuntimeBoundaryTests(unittest.TestCase):
    def stub(self):
        world=object.__new__(WorldRunner)
        world.source={'geometry':{'localization_tolerance_mm':10}}
        world.nav=SimpleNamespace(envelope={'length_mm':512,'width_mm':412},radius=math.hypot(256,206),
                                  reserve=85,level_z={'EG':0})
        world.vehicles={'BF01':{'pose_mm_rad':[0.,0.,0.],'level':'EG','z_mm':0.,'phase':'home',
            'aboard':False,'mission_pending':False,'home':{'pose_mm_rad':[0.,0.,0.],'level':'EG'},
            'vehicle_id':'BF01','driver':None,'episodes':[],'action':None,'leg_id':None,'hold_reason':'home',
            'hold_condition':'observed_final_home','peer_positions':['never-forward-this']}}
        return world

    def test_vehicle_snapshot_contains_only_own_localization_and_status(self):
        world=self.stub();own=world.own('BF01')
        self.assertEqual(set(own),{'vehicle_id','pose_mm_rad','level','z_mm','phase','aboard','home','mission_pending'})
        self.assertNotIn('peer',repr(own));self.assertTrue(own['home'])
        world.vehicles['BF01']['pose_mm_rad'][0]=100
        self.assertFalse(world.own('BF01')['home'])

    def test_between_tick_functional_arrival_is_not_hidden_in_a_driving_episode(self):
        world=self.stub();world.vehicles['BF01']['action']={'terminal':{'kind':'home'}}
        world.vehicles['BF01']['leg_id']=1
        driver=SimpleNamespace(mode='arrived',reason='clear_scan')
        def point(t,x,v):return{'time_s':t,'pose_mm_rad':[x,0.,0.],
            'velocity_mm_rad_s':[v,0.,0.],'acceleration_mm_rad_s2':[0.,0.,0.]}
        world.append_episode('BF01',0,.05,[point(0,0,100),point(.04,2,0),point(.05,2,0)],driver,{'phase':'idle'})
        episodes=world.vehicles['BF01']['episodes'];self.assertEqual([e['mode']for e in episodes],['driving','hold'])
        self.assertEqual(episodes[0]['end_s'],.04);self.assertEqual(episodes[1]['start_s'],.04)
        self.assertEqual(episodes[1]['hold_reason'],'home')
        self.assertTrue(runner.floor.no_stop(runner.floor.motion.Curve(runner.floor.canonical(episodes[0]['points'])))['passed'])

    def test_body_clear_cannot_be_acknowledged_from_inside_a_port(self):
        world=self.stub();port={'id':'P','level_id':'EG','z_mm':0,'plane_x_mm':700.,
            'wall_thickness_mm':180.,'exit_eye_mm':[1000.,0.,0.]}
        world.lift=SimpleNamespace(ports={'P':port})
        world.vehicles['BF01']['pose_mm_rad']=[1000.,0.,0.]
        with self.assertRaises(RuntimeError):world.require_port_body_clear('BF01','P')
        world.vehicles['BF01']['pose_mm_rad']=[1200.,0.,0.]
        world.require_port_body_clear('BF01','P')
        world.vehicles['BF01']['z_mm']=4250
        with self.assertRaises(RuntimeError):world.require_port_body_clear('BF01','P')

    def test_alighting_metadata_ends_after_actual_body_clear_without_pva_break(self):
        world=self.stub();row=world.vehicles['BF01']
        row['aboard']=True;row['leg_id']=1
        row['action']={'terminal':{'kind':'capacity_wait'},'lift_phase':{'kind':'alighting','slot':0},
            'port_id':'P','cabin_slot':0,'reverse':False}
        driver=SimpleNamespace(mode='waiting',reason='local_obstacle')
        def point(t,x,v):return{'time_s':t,'pose_mm_rad':[x,0.,0.],
            'velocity_mm_rad_s':[v,0.,0.],'acceleration_mm_rad_s2':[0.,0.,0.]}
        world.append_episode('BF01',0,.05,[point(0,0,100),point(.05,5,100)],driver,{'phase':'alighting'})
        self.assertEqual(row['episodes'][0]['lift_phase'],'alighting')
        # The world observes and acknowledges full body-clear after this
        # frame. Its next drive/hold frames are ordinary floor episodes.
        row['aboard']=False
        world.append_episode('BF01',.05,.1,[point(.05,5,100),point(.1,10,0)],driver,{'phase':'idle'})
        world.append_episode('BF01',.1,.15,[point(.1,10,0),point(.15,10,0)],driver,{'phase':'idle'})
        self.assertEqual(len(row['episodes']),3)
        self.assertNotIn('lift_phase',row['episodes'][1]);self.assertNotIn('lift_phase',row['episodes'][2])
        self.assertEqual(row['episodes'][2]['hold_reason'],'protective_stop')
        self.assertEqual(row['episodes'][0]['points'][-1],row['episodes'][1]['points'][0])
        self.assertEqual(row['episodes'][1]['points'][-1],row['episodes'][2]['points'][0])

    def test_repeated_source_door_passages_have_monotone_own_markers(self):
        world=self.stub();world.route_door_ids=set()
        world.nav.portals={'EG':[{'opening':'D','centre_mm':[0,0],'normal':[1,0],
            'tangent':[0,1],'opening_width_mm':4000}]}
        world.nav.mesh=SimpleNamespace(manifest={'objects':[{'id':'Door','opening_id':'D',
            'mechanism':'room_door','level_id':'EG','reference_state':'open'}]})
        path=runner.Path([[-1000,0],[1000,0],[1000,1000],[-1000,1000],[-1000,0],[1000,0]])
        markers=world.door_markers('EG',path)
        self.assertEqual(len(markers),3)
        self.assertEqual(world.route_door_ids,{'Door'})
        self.assertEqual([m['progress_mm']for m in markers],sorted(m['progress_mm']for m in markers))
        self.assertGreater(markers[-1]['progress_mm'],markers[0]['progress_mm']+5000)

    def test_runtime_requires_a_canonical_geometry_checker(self):
        with self.assertRaisesRegex(ValueError,'Canonical'):
            WorldRunner({},None,None,None,None)

    def test_complete_program_rejects_a_negative_actual_range_margin(self):
        world=object.__new__(WorldRunner);world.completed=lambda:True;world.sensor={'range_mm':2200}
        world.driver_checks=[{'perception_limit':{'required_range_mm':1000},
            'perception_audit':{'checks':1,'minimum_range_margin_mm':-1.}}]
        with self.assertRaisesRegex(RuntimeError,'every actual'):world.program()

    def test_public_compile_preserves_original_seed_on_runtime_failure(self):
        source=runner.model.load();nav=SimpleNamespace(homes={'BF%02d'%i:{}for i in range(1,21)},config=source)
        with tempfile.TemporaryDirectory(dir=runner.model.ROOT/'exports')as folder:
            with patch.object(runner,'WorldRunner',side_effect=RuntimeError('fixture runtime failure')):
                with self.assertRaisesRegex(RuntimeError,'fixture'):
                    compile_program(source,nav,folder,prepared=(object(),object(),object()),geometry_checker=lambda *a:{'passed':True})
            report=json.loads((Path(folder)/'runtime-failure.json').read_text())
            self.assertEqual(report['seed'],source['missions']['seed']);self.assertFalse(report['passed'])
            self.assertFalse(report['complete_fleet_run']);self.assertFalse((Path(folder)/'program.json').exists())

    def test_own_input_evidence_binds_exact_clocks_and_original_capture(self):
        import l01_local_traffic
        with tempfile.TemporaryDirectory(dir=runner.model.ROOT/'exports')as folder:
            writer=EvidenceWriter(folder);clock=l01_local_traffic.braking(100,0,500,1000)
            identity=writer.clock(clock);self.assertEqual(identity,writer.clock(clock))
            writer.write('scan',vehicle_id='BF01',captured_s=.1,pose_mm_rad=[1,2,0],level='EG',z_mm=0,returns_local_mm=[[0,500]])
            proof=writer.close();self.assertEqual(proof['counts'],{'stop_clock':1,'scan':1})
            self.assertEqual(proof['sha256'],runner.model.digest(Path(folder)/'own-controller-observations.jsonl.gz'))
            rows=[json.loads(line)for line in gzip.decompress((Path(folder)/'own-controller-observations.jsonl.gz').read_bytes()).decode().splitlines()]
            self.assertEqual(rows[0]['points'],clock.points);self.assertEqual(rows[1]['captured_s'],.1)

    def test_keyboard_interruption_closes_raw_evidence_and_preserves_original_pins(self):
        source=runner.model.load();nav=SimpleNamespace(homes={'BF%02d'%i:{}for i in range(1,21)},config=source)
        with tempfile.TemporaryDirectory(dir=runner.model.ROOT/'exports')as folder:
            class InterruptedWorld:
                def __init__(self,*args,**kwargs):
                    self.evidence=EvidenceWriter(kwargs['output_dir']);self.now=.05;self.vehicles={}
                def run(self):
                    self.evidence.write('scan',vehicle_id='BF01',captured_s=0,pose_mm_rad=[0,0,0],
                        level='EG',z_mm=0,returns_local_mm=[])
                    raise KeyboardInterrupt()
            with patch.object(runner,'WorldRunner',InterruptedWorld):
                with self.assertRaises(KeyboardInterrupt):
                    compile_program(source,nav,folder,prepared=(object(),object(),object()),geometry_checker=lambda *a:{'passed':True})
            path=Path(folder);failure=json.loads((path/'runtime-failure.json').read_text())
            self.assertTrue(failure['interrupted']);self.assertFalse(failure['complete_fleet_run'])
            self.assertEqual(failure['seed'],source['missions']['seed'])
            self.assertEqual(failure['source_files_sha256'],json.loads((path/'runtime-source-start.json').read_text()))
            rows=gzip.decompress((path/'own-controller-observations.jsonl.gz').read_bytes()).decode().splitlines()
            self.assertEqual(len(rows),1);self.assertFalse((path/'program.json').exists())


if __name__=='__main__':unittest.main()
