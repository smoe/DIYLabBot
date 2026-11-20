"""Independent geometry/clearance checks for BF01 navigation primitives."""
import math
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
    @unittest.skipUnless((nav.ROOT/'exports/building-walkthrough/pages-master-0d8d52a/build-report.json').is_file(),
                         'Requires separately built, current pinned native walkthrough export')
    def test_actual_solids_cut_both_existing_lane_connections(self):
        mesh=nav.NativeMesh(nav.ROOT/'exports/building-walkthrough/pages-master-0d8d52a')
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


if __name__=='__main__':unittest.main()
