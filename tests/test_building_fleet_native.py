"""Pinned native-vehicle inputs must fail closed before loading any CAD runtime."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

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


if __name__=='__main__':unittest.main()
