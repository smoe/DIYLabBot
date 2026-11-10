"""Adaptive refinement always retains interval bounds, not sampled maxima."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import sample_motion as sample
motion=sample.motion


def kin():
    identity=[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]]
    return SimpleNamespace(base=identity,frames=[copy.deepcopy(identity) for _ in range(6)],flange=[100.,0.,0.],length=0.)


def limits():
    return {'sample_translation':{'velocity_mm_s':1.,'acceleration_mm_s2':1e8,'jerk_mm_s3':1e8},
            'sample_rotation':{'velocity_deg_s':1e8,'acceleration_deg_s2':1e8,'jerk_deg_s3':1e8}}


class AdaptiveBoundsTests(unittest.TestCase):
    def test_interval_upper_is_not_replaced_by_exact_samples(self):
        points=[{'time_s':t,'positions_rad':[t,0.,0.,0.,0.,0.],
                 'velocities_rad_s':[1.,0.,0.,0.,0.,0.],'accelerations_rad_s2':[0.]*6} for t in [0.,1.]]
        result=sample.adaptive_bounds(kin(),points,points_mm=[[20.,0.,0.]],subdivisions=1,max_subdivisions=16,limits=limits())
        self.assertGreater(result['adaptive']['segment_subdivisions'][0],1)
        self.assertEqual(result['adaptive']['stop_reason'],'sampled_factor_gap')
        self.assertGreater(result['velocity_mm_s'],result['adaptive']['sampled_peaks']['velocity_mm_s'])
        self.assertLessEqual(result['adaptive']['factor_upper'],1.1*result['adaptive']['sampled_factor_lower'])
        self.assertEqual(result['intervals'],sum(result['adaptive']['segment_subdivisions']))

    def test_all_linear_and_angular_bounds_cover_dense_actual_derivatives_and_retiming(self):
        positions=[[0.,.1,0.,0.,0.,0.],[.4,-.2,.1,0.,0.,0.],[.8,.3,-.1,0.,0.,0.]]
        points=motion.from_positions([0.,.8,2.],positions);model=sample.KinematicJets(kin());local=[[12.,-9.,5.],[-30.,10.,0.]]
        caps=limits();result=sample.adaptive_bounds(model,points,local,subdivisions=1,max_subdivisions=8,limits=caps)
        for t in [2*i/200 for i in range(201)]:
            for side in ('left','right'):
                value=model.evaluate(motion.evaluate(points,t,side=side),local)
                for field in sample.LINEAR[1:]:
                    self.assertLessEqual(max(math.hypot(*p[field]) for p in value['points']),result[field]*(1+1e-12))
                for field in sample.ANGULAR:self.assertLessEqual(math.hypot(*value[field]),result[field]*(1+1e-12)+1e-12)
        factor=result['adaptive']['factor_upper'];scaled=motion.scale(points,factor)
        metric_caps={**caps['sample_translation'],
                     **{field:math.radians(caps['sample_rotation'][key]) for field,key in zip(sample.ANGULAR,
                        ['velocity_deg_s','acceleration_deg_s2','jerk_deg_s3'])}}
        for t in [scaled[-1]['time_s']*i/100 for i in range(101)]:
            value=model.evaluate(motion.evaluate(scaled,t),local)
            for field in sample.LINEAR[1:]:self.assertLessEqual(max(math.hypot(*p[field]) for p in value['points']),metric_caps[field]*(1+1e-10))
            for field in sample.ANGULAR:self.assertLessEqual(math.hypot(*value[field]),metric_caps[field]*(1+1e-10))

    def test_refines_worst_segment_and_reuses_compiled_kinematics(self):
        class Counted(sample.KinematicJets):
            count=0
            def __init__(self,value):type(self).count+=1;super().__init__(value)
        model=Counted(kin());points=motion.from_positions([0.,1.],[[0.]*6,[1.,0.,0.,0.,0.,0.]])
        points.append({**copy.deepcopy(points[-1]),'time_s':2.})
        result=sample.adaptive_bounds(model,points,subdivisions=1,max_subdivisions=16,limits=limits())
        self.assertEqual(Counted.count,1)
        self.assertGreater(result['adaptive']['segment_subdivisions'][0],1)
        self.assertEqual(result['adaptive']['segment_subdivisions'][1],1)

    def test_maximum_refinement_is_explicit_when_gap_cannot_be_closed(self):
        points=motion.from_positions([0.,1.],[[0.]*6,[2.,0.,0.,0.,0.,0.]])
        result=sample.adaptive_bounds(kin(),points,subdivisions=1,max_subdivisions=1,limits=limits())
        self.assertEqual(result['adaptive']['stop_reason'],'worst_segment_at_maximum')
        self.assertEqual(result['adaptive']['segment_subdivisions'],[1])
        self.assertGreater(result['adaptive']['factor_upper'],result['adaptive']['sampled_factor_lower'])

    def test_invalid_limits_and_refinement_contract_are_rejected(self):
        points=motion.from_positions([0.,1.],[[0.]*6,[.1,0.,0.,0.,0.,0.]])
        for base,maximum in [(0,4),(True,4),(4,3),(3,8)]:
            with self.subTest(base=base,maximum=maximum),self.assertRaises(ValueError):
                sample.adaptive_bounds(kin(),points,subdivisions=base,max_subdivisions=maximum,limits=limits())
        for value in [None,{}, {'sample_translation':{'velocity_mm_s':0.}}]:
            with self.subTest(limits=value),self.assertRaises(ValueError):sample.adaptive_bounds(kin(),points,limits=value)


if __name__=='__main__':unittest.main()
