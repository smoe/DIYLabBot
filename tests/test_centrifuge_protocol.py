"""CF01 timeline, SI mapping and observable execution/transfer semantics."""
import copy
import math
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import centrifuge_model as model
import centrifuge_protocol as protocol
from centrifuge_control import Simulator,ControlError,COMMAND_ARGUMENTS
from build_centrifuge_interfaces import FIELDS,feature


class CF01ProtocolTests(unittest.TestCase):
    def fixture(self):
        clock=[0.]
        sim=Simulator(clock=lambda:clock[0],qualification={'simulation_fixture':True,'rotor_rpm':15000,'drive_rpm':15000,
            'assembly_rcf_x_g':16000,'tube_rcf_x_g':16000,'tube_mass_limit_g':3.,'pair_tolerance_g':.01})
        for item in sim.slots.values():item['mass_g']=2.
        bridge=protocol.MockProtocol(sim);token=bridge.invoke('acquire',client_id='offline-test')['token']
        return clock,sim,bridge,token

    def test_timeline_keeps_rotor_held_and_pins_clear_before_lid_moves(self):
        spec=model.load();p=model.parameters(spec);keys=protocol.frames(spec,p);source=model.expanded(spec,p)
        for i in range(331):
            values=protocol.at_time(keys,i/10)['values'];model.validate_pose(source,values)
            self.assertEqual(values['Rotor'],0);self.assertEqual(values['BrakeUpper'],0)
            if values['TubeLift']>0:
                self.assertEqual(values['Lid'],105)
                self.assertAlmostEqual(values['Lift']-values['TubeLift'],p['park_gap'])
        self.assertEqual(protocol.at_time(keys,0)['values'],protocol.at_time(keys,33)['values'])
        self.assertEqual(protocol.at_time(keys,16)['values']['TubeLift'],16)

    def test_si_state_is_coherent_and_pickup_is_only_valid_after_presentation(self):
        _,sim,bridge,token=self.fixture()
        a=protocol.state_si(sim.status());self.assertFalse(a['pickup_valid'])
        for command,args in [('index',{'slot':1}),('open_lid',{}),('present_tube',{})]:bridge.begin(command,token,**args)
        state=protocol.state_si(sim.status());self.assertTrue(state['pickup_valid'])
        self.assertAlmostEqual(state['lift_m'],.016);self.assertAlmostEqual(state['lid_angle_rad'],math.radians(105))
        self.assertEqual(set(state),{n for _,n,_ in FIELDS})
        self.assertEqual(state['pickup_position_m'],[v/1000 for v in sim.status()['grip_frame']['position_mm']])

    def test_unknown_encoder_number_has_explicit_invalid_flag(self):
        _,sim,_,_=self.fixture();sim.encoder_healthy=False
        state=protocol.state_si(sim.status());self.assertFalse(state['speed_valid']);self.assertFalse(state['rotor_angle_valid']);self.assertFalse(state['pickup_valid'])
        self.assertEqual(state['speed_rad_s'],0)

    def test_transfer_requires_grasp_absence_and_clear_workspace(self):
        _,sim,bridge,token=self.fixture()
        for command,args in [('index',{'slot':1}),('open_lid',{}),('present_tube',{})]:bridge.begin(command,token,**args)
        with self.assertRaises(ControlError):bridge.invoke('confirm_removed',token,grasp_confirmed=True,tube_absent=False)
        sim.robot_clear=False
        bridge.invoke('confirm_removed',token,grasp_confirmed=True,tube_absent=True)
        self.assertFalse(protocol.state_si(sim.status())['pickup_valid'])
        for command in ('retract_lift','close_lid'):
            with self.assertRaises(ControlError):bridge.begin(command,token)
        sim.robot_clear=True;bridge.begin('retract_lift',token);bridge.begin('close_lid',token)
        self.assertTrue(sim.locked);self.assertEqual(sim.lift_mm,0)

    def test_run_observable_waits_through_deceleration(self):
        clock,sim,bridge,token=self.fixture();job=bridge.begin('start',token,rcf_x_g=1000,duration_s=2)
        self.assertEqual(job['phase'],'running');self.assertFalse(job['state']['standstill_confirmed'])
        clock[0]=2.;job=bridge.poll(job['id']);self.assertEqual(job['phase'],'braking');self.assertFalse(sim.brake)
        clock[0]=7.1;job=bridge.poll(job['id']);self.assertEqual(job['phase'],'succeeded');self.assertTrue(sim.brake)

    def test_cancel_does_not_complete_at_rpc_acceptance(self):
        clock,sim,bridge,token=self.fixture();job=bridge.begin('start',token,rcf_x_g=1000,duration_s=30)
        result=bridge.cancel(job['id']);self.assertEqual(result['phase'],'stopping');self.assertFalse(result['state']['standstill_confirmed'])
        clock[0]=4.;self.assertEqual(bridge.poll(job['id'])['phase'],'stopping')
        clock[0]=5.1;self.assertEqual(bridge.poll(job['id'])['phase'],'canceled');self.assertEqual(sim.rpm,0)

    def test_busy_motion_cannot_replace_run_and_heartbeat_remains_available(self):
        _,_,bridge,token=self.fixture();bridge.begin('start',token,rcf_x_g=1000,duration_s=30)
        bridge.invoke('heartbeat',token)
        with self.assertRaises(ControlError) as failure:bridge.begin('index',token,slot=2)
        self.assertEqual(failure.exception.code,'Busy')

    def test_owner_loss_faults_job_without_false_success(self):
        clock,sim,bridge,token=self.fixture();job=bridge.begin('start',token,rcf_x_g=1000,duration_s=30)
        clock[0]=11;result=bridge.poll(job['id']);self.assertEqual(result['phase'],'stopping');self.assertEqual(result['error_code'],'OwnerTimeout')
        clock[0]=17;result=bridge.poll(job['id']);self.assertEqual(result['phase'],'failed');self.assertTrue(result['state']['standstill_confirmed'])

    def test_default_source_does_not_authorize_physical_or_fixture_spin(self):
        sim=Simulator();bridge=protocol.MockProtocol(sim);token=bridge.invoke('acquire',client_id='default')['token']
        with self.assertRaises(ControlError) as failure:bridge.begin('start',token,rcf_x_g=1000,duration_s=2)
        self.assertEqual(failure.exception.code,'UnqualifiedAssembly')

    def test_sila_and_ros_names_map_same_command_contract(self):
        data=protocol.load();root=ET.fromstring(feature(data));ns={'s':'http://www.sila-standard.org'}
        commands=root.findall('s:Command',ns)
        self.assertEqual({c.find('s:Identifier',ns).text for c in commands},{c['name'] for c in data['commands'] if not c.get('local_only')})
        self.assertEqual(COMMAND_ARGUMENTS,protocol.command_arguments())
        self.assertEqual(sum(c.find('s:Observable',ns).text=='Yes' for c in commands),7)

    def test_both_wire_parameter_encodings_execute_the_same_pickup(self):
        for transport in ('ros2','sila2'):
            sim=Simulator();bridge=protocol.MockProtocol(sim)
            if transport=='ros2':
                acquired=bridge.dispatch(transport,'acquire',{'client_id':'ros-client'});token=acquired['control_token']
                requests=[('index',{'control_token':token,'slot':1}),('open_lid',{'control_token':token}),('present_tube',{'control_token':token})]
            else:
                acquired=bridge.dispatch(transport,'AcquireControl',{'ClientId':'sila-client'});token=acquired['control_token']
                requests=[('IndexRotor',{'ControlToken':token,'Slot':1}),('OpenLid',{'ControlToken':token}),('PresentTube',{'ControlToken':token})]
            for name,args in requests:result=bridge.dispatch(transport,name,args)
            self.assertEqual(result['phase'],'succeeded');self.assertTrue(result['state']['pickup_valid']);self.assertEqual(result['state']['lift_m'],.016)


if __name__=='__main__':unittest.main()
