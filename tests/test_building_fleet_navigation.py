"""Independent geometry/clearance checks for BF01 navigation primitives."""
import math
import os
import hashlib
import json
import tempfile
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_navigation as nav


class DistanceTransformTests(unittest.TestCase):
    def test_exact_transform_matches_brute_force(self):
        randomizer=random.Random(17)
        for width,height in ((3,8),(9,5),(1,7),(7,1)):
            cells=bytearray(randomizer.random()<.3 for _ in range(width*height));cells[0]=1
            actual=nav.squared_distance_transform(cells,width,height)
            sites=[(i%width,i//width)for i,x in enumerate(cells)if x]
            expected=[min((i%width-x)**2+(i//width-y)**2 for x,y in sites)for i in range(len(cells))]
            self.assertEqual(list(actual),expected)

    def test_no_obstacles_is_infinite(self):
        self.assertTrue(all(math.isinf(x)for x in nav.squared_distance_transform(bytearray(12),4,3)))

    def test_missing_floor_and_touched_cells_are_blocked(self):
        g=nav.ClearanceGrid({'min':[0,0,0],'max':[1000,1000,0]},50)
        g.raster([[0,0],[1000,0],[1000,1000],[0,1000]],support=True)
        g.raster([[500,100],[500,900]])
        g.finalize()
        self.assertEqual(g.clearance_lower_mm([-25,-25]),0)
        self.assertEqual(g.clearance_lower_mm([500,500]),0)
        self.assertFalse(g.line_free([200,500],[800,500],20))
        self.assertTrue(g.line_free([150,150],[300,800],20))

    def test_disconnected_components_fail_search(self):
        g=nav.ClearanceGrid({'min':[0,0,0],'max':[1000,1000,0]},25)
        g.raster([[0,0],[1000,0],[1000,1000],[0,1000]],True)
        g.raster([[490,0],[510,0],[510,1000],[490,1000]])
        g.finalize()
        with self.assertRaisesRegex(ValueError,'No conservative disc route'):
            g.search([200,500],[800,500],40)


class NativeGeometryTests(unittest.TestCase):
    def test_height_band_clipping(self):
        polygon=nav.clip_height([[0,0,0],[20,0,200],[0,20,200]],50,100)
        self.assertTrue(polygon)
        self.assertTrue(all(5-1e-9<=sum(p)<=10+1e-9 for p in polygon))
        self.assertEqual(nav.clip_height([[0,0,0],[1,0,0],[0,1,0]],20,100),[])

    def test_touch_includes_tangent_and_degenerate_projection(self):
        self.assertTrue(nav.polygon_touches_box([[2,0],[2,4]],0,0,2,2))
        self.assertFalse(nav.polygon_touches_box([[3,0],[3,4]],0,0,2,2))
        self.assertFalse(nav.polygon_touches_box([],0,0,2,2))

    def test_closed_door_is_relative_to_native_open_reference(self):
        obj={'joint':{'type':'revolute','axis':[0,0,1],'origin_mm':[100,200,0]},
             'states':{'open':90,'closed':0},'reference_state':'open','initial_state':'closed'}
        point=nav.initial_transform(obj,[100,300,20])
        self.assertAlmostEqual(point[0],200)
        self.assertAlmostEqual(point[1],200)
        self.assertAlmostEqual(point[2],20)

    def test_topology_stairs_excluded_and_all_active_ports_have_landings(self):
        data=nav.topology()
        self.assertEqual(data['KG']['landing_neighbors'],{'LiftPort_KG_inward':['K0_019']})
        for level in data.values():
            self.assertTrue(level['active_ports'])
            self.assertTrue(all(level['landing_neighbors'].values()))
            self.assertTrue(all(not(set(e['areas'])&nav.EXCLUDED)for e in level['connections']))
        self.assertFalse(any('K0_013'in e['areas']for e in data['KG']['connections']))


class PinTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'source.json';source.write_text('{}')
        bundle=root/'export';bundle.mkdir()
        files={'html':'index.html','manifest':'manifest.json','native_mesh':'native-mesh.json'}
        (bundle/'index.html').write_text('checked')
        (bundle/'manifest.json').write_text(json.dumps({'format':'solidcraftbot.building-walkthrough/1','objects':[]}))
        (bundle/'native-mesh.json').write_text(json.dumps({'format':'solidcraftbot.building-walkthrough-mesh/1','scenes':{'building':{'positions_base64':'','indices_base64':'','groups':[]}}}))
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        report={'format':'solidcraftbot.building-walkthrough-build/1','passed':True,
                'source_files_sha256':{'source.json':digest(source)},
                'files':{k:'export/'+name for k,name in files.items()},
                'artifact_sha256':{k:digest(bundle/name)for k,name in files.items()}}
        (bundle/'build-report.json').write_text(json.dumps(report))
        return bundle,report

    def test_consumed_bundle_and_source_pins_are_checked(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);bundle,report=self.fixture(root)
            nav.NativeMesh(bundle,root=root)
            (bundle/'manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'Changed walkthrough artifact'):
                nav.NativeMesh(bundle,root=root)
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);bundle,report=self.fixture(root)
            (root/'source.json').write_text('changed')
            with self.assertRaisesRegex(ValueError,'Stale walkthrough source'):
                nav.NativeMesh(bundle,root=root)

    def test_external_export_and_pin_paths_rejected(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);bundle,report=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'Project-local'):
                nav.NativeMesh(bundle,root=root/'other')
            report['source_files_sha256']={'../outside.json':'0'*64}
            (bundle/'build-report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'External source pin'):
                nav.NativeMesh(bundle,root=root)


class NativeL01StopTests(unittest.TestCase):
    def test_actual_solids_cut_both_existing_lane_connections(self):
        selected=os.environ.get('SOLIDCRAFTBOT_FLEET_WALKTHROUGH_EXPORT')
        if selected:
            mesh=nav.NativeMesh(nav.ROOT/selected)  # Explicit stale input fails.
        else:
            candidates=sorted((nav.ROOT/'exports/building-walkthrough').glob('*/build-report.json'),
                              key=lambda p:p.stat().st_mtime,reverse=True)
            mesh=None
            for candidate in candidates:
                try:mesh=nav.NativeMesh(candidate.parent);break
                except ValueError:continue  # Historical caches are not current proofs.
            if mesh is None:self.skipTest('Requires a separately built current pinned native walkthrough export')
        report=nav.check_l01_feasibility(mesh)
        self.assertFalse(report['passed'])
        self.assertTrue(report['rejection_proven'])
        self.assertEqual(report['status'],'blocked_existing_lane_graph')
        self.assertEqual(report['corner_trim_mm'],250)
        self.assertEqual(report['door_initial_state'],'open')
        self.assertEqual(report['door_reference_state'],'open')
        self.assertTrue(all(w['membership']['inside']for w in report['witnesses']))
        self.assertTrue(all(w['outside_existing_corner_blends']for w in report['witnesses']))
        self.assertFalse(report['qualification']['unconstrained_room_unreachability_claimed'])


class QualifiedSearchTests(unittest.TestCase):
    def test_edge_certificate_also_controls_visibility_shortcuts(self):
        grid=nav.ClearanceGrid({'min':[0,0,0],'max':[2000,2000,0]},100)
        grid.raster([[0,0],[2000,0],[2000,2000],[0,2000]],support=True);grid.finalize()
        start,end=[300,1000],[1700,1000]
        def qualified(a,b):
            if (a[0]-1000)*(b[0]-1000)>0:return True
            if a[0]==b[0]:return a[0]!=1000 or min(a[1],b[1])>=1400
            u=(1000-a[0])/(b[0]-a[0]);y=a[1]+u*(b[1]-a[1])
            return y>=1400
        self.assertEqual(grid.search(start,end,50),[start,end])
        result=grid.search(start,end,50,edge_validator=qualified)
        self.assertGreater(len(result),2)
        self.assertTrue(all(qualified(a,b)for a,b in zip(result,result[1:])))
        self.assertTrue(any(p[1]>=1400 for p in result))


if __name__=='__main__':unittest.main()
