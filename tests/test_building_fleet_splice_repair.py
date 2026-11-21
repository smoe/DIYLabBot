"""Independent static splice admission tests; fixtures are not native proofs."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from building_fleet_runner import RouteGraph,splice_hub_paths,splice_hub_paths_with_junction
from building_fleet_resources import ResourceCatalog
from building_fleet_missions import MissionPlanner
from building_fleet_routes import reverse_centreline
from building_fleet_motion import Path as MotionPath


class StaticMap:
    """Small immutable map, with explicitly instrumented admission predicates."""
    def __init__(self,level='EG',transform=lambda p:p[:]):
        self.level=level;self.transform=transform
        self.A=[transform(p)for p in[[-40,80],[-30,80],[40,0],[35,-20],[0,-30]]]
        self.B=[transform(p)for p in[[45,-5],[35,-20],[0,-30]]]
        self.radius=5.;self.reserve=5.;self.envelope={'length_mm':2.,'width_mm':2.}
        self.mesh=SimpleNamespace(scene={'linear_tessellation_deflection_mm':0.,'maximum_float32_error_mm':0.})
        self.waits={level:[[30,-5,math.pi]]};self.road_hubs={level:self.A[-1]};self.homes={};self.inspections={}
        self._route_cache={};self.checks=[];self.hit=lambda a,b:[];self.refine=lambda r:r
        self.config={'missions':{'targets':[]},'depot':{'level':level,'areas':[]}}
        self.topological={level:{'connections':[],'plan':{'areas':[{'id':'C','kind':'corridor'}]},'excluded_areas':[]}}
        self.polygons={level:{'C':[[-1000,-1000],[1000,-1000],[1000,1000],[-1000,1000]]}}

    def route(self,level,start,end):
        points=next(p for p in(self.A,self.B)if tuple(p[0])==tuple(start))
        assert tuple(points[-1])==tuple(end)
        row={'level':level,'points_mm':copy.deepcopy(points),'resources':[],'zone_segments':[],
             'portal_certificates':[],'curve_qualified':False}
        self._route_cache[level,tuple(start),tuple(end)]=copy.deepcopy(row)
        self._route_cache[level,tuple(end),tuple(start)]=reverse_centreline(row)
        return copy.deepcopy(row)

    def _straight_hits(self,level,a,b):
        self.checks.append((level,tuple(a),tuple(b)))
        return self.hit(a,b)

    def _own_right(self,row):return self.refine(copy.deepcopy(row))


def prepared(nav):
    graph=RouteGraph(nav);graph.add_endpoint(nav.level,nav.A[0]);graph.add_endpoint(nav.level,nav.B[0]);graph.prepare()
    return graph


class SpliceRepairReview(unittest.TestCase):
    def test_junction_metadata_identifies_only_composed_vertex(self):
        nav=StaticMap();points,index=splice_hub_paths_with_junction(nav.A,nav.B)
        self.assertEqual(points,splice_hub_paths(nav.A,nav.B));self.assertEqual(points[index],[35,-20])
        graph=prepared(nav);route=graph.route('EG',nav.A[0],nav.B[0])
        self.assertEqual(route['points_mm'],points[:index]+points[index+1:])
        self.assertEqual(route['points_mm'][:2],points[:2]);self.assertEqual(route['points_mm'][-1],points[-1])
        self.assertFalse(route['splice_repair']['native_C2_curve_checked'])
        self.assertFalse(route['curve_qualified'],'Static visibility is never full motion qualification')

    def test_translation_and_rotation_do_not_select_lab_specific_coordinates(self):
        for angle,offset in[(0.,[0,0]),(.73,[1000,-1500]),(math.pi,[219,341])]:
            c,s=math.cos(angle),math.sin(angle)
            transform=lambda p:[offset[0]+c*p[0]-s*p[1],offset[1]+s*p[0]+c*p[1]]
            nav=StaticMap(transform=transform);graph=prepared(nav)
            route=graph.route('EG',nav.A[0],nav.B[0])
            self.assertIn('splice_repair',route)
            self.assertEqual(route['points_mm'],[nav.A[0],nav.A[1],nav.A[2],nav.B[0]])

    def test_ordinary_native_floor_or_reserved_bay_rejection_prevents_shortcut(self):
        for body in('NativeWall','NativeFloorSupportR1','ReservedLiftWaitingBay.EG.0','ReservedDepotBay.BF02','ExcludedArea.R3_028'):
            nav=StaticMap();nav.hit=lambda a,b:[body]
            graph=prepared(nav)
            self.assertEqual(graph.repairs,{})
            self.assertNotIn('splice_repair',graph.route('EG',nav.A[0],nav.B[0]))

    def test_all_lowered_segments_rechecked_before_registration(self):
        nav=StaticMap()
        def refine(route):
            if 'splice_repair'in route:route['points_mm'].insert(1,[999,999])
            return route
        nav.refine=refine;nav.hit=lambda a,b:['bad_lowered_segment']if[999,999]in(a,b)else[]
        self.assertEqual(prepared(nav).repairs,{})
        self.assertTrue(any((999,999)in row for row in nav.checks))

    def test_canonical_bench_mask_cannot_be_overridden_by_navigation_attribute(self):
        nav=StaticMap('OG3');nav.bench_safety_by_level={'OG3':[]}
        work=[{'world_polygon_mm':[[41,-4],[44,-4],[44,-1],[41,-1]]}]
        with patch('building_fleet_l01.definition',return_value={'work_areas':work})as source:
            graph=prepared(nav)
        self.assertTrue(source.called);self.assertEqual(graph.repairs,{})
        self.assertEqual(graph.bench_polygons('OG3'),[work[0]['world_polygon_mm']])

    def test_bench_sweep_retains_the_canonical_mesh_reserve(self):
        nav=StaticMap('OG3');nav.reserve=1.;nav.envelope={'length_mm':4.,'width_mm':4.}
        nav.mesh.scene['linear_tessellation_deflection_mm']=3.
        # Physical halfwidth2+reserve1 would miss this strip. The canonical
        # additional3mm mesh reserve must reject it before registration.
        work=[{'world_polygon_mm':[[4,4],[6,4],[6,5],[4,5]]}]
        graph=RouteGraph(nav)
        with patch('building_fleet_l01.definition',return_value={'work_areas':work}):
            self.assertFalse(graph.shortcut_clear('OG3',[0,0],[10,0]))

    def test_repaired_routes_enter_catalog_before_runtime_and_remain_copy_isolated(self):
        nav=StaticMap();graph=prepared(nav);bank=graph.base_routes()
        repaired=[r for r in bank if'splice_repair'in r];self.assertEqual(len(repaired),1)
        catalog=ResourceCatalog(nav,bank);alias=repaired[0]['resources'][0]['id']
        self.assertIn(alias,catalog.canonical)
        self.assertTrue(any(row['alias']==alias for row in catalog.regions))
        spans=catalog.spans('EG',MotionPath(repaired[0]['points_mm']))
        self.assertTrue(any(row['resource']==catalog.canonical[alias]for row in spans))
        saved=copy.deepcopy(graph.repairs);nav.checks.clear()
        first=graph.route('EG',nav.A[0],nav.B[0]);first['points_mm'][0][0]+=1000
        self.assertEqual(graph.repairs,saved);self.assertEqual(nav.checks,[],'A registered repaired route is lookup-only during runtime')
        with self.assertRaises(ValueError):graph.prepare_repairs()
        with self.assertRaises(ValueError):graph.add_endpoint('EG',[300,300])
        with self.assertRaises(ValueError):graph.route('EG',[300,300],nav.B[0])

    def test_actual_action_keeps_home_departure_and_private_waiting_approach(self):
        nav=StaticMap();start=[-50,80,0.]
        nav.homes={'BF01':{'level':'EG','area':'D','pose_mm_rad':start,
                          'departure_xy_mm':nav.A[0],'arrival_xy_mm':nav.A[0]}}
        graph=prepared(nav);planner=object.__new__(MissionPlanner)
        planner.nav=nav;planner.graph=graph;planner.source={'geometry':{'localization_tolerance_mm':1}}
        planner.trim_mm=1.;planner.variants={};planner.wait_approaches={('EG',0):[[nav.B[0],nav.waits['EG'][0][:2]]]}
        planner.states={'BF01':{'queue':[{'mission_id':'M','goal':{'level':'OG3','kind':'inspection_pass'}}],
                               'completed':set(),'active':None}}
        own={'vehicle_id':'BF01','level':'EG','pose_mm_rad':start,'home':True}
        grants={'waiting_place':{'status':'granted','level':'EG','slot':0,'pose_mm':nav.waits['EG'][0]}}
        action=planner._floor_leg(own,grants)
        self.assertEqual(action['kind'],'drive')
        self.assertEqual(action['points_mm'][:2],[start[:2],nav.A[0]])
        self.assertEqual(action['points_mm'][-2:],[nav.B[0],nav.waits['EG'][0][:2]])
        self.assertEqual(action['terminal'],{'kind':'lift_wait','level':'EG','slot':0,'to_level':'OG3'})
        self.assertNotIn([35,-20],action['points_mm'])


if __name__=='__main__':unittest.main()
