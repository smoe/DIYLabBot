"""CF01 source, frame coupling and mock control rejection/transfer behavior."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import centrifuge_model as model
from centrifuge_control import Simulator,ControlError,demo


class ModelTests(unittest.TestCase):
    def test_rcf_and_invalid_units(self):
        self.assertAlmostEqual(model.rpm_for_rcf(16000,80),13375.0094,delta=0.01)
        for v in [0,-1,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError): model.rpm_for_rcf(v,80)

    def test_pattern_and_index_frames(self):
        spec=model.load(); p=model.parameters(spec); source=model.expanded(spec,p)
        for slot in range(1,13):
            bottom,axis=model.pocket(spec,p,slot)
            self.assertAlmostEqual(math.hypot(*bottom[:2]),p['bottom_radius'])
            self.assertAlmostEqual(sum(a*a for a in axis),1)
            moved=model.transform(source,'RotorGroup',bottom,{**model.pose(spec,p,'closed'),'Rotor':-(slot-1)*30})
            self.assertAlmostEqual(moved[0],0,places=7); self.assertAlmostEqual(moved[1],-p['bottom_radius'])

    def test_parameter_geometry_and_anchor_coupling(self):
        spec=model.load()
        for value in [78,84]:
            p=model.parameters(spec,{'bottom_radius':value}); source=model.expanded(spec,p)
            anchor=next(j for j in source['joints'] if j['id']=='TubeLift')['origin']
            cone=next(o for o in source['operations'] if o['id']=='TubeCone01')['shape']['origin']
            self.assertEqual(anchor,cone); self.assertAlmostEqual(anchor[1],-value)
        p=model.parameters(spec,{'base_height':154,'lid_clearance':8}); source=model.expanded(spec,p)
        self.assertEqual(next(j for j in source['joints'] if j['id']=='Lid')['origin'][2],p['lid_z']+p['hinge_lift'])

    def test_recipe_ids_poses_and_markings(self):
        spec=model.load(); p=model.parameters(spec); source=model.expanded(spec,p)
        for key in ['bodies','operations','joints']:
            self.assertEqual(len(source[key]),len({v['id'] for v in source[key]}))
        self.assertEqual(sum(b['id'].startswith('Number') for b in source['bodies']),24)
        for sample in model.samples(spec,p): model.validate_pose(source,sample['values'])
        for slot in [0,13,True,1.5]:
            with self.assertRaises(ValueError): model.pocket(spec,p,slot)

    def test_steel_wall_floor_and_hinge_follow_same_dimensions(self):
        spec=model.load(); self.assertIsNone(spec['rotor']['material'])
        self.assertEqual(spec['structure']['material'],'steel')
        for thickness in [22,26]:
            p=model.parameters(spec,{'chamber_wall':thickness}); src=model.expanded(spec,p)
            wall=next(o for o in src['operations'] if o['id']=='ChamberOuter')['shape']
            hinge=next(j for j in src['joints'] if j['id']=='Lid')['origin']
            self.assertEqual(wall['radius']-p['chamber_inner_radius'],thickness)
            self.assertEqual(hinge[1],wall['radius']+2)
            posts=[o['shape'] for o in src['operations'] if o['id'].startswith('SupportPost')]
            self.assertEqual(len(posts),4)
            self.assertTrue(all(s['origin'][2]==p['base_floor'] and s['origin'][2]+s['height']==p['chamber_floor_z'] for s in posts))

    def test_power_inlet_cord_and_sensor_frames_follow_parameters(self):
        spec=model.load(); p=model.parameters(spec); a=model.power_cord(spec,p)
        pp=model.parameters(spec,{'base_width':440,'encoder_gap':1.5}); b=model.power_cord(spec,pp)
        self.assertAlmostEqual(b['origin'][0]-a['origin'][0],20)
        for first,second in zip(a['curves'],a['curves'][1:]): self.assertEqual(first['end'],second['start'])
        self.assertEqual(model.service_frames(spec,pp)['encoder_readhead'][0]-pp['encoder_radius'],1.5)
        self.assertIsNone(spec['services']['power']['manufacturer_minimum_bend_radius_mm'])

    def test_encoder_bandwidth_and_resolution_are_requirements(self):
        spec=model.load(); result=model.encoder_requirements(spec,model.parameters(spec))
        self.assertTrue(result['bandwidth_requirement_sufficient']); self.assertFalse(result['accuracy_verified'])
        self.assertAlmostEqual(result['resolution_deg'],360/4096)
        self.assertGreater(result['target_counter_edges_hz'],900000)

    def test_encoder_count_conversion_never_establishes_safe_standstill(self):
        self.assertEqual(model.encoder_measurement(4096,1)['speed_rpm'],60)
        self.assertEqual(model.encoder_measurement(-1024,0.5)['speed_rpm'],-30)
        self.assertFalse(model.encoder_measurement(0,1)['standstill_confirmed'])
        for dt in [0,-1,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError): model.encoder_measurement(1,dt)
    def test_mechanism_coordinates_and_interlocks(self):
        spec=model.load();p=model.parameters(spec);src=model.expanded(spec,p)
        self.assertEqual(len(src['joints']),8)
        unsafe={**model.pose(spec,p,'closed'),'Lid':30}
        with self.assertRaises(ValueError):model.validate_pose(src,unsafe)
        with self.assertRaises(ValueError):model.validate_pose(src,{**model.pose(spec,p),'BrakeUpper':1})
        req=model.mechanisms.requirements(spec,p);self.assertTrue(req['gravity_target_covers_case']);self.assertIsNone(req['stored_energy_j'])
        self.assertEqual(spec['mechanisms']['braking']['engagement_speed_rpm'],0)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.now=0.; self.sim=Simulator(clock=lambda:self.now)
        self.token=self.sim.execute('acquire',client_id='robot')['token']
    def call(self,command,**args): return self.sim.execute(command,self.token,**args)
    def fails(self,code,command,**args):
        with self.assertRaises(ControlError) as caught: self.call(command,**args)
        self.assertEqual(caught.exception.code,code)
    def present(self):
        self.call('index',slot=3); self.call('open_lid'); return self.call('present_tube')
    def qualify_mock(self):
        self.sim.qualification={'simulation_fixture':True,'rotor_rpm':15000,'drive_rpm':15000,'assembly_rcf_x_g':16000,'tube_rcf_x_g':16000,'tube_mass_limit_g':3,'pair_tolerance_g':0.01}
        for item in self.sim.slots.values(): item['mass_g']=2.0

    def test_exclusive_owner_and_boot_tokens(self):
        self.fails('OwnershipConflict','acquire',client_id='other')
        with self.assertRaises(ControlError): self.sim.execute('open_lid','wrong-token')
        other=Simulator(); self.assertNotEqual(other.boot_id,self.sim.boot_id)
        with self.assertRaises(ControlError): other.execute('open_lid',self.token)
    def test_default_spin_is_disabled(self): self.fails('UnqualifiedAssembly','start',rcf_x_g=16000,duration_s=10)
    def test_invalid_values(self):
        for value in [float('nan'),float('inf'),-1,0,True]: self.fails('InvalidArgument','start',rcf_x_g=value,duration_s=10)
        for value in [0,13,True,1.5]: self.fails('InvalidArgument','index',slot=value)
    def test_pick_handshake_and_clearance(self):
        state=self.present(); self.assertEqual(state['lift_mm'],16); self.assertTrue(state['grip_frame']['valid'])
        self.fails('UnconfirmedTransfer','retract_lift'); self.fails('TubeRaised','close_lid')
        self.fails('UnconfirmedTransfer','confirm_removed',grasp_confirmed=True)
        self.sim.robot_clear=False; self.call('confirm_removed',grasp_confirmed=True,tube_absent=True)
        self.fails('WorkspaceOccupied','retract_lift'); self.sim.robot_clear=True
        self.call('retract_lift'); self.call('close_lid'); self.assertFalse(self.sim.slots[3]['present'])
    def test_lower_on_failed_pick(self):
        self.present(); self.fails('UnconfirmedTransfer','lower_tube')
        self.call('lower_tube',seated_confirmed=True); self.call('close_lid')
        self.assertTrue(self.sim.slots[3]['seated'])
    def test_closed_lid_index_and_encoder(self):
        self.call('open_lid'); self.fails('LidUnlocked','index',slot=1)
        self.call('close_lid'); self.call('index',slot=1); self.call('open_lid')
        self.sim.encoder_deg=1.; self.fails('IndexMismatch','present_tube')
    def test_zero_speed_and_brake_independent(self):
        self.sim.zero_speed=False; self.fails('NotStationary','open_lid')
        self.sim.zero_speed=True; self.sim.brake=False; self.fails('NotStationary','open_lid')
    def test_freshness(self):
        self.sim.auto_feedback=False; self.now=0.6; self.fails('StaleFeedback','open_lid')
    def test_grip_frame_invalid_after_removed_or_feedback_disagreement(self):
        self.present(); self.assertTrue(self.call('status')['grip_frame']['valid'])
        self.sim.encoder_deg+=1; self.assertFalse(self.call('status')['grip_frame']['valid'])
        self.sim.encoder_deg-=1; self.call('confirm_removed',grasp_confirmed=True,tube_absent=True)
        self.assertFalse(self.call('status')['grip_frame']['valid'])
    def test_balanced_spin_and_access_denial(self):
        self.qualify_mock(); state=self.call('start',rcf_x_g=16000,duration_s=2)
        self.assertGreater(state['speed_rpm'],13000); self.fails('NotStationary','open_lid'); self.fails('NotStationary','index',slot=1)
        self.now=3; state=self.call('status'); self.assertEqual(state['run']['phase'],'braking'); self.assertTrue(state['lid_locked']);self.assertFalse(state['brake_held'])
        self.now=8;state=self.call('status');self.assertEqual(state['run']['phase'],'completed');self.assertTrue(state['brake_held'])
    def test_balance_unknown_and_mismatch(self):
        self.qualify_mock(); self.sim.slots[7]['mass_g']=None; self.fails('InvalidArgument','start',rcf_x_g=1000,duration_s=2)
        self.sim.slots[7]['mass_g']=2.1; self.fails('UnbalancedLoad','start',rcf_x_g=1000,duration_s=2)
        self.sim.slots[7]['mass_g']=2.; self.sim.slots[7]['present']=False; self.fails('UnbalancedLoad','start',rcf_x_g=1000,duration_s=2)
    def test_rating_and_source_target(self):
        self.qualify_mock(); self.sim.qualification['rotor_rpm']=10000
        self.fails('LimitExceeded','start',rcf_x_g=16000,duration_s=2)
        self.fails('LimitExceeded','start',rcf_x_g=16001,duration_s=2)
    def test_lease_timeout_and_recovery(self):
        self.qualify_mock(); self.call('start',rcf_x_g=16000,duration_s=100)
        self.now=11; state=self.call('status'); self.assertEqual(state['fault'],'OwnerTimeout'); self.assertTrue(state['lid_locked'])
        self.assertEqual(state['run']['phase'],'braking'); self.fails('RecoveryRequired','open_lid')
        self.call('heartbeat');self.fails('NotStationary','reset_fault');self.now=17
        self.call('reset_fault');self.assertEqual(self.call('status')['run']['phase'],'faulted');self.call('open_lid')
    def test_recovery_with_raised_tube(self):
        self.present(); self.now=11; self.call('status'); self.call('heartbeat')
        self.fails('TubeRaised','reset_fault'); self.call('lower_tube',seated_confirmed=True); self.call('reset_fault')
    def test_sensor_loss_during_spin(self):
        self.qualify_mock(); self.call('start',rcf_x_g=16000,duration_s=100)
        self.sim.auto_feedback=False; self.now=1; state=self.call('status')
        self.assertEqual(state['fault'],'StaleFeedback'); self.assertTrue(state['lid_locked'])
    def test_rotation_feedback_command_and_homing(self):
        self.call('index',slot=2); feedback=self.sim.execute('rotation_feedback')
        self.assertEqual(feedback['id'],'CF01.ENCODER'); self.assertEqual(feedback['angle_deg'],-30)
        self.assertTrue(feedback['z_homed']); self.assertEqual(feedback['counts_per_revolution'],4096)
        self.assertFalse(feedback['independent_standstill_monitor_implemented'])
    def test_encoder_fault_blocks_access_and_faults_moving_run(self):
        self.sim.encoder_healthy=False; self.fails('RotationSensorFault','open_lid')
        self.sim.encoder_healthy=True; self.qualify_mock(); self.call('start',rcf_x_g=16000,duration_s=100)
        self.sim.encoder_healthy=False; state=self.call('status')
        self.assertEqual(state['fault'],'RotationSensorFault'); self.assertTrue(state['lid_locked'])
        self.assertIsNone(state['rotation_sensor']['speed_rpm'])
    def test_stale_encoder_is_separate_from_other_feedback(self):
        self.sim.auto_feedback=False; self.now=0.6; self.sim.feedback_time=0.6
        self.fails('StaleRotationFeedback','open_lid')
    def test_stop_and_no_auto_resume(self):
        self.qualify_mock(); self.call('start',rcf_x_g=16000,duration_s=100)
        state=self.sim.execute('stop'); self.assertEqual(state['run']['phase'],'braking');self.assertFalse(state['brake_held'])
        self.fails('NotStationary','open_lid');self.now=2;state=self.call('status');self.assertGreater(state['speed_rpm'],0)
        self.sim.execute('stop');self.now=6;self.assertEqual(self.call('status')['run']['phase'],'aborted')
    def test_powered_lid_sequences_need_no_manual_step(self):
        state=self.call('open_lid');self.assertFalse(state['mechanisms']['manual_lid_step_required']);self.assertTrue(state['mechanisms']['lid_open_limit'])
        kinds=[e['kind'] for e in self.sim.events]
        self.assertLess(kinds.index('CF01.lid.pins_retracted'),kinds.index('CF01.lid.motor_move'))
        state=self.call('close_lid');self.assertTrue(state['lid_locked']);self.assertEqual(state['mechanisms']['locking_pin_retraction_mm'],[0,0])
    def test_lid_drive_lock_and_obstruction_faults(self):
        self.sim.pins_retracted_confirmed=False;self.fails('LatchReleaseUnconfirmed','open_lid');self.assertTrue(self.sim.locked)
        self.sim.pins_retracted_confirmed=True;self.call('open_lid');self.sim.obstruction=True
        self.fails('LidObstructed','close_lid');self.assertEqual(self.sim.lid,'open')
        self.sim.obstruction=False;self.sim.pins_locked_confirmed=False;self.fails('LatchLockUnconfirmed','close_lid')
        self.fails('LidUnlocked','index',slot=1)
    def test_parking_brake_release_feedback_required(self):
        self.qualify_mock();self.sim.brake_release_confirmed=False
        self.fails('BrakeReleaseUnconfirmed','start',rcf_x_g=16000,duration_s=100);self.assertEqual(self.sim.rpm,0)
    def test_parking_brake_not_applied_on_fault_at_speed(self):
        self.qualify_mock();self.call('start',rcf_x_g=16000,duration_s=100);self.sim.encoder_healthy=False
        state=self.call('status');self.assertFalse(state['brake_held']);self.assertTrue(state['mechanisms']['electrical_braking']);self.assertTrue(state['lid_locked'])
    def test_demo_is_explicitly_mock(self):
        result=demo(); self.assertEqual(result['mode'],'SIMULATION_ONLY'); self.assertEqual(result['trace'][-1]['lift_mm'],0)


if __name__=='__main__': unittest.main()
