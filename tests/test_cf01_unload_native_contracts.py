"""CAD-free regression checks for the native unloading audit's contracts."""
import itertools
import io
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import check_cf01_unload_motion as qa
import synthetic_lab_scene as layout


class NativeUnloadContractTests(unittest.TestCase):
    def test_world_hinge_envelopes_contain_every_corner_including_interior_extrema(self):
        entry=next(e for e in layout.instrument_instances() if e['instance']['asset']=='nanodrop')
        minimum=[-7.,-100.,-30.];maximum=[30.,37.,120.]
        lower,upper=qa.swept_bounds(entry,minimum,maximum)
        for index in range(401):
            angle=entry['parameters']['max_open']*index/400
            matrix=layout.component_matrix(entry,'MovingArm',angle)
            for corner in itertools.product(*zip(minimum,maximum)):
                point=qa.pickup.robot.transform(matrix,corner)
                for axis in range(3):
                    self.assertGreaterEqual(point[axis],lower[axis]);self.assertLessEqual(point[axis],upper[axis])
        endpoints=[qa.pickup.robot.transform(layout.component_matrix(entry,'MovingArm',angle),corner)
                   for angle in [0.,entry['parameters']['max_open']]
                   for corner in itertools.product(*zip(minimum,maximum))]
        self.assertTrue(any(upper[i]>max(v[i] for v in endpoints)+1. for i in range(3)))

    def test_all_twelve_sample_pairs_have_collision_scope_independent_of_owner(self):
        frame={'id':'Rotor','kind':'station','group':'RotorGroup','sample_id':None}
        arm={'id':'ArmShell','kind':'arm','group':'Arm.L2','sample_id':None}
        for index in range(1,13):
            tube={'id':f'Tube{index:02d}','sample_id':f'Sample{index:02d}','kind':'station','group':f'Tube{index:02d}'}
            cap={**tube,'id':f'ClosedCap{index:02d}'}
            self.assertEqual(qa.pair_category(tube,frame,{}),'sample_environment')
            self.assertEqual(qa.pair_category(tube,arm,{}),'sample_environment')
            self.assertIsNone(qa.pair_category(tube,cap,{}))
            neighbor={**tube,'id':'Neighbor','sample_id':'other'}
            self.assertEqual(qa.pair_category(tube,neighbor,{}),'different_samples')

    def test_grasp_exception_only_active_tube_two_pads_until_release(self):
        tube={'id':'Tube02','sample_id':'Sample02'};cap={**tube,'id':'ClosedCap02'}
        pad={'id':'LeftFingerPad'};sample={'time_s':2.,'active_sample_id':'Sample02'}
        transfers={'Sample02':{'released_s':3.}}
        self.assertTrue(qa.intended_pad_contact(tube,pad,sample,transfers))
        self.assertTrue(qa.intended_pad_contact({'id':'RightFingerPad'},tube,sample,transfers))
        self.assertFalse(qa.intended_pad_contact(cap,pad,sample,transfers))
        self.assertFalse(qa.intended_pad_contact(tube,{'id':'LeftFingerStem'},sample,transfers))
        self.assertFalse(qa.intended_pad_contact(tube,pad,{**sample,'active_sample_id':'Sample01'},transfers))
        self.assertFalse(qa.intended_pad_contact(tube,pad,{**sample,'time_s':3.001},transfers))

    def test_support_exception_only_thin_actual_base_top_intersection(self):
        tube={'id':'Tube02','sample_id':'Sample02'}
        base={'id':'Rack.Base','box':{'max':[0.,0.,3.]}}
        thin=SimpleNamespace(BoundBox=SimpleNamespace(ZMin=2.9999,ZMax=3.0001))
        deep=SimpleNamespace(BoundBox=SimpleNamespace(ZMin=2.99,ZMax=3.))
        self.assertTrue(qa.support_boundary(tube,base,thin))
        self.assertFalse(qa.support_boundary(tube,base,deep))
        self.assertFalse(qa.support_boundary(tube,{**base,'id':'Rack.Guide'},thin))
        self.assertFalse(qa.support_boundary({**tube,'id':'ClosedCap02'},base,thin))

    def test_clearance_is_recomputed_for_each_actual_station_movement(self):
        values=[[0.,0.,0.],[30.,0.,0.],[30.,0.,0.],[30.,0.,10.],[30.,105.,10.]]
        points=[{'time_s':float(t),'p':value,'v':[0.]*3,'a':[0.]*3} for t,value in enumerate(values)]
        program={'station':{'joint_names':['Rotor','Lid','Lift'],'points':points}}
        windows=qa.clearance_windows(program)
        self.assertEqual([(w['start_s'],w['end_s'],w['changed_coordinates']) for w in windows],
                         [(0.,1.,['Rotor']),(2.,3.,['Lift']),(3.,4.,['Lid'])])
        self.assertIn('RotorGroup',windows[0]['station_groups']);self.assertIn('PresentedTube',windows[0]['station_groups'])
        self.assertEqual(windows[1]['station_groups'],['EjectorGroup']);self.assertEqual(windows[2]['station_groups'],['LidGroup'])
        program['samples']=[{'id':'one','tube_body':'Tube01'},{'id':'two','tube_body':'Tube02'}]
        sample={'owners':{'one':'gripper','two':'rotor'},'active_sample_id':'one'}
        moved=qa.moving_groups(windows[0],sample,program)
        self.assertNotIn('Tube01',moved);self.assertIn('Tube02',moved)
        lift={'station_groups':['PresentedTube'],'changed_coordinates':['TubeLift']}
        self.assertEqual(qa.moving_groups(lift,sample,program),set())
        sample['active_sample_id']='two';self.assertEqual(qa.moving_groups(lift,sample,program),{'Tube02'})

    def test_carried_tube_three_mm_from_moving_rotor_fails_station_margin(self):
        """The old robot-only equipment margin would miss this carried tube."""
        scene=qa.pickup.load();arm_group='Arm.'+qa.pickup.arm_source(scene)['links'][0]['id']
        class Placement:
            def multiply(self,other):return self
        class Shape:
            def __init__(self):self.Placement=Placement()
            def copy(self):return Shape()
            def distToShape(self,other):return (3.,None,None)
        def record(identity,group,minimum,maximum,kind,sample_id=None):
            return {'id':identity,'group':group,'minimum':minimum,'maximum':maximum,
                    'kind':kind,'sample_id':sample_id,'shape':Shape()}
        records=[record('Rotor','RotorGroup',[0.,0.,0.],[1.,1.,1.],'station'),
                 record('Tube01','Tube01',[4.,0.,0.],[5.,1.,1.],'station','one'),
                 record('ArmBody',arm_group,[100.,0.,0.],[101.,1.,1.],'arm')]
        points=qa.compiler.motion.from_positions([0.,1.],[[0.],[30.]])
        program={'scene':scene,'samples':[{'id':'one','tube_body':'Tube01'},{'id':'two','tube_body':'Tube02'}],
                 'station':{'joint_names':['Rotor'],'points':qa.compiler._generic(points)},
                 'transfers':[{'sample_id':'one','released_s':2.}]}
        sample={'time_s':.5,'owners':{'one':'gripper','two':'rotor'},'active_sample_id':'one','phase_key':'indexing'}
        matrices={r['group']:qa.pickup.robot.identity() for r in records}
        frames=[{'sample':sample,'matrices':matrices,'side':'right'}]
        with patch.object(qa.compiler,'SceneEvaluator',return_value=lambda sample:matrices),\
             patch.object(qa,'adaptive_frames',return_value=(frames,{})),\
             patch.object(qa,'_placement',return_value=Placement()),patch('sys.stdout',new=io.StringIO()):
            result=qa.audit(None,program,records)
        failures=[f for f in result['distance_failures'] if f['category']=='moving_station']
        self.assertFalse(result['passed']);self.assertEqual(len(failures),1)
        self.assertEqual(failures[0]['distance_mm'],3.);self.assertEqual(failures[0]['changed_coordinates'],['Rotor'])
        self.assertGreater(result['moving_station_clearance']['windows'][0]['bound_tests'],0)

    def test_adaptive_evaluation_uses_actual_interior_curve_knots_and_event_sides(self):
        calls=[]
        class Evaluator:
            def __init__(self,program):pass
            def __call__(self,t,side='right'):
                calls.append((t,side))
                return {'time_s':t,'joints_deg':[4*math.sin(2*math.pi*t)],
                        'station':{'Lid':0.,'Rotor':0.}}
        program={'duration_s':1.,'arm':{'points':[{'time_s':0.},{'time_s':1.}]},
                 'station':{'points':[{'time_s':0.},{'time_s':.3},{'time_s':1.}]},
                 'jaw':{'points':[{'time_s':0.},{'time_s':1.}]},'events':[{'time_s':.7}]}
        def projection(sample):return {'test':qa.pickup.placement([20*math.sin(2*math.pi*sample['time_s']),0.,0.],0.)}
        record={'group':'test','minimum':[-1.,-1.,-1.],'maximum':[1.,1.,1.]}
        with patch.object(qa.compiler,'ProgramEvaluator',Evaluator):frames,spacing=qa.adaptive_frames(program,projection,[record])
        self.assertGreater(len(frames),8)
        self.assertLessEqual(spacing['maximum_body_bound_corner_step_mm'],2.)
        self.assertLessEqual(spacing['maximum_joint_rotor_or_lid_step_deg'],1.)
        self.assertIn((.3,'right'),calls);self.assertIn((.7,'left'),calls);self.assertIn((.7,'right'),calls)


if __name__=='__main__':unittest.main()
