"""Opt-in open-lid indexing and synthetic program-event replay.

No command registration, transport server, hardware I/O or safety qualification.
The existing Simulator and its closed-lid index/start contracts stay unchanged.
"""
import hashlib
import json
import math
from pathlib import Path
import time

from centrifuge_control import Simulator,ControlError,require
import centrifuge_model as model

ROOT=model.ROOT
SOURCE=ROOT/'model/cf01-open-lid-index.protocol.json'
SCHEMA=ROOT/'model/cf01-open-lid-index.schema.json'
FORMAT='solidcraftbot.cf01-open-lid-index-protocol/1'
OBSERVATION_TOLERANCE=1e-7  # Numeric replay roundoff, not a physical sensor tolerance.


def _read_reference(reference,expected):
    if not isinstance(reference,dict) or set(reference)!={'source','source_sha256'} or reference['source']!=expected:
        raise ValueError('Exactly the existing '+expected+' source must be bound')
    path=ROOT/expected
    if model.digest(path)!=reference['source_sha256']:raise ValueError('Pinned source changed: '+expected)
    return json.loads(path.read_text(encoding='utf-8'))


def load(path=SOURCE):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    schema=json.loads(SCHEMA.read_text(encoding='utf-8'))
    if not isinstance(data,dict) or set(data)!=set(schema['required']):raise ValueError('Exact additive open-lid contract fields required')
    for key,rule in schema['properties'].items():
        if 'const' in rule and data[key]!=rule['const']:raise ValueError('Unsupported open-lid contract: '+key)
    if data['format']!=FORMAT or not isinstance(data['sources'],dict) or set(data['sources'])!={'station','protocol'}:
        raise ValueError('Station and existing protocol bindings required')
    station=_read_reference(data['sources']['station'],'model/centrifuge-cf01.shared.json')
    protocol=_read_reference(data['sources']['protocol'],'model/centrifuge-cf01.protocol.json')
    if data['command']['id']!='index_open_lid' or data['command']['preconditions']!=['owner','no_latched_fault','_still','_clear','_parked','open_lid_held']:
        raise ValueError('The implemented open-lid predicates must remain explicit')
    if data['limits']!={'index_speed_rpm':{'source':'station','path':['handling','index_limit_rpm'],'unit':'rpm'}}:
        raise ValueError('Index speed must reference the existing station limit')
    limit=station['handling']['index_limit_rpm']
    if type(limit) not in (int,float) or not math.isfinite(limit) or limit<=0:raise ValueError('Finite source index speed required')
    used={'InvalidArgument','InvalidToken','RecoveryRequired','StaleFeedback','NotStationary',
          'WorkspaceOccupied','TubeRaised','LidNotOpen','LidAccessFault','ParkingBrakeFault',
          'RotationSensorFault','StaleRotationFeedback','BrakeReleaseUnconfirmed'}
    if not used<=set(protocol['errors']):raise ValueError('Only existing protocol errors may be used')
    if (not isinstance(data['limitations'],list) or not data['limitations']
            or any(not isinstance(text,str) or not text.strip() for text in data['limitations'])):
        raise ValueError('Explicit simulation limitations required')
    return data


class OpenLidIndexSimulator(Simulator):
    """Only explicit construction of this class enables index_open_lid."""
    def __init__(self,spec=None,clock=time.monotonic,qualification=None,auto_feedback=True,initial_slots=None,contract_source=SOURCE):
        self.open_lid_contract=load(contract_source)
        expected=json.loads((ROOT/self.open_lid_contract['sources']['station']['source']).read_text(encoding='utf-8'))
        if spec is not None and spec!=expected:raise ValueError('Opt-in contract binds the exact existing station source')
        super().__init__(spec=spec or expected,clock=clock,qualification=qualification,
                         auto_feedback=auto_feedback,initial_slots=initial_slots)

    def execute(self,command,token=None,**args):
        if command!='index_open_lid':return super().execute(command,token,**args)
        self._sync();self._owner(token)
        require(self.fault is None,'RecoveryRequired','Latched fault requires explicit recovery')
        self._still();self._clear();self._parked()
        require(self.lid=='open','LidNotOpen','Fully open lid required for opt-in indexing')
        require(self.lid_open_switch and self.lid_holding_brake and self.lid_brake_healthy,
                'LidAccessFault','Open limit and healthy held lid required')
        slot=args.get('slot')
        require(set(args)=={'slot'} and type(slot) is int and 1<=slot<=self.spec['rotor']['slots'],
                'InvalidArgument','Exactly one existing integer rotor slot required')
        self._release_brake()
        # Same idealized rotor/encoder/brake effect as base index, preserving lid state.
        self.indexed_slot=slot;self.encoder_deg=-(slot-1)*360/self.spec['rotor']['slots']
        self.index_ok=True;self.encoder_homed=True
        self.event('CF01.index_open_lid',slot=slot,peak_speed_rpm=self.spec['handling']['index_limit_rpm'],rotor_angle_deg=self.encoder_deg)
        require(self.parking_brake_healthy and self.brake_engage_confirmed,'ParkingBrakeFault','Confirm parking caliper holds indexed rotor')
        self.brake=True;self.event('CF01.brake.held')
        return self.status()


