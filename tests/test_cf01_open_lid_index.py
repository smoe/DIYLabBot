"""Additive open-lid command guards and synthetic event-replay regression tests."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import cf01_open_lid_index as extension
import cf01_rack_batch as batch
import centrifuge_model as model
import centrifuge_protocol as protocol
from centrifuge_control import Simulator,ControlError,COMMAND_ARGUMENTS,request_schema


def replay_fixture(count=3):
    """Ideal stationary boundary observations, deliberately no native evidence."""
    spec=model.load();p=model.parameters(spec)
    samples=copy.deepcopy(batch.load()['samples']);chosen=samples[:count]
    program={'format':'solidcraftbot.cf01-unload-program/1',
             'definition':{'initial_state':'full_rotor_after_spin'},'samples':samples,
             'selected_samples':[item['id'] for item in chosen],
             'scene':{'gripper':{'open_gap_mm':20.}},'transfers':[],'events':[]}
    values=model.pose(spec,p,'closed');history=[(0.,copy.deepcopy(values))];cursor=0.
    def event(t,kind,sample=None,**extra):
        program['events'].append({'time_s':t,'kind':kind,'sample_id':sample,**extra})
    def command(start,end,name,sample,changes=None):
        event(start,'station_command_started',sample,command=name)
        if changes:
            values.update(changes);history.append((end,copy.deepcopy(values)))
        event(end,'station_command_confirmed',sample,command=name)
    event(0.,'initial',workspace_clear=True)
    for index,sample in enumerate(chosen):
        identity=sample['id'];event(cursor,'active',identity)
        command(cursor,cursor+1,'index' if index==0 else 'index_open_lid',identity,
                {'Rotor':-(sample['rotor_slot']-1)*30.});cursor+=1
        if index==0:
            command(cursor,cursor+1,'open_lid',identity,
                    {'Lid':105.,'LatchLeft':p['latch_travel'],'LatchRight':p['latch_travel']});cursor+=1
        command(cursor,cursor+1,'present_tube',identity,
                {'Lift':p['park_gap']+p['lift_travel'],'TubeLift':p['lift_travel']});cursor+=1
        grip=cursor+2;removed=cursor+3;clear=cursor+4;support=clear+3;release=clear+4
        event(cursor+1,'workspace',identity,workspace_clear=False)
        event(grip,'owner',identity,owner='gripper')
        command(removed,removed,'confirm_removed',identity)
        event(clear,'workspace',identity,workspace_clear=True)
        command(clear,clear+1,'retract_lift',identity,{'Lift':0.,'TubeLift':0.})
        if index==count-1:
            command(clear+1,clear+2,'close_lid',identity,{'Lid':0.,'LatchLeft':0.,'LatchRight':0.})
        event(support,'owner',identity,owner='rack')
        event(release,'phase',identity,phase_key='jaws_released')
        program['transfers'].append({'sample_id':identity,'gripped_s':grip,'removed_confirmed_s':removed,
                                    'clear_s':clear,'support_s':support,'released_s':release})
        cursor=release+1
    program['events'].sort(key=lambda item:item['time_s'])
    def evaluate(t):
        coordinates=history[0][1]
        for time_s,item in history:
            if time_s<=t:coordinates=item
        return {'station':copy.deepcopy(coordinates),'station_state':{'v':[0.]*len(values),'a':[0.]*len(values)},'jaw_gap_mm':20.}
    return program,evaluate


class OpenLidCommandTests(unittest.TestCase):
    def fixture(self,open_lid=True,auto_feedback=True):
        clock=[0.];sim=extension.OpenLidIndexSimulator(clock=lambda:clock[0],auto_feedback=auto_feedback)
        token=sim.execute('acquire',client_id='unit-test')['token']
        if open_lid:sim.execute('open_lid',token)
        return clock,sim,token

    def assert_code(self,code,sim,token,**args):
        with self.assertRaises(ControlError) as failure:sim.execute('index_open_lid',token,**({'slot':2}|args))
        self.assertEqual(failure.exception.code,code)

    def test_contract_pins_old_sources_and_references_the_existing_limit(self):
        contract=extension.load()
        self.assertEqual(contract['limits']['index_speed_rpm'],{'source':'station','path':['handling','index_limit_rpm'],'unit':'rpm'})
        self.assertTrue(contract['simulation_only']);self.assertFalse(contract['safety_qualified'])
        self.assertFalse(any(contract['bindings'].values()))
        for reference in contract['sources'].values():
            self.assertEqual(model.digest(model.ROOT/reference['source']),reference['source_sha256'])

    def test_contract_rejects_pin_drift_modified_guards_or_duplicated_limit(self):
        for mutate in [lambda data:data['sources']['station'].update(source_sha256='0'*64),
                       lambda data:data['command']['preconditions'].remove('_parked'),
                       lambda data:data['limits'].update(index_speed_rpm=2),
                       lambda data:data.update(simulation_only=False),
                       lambda data:data['bindings'].update(ros2=True)]:
            data=extension.load();mutate(data)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'contract.json';path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):extension.load(path)

    def test_schema_validates_the_contract_when_jsonschema_is_available(self):
        try:import jsonschema
        except ImportError:self.skipTest('Optional jsonschema is not installed; runtime contract validation is tested separately')
        schema=json.loads(extension.SCHEMA.read_text());jsonschema.Draft202012Validator.check_schema(schema)
        validator=jsonschema.Draft202012Validator(schema);validator.validate(extension.load())
        invalid=extension.load();invalid['extra']='not supported'
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_standard_simulator_and_wire_contracts_do_not_register_the_command(self):
        self.assertNotIn('index_open_lid',COMMAND_ARGUMENTS)
        self.assertNotIn('index_open_lid',[rule['properties']['command']['const'] for rule in request_schema()['oneOf']])
        self.assertNotIn('index_open_lid',protocol.command_arguments())
        sim=Simulator();token=sim.execute('acquire',client_id='standard-test')['token']
        with self.assertRaises(ControlError) as failure:sim.execute('index_open_lid',token,slot=2)
        self.assertEqual(failure.exception.code,'UnknownCommand')
        # The existing typed dispatch and observable-job contracts stay closed.
        _,special,token=self.fixture();bridge=protocol.MockProtocol(special)
        with self.assertRaises(ControlError) as failure:bridge.dispatch('ros2','index_open_lid',{'control_token':token,'slot':2})
        self.assertEqual(failure.exception.code,'UnknownCommand')
        with self.assertRaises(ControlError):bridge.dispatch('sila2','IndexOpenLid',{'ControlToken':token,'Slot':2})
        with self.assertRaises(ValueError):bridge.begin('index_open_lid',token,slot=2)

    def test_index_effect_matches_closed_index_and_preserves_open_lid(self):
        for slot in (1,2,12):
            _,sim,token=self.fixture();result=sim.execute('index_open_lid',token,slot=slot)
            base=Simulator();base_token=base.execute('acquire',client_id='closed-test')['token'];closed=base.execute('index',base_token,slot=slot)
            for field in ['indexed_slot','encoder_deg','index_confirmed','speed_rpm','standstill_confirmed','brake_held','lift_mm','slots']:
                self.assertEqual(result[field],closed[field])
            self.assertEqual(result['lid'],'open');self.assertEqual(sim.lid_angle_deg,105.)
            self.assertTrue(sim.lid_open_switch and sim.lid_holding_brake)
            index_event=next(item for item in sim.events if item['kind']=='CF01.index_open_lid')
            self.assertEqual(index_event['peak_speed_rpm'],sim.spec['handling']['index_limit_rpm'])

    def test_closed_or_partly_open_lid_is_rejected(self):
        _,sim,token=self.fixture(open_lid=False);self.assert_code('LidNotOpen',sim,token)
        sim.lid='moving';sim.lid_angle_deg=90.;self.assert_code('LidNotOpen',sim,token)

    def test_open_limit_and_healthy_held_lid_brake_are_required(self):
        for field in ['lid_open_switch','lid_holding_brake','lid_brake_healthy']:
            with self.subTest(field=field):
                _,sim,token=self.fixture();setattr(sim,field,False);self.assert_code('LidAccessFault',sim,token)

    def test_raised_lift_or_another_unseated_present_tube_is_rejected(self):
        _,sim,token=self.fixture();sim.lift_mm=1.;self.assert_code('TubeRaised',sim,token)
        sim.lift_mm=0.;sim.slots[12]['seated']=False;self.assert_code('TubeRaised',sim,token)

    def test_occupied_workspace_is_rejected(self):
        _,sim,token=self.fixture();sim.robot_clear=False;self.assert_code('WorkspaceOccupied',sim,token)

    def test_missing_standstill_or_parking_brake_is_rejected(self):
        for field,value in [('rpm',1.),('zero_speed',False),('brake',False)]:
            with self.subTest(field=field):
                _,sim,token=self.fixture();setattr(sim,field,value);self.assert_code('NotStationary',sim,token)

    def test_stale_feedback_and_latched_fault_are_rejected(self):
        clock,sim,token=self.fixture(auto_feedback=False)
        clock[0]=sim.spec['handling']['sensor_max_age_s']+.01;self.assert_code('StaleFeedback',sim,token)
        _,sim,token=self.fixture();sim.fault='OwnerTimeout';self.assert_code('RecoveryRequired',sim,token)

    def test_rotation_sensor_predicates_are_inherited(self):
        _,sim,token=self.fixture(auto_feedback=False);sim.encoder_healthy=False
        self.assert_code('RotationSensorFault',sim,token)
        sim.encoder_healthy=True;sim.encoder_feedback_time=-sim.spec['handling']['sensor_max_age_s']-.01
        self.assert_code('StaleRotationFeedback',sim,token)

    def test_brake_hardware_confirmations_remain_required(self):
        for field,code in [('parking_brake_healthy','ParkingBrakeFault'),('brake_release_confirmed','BrakeReleaseUnconfirmed'),('brake_engage_confirmed','ParkingBrakeFault')]:
            with self.subTest(field=field):
                _,sim,token=self.fixture();setattr(sim,field,False);self.assert_code(code,sim,token)

    def test_invalid_token_slots_and_extra_arguments_are_rejected(self):
        _,sim,token=self.fixture();self.assert_code('InvalidToken',sim,'wrong-token')
        for slot in [None,True,0,13,2.,'2']:
            with self.subTest(slot=slot):self.assert_code('InvalidArgument',sim,token,slot=slot)
        self.assert_code('InvalidArgument',sim,token,extra=True)

    def test_old_index_and_start_still_require_closed_locked_lid(self):
        _,sim,token=self.fixture()
        for name,args in [('index',{'slot':2}),('start',{'rcf_x_g':1000,'duration_s':1})]:
            with self.assertRaises(ControlError) as failure:sim.execute(name,token,**args)
            self.assertEqual(failure.exception.code,'LidUnlocked')


class StationReplayTests(unittest.TestCase):
    def test_three_samples_replay_in_order_and_keep_all_original_identities(self):
        program,evaluator=replay_fixture();report=extension.replay_station_commands(program,evaluator)
        self.assertTrue(report['passed']);self.assertFalse(report['watchdog_tested'])
        self.assertEqual(report['command_count'],14)
        self.assertEqual([item['command'] for item in report['commands']].count('index_open_lid'),2)
        self.assertEqual(len(report['owners']),12)
        self.assertEqual([key for key,value in report['owners'].items() if value=='rack'],program['selected_samples'])
        self.assertEqual(report['final_station']['lid'],'closed')
        self.assertTrue(report['source_files_sha256'])

    def test_long_logical_intervals_use_explicit_synthetic_heartbeats_without_watchdog_claim(self):
        program,evaluator=replay_fixture(count=1)
        for event in program['events']:event['time_s']*=20
        for transfer in program['transfers']:
            for key in ['gripped_s','removed_confirmed_s','clear_s','support_s','released_s']:transfer[key]*=20
        report=extension.replay_program(program,lambda t:evaluator(t/20))
        self.assertGreater(report['synthetic_owner_heartbeats'],len(program['events']))
        self.assertFalse(report['watchdog_tested'])

    def test_swapping_explicit_station_commands_is_rejected(self):
        program,evaluator=replay_fixture()
        starts=[event for event in program['events'] if event['kind']=='station_command_started']
        starts[0]['command'],starts[1]['command']=starts[1]['command'],starts[0]['command']
        with self.assertRaisesRegex(ValueError,'order'):extension.replay_program(program,evaluator)

    def test_missing_confirmation_or_removed_event_is_rejected(self):
        for name,kind in [('present_tube','station_command_confirmed'),('confirm_removed','station_command_started')]:
            program,evaluator=replay_fixture()
            event=next(item for item in program['events'] if item.get('command')==name and item['kind']==kind)
            program['events'].remove(event)
            with self.assertRaises(ValueError):extension.replay_program(program,evaluator)

    def test_next_sample_cannot_become_active_before_complete_jaw_release(self):
        program,evaluator=replay_fixture();event=next(item for item in program['events'] if item['kind']=='active' and item['sample_id']=='Sample02')
        event['time_s']=program['transfers'][0]['support_s'];program['events'].sort(key=lambda item:item['time_s'])
        with self.assertRaisesRegex(ValueError,'jaw release'):extension.replay_program(program,evaluator)

    def test_boundary_motion_instead_of_standstill_is_rejected(self):
        program,evaluator=replay_fixture()
        def moving(t):
            state=evaluator(t);state['station_state']['v'][0]=.1;return state
        with self.assertRaisesRegex(ValueError,'NotStationary'):extension.replay_program(program,moving)

    def test_wrong_rotor_endpoint_or_lid_pin_confirmation_is_rejected(self):
        for name in ['Rotor','LatchLeft']:
            program,evaluator=replay_fixture()
            def wrong(t):
                state=evaluator(t);state['station'][name]+=1.;return state
            with self.assertRaises(ValueError):extension.replay_program(program,wrong)

    def test_original_identity_binding_cannot_be_overwritten(self):
        for field,value in [('rack_slot',12),('rotor_slot',2),('mass_g',999.)]:
            program,evaluator=replay_fixture();program['samples'][0][field]=value
            with self.assertRaisesRegex(ValueError,'binding'):extension.replay_program(program,evaluator)

    def test_duplicate_transfer_is_rejected(self):
        program,evaluator=replay_fixture();program['transfers'].append(copy.deepcopy(program['transfers'][0]))
        with self.assertRaisesRegex(ValueError,'One transfer'):extension.replay_program(program,evaluator)

    def test_clearance_without_explicit_removal_or_jaw_release_without_support_fails(self):
        for kind in ['station_command_started','owner']:
            program,evaluator=replay_fixture()
            if kind=='owner':
                event=next(item for item in program['events'] if item['kind']=='owner' and item.get('owner')=='rack');program['events'].remove(event)
            else:
                event=next(item for item in program['events'] if item['kind']=='workspace' and item.get('workspace_clear') is True)
                event['time_s']=program['transfers'][0]['gripped_s'];program['events'].sort(key=lambda item:item['time_s'])
            with self.assertRaises(ValueError):extension.replay_program(program,evaluator)


if __name__=='__main__':unittest.main()
