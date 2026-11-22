"""Pinned native-vehicle inputs must fail closed before loading any CAD runtime."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import export_building_fleet_vehicle_freecad as exporter
import tr01_camera_model as kit


class NativeVehicleInputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        names=['model/tr01-awareness-camera.shared.json','model/tr01-awareness-camera.schema.json','model/sample-transport-tr01.shared.json','model/camera.schema.json','scripts/tr01_camera_model.py','scripts/build_tr01_awareness.py','scripts/build_tr01_awareness_freecad.py']
        pins={}
        for name in names:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p);pins[name]=kit.digest(p)
        # Synthetic bytes deliberately are not executed. This fixture checks the
        # proof-consumer's integrity boundary, not a fabricated native CAD pass.
        for n in ['freecad','solidcraft']:(self.root/n).write_bytes(('synthetic-'+n).encode())
        source=kit.expanded(kit.load())
        self.report={'format':'solidcraftbot.tr01-awareness-cross-cad/1','passed':True,'source_files_sha256':pins,'files':{'freecad':'freecad','solidcraft':'solidcraft'},'artifact_sha256':{n:kit.digest(self.root/n)for n in ['freecad','solidcraft']},'body_count':len(source['bodies']),'camera_frame':source['camera_frame']}
        self.path=self.root/'proof.json';self.write()

    def write(self):self.path.write_text(json.dumps(self.report))

    def test_fixture_integrity_without_loading_cad(self):
        before=sys.modules.get('FreeCAD')
        self.assertEqual(exporter.checked_camera_report(self.path,self.root)['body_count'],35)
        self.assertIs(sys.modules.get('FreeCAD'),before)

    def test_failed_stale_or_incomplete_proof_rejected(self):
        changes=[lambda d:d.update(passed=False),lambda d:d.update(format='other'),lambda d:d.update(body_count=34),lambda d:d['source_files_sha256'].pop('model/sample-transport-tr01.shared.json'),lambda d:d['files'].pop('solidcraft'),lambda d:d['camera_frame'].update(origin_mm=[0,0,0])]
        original=copy.deepcopy(self.report)
        for change in changes:
            with self.subTest(change=change):
                self.report=copy.deepcopy(original);change(self.report);self.write()
                with self.assertRaises(ValueError):exporter.checked_camera_report(self.path,self.root)

    def test_changed_source_and_artifact_bytes_rejected(self):
        for name in ['model/tr01-awareness-camera.shared.json','freecad']:
            with self.subTest(name=name):
                p=self.root/name;before=p.read_bytes();p.write_bytes(before+b'changed')
                with self.assertRaises(ValueError):exporter.checked_camera_report(self.path,self.root)
                p.write_bytes(before)

    def test_external_paths_and_nonfinite_tolerances_rejected(self):
        self.report['files']['freecad']='../outside';self.write()
        with self.assertRaises(ValueError):exporter.checked_camera_report(self.path,self.root)
        for value in [0,-1,True,float('nan'),float('inf'),3]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):exporter.export('unused','unused',deflection_mm=value)


class NativeIntervalContractTests(unittest.TestCase):
    """Shared polynomial bounds and source schedule evaluation without CAD."""
    @staticmethod
    def module():
        import check_building_fleet_freecad
        return check_building_fleet_freecad

    def test_spatial_supercover_has_no_near_pair_omission(self):
        import random
        c=self.module();rng=random.Random(715)
        boxes={str(i):{'min':[rng.uniform(-10000,10000)for _ in range(3)]}for i in range(100)}
        for box in boxes.values():box['max']=[v+rng.uniform(1,5000)for v in box['min']]
        index=c.SpatialIndex(boxes,maximum_cells=8)
        for _ in range(30):
            point=[rng.uniform(-10000,10000)for _ in range(3)];query={'min':point,'max':[v+100 for v in point]};found=index.query(c.inflate_box(query,85))
            self.assertTrue({name for name,box in boxes.items()if c.box_distance(query,box)<=85}<=found)

    def test_quintic_endpoints_and_invalid_time(self):
        c=self.module();self.assertEqual(c.quintic_fraction(1,3,1),0);self.assertEqual(c.quintic_fraction(1,3,3),1)
        self.assertAlmostEqual(c.quintic_fraction(1,3,2),.5)
        for values in [(1,1,1),(3,1,1),(0,1,float('nan'))]:
            with self.assertRaises(ValueError):c.quintic_fraction(*values)

    def test_shared_curve_extrema_enclose_interior_pva_overshoot(self):
        c=self.module();points=[{'time_s':t,'pose_mm_rad':[x,0,0],'velocity_mm_rad_s':[v,0,0],'acceleration_mm_rad_s2':[0,0,0]}for t,x,v in [(0,0,100),(1,0,-100)]]
        curve=c.floor.motion.Curve(c.floor.canonical(points));bounds=c.curve_extrema(curve,0,1)
        self.assertGreater(bounds['max'][0],20)
        for i in range(1001):
            state=curve.evaluate(i/1000)[c.floor.F[0]]
            self.assertTrue(all(bounds['min'][k]<=state[k]<=bounds['max'][k]for k in range(3)))

    def test_hold_cannot_hide_motion_or_gap(self):
        c=self.module();config={'reference_z_mm':0,'reference_level':'EG','object_id':'Lift','ports':[],'door_objects':[]};lift=c.LiftTimeline(config,[])
        point=lambda t,x:{'time_s':t,'pose_mm_rad':[x,0,0],'velocity_mm_rad_s':[0,0,0],'acceleration_mm_rad_s2':[0,0,0]}
        episode={'level_id':'EG','mode':'hold','start_s':0,'end_s':1,'points':[point(0,0),point(1,0)],'attached_cabin':False,'hold_reason':'resource'}
        trajectory=c.Trajectory({'vehicle_id':'BF01','episodes':[episode]},{'EG':{'z_mm':0}},lift);self.assertEqual(trajectory.pose(.5),[0,0,0,0])
        for change in [lambda e:e.update(hold_reason=None),lambda e:e['points'][1].update(pose_mm_rad=[10,0,0])]:
            altered=copy.deepcopy(episode);change(altered)
            with self.assertRaises(ValueError):c.Trajectory({'vehicle_id':'BF01','episodes':[altered]},{'EG':{'z_mm':0}},lift)
        second=copy.deepcopy(episode);second.update(start_s=2,end_s=3,points=[point(2,0),point(3,0)])
        with self.assertRaises(ValueError):c.Trajectory({'vehicle_id':'BF01','episodes':[episode,second]},{'EG':{'z_mm':0}},lift)

    def test_lift_schedule_drives_only_active_doors_and_absolute_z(self):
        c=self.module();door=lambda name:{'id':name,'states':{'closed':0,'open':100}}
        config={'reference_z_mm':0,'reference_level':'EG','object_id':'Lift','door_objects':[door('inside'),door('outside')], 'ports':[{'active':True,'level_id':'EG','door_object_ids':['inside']},{'active':True,'level_id':'OG3','door_object_ids':['outside']}]}
        timeline=c.LiftTimeline(config,[{'kind':'doors','start_s':0,'end_s':1,'level':'EG','target':'closed'},{'kind':'travel','start_s':1,'end_s':3,'from_z_mm':0,'to_z_mm':12750},{'kind':'doors','start_s':3,'end_s':4,'level':'OG3','target':'open'}])
        self.assertEqual(timeline.values(0)['inside'],100);self.assertEqual(timeline.values(2)['inside'],0);self.assertAlmostEqual(timeline.z(2),6375)
        self.assertEqual(timeline.values(4)['outside'],100);self.assertEqual(timeline.values(4)['inside'],0)

    def test_rigid_point_displacement_is_enclosed_between_nodes(self):
        import math
        c=self.module();lift=c.LiftTimeline({'reference_z_mm':0,'reference_level':'EG','object_id':'Lift','ports':[],'door_objects':[]},[])
        points=[{'time_s':t,'pose_mm_rad':pose,'velocity_mm_rad_s':velocity,'acceleration_mm_rad_s2':[0,0,0]}for t,pose,velocity in [(0,[0,0,0],[200,50,2]),(1,[200,80,1],[100,40,-1])]]
        episode={'level_id':'EG','mode':'driving','start_s':0,'end_s':1,'points':points,'attached_cabin':False,'hold_reason':None};trajectory=c.Trajectory({'vehicle_id':'BF01','episodes':[episode]},{'EG':{'z_mm':0}},lift)
        radius=350;bound=trajectory.inflation(.1,.9,radius);mid=trajectory.pose(.5)
        def corner(p):return [p[0]+radius*math.cos(p[3]),p[1]+radius*math.sin(p[3])]
        reference=corner(mid)
        for i in range(1001):self.assertLessEqual(math.dist(reference,corner(trajectory.pose(.1+.8*i/1000))),bound)

    def test_lift_overlap_and_pva_discontinuity_rejected(self):
        c=self.module();config={'reference_z_mm':0,'reference_level':'EG','object_id':'Lift','ports':[],'door_objects':[]}
        with self.assertRaises(ValueError):c.LiftTimeline(config,[{'kind':'travel','start_s':0,'end_s':2,'from_z_mm':0,'to_z_mm':100},{'kind':'travel','start_s':1,'end_s':3,'from_z_mm':100,'to_z_mm':200}])
        lift=c.LiftTimeline(config,[])
        def hold(start,end,x):return {'level_id':'EG','mode':'hold','start_s':start,'end_s':end,'points':[{'time_s':t,'pose_mm_rad':[x,0,0],'velocity_mm_rad_s':[0,0,0],'acceleration_mm_rad_s2':[0,0,0]}for t in [start,end]],'attached_cabin':False,'hold_reason':'resource'}
        with self.assertRaises(ValueError):c.Trajectory({'vehicle_id':'BF01','episodes':[hold(0,1,0),hold(1,2,10)]},{'EG':{'z_mm':0}},lift)

    def test_flattened_walkthrough_lift_objects_are_resolved_by_source_ids(self):
        c=self.module();obj={'id':'CabinDoor','mechanism':'lift_door','states':{'closed':0,'open':100}}
        manifest={'elevator':{'reference_z_mm':0,'reference_level':'EG','object_id':'Lift','ports':[{'active':True,'level_id':'EG','door_object_ids':['CabinDoor']}]},'objects':[obj]}
        self.assertEqual(c.timeline_from_manifest(manifest,[]).values(0)['CabinDoor'],100)
        with self.assertRaises(ValueError):c.LiftTimeline(manifest['elevator'],[])

    def test_native_part_branch_bound_matches_exact_union_minimum(self):
        import math
        c=self.module()
        class Sphere:
            def __init__(self,centre):self.centre=centre
            def distToShape(self,other):return(max(0,math.dist(self.centre,other.centre)-2),)
        def part(x,y):
            shape=Sphere((x,y,0));return shape,{'min':[x-1,y-1,-1],'max':[x+1,y+1,1]}
        first=[part(0,0),part(20,0),part(40,0)];second=[part(3,3),part(4,0),part(100,100)]
        expected=min(a[0].distToShape(b[0])[0]for a in first for b in second);count={'kernel':0}
        self.assertEqual(c.parts_distance(first,second,count,'kernel'),expected)
        self.assertLess(count['kernel'],len(first)*len(second))
        with self.assertRaises(ValueError):c.parts_distance([],second,count,'kernel')


class NativeProgramHeaderTests(unittest.TestCase):
    """Partial or foreign fleet records cannot acquire a full-native scope."""
    def test_full_audit_header_fails_before_resolving_native_artifacts(self):
        import check_building_fleet_freecad as c
        seed=c.fleet.load()['missions']['seed'];before=sys.modules.get('FreeCAD')
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'programme.json'
            for changes in [{'complete':False},{'complete':1},{'format':'other'},
                            {'seed':seed+1},{'seed':str(seed)},{'seed':True}]:
                program={'format':'solidcraftbot.building-fleet-program/1','complete':True,
                         'seed':seed,'source_files_sha256':{'fixture':'0'*64},**changes}
                path.write_text(json.dumps(program))
                with self.subTest(changes=changes),patch.object(c.native,'project_path',return_value=path),\
                     patch.object(c.native,'verify_pins'),\
                     patch.object(c,'checked_walkthrough',side_effect=AssertionError('Native artifacts reached before header rejection')):
                    with self.assertRaises(ValueError):c.audit(path,Path(directory)/'out.json')
        self.assertIs(sys.modules.get('FreeCAD'),before)

    def test_complete_new_audit_fields_and_standalone_probe_retain_their_boundaries(self):
        import check_building_fleet_freecad as c
        seed=c.fleet.load()['missions']['seed'];before=sys.modules.get('FreeCAD')
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'programme.json'
            for probe in [False,True]:
                program={'format':'standalone_fixture'if probe else'solidcraftbot.building-fleet-program/1',
                         'complete':not probe,'seed':seed,'scope':'standalone_curve_only'if probe else'full_fleet_program',
                         'source_files_sha256':{'fixture':'0'*64},
                         'trajectories':[{'vehicle_id':'BF%02d'%i}for i in range(1,2 if probe else 21)],
                         'artifacts':{'walkthrough_report':{},'camera_report':{}},
                         'capacity_audit_fields':{'fixture':'extra programme evidence'}}
                path.write_text(json.dumps(program))
                with self.subTest(probe=probe),patch.object(c.native,'project_path',return_value=path),\
                     patch.object(c.native,'verify_pins'),patch.object(c,'reference',return_value=path),\
                     patch.object(c,'checked_walkthrough',side_effect=RuntimeError('native-artifact-boundary')):
                    with self.assertRaisesRegex(RuntimeError,'native-artifact-boundary'):
                        c.audit(path,Path(directory)/'out.json',_curve_probe=probe)
        self.assertIs(sys.modules.get('FreeCAD'),before)


class NativeWorldSnapshotTests(unittest.TestCase):
    """Reuse original native shapes without reusing posed audit dictionaries."""
    def setUp(self):
        import check_building_fleet_freecad as checker
        self.checker=checker;checker._NATIVE_WORLD_CACHE.clear()
        self.addCleanup(checker._NATIVE_WORLD_CACHE.clear)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ['source','cad']:(self.root/name).write_text(name)
        digest=lambda name:hashlib.sha256((self.root/name).read_bytes()).hexdigest()
        self.reports={'building':{'source_files_sha256':{'source':digest('source')},
            'files':{'freecad':'cad'},'artifact_sha256':{'freecad':digest('cad')}}}
        class Shape:
            BoundBox=SimpleNamespace(XMin=0,YMin=0,ZMin=0,XMax=1,YMax=2,ZMax=3)
            Solids=[True]
            def copy(self):return Shape()
            def isNull(self):return False
            def isValid(self):return True
        self.opens=[]
        self.app=SimpleNamespace(openDocument=lambda path:self.opens.append(path)or SimpleNamespace(Name='source'),closeDocument=lambda name:None)
        self.geo=SimpleNamespace(features=lambda doc:[SimpleNamespace(SourceBody='Body',ModelRole='native_geometry')],world_shape=lambda obj:Shape())
        self.bindings=[];self.manifest={'laboratories':[]}
        original_verify=checker.native.verify_pins
        patches=[patch.object(checker.native,'project_path',lambda name,root=None:self.root/name),
            patch.object(checker.native,'verify_pins',lambda pins:original_verify(pins,self.root)),
            patch.object(checker.native,'native_equipment_bindings',lambda labs:self.bindings)]
        for active in patches:active.start();self.addCleanup(active.stop)

    def world(self,**kwargs):
        return self.checker.native_world(self.reports,kwargs.get('manifest',self.manifest),kwargs.get('expected',{'Body'}),self.app,self.geo)

    def test_reuse_is_source_pinned_and_rows_are_isolated(self):
        first=self.world();original_shape=first['Body']['shape']
        first['Body']['shape']='posed copy';first['Body']['bounds']['min'][0]=-900
        second=self.world()
        self.assertEqual(len(self.opens),1)
        self.assertIs(second['Body']['shape'],original_shape)
        self.assertEqual(second['Body']['bounds']['min'],[0,0,0])
        self.assertIsNot(first['Body'],second['Body'])

    def test_changed_source_and_artifact_fail_before_cache_reuse(self):
        self.world()
        for name in ['source','cad']:
            with self.subTest(name=name):
                path=self.root/name;before=path.read_bytes();path.write_bytes(before+b'changed')
                with self.assertRaises(ValueError):self.world()
                path.write_bytes(before)
        self.assertEqual(len(self.opens),1)

    def test_manifest_bindings_and_expected_ids_are_exact_cache_inputs(self):
        self.world();self.world(manifest={'laboratories':[],'objects':[{'id':'different'}]})
        self.assertEqual(len(self.opens),2)
        self.bindings=[({'id':'lab'},{'id':'device','transform':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]})]
        self.world();self.assertEqual(len(self.opens),3)
        with self.assertRaises(ValueError):self.world(expected={'Missing'})
        self.assertEqual(len(self.opens),4)

    def test_changed_input_during_restore_is_not_cached(self):
        original=self.geo.features
        def changed(doc):
            (self.root/'source').write_text('changed during restoration')
            return original(doc)
        self.geo.features=changed
        with self.assertRaises(ValueError):self.world()
        self.assertFalse(self.checker._NATIVE_WORLD_CACHE)


class NativeEnvelopeAndTimelineTests(unittest.TestCase):
    def module(self):
        import check_building_fleet_freecad
        return check_building_fleet_freecad

    def test_unsorted_queries_replay_source_states_and_critical_events(self):
        c=self.module();doors=[{'id':name,'states':{'closed':0.,'open':100.}}for name in ['EGdoor','OGdoor']]
        config={'reference_z_mm':0.,'reference_level':'EG','object_id':'Lift','door_objects':doors,
                'ports':[{'active':True,'level_id':level,'door_object_ids':[name]}for level,name in [('EG','EGdoor'),('OG1','OGdoor')]]}
        schedule=[{'kind':'doors','start_s':0,'end_s':1,'level':'EG','target':'closed'},
                  {'kind':'travel','start_s':1,'end_s':3,'from_z_mm':0,'to_z_mm':4250},
                  {'kind':'doors','start_s':3,'end_s':4,'level':'OG1','target':'open'},
                  {'kind':'doors','start_s':4,'end_s':5,'level':'OG1','target':'closed'},
                  {'kind':'travel','start_s':5,'end_s':7,'from_z_mm':4250,'to_z_mm':0},
                  {'kind':'doors','start_s':7,'end_s':8,'level':'EG','target':'open'}]
        timeline=c.LiftTimeline(config,schedule)
        expected={8:(0,100,0),-1:(0,100,0),3.5:(4250,0,50),.5:(0,50,0),6:(2125,0,0),2:(2125,0,0),7.5:(0,50,0)}
        for time,(z,eg,og)in expected.items():self.assertEqual(timeline.values(time),{'Lift':z,'EGdoor':eg,'OGdoor':og})
        self.assertEqual(timeline.events(1,7),[3,4,5]);self.assertEqual(timeline.z_bound(1,7,4),4250)
        config['door_objects'][0]['states']['open']=9000;schedule[0]['target']='open'
        self.assertEqual(timeline.values(.5)['EGdoor'],50)

    def test_outward_native_prism_coordinates_keep_large_and_short_spans(self):
        c=self.module()
        def box(dx,dy,dz,origin):
            return SimpleNamespace(BoundBox=SimpleNamespace(XMin=origin[0],YMin=origin[1],ZMin=origin[2],XMax=origin[0]+dx,YMax=origin[1]+dy,ZMax=origin[2]+dz))
        app=SimpleNamespace(Vector=lambda *values:values);part=SimpleNamespace(makeBox=box)
        for bounds in [{'min':[1e9,-1e9,-1],'max':[1e9+1,-1e9+1,2]},
                       {'min':[-1.,-2.,-3.],'max':[1.,2.,3.]},
                       {'min':[1e-300,-1e-300,1e-299],'max':[2e-300,1e-300,2e-299]}]:
            actual=c.shape_bounds(c.native_envelope(bounds,app,part))
            self.assertTrue(all(actual['min'][i]<=bounds['min'][i]and actual['max'][i]>=bounds['max'][i]for i in range(3)))
        part.makeBox=lambda *args:SimpleNamespace(BoundBox=SimpleNamespace(XMin=0,YMin=0,ZMin=0,XMax=.5,YMax=.5,ZMax=.5))
        with self.assertRaisesRegex(ValueError,'lost source containment'):c.native_envelope({'min':[0,0,0],'max':[1,1,1]},app,part)
        with self.assertRaises(ValueError):c.native.validate_rigid([[-1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])

    @unittest.skipUnless(os.environ.get('SOLIDCRAFTBOT_BF01_NATIVE_ENVELOPE_TESTS')=='1',
                         'Opt-in installed FreeCAD native pose-containment fixture')
    def test_native_concave_body_remains_inside_prism_at_translated_yaw_poses(self):
        import FreeCAD as App
        import Part
        c=self.module()
        physical=Part.makeBox(300,40,200).fuse(Part.makeBox(40,300,200))
        physical=physical.cut(Part.makeCylinder(10,200,App.Vector(20,20,0)))
        prism=c.native_envelope(c.shape_bounds(physical),App,Part)
        for translation,yaw in [([0,0,0],0),([10000,16000,12750],37),([-10000,16000,-4250],-90)]:
            placement=App.Placement(App.Vector(*translation),App.Rotation(App.Vector(0,0,1),yaw))
            body=physical.copy();body.Placement=placement.multiply(body.Placement)
            envelope=prism.copy();envelope.Placement=placement.multiply(envelope.Placement)
            bb,eb=c.shape_bounds(body),c.shape_bounds(envelope)
            self.assertTrue(all(eb['min'][i]<=bb['min'][i]and eb['max'][i]>=bb['max'][i]for i in range(3)))
            self.assertEqual(body.cut(envelope).Volume,0)


if __name__=='__main__':unittest.main()
