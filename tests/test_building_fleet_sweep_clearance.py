"""Strict one-sided anonymous-ray clearance over actual own future geometry."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_control as control
import building_fleet_motion as motion
import building_fleet_model as model


def rectangle_distance(point,pose,L=256.,W=206.):
    dx,dy=point[0]-pose[0],point[1]-pose[1];c,s=math.cos(pose[2]),math.sin(pose[2])
    return math.hypot(max(0.,abs(c*dx+s*dy)-L),max(0.,abs(-s*dx+c*dy)-W))


class SweepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=model.load()
    def car(self,points=None,progress=0.):
        c=control.Controller.__new__(control.Controller)
        c.path=motion.Path(points or[[0,0],[1500,0],[1500,1600]])
        c.source=self.source;c.settings=model.resolved_sensor(self.source);c.y=progress;c.goal=c.path.length
        c.radius=math.hypot(256,206);c.half_length=256.;c.half_width=206.;c.heading_offset=0.;c.static_return=None
        c.now=0.;c.record_times=[0.];c.recorded=[{'pose_mm_rad':c.path.evaluate(progress)[0]}]
        return c
    def padding(self,c):return c.settings['clearance_mm']+c.settings['range_error_mm']+c.settings['range_mm']*math.sin(math.radians(c.settings['angular_step_deg']))+self.source['geometry']['localization_tolerance_mm']

    def test_recorded_fixed_peer_ray_is_outside_the_whole_actual_rectangle_sweep(self):
        points=[[8875.,15475.],[9281.219033984651,15475.],[9281.219033984651,15759.629330428337],
            [8708.24552897667,15759.629330428337],[8257.50541137794,15925.],[8225.,15925.]]
        c=self.car(points,385.4361417333006);ray=[837.5947586366375,-408.52225979904523]
        pose=c.pose();side,forward=ray
        point=[pose[0]+math.cos(pose[2])*forward-math.sin(pose[2])*side,
               pose[1]+math.sin(pose[2])*forward+math.cos(pose[2])*side]
        self.assertTrue(c._future_rectangle_excludes(point,self.padding(c),c.settings['range_mm']+c.radius))
        original=copy.copy(c);original._future_rectangle_excludes=lambda *args:False
        old=original._observed_gap({'captured_s':0.,'returns_local_mm':[ray]},0.)[0]
        new=c._observed_gap({'captured_s':0.,'returns_local_mm':[ray]},0.)[0]
        empty=c._observed_gap({'captured_s':0.,'returns_local_mm':[]},0.)[0]
        self.assertAlmostEqual(old,655.4277287972936)
        self.assertEqual(new,empty)

    def test_a_real_curve_front_contact_remains_a_hazard(self):
        c=self.car();piece=next(i for i,p in enumerate(c.path.pieces)if len(p['controls'])>2)
        start=c.path.ends[piece-1];point=c.path.evaluate(start+.413*c.path.pieces[piece]['weight'])[0][:2]
        self.assertFalse(c._future_rectangle_excludes(point,self.padding(c),c.settings['range_mm']+c.radius))
        gap=c._observed_gap({'captured_s':0.,'returns_local_mm':[[point[1],point[0]]]},0.)[0]
        self.assertLess(gap,c._observed_gap({'captured_s':0.,'returns_local_mm':[]},0.)[0])

    def test_between_sample_contact_cannot_be_cleared_by_sampling_endpoints(self):
        c=self.car();piece=next(i for i,p in enumerate(c.path.pieces)if len(p['controls'])>2)
        start=c.path.ends[piece-1];end=c.path.ends[piece]
        def corner(s):
            p=c.path.evaluate(s)[0];co,si=math.cos(p[2]),math.sin(p[2])
            return [p[0]-c.half_length*co+c.half_width*si,p[1]-c.half_length*si-c.half_width*co]
        a,b=start,end
        for _ in range(70):
            x,y=a+(b-a)/3,b-(b-a)/3
            if corner(x)[1]<corner(y)[1]:b=y
            else:a=x
        at=(a+b)/2;support=corner(at);padding=self.padding(c);point=[support[0],support[1]-padding+.00001]
        self.assertLess(rectangle_distance(point,c.path.evaluate(at)[0]),padding)
        left,right=next((a,b)for a,b,_,_ in c.path.samples if a<at<b)
        self.assertGreater(rectangle_distance(point,c.path.evaluate(left)[0]),padding)
        self.assertGreater(rectangle_distance(point,c.path.evaluate(right)[0]),padding)
        self.assertFalse(c._future_rectangle_excludes(point,padding,c.goal))

    def test_singleton_goal_and_clipped_window_cover_the_current_rectangle(self):
        c=self.car([[0,0],[2000,0]]);padding=self.padding(c)
        self.assertFalse(c._future_rectangle_excludes([0,0],padding,0))
        self.assertTrue(c._future_rectangle_excludes([600,0],padding,100))
        self.assertFalse(c._future_rectangle_excludes([600,0],padding,600))
        c.y=c.goal
        self.assertFalse(c._future_rectangle_excludes([2000,0],padding,2200))
        self.assertTrue(c._future_rectangle_excludes([0,1000],padding,2200))

    def test_sub_tolerance_piece_tail_uses_full_derivative_bounds_and_fails_closed(self):
        c=self.car();index=next(i for i,p in enumerate(c.path.pieces)if len(p['controls'])>2)
        c.y=c.path.ends[index]-5e-11;c.goal=c.path.ends[index]
        point=[-1000.,-1000.]
        with patch.object(control,'spatial_bounds',side_effect=ValueError('unresolved tangent')):
            self.assertFalse(c._future_rectangle_excludes(point,self.padding(c),1.))
        self.assertTrue(c._future_rectangle_excludes(point,self.padding(c),1.))

    def test_adjacent_progress_endpoints_do_not_underestimate_midpoint_radius(self):
        c=self.car();a=50000.;b=math.nextafter(a,math.inf)
        self.assertEqual((a+b)/2,a)
        c.y=a;c.goal=b
        c.path=SimpleNamespace(pieces=[{'controls':[[0.,0.]]*6}],ends=[b],
                              evaluate=lambda s:([0.,0.,0.],))
        point=[c.half_length+self.padding(c)+1.,0.]
        # The loose derivative enclosure is valid for this fixed pose. An
        # exact-half assumption would incorrectly declare its coarse bound
        # sufficient; the rounded endpoint midpoint must remain unresolved.
        with patch.object(control,'spatial_bounds',return_value={'linear':[2e11], 'angular':[0.]}):
            self.assertFalse(c._future_rectangle_excludes(point,self.padding(c),b-a))

    def test_straight_gaps_are_unchanged_and_large_translated_reverse_bounds_are_safe(self):
        for offset in(0.,1e9):
            c=self.car([[offset,-offset],[offset+1500,-offset],[offset+1500,-offset+1600]])
            c.heading_offset=math.pi
            self.assertTrue(c._future_rectangle_excludes([offset-1000,-offset-1000],self.padding(c),c.goal))
            self.assertFalse(c._future_rectangle_excludes([offset+100,-offset],self.padding(c),c.goal))
        c=self.car([[0,0],[2000,0]])
        old=copy.copy(c);old._future_rectangle_excludes=lambda *args:False
        for rays in([[0.,1000.]],[[394.,1000.]],[[0.,100.]],[[-350.,800.]]):
            self.assertEqual(c._observed_gap({'captured_s':0.,'returns_local_mm':rays},0.),
                             old._observed_gap({'captured_s':0.,'returns_local_mm':rays},0.))


if __name__=='__main__':unittest.main()
