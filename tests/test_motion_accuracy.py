"""Accuracy regressions for local derivative fitting; no robot or hardware proof."""
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ros2_ws/src/solidcraftbot_ros'))
from solidcraftbot_ros import motion


def polynomial(coefficients,t,order=0):
    return math.fsum(coefficient*math.factorial(i)/math.factorial(i-order)*t**(i-order)
                     for i,coefficient in enumerate(coefficients) if i>=order)


def quadratic_reference(times,positions,rest_endpoints=True):
    """Frozen former three-point fit, solely for numerical comparison."""
    size=len(positions[0]);v=[[0.]*size for _ in times];a=[[0.]*size for _ in times]
    slopes=[[(y-x)/(tb-ta) for x,y in zip(pa,pb)] for ta,tb,pa,pb in zip(times,times[1:],positions,positions[1:])]
    for i in range(1,len(times)-1):
        left,right=times[i]-times[i-1],times[i+1]-times[i]
        v[i]=[(right*x+left*y)/(left+right) for x,y in zip(slopes[i-1],slopes[i])]
        a[i]=[2*(y-x)/(left+right) for x,y in zip(slopes[i-1],slopes[i])]
    if not rest_endpoints:
        if len(times)==2:v[0],v[-1]=slopes[0][:],slopes[0][:]
        else:
            a[0],a[-1]=a[1][:],a[-2][:]
            v[0]=[x-y*(times[1]-times[0])/2 for x,y in zip(slopes[0],a[0])]
            v[-1]=[x+y*(times[-1]-times[-2])/2 for x,y in zip(slopes[-1],a[-1])]
    return [{'time_s':t,'positions_rad':list(p),'velocities_rad_s':dv,'accelerations_rad_s2':da}
            for t,p,dv,da in zip(times,positions,v,a)]


def errors(points,coefficients):
    curve=motion.Curve(points);maximum=[0.]*4
    for a,b in zip(points,points[1:]):
        for k in range(9):
            t=a['time_s']+(b['time_s']-a['time_s'])*k/8
            for side in ['left','right']:
                actual=motion.evaluate(curve,t,side=side)
                for order,field in enumerate(motion.FIELDS):
                    maximum[order]=max(maximum[order],abs(actual[field][0]-polynomial(coefficients,t,order)))
    return maximum


class DerivativeFitAccuracy(unittest.TestCase):
    def test_nonuniform_stencils_reproduce_every_polynomial_through_degree_four(self):
        times=[-.9,-.4,0.,.3,.8,1.1,1.8]
        for degree in range(5):
            coefficients=[(-1)**i/(i+1) for i in range(degree+1)]
            positions=[[polynomial(coefficients,t),3*polynomial(coefficients,t)+2] for t in times]
            points=motion.from_positions(times,positions,rest_endpoints=False)
            for knot in points:
                for order,field in [(1,'velocities_rad_s'),(2,'accelerations_rad_s2')]:
                    expected=polynomial(coefficients,knot['time_s'],order)
                    self.assertAlmostEqual(knot[field][0],expected,delta=2e-11)
                    self.assertAlmostEqual(knot[field][1],3*expected,delta=6e-11)

    def test_five_point_one_sided_stencils_and_large_time_origin(self):
        origin=1e9;times=[origin+x for x in [0.,.02,.06,.13,.21]]
        coefficients=[1,-2,.3,-.04,.005]
        positions=[[polynomial(coefficients,t-origin)] for t in times]
        points=motion.from_positions(times,positions,rest_endpoints=False)
        for knot in points:
            for order,field in [(1,'velocities_rad_s'),(2,'accelerations_rad_s2')]:
                self.assertAlmostEqual(knot[field][0],polynomial(coefficients,knot['time_s']-origin,order),delta=2e-10)

    def test_rest_endpoints_remain_exact_zero_without_changing_positions(self):
        times=[0.,.1,.3,.55,.8,1.]
        positions=[[t+t*t,2-t] for t in times]
        points=motion.from_positions(times,positions)
        self.assertEqual([p['positions_rad'] for p in points],positions)
        for knot in [points[0],points[-1]]:
            self.assertEqual(knot['velocities_rad_s'],[0.,0.])
            self.assertEqual(knot['accelerations_rad_s2'],[0.,0.])
        for knot in points[1:-1]:
            self.assertAlmostEqual(knot['velocities_rad_s'][0],1+2*knot['time_s'],places=11)
            self.assertAlmostEqual(knot['accelerations_rad_s2'][0],2,places=10)

    def test_fewer_than_five_points_preserve_the_previous_fit_exactly(self):
        for count in [2,3,4]:
            times=[(i/(count-1))**1.2 for i in range(count)]
            positions=[[t*t+2*t,3*t**3] for t in times]
            for rest in [False,True]:
                self.assertEqual(motion.from_positions(times,positions,rest),quadratic_reference(times,positions,rest))

    def test_quintic_reconstruction_and_jerk_errors_converge_under_refinement(self):
        coefficients=[.1,-.2,.3,-.4,.5,.6]
        measured=[]
        for count in [17,33]:
            times=[(i/(count-1))**1.15 for i in range(count)]
            positions=[[polynomial(coefficients,t)] for t in times]
            measured.append(errors(motion.from_positions(times,positions,rest_endpoints=False),coefficients))
        for order in range(4):
            self.assertGreater(measured[0][order],1e-12)
            self.assertLess(measured[1][order],measured[0][order]*.5)

    def test_nonuniform_jerk_oscillation_is_reduced_against_the_old_fit(self):
        coefficients=[0.,0.,0.,10.,-15.,6.]
        times=[(i/32)**1.1 for i in range(33)]
        positions=[[polynomial(coefficients,t)] for t in times]
        old=quadratic_reference(times,positions);new=motion.from_positions(times,positions)
        old_error,new_error=errors(old,coefficients)[3],errors(new,coefficients)[3]
        self.assertLess(new_error,old_error*.15)
        def jumps(points):
            curve=motion.Curve(points)
            return max(abs(motion.evaluate(curve,t,side='left')['jerks_rad_s3'][0]
                           -motion.evaluate(curve,t,side='right')['jerks_rad_s3'][0]) for t in times[1:-1])
        self.assertLess(jumps(new),jumps(old)*.15)


if __name__=='__main__':unittest.main()
