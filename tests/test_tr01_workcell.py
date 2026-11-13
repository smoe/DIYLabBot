import unittest,sys,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import tr01_workcell as m

class WorkcellContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.s=m.load()
    def test_shared_left_work_area(self):
        self.assertEqual(self.s['stations']['DNA']['work_area'],self.s['stations']['TS01']['work_area'])
        self.assertEqual(self.s['guards']['initial_occupancy'],'unknown')
    def test_additional_arm_reuses_six_axis_source(self):
        source,scene,kin=m.actor_source(self.s,'ArmDNA')
        self.assertEqual(len(source['joints']),6)
        self.assertIsNone(self.s['actors']['ArmDNA']['source_instance'])
        self.assertEqual(kin.p['upper_len'],200)
    def test_cargo_targets_derived_from_station_racks(self):
        for station in self.s['stations']:
            bench,car=m.grip(self.s,station)
            self.assertAlmostEqual(bench[2],934)
            self.assertAlmostEqual(car[2],936)
    def test_caps_are_part_of_carried_material_bounds(self):
        fs=m.floor.load();spec,p,variant=m.floor.vehicle_source(fs,m.floor.layout.load(validate_builds=False))
        geometry=m.tube_geometry(m.floor.vehicle.expanded(spec,p,variant),self.s['cargo_slot_body'],self.s['cargo_grip_offset_from_top_mm'])
        self.assertEqual(geometry['radius_mm'],7)
        self.assertEqual(geometry['tool_axial_bounds_mm'],[-10,30])
    def test_departure_exactly_reverses_pose_and_velocity(self):
        s={'id':'DNA.approach','duration_s':2,'points':[{'time_s':t,'pose_mm_rad':[t,2*t,.1*t],'velocity_mm_rad_s':[1,2,.1],'acceleration_mm_rad_s2':[0,0,0]} for t in [0,1,2]]}
        a=m.floor.motion.Curve(m.floor.canonical(s['points']));b=m.floor.motion.Curve(m.floor.canonical(m.reverse_curve(s)['points']))
        for t in [.03,.4,1.2,1.97]:
            for x,y in zip(a.evaluate(2-t)[m.F[0]],b.evaluate(t)[m.F[0]]):self.assertAlmostEqual(x,y)
            for x,y in zip(a.evaluate(2-t)[m.F[1]],b.evaluate(t)[m.F[1]]):self.assertAlmostEqual(x,-y)
    def test_source_schema(self):
        try:import jsonschema
        except ImportError:self.skipTest('jsonschema not installed')
        jsonschema.validate(self.s,json.loads((ROOT/'model/tr01-l01-workcell.schema.json').read_text()))
    def test_through_traffic_never_enters_work_reservations(self):
        # An enclosing 330 mm circle is independent of vehicle orientation.
        # Polynomial interval boxes therefore test between all route nodes.
        for route in m.floor.compile_program(330)['routes']:
            curve=m.floor.motion.Curve(m.floor.canonical(route['points']))
            for a,b in zip(curve.times,curve.times[1:]):
                bounds=m.floor.extrema(curve,a,b)
                for area in self.s['work_areas'].values():
                    x0,x1,y0,y1=area['bounds_xy_mm']
                    separated=(bounds['max'][0]+330<x0 or bounds['min'][0]-330>x1 or
                               bounds['max'][1]+330<y0 or bounds['min'][1]-330>y1)
                    self.assertTrue(separated,route['id']+' enters a bench reservation')