def _finite(value,name):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Finite '+name+' required')
    return value


def _near(a,b):return abs(a-b)<=OBSERVATION_TOLERANCE


def _observation(sim,state,clear):
    values=state.get('station');numeric=state.get('station_state',{})
    names=[joint['id'] for joint in model.expanded(sim.spec,sim.p)['joints']]
    if not isinstance(values,dict) or set(values)!=set(names):raise ValueError('Complete synthetic station coordinates required')
    for name,value in values.items():_finite(value,name)
    velocities=numeric.get('v');accelerations=numeric.get('a')
    if not isinstance(velocities,list) or not isinstance(accelerations,list) or len(velocities)!=len(names) or len(accelerations)!=len(names):
        raise ValueError('Complete synthetic station velocity and acceleration required')
    for value in [*velocities,*accelerations]:_finite(value,'station derivative')
    require(all(abs(value)<=OBSERVATION_TOLERANCE for value in [*velocities,*accelerations]),
            'NotStationary','All station axes must be resting at command boundaries')
    angle=values['Lid'];closed=_near(angle,0.);opened=_near(angle,105.)
    sim.lid='closed' if closed else 'open' if opened else 'moving'
    sim.lid_angle_deg=0. if closed else 105. if opened else angle
    sim.lid_closed_switch=closed;sim.lid_open_switch=opened
    sim.latch_positions=[0. if _near(values[name],0.) else sim.p['latch_travel'] if _near(values[name],sim.p['latch_travel']) else values[name]
                         for name in ['LatchLeft','LatchRight']]
    sim.pins_locked_confirmed=sim.latch_positions==[0.,0.]
    sim.pins_retracted_confirmed=sim.latch_positions==[sim.p['latch_travel']]*2
    sim.locked=closed and sim.pins_locked_confirmed
    sim.lid_holding_brake=closed or opened
    sim.brake=_near(values['BrakeUpper'],0.) and _near(values['BrakeLower'],0.)
    sim.rpm=0.;sim.zero_speed=True;sim.robot_clear=clear
    tube=values['TubeLift'];pusher=values['Lift']
    sim.lift_mm=0. if _near(tube,0.) and _near(pusher,0.) else tube if not _near(tube,0.) else pusher
    sim.encoder_deg=values['Rotor']
    sim.feedback_time=sim.clock();sim.encoder_feedback_time=sim.clock()
    return values


def _projection(sim):
    return {'lid':sim.lid,'lid_locked':sim.locked,'lid_angle_deg':sim.lid_angle_deg,
            'latch_positions_mm':sim.latch_positions[:],
            'indexed_slot':sim.indexed_slot,'encoder_deg':sim.encoder_deg,'index_confirmed':sim.index_ok,
            'brake_held':sim.brake,'lift_mm':sim.lift_mm,'robot_clear':sim.robot_clear}


