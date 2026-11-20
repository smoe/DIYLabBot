"""Empty robot commands reuse instance FK and respect stop-inclusive limits."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import walkthrough_robots as robots
import robot_spec as robot
import lab_layout_model as layout


class RobotCommandsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A rigid test placement independent of expensive whole-building compile.
        cls.source=layout.load(validate_builds=False)
        cls.item=next(i for i in cls.source['instances'] if i['id']=='ArmA')
        cls.world=layout.matrix(cls.item,layout.parameters(cls.source))
        interface={'laboratories':[{'id':'Lab3003','level_id':'OG3','layout_source':{'source':'model/lab-layout-l01.shared.json'},'device_instances':[{'id':'ArmA','asset':'arm','world_pose':cls.world,'body_prefix':'Lab3003_ArmA_'}]}]}
        cls.objects,items=robots.compile(interface);cls.config=items[0]

    def test_motion_limits_include_any_stop_time(self):
        c=self.config
        self.assertGreater(c['duration_s'],0)
        self.assertLess(c['duration_s'],3)
        for key,limit in c['limits'].items():self.assertLessEqual(max(c['derivative_bounds'][key]),limit)
        self.assertIsNone(c['human_comparison'])
        self.assertFalse(any(c['qualification'].values()))

    def test_all_link_bodies_and_cameras_follow_their_source_link(self):
        spec=robot.expanded(layout.instance_source(self.source,self.item))
        expected={link['id']:{'Lab3003_ArmA_'+o['body'] for o in link['recipe'] if o['action']=='create' and o['role']!='viewing_cone'} for link in spec['links']}
        owners=set()
        for o,j in zip(self.objects,spec['joints']):
            self.assertEqual(set(o['moving_body_ids']),expected[j['child']])
            self.assertFalse(owners&set(o['moving_body_ids']));owners.update(o['moving_body_ids'])
        self.assertEqual(set(self.config['trigger_body_ids']),set.union(*expected.values()))

    def test_flange_position_and_orientation_derivatives_are_finite_and_enclosed(self):
        from types import SimpleNamespace
        import sample_motion as sample
        spec=layout.instance_source(self.source,self.item)
        p=robot.parameters(spec)
        kin=SimpleNamespace(base=self.world,frames=[robot.frame(j,p) for j in spec['joints']],
            flange=[robot.evaluate(v,p) for v in spec['flange_reference']['point']],length=0.)
        c=self.config
        for start,end in [(c['reference_deg'],c['demo_deg']),(c['demo_deg'],c['reference_deg'])]:
            points=robots.points(start,end,c['duration_s']);curve=robots.motion.Curve(points)
            enclosed=sample.bounds(kin,points,subdivisions=4)
            for n in range(81):
                state=sample.evaluate(kin,curve.evaluate(c['duration_s']*n/80))
                for field in (*sample.LINEAR[1:],*sample.ANGULAR):
                    norm=math.sqrt(sum(v*v for v in state[field]))
                    self.assertTrue(math.isfinite(norm))
                    self.assertLessEqual(norm,enclosed[field]+1e-6)

    def test_runtime_and_serial_deltas_match_independent_robot_fk(self):
        spec=layout.instance_source(self.source,self.item)
        reference=robot.forward(spec,self.config['reference_deg'])
        samples=[]
        for fraction in [0,.17,.5,.83,1]:
            q=[a+fraction*(b-a) for a,b in zip(self.config['reference_deg'],self.config['demo_deg'])]
            fk=robot.forward(spec,q);matrices=[]
            for j in spec['joints']:
                pose=robot.multiply(self.world,fk[j['child']]);base=robot.multiply(self.world,reference[j['child']])
                m=robot.multiply(pose,robot.inverse(base))
                matrices.append([m[r][c]/(1000 if c==3 and r<3 else 1) for c in range(4) for r in range(4)])
            samples.append({'q':q,'matrices':matrices})
        result=subprocess.run(['node',str(ROOT/'tests/check_walkthrough_robots.cjs')],input=json.dumps({'robot':self.config,'objects':self.objects,'fk':samples}),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
