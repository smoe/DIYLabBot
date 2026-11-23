"""World velocity bounds retain the protected primitive's full interval result."""
import math
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_runner as runner
import tr01_floor_motion as floor

def point(t,p,v,a):return{'time_s':t,**dict(zip(floor.F[:3],(p,v,a)))}

class ActualVelocityProofTests(unittest.TestCase):
    def test_constant_coefficients_prove_zero_without_a_root_search(self):
        for t in (0.,.15,1e5):
            curve=floor.motion.Curve([point(t,[8700,3500,math.pi/2],[0.]*3,[0.]*3),
                                      point(t+.05,[8700,3500,math.pi/2],[0.]*3,[0.]*3)])
            with patch.object(runner.floor,'extrema',side_effect=AssertionError('Unneeded roots')):
                self.assertEqual(runner.world_velocity_bound(curve),{'linear_mm_s':0.,'yaw_rad_s':0.})

    def test_random_actual_polynomials_retain_full_protected_velocity_bounds(self):
        randoms=random.Random(20261120)
        for _ in range(100):
            t=randoms.uniform(0,1000)
            nodes=[point(t+offset,[randoms.uniform(-1e5,1e5)for _ in range(3)],
                         [randoms.uniform(-100,100)for _ in range(3)],
                         [randoms.uniform(-1000,1000)for _ in range(3)])for offset in(0,.02,.05)]
            curve=floor.motion.Curve(nodes);old=floor.motion.bounds(curve)[floor.F[1]]['max_abs']
            self.assertEqual(runner.world_velocity_bound(curve),{'linear_mm_s':math.hypot(*old[:2]),'yaw_rad_s':old[2]})

    def test_safe_endpoints_do_not_hide_motion_between_knots(self):
        curve=floor.motion.Curve([point(0,[0.,0.,0.],[20.,0.,0.],[0.]*3),
                                  point(.05,[0.,0.,0.],[-20.,0.,0.],[0.]*3)])
        self.assertGreater(runner.world_velocity_bound(curve)['linear_mm_s'],0)

if __name__=='__main__':unittest.main()
