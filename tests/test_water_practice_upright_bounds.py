import copy
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import water_practice_l01 as demo
import water_practice_upright_bounds as reduced
import sample_motion as common


class UprightBoundsTests(unittest.TestCase):
    def setUp(self):
        self.definition=demo.load()
        workcell=demo.read(demo.ROOT/'model/tr01-l01-workcell.protocol.json')
        actor=workcell['actors']['ArmDNA']
        self.kin=demo.kinematics(self.definition,'ArmDNA',{'ArmDNA':{'base':demo.pickup.placement(actor['xyz_mm'],actor['yaw_deg'])}})

    def test_reduction_matches_independent_shared_fk_through_jerk(self):
        rng=random.Random(2047);points=[[0,0,0],[40,24,-190],[-40,-24,-190]]
        for _ in range(80):
            state={f:[rng.uniform(-1,1) for _ in range(6)] for f in demo.F}
            for f in demo.F:state[f][3]=0
            q=[common.Jet(*(state[f][j] for f in demo.F)) for j in range(6)]
            value=reduced.raw(self.kin,q,q[1]+q[2]+q[4]-math.pi,q[0]-q[5],points)
            actual=common.evaluate(self.kin,state,points_mm=points)
            for field in (*common.LINEAR,*common.ANGULAR):
                for a,b in zip(value[field],actual[field]):self.assertAlmostEqual(a,b,places=8)
            for result,reference in zip(value['points'],actual['points']):
                for field in common.LINEAR:
                    for a,b in zip(result[field],reference[field]):self.assertAlmostEqual(a,b,places=8)

    def test_full_interval_enclosure_includes_nonzero_export_residuals(self):
        positions=[]
        for i in range(9):
            a=.1*i;b=.2+.03*i;c=.6-.02*i
            positions.append([a,b,c,0,math.pi-b-c+1e-5*math.sin(i),a+.3+1e-5*math.cos(i)])
        curve=demo.motion.Curve(demo.motion.from_positions(list(range(9)),positions))
        points=[[40,24,0],[-40,-24,-190]]
        bounds=reduced.bounds(self.kin,curve,points,8)
        self.assertGreater(bounds['angular_velocity_rad_s'],1e-6)
        for i in range(401):
            state=curve.evaluate(curve.times[-1]*i/400);actual=common.evaluate(self.kin,state,points_mm=points)
            for field in common.LINEAR[1:]:
                self.assertLessEqual(math.hypot(*actual[field]),bounds[field]+1e-8)
                for point in actual['points']:self.assertLessEqual(math.hypot(*point[field]),bounds[field]+1e-8)
            for field in common.ANGULAR:self.assertLessEqual(math.hypot(*actual[field]),bounds[field]+1e-8)

    def test_unsupported_joint_motion_is_rejected(self):
        positions=[[0,.3,.8,.01,1,0],[.1,.4,.7,.02,1,0]]
        with self.assertRaisesRegex(ValueError,'J4'):reduced.bounds(self.kin,demo.motion.from_positions([0,1],positions),[],4)
        invalid=copy.deepcopy(self.kin);invalid.arm['joints'][1]['frame']['axis']=[1,0,0]
        with self.assertRaisesRegex(ValueError,'axis'):reduced.validate_chain(invalid)


if __name__=='__main__':unittest.main()