def replay_program(program,evaluator=None):
    """Replay explicit station event pairs against synthetic boundary observations.

    The logical clock and injected local heartbeats only maintain the mock owner;
    this is no watchdog, communication, execution-time or physical-sensor test.
    ``evaluator`` is a test dependency; production callers use ProgramEvaluator.
    """
    contract=load()
    if program.get('format')!='solidcraftbot.cf01-unload-program/1' or program.get('definition',{}).get('initial_state')!='full_rotor_after_spin':
        raise ValueError('A compiled full-post-spin unloading program is required')
    from cf01_rack_batch import load as load_batch,SOURCE as BATCH_SOURCE
    originals=sorted(load_batch()['samples'],key=lambda item:item['rack_slot'])
    samples=program.get('samples');selected=program.get('selected_samples')
    if not isinstance(samples,list) or len(samples)!=len(originals):raise ValueError('All original post-spin samples required')
    expected={item['id']:item for item in originals};actual={item.get('id'):item for item in samples}
    if len(actual)!=len(samples) or set(actual)!=set(expected):raise ValueError('Unique original sample identities required')
    for identity,item in expected.items():
        if any(actual[identity].get(key)!=item[key] for key in ['rotor_slot','rack_slot','mass_g']):
            raise ValueError('Original rotor/rack/mass binding changed: '+identity)
    if not isinstance(selected,list) or not selected or selected!=[item['id'] for item in originals[:len(selected)]]:
        raise ValueError('An original ordered unloading prefix is required')
    transfers={item['sample_id']:item for item in program.get('transfers',[])}
    if len(transfers)!=len(program.get('transfers',[])) or set(transfers)!=set(selected):raise ValueError('One transfer per selected sample required')
    for item in transfers.values():
        times=[_finite(item.get(key),key) for key in ['gripped_s','removed_confirmed_s','clear_s','support_s','released_s']]
        if any(a>=b for a,b in zip(times,times[1:])):raise ValueError('Ordered grasp/removal/clear/support/release times required')
    expected_commands=[]
    for index,identity in enumerate(selected):
        expected_commands.extend([(identity,'index' if index==0 else 'index_open_lid')])
        if index==0:expected_commands.append((identity,'open_lid'))
        expected_commands.extend((identity,name) for name in ['present_tube','confirm_removed','retract_lift'])
    expected_commands.append((selected[-1],'close_lid'))
    if evaluator is None:
        from cf01_unload_motion import ProgramEvaluator
        evaluator=ProgramEvaluator(program)
    if not callable(evaluator):raise ValueError('Synthetic program evaluator required')
    now=[0.];sim=OpenLidIndexSimulator(clock=lambda:now[0],auto_feedback=False,
        initial_slots={item['rotor_slot']:{'present':True,'seated':True,'mass_g':item['mass_g']} for item in originals})
    token=sim.execute('acquire',client_id='synthetic-open-lid-replay')['token']
    heartbeat_count=0;clear=True;owners={identity:'rotor' for identity in expected};active=None
    released=set();removed=set();commands=[];pending=None;next_command=0;previous_time=-1.
    def advance(t):
        nonlocal heartbeat_count
        interval=sim.spec['handling']['owner_timeout_s']/2
        while now[0]+interval<t:
            now[0]+=interval;sim.execute('heartbeat',token);heartbeat_count+=1
        now[0]=t;sim.execute('heartbeat',token);heartbeat_count+=1
    try:
        events=program.get('events',[])
        for event_index,event in enumerate(events):
            t=_finite(event.get('time_s'),'event time')
            if t<0 or t<previous_time:raise ValueError('Program events must be in nondecreasing logical time')
            previous_time=t;advance(t)
            kind=event.get('kind');identity=event.get('sample_id')
            if kind=='active':
                if identity not in selected:raise ValueError('Unknown active sample')
                if active is not None and identity!=active and active not in released:
                    raise ValueError('Next sample cannot be active before prior jaw release')
                active=identity
            if 'workspace_clear' in event:
                observed=event['workspace_clear']
                if type(observed) is not bool:raise ValueError('Boolean synthetic workspace observation required')
                if observed is False and pending is not None:raise ValueError('Robot entry while station command is pending')
                if observed is True and clear is False and active not in removed:
                    raise ValueError('Clearance cannot precede confirmed tube removal')
                clear=observed
            if kind=='owner':
                if identity!=active or identity not in owners:raise ValueError('Ownership must name the active original')
                target=event.get('owner')
                if target=='gripper':
                    if owners[identity]!='rotor' or clear or not _near(t,transfers[identity]['gripped_s']):raise ValueError('Grasp requires matching occupied-workspace observation')
                elif target=='rack':
                    if owners[identity]!='gripper' or identity not in removed or not clear or not _near(t,transfers[identity]['support_s']):raise ValueError('Rack support requires confirmed removed original and clearance')
                else:raise ValueError('Unsupported ownership change')
                owners[identity]=target
            if event.get('phase_key')=='jaws_released':
                state=evaluator(t)
                if identity not in selected or owners[identity]!='rack' or not _near(t,transfers[identity]['released_s']) or not _near(state['jaw_gap_mm'],program['scene']['gripper']['open_gap_mm']):
                    raise ValueError('Complete matching jaw-release observation required')
                released.add(identity)
            if kind=='station_command_started':
                name=event.get('command')
                if pending is not None or next_command>=len(expected_commands) or (identity,name)!=expected_commands[next_command]:
                    raise ValueError('Station command order or pending command mismatch')
                if identity!=active:raise ValueError('Station command does not name active sample')
                if name in {'index','index_open_lid'}:
                    index=selected.index(identity)
                    if index and selected[index-1] not in released:raise ValueError('Index must wait for previous jaw release')
                state=evaluator(t);_observation(sim,state,clear);before=_projection(sim)
                if name in {'open_lid','close_lid'}:
                    # The frozen core executes a lid move instantaneously and
                    # consumes the pin acknowledgement before its ideal effect.
                    # Use only this command's explicit completion endpoint to
                    # supply that synthetic acknowledgement; it is not feedback
                    # available at the earlier physical start time.
                    completion=next((item for item in events[event_index+1:]
                                     if item.get('kind') in {'station_command_started','station_command_confirmed'}),None)
                    if (completion is None or completion.get('kind')!='station_command_confirmed'
                            or (completion.get('sample_id'),completion.get('command'))!=(identity,name)):
                        raise ValueError('Lid command requires its next explicit completion endpoint')
                    end_state=evaluator(_finite(completion.get('time_s'),'completion time'))
                    pins=end_state.get('station',{})
                    target=sim.p['latch_travel'] if name=='open_lid' else 0.
                    if any(type(pins.get(pin)) not in (int,float) or not _near(pins[pin],target)
                           for pin in ['LatchLeft','LatchRight']):
                        raise ValueError('Synthetic lid completion must acknowledge both locking pins')
                    if name=='open_lid':sim.pins_retracted_confirmed=True
                    else:sim.pins_locked_confirmed=True
                if name=='confirm_removed':
                    if owners[identity]!='gripper' or not _near(t,transfers[identity]['removed_confirmed_s']):raise ValueError('Explicit matching tube-removal threshold observation required')
                    sim.execute(name,token,grasp_confirmed=True,tube_absent=True);removed.add(identity)
                elif name in {'index','index_open_lid'}:sim.execute(name,token,slot=actual[identity]['rotor_slot'])
                else:sim.execute(name,token)
                pending={'sample_id':identity,'command':name,'started_s':t,'start':before,'expected':_projection(sim)}
                next_command+=1
            elif kind=='station_command_confirmed':
                name=event.get('command')
                if pending is None or (identity,name)!=(pending['sample_id'],pending['command']):raise ValueError('Unmatched station confirmation')
                state=evaluator(t);_observation(sim,state,clear);observed=_projection(sim)
                for key,value in pending['expected'].items():
                    if type(value) in (int,float) and value is not None:
                        matches=type(observed[key]) in (int,float) and _near(observed[key],value)
                    else:matches=observed[key]==value
                    if not matches:raise ValueError('Station confirmation disagrees with command effect: '+name+'/'+key)
                commands.append({**{key:value for key,value in pending.items() if key!='expected'},'confirmed_s':t,'confirmed':observed,'evidence':'synthetic_program_state'})
                pending=None
        if pending is not None or next_command!=len(expected_commands):raise ValueError('Missing station command or completion')
        if released!=set(selected) or removed!=set(selected):raise ValueError('All selected transfers need removal and jaw release')
        if owners!={identity:'rack' if identity in selected else 'rotor' for identity in expected}:raise ValueError('Original sample ownership changed')
        _observation(sim,evaluator(now[0]),clear)
        sim._closed();sim._still();sim._clear();sim._parked()
        for identity,item in actual.items():
            if sim.slots[item['rotor_slot']]['present']!=(identity not in selected):raise ValueError('Final rotor inventory disagrees with original identities')
    except ControlError as error:
        raise ValueError('Synthetic station replay rejected ('+error.code+'): '+str(error)) from error
    paths=[SOURCE,SCHEMA,Path(__file__),ROOT/'scripts/centrifuge_control.py',BATCH_SOURCE,
           *[ROOT/ref['source'] for ref in contract['sources'].values()]]
    return {'passed':True,'mode':'simulation_only','command_count':len(commands),'commands':commands,
            'selected_samples':selected,'owners':owners,'final_station':_projection(sim),
            'source_files_sha256':{str(path.relative_to(ROOT)):model.digest(path) for path in paths},
            'program_semantic_sha256':hashlib.sha256(json.dumps(program,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
            'synthetic_owner_heartbeats':heartbeat_count,'watchdog_tested':False,
            'clock':'Logical program event clock; injected synthetic heartbeats only retain mock ownership',
            'limits':'Synthetic predicate replay only; no physical observations, timing qualification, transport binding or safety proof'}


def replay_station_commands(program,evaluator=None):return replay_program(program,evaluator)
