"""Actual exported curves, inter-knot stops and conservative swept bounds."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import tr01_floor_motion as floor
import check_tr01_floor_motion as clearance


class FloorMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program=floor.compile_program(330.)

    def test_each_station_uses_layout_identity_and_only_endpoints_rest(self):
        layout=floor.layout.load(validate_builds=False)
        ids={i['id'] for i in layout['instances']}
        for station in self.program['definition']['stations'].values():self.assertIn(station['handoff_instance'],ids)
        self.assertEqual(len(self.program['routes']),4)
        parking={}
        for route in self.program['routes']:
            curve=floor.motion.Curve(floor.canonical(route['points']))
            for station,point in ((route['from'],curve.points[0]),(route['to'],curve.points[-1])):
                pose=point[floor.F[0]]
                if station in parking:
                    self.assertLess(math.dist(pose[:2],parking[station][:2]),1e-6)
                    self.assertLess(abs((pose[2]-parking[station][2]+math.pi)%(2*math.pi)-math.pi),1e-6)
                parking[station]=pose
            self.assertTrue(floor.no_stop(curve)['passed'])
            for point in (curve.points[0],curve.points[-1]):
                self.assertLess(max(abs(v) for f in floor.F[1:3] for v in point[f]),1e-8)
            for a,b in zip(curve.points,curve.points[1:]):
                for field in floor.F[:3]:
                    left=curve.evaluate(b['time_s'],'left')[field]
                    right=curve.evaluate(b['time_s'],'right')[field]
                    self.assertLess(max(abs(x-y) for x,y in zip(left,right)),1e-7)

    def test_quantized_export_limits_cover_dense_carried_point_derivatives(self):
        for route in self.program['routes']:
            points=json.loads(json.dumps(route['points']))
            curve=floor.motion.Curve(floor.canonical(points));bounds=floor.dynamics(curve,330.)
            for key in ('linear','angular','carried_points'):
                for field,value in bounds[key].items():self.assertLessEqual(value,self.program['definition']['limits'][key][field])
            for point in points:self.assertAlmostEqual(point['time_s']/.001,round(point['time_s']/.001),places=6)
            for a,b in zip(curve.times,curve.times[1:]):
                for fraction in (0.,.25,.5,.75,1.):
                    state=curve.evaluate(a+(b-a)*fraction)
                    for order,field in enumerate(('velocity','acceleration','jerk'),1):
                        actual=state[floor.F[order]]
                        self.assertLessEqual(math.hypot(*actual[:2]),bounds['linear'][field]+1e-6)
                        self.assertLessEqual(abs(actual[2]),bounds['angular'][field]+1e-6)

    def test_internal_stop_is_detected_between_endpoints(self):
        points=floor.motion.from_positions([0.,1.,2.],[[0.,0.,0.],[1.,0.,0.],[0.,0.,0.]])
        self.assertFalse(floor.no_stop(floor.motion.Curve(points))['passed'])

    def test_rigid_displacement_hull_covers_intermediate_positions_and_yaw(self):
        route=self.program['routes'][0];curve=floor.motion.Curve(floor.canonical(route['points']))
        for a,b in zip(curve.times[::5],curve.times[5::5]):
            upper,mid=clearance.displacement(curve,a,b,330.)
            for i in range(21):
                value=curve.evaluate(a+(b-a)*i/20)[floor.F[0]]
                dx=value[0]-mid[0]+330*(math.cos(value[2])-math.cos(mid[2]))
                dy=value[1]-mid[1]+330*(math.sin(value[2])-math.sin(mid[2]))
                self.assertLessEqual(math.hypot(dx,dy),upper+1e-6)

    def test_missing_cover_and_stale_source_rejected(self):
        definition=copy.deepcopy(self.program['definition']);definition['vehicle']['include_transport_cover']=False
        with patch.object(floor.json,'loads',return_value=definition):
            with self.assertRaises(ValueError):floor.load()
        with self.assertRaises(ValueError):floor.verify({'model/tr01-l01.motion.json':'0'*64})

    def test_thin_obstacle_between_nodes_cannot_pass_as_sampled_clearance(self):
        from types import SimpleNamespace
        class Shape:
            def __init__(self,lo,hi):self.lo=lo;self.hi=hi;self.Placement=SimpleNamespace(x=0.,y=0.)
            def copy(self):return Shape(self.lo,self.hi)
            @property
            def BoundBox(self):
                x,y=self.Placement.x,self.Placement.y
                return SimpleNamespace(XMin=self.lo[0]+x,YMin=self.lo[1]+y,ZMin=self.lo[2],
                                       XMax=self.hi[0]+x,YMax=self.hi[1]+y,ZMax=self.hi[2])
            def distToShape(self,other):return (clearance.box_distance(clearance.box(self),clearance.box(other)),)
        app=SimpleNamespace(Vector=lambda *v:v,Rotation=lambda *v:None,
                            Placement=lambda point,rotation:SimpleNamespace(x=point[0],y=point[1]))
        points=floor.motion.from_positions([0.,1.],[[0.,0.,0.],[10.,0.,0.]])
        program={'definition':{'collision':{'minimum_clearance_mm':.1,'distance_tolerance_mm':.001,
                   'maximum_depth':12,'minimum_interval_s':.0001,'floor_contact_body':'Floor'}},
                 'routes':[{'id':'ThinWall','duration_s':1.,'points':floor.public(points)}]}
        vehicle=Shape([-1.,-1.,0.],[1.,1.,1.]);wall=Shape([2.29,-2.,0.],[2.31,2.,1.])
        with patch('builtins.print'):
            result=clearance.validate(program,vehicle,[('ThinWall',wall,clearance.box(wall))],1.5,app)
        self.assertFalse(result['passed']);self.assertTrue(result['routes'][0]['failures'])
        distant=Shape([20.,-2.,0.],[21.,2.,1.])
        with patch('builtins.print'):
            result=clearance.validate(program,vehicle,[('FarWall',distant,clearance.box(distant))],1.5,app)
        self.assertTrue(result['passed'])

    def test_native_certificate_when_available(self):
        path=ROOT/'cad/tr01-l01/shared-build-report.json'
        if not path.exists():self.skipTest('Current native route build not available')
        report=json.loads(path.read_text());floor.verify(report['source_files_sha256'])
        self.assertTrue(report['passed']);self.assertTrue(report['export_round_trip_passed'])
        native=report['collision_validation'];self.assertTrue(native['full_cover_included'])
        self.assertTrue(all(c['passed'] for c in native['installation_checks']))
        for route in native['routes']:
            self.assertFalse(route['failures']);self.assertTrue(route['passed'])
            self.assertGreaterEqual(route['minimum_certified_clearance_mm'],15.)


if __name__=='__main__':unittest.main()
