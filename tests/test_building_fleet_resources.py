"""Static conflict closure must precede independent own vehicle grants."""
from pathlib import Path
from types import SimpleNamespace
import copy
import hashlib
import json
import tempfile
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_resources import ResourceCatalog,_positive_overlap,_path_input_hash
import building_fleet_model as model
from building_fleet_motion import Path as MotionPath


def navigation(rooms=()):
    return SimpleNamespace(radius=50,reserve=10,
        config={'missions':{'targets':[{'level':'EG','area':a}for a in rooms]},'depot':{'level':'EG','areas':[]}},
        polygons={'EG':{a:[[i*1000,0],[(i+1)*1000,0],[(i+1)*1000,1000],[i*1000,1000]]for i,a in enumerate(rooms)}},
        topological={'EG':{'connections':[{'areas':list(rooms[:2]),'wall':'W1','opening':'D1'}]if len(rooms)>=2 else[]}})


def route(identifier,x,level='EG'):
    return {'level':level,'points_mm':[[x-1000,0],[x+1000,0]],
            'resources':[{'id':identifier,'kind':'passage','start_index':0,'end_index':1,'crossing_mm':[x,0]}]}


class StaticResourcesTests(unittest.TestCase):
    def test_different_names_and_opposite_routes_share_overlapping_token(self):
        a=route('EG.merge.A',1000);b=route('EG.merge.B',1050)
        b['points_mm'].reverse()
        c=ResourceCatalog(navigation(),[a,b])
        self.assertEqual(c.canonical['EG.merge.A'],c.canonical['EG.merge.B'])
        self.assertEqual(len(c.resources),1)
        self.assertTrue(c.normalize(a)['resource_spans'])
        self.assertEqual(c.normalize(a)['resource_spans'][0]['resource'],c.normalize(b)['resource_spans'][0]['resource'])

    def test_separated_regions_and_other_floors_are_not_global_mutex(self):
        c=ResourceCatalog(navigation(),[route('EG.A',0),route('EG.B',3000),route('OG1.A',0,'OG1')])
        self.assertEqual(len(c.resources),3)
        self.assertFalse(c.report()['whole_floor_mutex_added'])

    def test_connected_selected_rooms_share_room_and_door_resource(self):
        nav=navigation(('R1','R2'))
        row={'level':'EG','points_mm':[[-500,500],[2500,500]],'resources':[
            {'id':'EG.D1','kind':'room','start_index':0,'end_index':1,'crossing_mm':[1000,500],'areas':['R1','R2']}]}
        c=ResourceCatalog(nav,[row])
        self.assertEqual(c.canonical['EG.room.R1'],c.canonical['EG.room.R2'])
        self.assertEqual(c.canonical['EG.D1'],c.canonical['EG.room.R1'])
        self.assertEqual(len(c.resources),1)

    def test_shared_boundary_is_not_positive_region_overlap(self):
        first=[[0,0],[1,0],[1,1],[0,1]]
        self.assertFalse(_positive_overlap(first,[[1,0],[2,0],[2,1],[1,1]]))
        self.assertTrue(_positive_overlap(first,[[.9,0],[2,0],[2,1],[.9,1]]))

    def test_optional_corner_caps_preserve_complete_catalog_path_and_spans(self):
        row={'level':'EG','points_mm':[[-500,0],[0,0],[0,400],[700,400]],
             'corner_trim_mm':250,'corner_trim_caps':[
                 {'point_index':2,'maximum_trim_mm':20},
                 {'point_index':1,'maximum_trim_mm':10}],
             'resources':[{'id':'EG.turn','kind':'passage','start_index':0,'end_index':3}]}
        original=copy.deepcopy(row);catalog=ResourceCatalog(navigation(),[row])
        expected=MotionPath(row['points_mm'],250,corner_trim_caps=row['corner_trim_caps'])
        self.assertEqual(catalog.paths[0][1].pieces,expected.pieces)
        normalized=catalog.normalize(row)
        self.assertEqual(normalized['corner_trim_caps'],sorted(row['corner_trim_caps'],key=lambda c:c['point_index']))
        self.assertEqual(normalized['resource_spans'],catalog.spans('EG',expected))
        self.assertEqual(row,original)
        legacy=route('EG.legacy',3000)
        self.assertNotIn('corner_trim_caps',ResourceCatalog(navigation(),[legacy]).normalize(legacy))
        invalid={**row,'corner_trim_caps':None}
        with self.assertRaisesRegex(ValueError,'JSON list'):ResourceCatalog(navigation(),[invalid])
        with self.assertRaisesRegex(ValueError,'JSON list'):catalog.normalize(invalid)


class ResourceCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (model.ROOT/'exports/building-fleet').mkdir(parents=True, exist_ok=True)

    def test_path_receipts_preserve_all_numeric_types_signed_zero_and_input_order(self):
        row={'points_mm':[[0.,-0.],[1000.,0.],[1000.,1000.],[2000.,1000.]],
             'corner_trim_mm':250,'corner_trim_caps':[
                 {'point_index':1,'maximum_trim_mm':25},
                 {'point_index':2,'maximum_trim_mm':20}]}
        original=_path_input_hash(row)
        for change in (lambda r:r.update(corner_trim_mm=250.),
                       lambda r:r['points_mm'][0].__setitem__(1,0.),
                       lambda r:r['points_mm'].__setitem__(0,tuple(r['points_mm'][0])),
                       lambda r:r['corner_trim_caps'].reverse()):
            changed=copy.deepcopy(row);change(changed)
            self.assertNotEqual(_path_input_hash(changed),original)

    def setup_cache(self,folder):
        nav=navigation();nav._cache_pins=lambda:{'tests/test_building_fleet_resources.py':model.digest(Path(__file__))}
        routes=[route('EG.merge.A',1000),route('EG.merge.B',1050),route('EG.other',4000)]
        catalog=ResourceCatalog(nav,routes);catalog.write_cache(folder,routes)
        return nav,routes,catalog

    def mutate(self,folder,change):
        path=Path(folder);data=json.loads((path/'closure.json').read_text());change(data)
        raw=(json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode();(path/'closure.json').write_bytes(raw)
        report=json.loads((path/'cache-report.json').read_text());report.update(bytes=len(raw),artifact_sha256=hashlib.sha256(raw).hexdigest())
        (path/'cache-report.json').write_text(json.dumps(report))

    def test_json_roundtrip_regenerates_guards_and_identical_future_spans(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
            nav,routes,fresh=self.setup_cache(folder);cached=ResourceCatalog.from_cache(nav,routes,folder)
            self.assertEqual(cached.report(),fresh.report())
            for points in [[[0,0],[2000,0]],[[5000,0],[0,0]],[[0,100],[2000,100]]]:
                path=MotionPath(points);self.assertEqual(cached.spans('EG',path),fresh.spans('EG',path))
            payload=json.loads((Path(folder)/'closure.json').read_text())
            self.assertEqual(set(payload),{'canonical'});self.assertNotIn('passed',payload)

    def test_changed_route_bank_and_payload_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
            nav,routes,_=self.setup_cache(folder);other=copy.deepcopy(routes);other[0]['points_mm'][0][0]+=.01
            with self.assertRaisesRegex(ValueError,'route-bank'):ResourceCatalog.from_cache(nav,other,folder)
            path=Path(folder)/'closure.json';path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'bytes changed'):ResourceCatalog.from_cache(nav,routes,folder)

    def test_changed_corner_caps_invalidate_complete_route_bank_cache(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
            nav=navigation();nav._cache_pins=lambda:{}
            row={'level':'EG','points_mm':[[0,0],[1000,0],[1000,1000]],
                 'corner_trim_mm':250,'corner_trim_caps':[{'point_index':1,'maximum_trim_mm':25}],
                 'resources':[{'id':'EG.turn','kind':'passage','start_index':0,'end_index':2}]}
            ResourceCatalog(nav,[row]).write_cache(folder,[row])
            changed=copy.deepcopy(row);changed['corner_trim_caps'][0]['maximum_trim_mm']=30
            with self.assertRaisesRegex(ValueError,'route-bank'):ResourceCatalog.from_cache(nav,[changed],folder)

    def test_current_generator_and_navigation_pins_cannot_be_relabelled(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
            nav,routes,_=self.setup_cache(folder)
            actual=model.digest
            for generator in ('building_fleet_resources.py','building_fleet_port_paths.py'):
                with patch.object(model,'digest',side_effect=lambda path:'0'*64 if Path(path).name==generator else actual(path)):
                    with self.assertRaisesRegex(ValueError,'pins are stale'):ResourceCatalog.from_cache(nav,routes,folder)
            nav._cache_pins=lambda:{'tests/test_building_fleet_resources.py':'0'*64}
            with self.assertRaisesRegex(ValueError,'pins are stale'):ResourceCatalog.from_cache(nav,routes,folder)

    def test_rehashed_cache_cannot_split_current_native_guard_overlap(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
            nav,routes,_=self.setup_cache(folder)
            def split(data):
                for alias in ('EG.merge.A','EG.merge.B'):
                    data['canonical'][alias]='EG.resource.'+hashlib.sha256(alias.encode()).hexdigest()[:16]
            self.mutate(folder,split)
            with self.assertRaisesRegex(ValueError,'splits'):ResourceCatalog.from_cache(nav,routes,folder)

    def test_rehashed_unknown_alias_or_wrong_deterministic_identity_is_rejected(self):
        for change in [lambda data:data['canonical'].update({'EG.fake':'EG.resource.fake'}),
                       lambda data:data['canonical'].update({'EG.other':'EG.resource.fake'})]:
            with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
                nav,routes,_=self.setup_cache(folder);self.mutate(folder,change)
                with self.assertRaises(ValueError):ResourceCatalog.from_cache(nav,routes,folder)

    def setup_validated_cache(self,folder):
        nav=navigation();nav._cache_pins=lambda:{}
        rows=[route('EG.A',1000),{'level':'EG','points_mm':[[3000.,-0.],[4000.,-0.],[4000.,1000.]],
            'corner_trim_mm':250,'corner_trim_caps':[{'point_index':1,'maximum_trim_mm':25}],
            'resources':[{'id':'EG.turn','kind':'passage','start_index':0,'end_index':2}]}]
        fresh=ResourceCatalog(nav,rows);fresh.write_cache(folder,rows,validated_paths=True)
        return nav,rows,fresh

    def test_validated_cache_reuses_only_static_validation_and_rebuilds_identical_regions(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
            nav,rows,fresh=self.setup_validated_cache(folder)
            with patch('building_fleet_resources.Path',side_effect=AssertionError('Static samples rebuilt')):
                cached=ResourceCatalog.from_cache(nav,rows,folder)
            self.assertEqual(cached.report(),fresh.report());self.assertEqual(cached.paths,[])
            for row in rows:self.assertEqual(cached.normalize(row),fresh.normalize(row))
            payload=json.loads((Path(folder)/'closure.json').read_text())
            self.assertEqual(set(payload),{'canonical','path_validation'})
            self.assertEqual(payload['path_validation']['validated_path_count'],len(rows))
            self.assertNotIn('samples',json.dumps(payload));self.assertNotIn('action',json.dumps(payload))
            with self.assertRaisesRegex(ValueError,'complete original path construction'):
                cached.write_cache(Path(folder)/'not-original',rows,validated_paths=True)

    def test_changed_exact_path_input_including_caps_type_order_and_signed_zero_rejects(self):
        changes=[lambda r:r[1]['corner_trim_caps'][0].update(maximum_trim_mm=30),
                 lambda r:r[1].update(corner_trim_mm=250.),
                 lambda r:r[1]['points_mm'][0].__setitem__(1,0.),
                 lambda r:r[1].update(corner_trim_caps=None)]
        for change in changes:
            with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
                nav,rows,_=self.setup_validated_cache(folder);changed=copy.deepcopy(rows);change(changed)
                report=Path(folder)/'cache-report.json';data=json.loads(report.read_text())
                data['route_bank_sha256']=ResourceCatalog.route_bank_hash(changed)
                report.write_text(json.dumps(data))
                with self.assertRaises((ValueError,TypeError)):
                    ResourceCatalog.from_cache(nav,changed,folder)

    def test_rehashed_missing_or_malformed_path_receipt_and_unknown_version_fail_closed(self):
        changes=[lambda d:d.pop('path_validation'),
                 lambda d:d['path_validation'].update(validated_path_count=True),
                 lambda d:d['path_validation']['ordered_input_sha256'].reverse(),
                 lambda d:d['path_validation'].update(format='unknown'),
                 lambda d:d['path_validation'].update(recorded_actions=[])]
        for change in changes:
            with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
                nav,rows,_=self.setup_validated_cache(folder);self.mutate(folder,change)
                with self.assertRaises(ValueError):ResourceCatalog.from_cache(nav,rows,folder)
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
            nav,rows,_=self.setup_validated_cache(folder);report=Path(folder)/'cache-report.json'
            data=json.loads(report.read_text());data['format']='solidcraftbot.building-fleet-resource-cache/3'
            report.write_text(json.dumps(data))
            with self.assertRaises(ValueError):ResourceCatalog.from_cache(nav,rows,folder)

    def test_validated_cache_still_rejects_current_native_guard_overlap_split(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'exports/building-fleet')as folder:
            nav=navigation();nav._cache_pins=lambda:{}
            rows=[route('EG.merge.A',1000),route('EG.merge.B',1050)]
            ResourceCatalog(nav,rows).write_cache(folder,rows,validated_paths=True)
            def split(data):
                for alias in ('EG.merge.A','EG.merge.B'):
                    data['canonical'][alias]='EG.resource.'+hashlib.sha256(alias.encode()).hexdigest()[:16]
            self.mutate(folder,split)
            with self.assertRaisesRegex(ValueError,'splits'):ResourceCatalog.from_cache(nav,rows,folder)


if __name__=='__main__':unittest.main()
