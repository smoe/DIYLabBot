"""Order-preserving Rack -> CF01 -> original Rack slots, with an injected station.

Robot handoffs are explicit synthetic confirmations, not loading motion plans.
The transporter is only the external rack-ready precondition.
"""
import copy
import json
import math
import hashlib
from pathlib import Path
import assembly_model as assembly
import centrifuge_model as cf
import centrifuge_protocol as protocol
import synthetic_workspace as workspace
import rack_slots
from centrifuge_control import Simulator, ControlError

ROOT=cf.ROOT
SOURCE=ROOT/'model/cf01-rack-batch.protocol.json'


class BatchError(ValueError):
    def __init__(self,message,report):super().__init__(message);self.report=report


class ProcessHold(RuntimeError):
    """A durably recorded hold: stop/observation remain possible, unlike failed storage."""


def load(path=SOURCE):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    validate(data)
    return data


def validate(data):
    if data['format']!='solidcraftbot.cf01-rack-batch/1' or data['mode']!='local_mock_only':raise ValueError('Local mock batch contract required')
    workspace.load(assembly.validate_reference(data['workspace']))
    if assembly.validate_reference(data['station_contract'])!=protocol.SOURCE.resolve():raise ValueError('Existing CF01 command contract required')
    if data['return_policy']!='original_rack_slot' or data['sample_order']!='ascending_rack_slot':raise ValueError('Stable rack order required')
    if data['preconditions']!={'rack_delivered_by_transporter':True,'transporter_modeled':False}:raise ValueError('External rack delivery is a precondition only')
    if data['initial_state']!={'rotor':'empty','rack':'samples'}:raise ValueError('Explicit synthetic initial state required')
    if data['handoff_policy']!={'completion':'robot_and_required_station_confirmation','on_partial_confirmation':'unresolved','during_handoff':'pending'}:raise ValueError('Explicit unresolved-handoff policy required')
    if data['mock_assumptions']!={'mass_source':'fictitious_profile','handoff_time_s':0}:raise ValueError('Explicit mock assumptions required')
    execution=data['command_execution']
    if set(execution)!={'poll_interval_s','completion_timeout_s'} or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in execution.values()):raise ValueError('Finite positive command timing required')
    if execution['poll_interval_s']>min(execution['completion_timeout_s'],cf.load()['mechanisms']['braking']['simulation_stop_s']/2):raise ValueError('Polling interval exceeds completion/braking observation window')
    samples=data['samples'];capacity=cf.load()['rotor']['slots']
    if len(samples)!=capacity:raise ValueError('Current batch profile requires a complete balanced twelve-place rotor')
    for field in ['rack_slot','rotor_slot']:
        values=[s[field] for s in samples]
        if any(type(v) is not int for v in values) or set(values)!=set(range(1,capacity+1)):raise ValueError('Unique complete '+field+' mapping required')
    if any(not isinstance(s['id'],str) or not s['id'] for s in samples) or len({s['id'] for s in samples})!=capacity:raise ValueError('Unique sample identities required')
    for s in samples:
        if type(s['mass_g']) not in (int,float) or not math.isfinite(s['mass_g']) or s['mass_g']<=0:raise ValueError('Explicit positive fictitious sample masses required')
    for key in ['rcf_x_g','duration_s']:
        value=data['spin'][key]
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Finite positive spin setting required')
    if data['simulation_qualification'].get('simulation_fixture') is not True:raise ValueError('Only explicit fictitious simulation qualification is supported')
    rack=workspace.read(workspace.load(assembly.validate_reference(data['workspace']))['devices']['Rack']['source'])
    if rack['rows']*rack['columns']!=capacity:raise ValueError('Rack and batch capacity mismatch')


def synthetic_feedback(event,sample):
    """Fictitious positive feedback helper for injected tests; identity is an echo, not a sensor.

    Default Runner feedback instead reads its separate synthetic world inventory.
    All values are for the local test fixture, never hardware."""
    return {'sample_id':sample['id'] if sample else None,'rack_present':True,'grasp_confirmed':True,
            'source_empty':True,'seated_confirmed':True,'cap_closed_confirmed':True,
            'released_confirmed':True,'workspace_clear':True}


class Runner:
    def __init__(self,data=None,transport='ros2',feedback=None,clock=None,advance_clock=None,checkpoint=None,station_backend=None,advance_hold_clock=None):
        self.data=copy.deepcopy(data or load());validate(self.data)
        self.station_backend=station_backend
        if station_backend is not None:
            if transport!='sila2' or clock is not None or advance_clock is not None:
                raise ValueError('Network station supplies its own SiLA transport and monotonic clock')
            clock,advance_clock=station_backend.now,station_backend.advance
        if transport not in ['ros2','sila2']:raise ValueError('Supported local contract decoding: ros2 or sila2')
        if (clock is None)!=(advance_clock is None):raise ValueError('External clock and advance_clock must be provided together')
        if any(callback is not None and not callable(callback) for callback in (clock,advance_clock,checkpoint,advance_hold_clock)):
            raise ValueError('Clock and checkpoint callbacks must be callable')
        self._local_now=0.;self._clock=clock;self._advance_clock=advance_clock;self._checkpoint=checkpoint
        self._advance_hold_clock=advance_hold_clock;self._held=False
        self._checkpoint_failed=False;self._checkpoint_sequence=0;self._command_sequence=0
        self._last_station=None;self._station_time=None;self._last_job=None;self._job_signature=None;self._heartbeat_count=0
        self.transport=transport;self.feedback=feedback;self.trace=[];self.token=None
        self.capacity=len(self.data['samples']);self.pending_handoff=None
        self.current_sample=None;self.operation=None;self.failure=None
        self.stop_attempted=False;self.stop_via_contract=False
        self.sim=None if station_backend is not None else Simulator(clock=lambda:self.now,qualification=self.data['simulation_qualification'],
                           initial_slots={i:{'present':False,'seated':False,'mass_g':None} for i in range(1,self.capacity+1)})
        self.bridge=station_backend if station_backend is not None else protocol.MockProtocol(self.sim)
        self.station_spec=station_backend.spec if station_backend is not None else self.sim.spec
        self.samples=sorted(self.data['samples'],key=lambda s:s['rack_slot'])
        devices=workspace.load(assembly.validate_reference(self.data['workspace']))['devices']
        self.rack_instance=devices['Rack']['id'];self.station_instance=devices['CF01']['id'];self.arm_instance=devices['Arm']['id']
        rack=workspace.read(devices['Rack']['source'])
        self.rack_places=rack_slots.places(rack)
        self.places_by_slot={p['slot']:p for p in self.rack_places}
        self.slots_by_place={p['place_id']:p['slot'] for p in self.rack_places}
        self.initial=[s['id'] for s in self.samples];self.rack=self.initial[:];self.rotor=[None]*self.capacity;self.gripper=None
        self.world={'rack':self.initial[:],'rotor':[None]*self.capacity,'gripper':None}
        self.stop_error=None;self.spin_completed=False

    def station_state(self):
        return self.station_backend.state() if self.station_backend is not None else protocol.state_si(self.sim.execute('status'))

    def station_slots(self, state=None):
        if self.station_backend is None:return self.sim.slots
        state=state or self.station_state()
        return {value['slot']:{'present':value['present'],'seated':value['seated'],
                              'mass_g':value['mass_g'] if value['mass_valid'] else None}
                for value in state['rotor_slots']}

    def robot_access(self,event,sample):
        if self.station_backend is not None:self.station_backend.observe_robot(event,sample)
        else:self.sim.robot_clear=event=='withdraw'

    @property
    def now(self):
        if self._clock is None:return self._local_now
        try:value=self._clock()
        except BaseException:
            self._checkpoint_failed=True
            raise
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            raise ValueError('External clock must return finite nonnegative seconds')
        return value

    @now.setter
    def now(self,value):
        if self._clock is not None:raise ValueError('External clock advances only through advance_clock')
        self._local_now=value

    def _checkpoint_healthy(self):
        if self._checkpoint_failed:raise RuntimeError('Checkpoint failure invalidated this CF01 execution')

    def checkpoint_view(self):
        """Last observed compact state; this is not a resumable simulator snapshot."""
        return {'inventory':self.snapshot(),**self.handoff_state(),'time_s':self.now,
                'operation':self.operation,'sample_id':self.current_sample,'spin_completed':self.spin_completed,
                'station':copy.deepcopy(self._last_station),'station_observed_at_s':self._station_time,
                'job':copy.deepcopy(self._last_job),'heartbeat_count':self._heartbeat_count,
                'stop_attempted':self.stop_attempted,'stop_via_contract':self.stop_via_contract,
                'stop_error':self.stop_error,'failure':copy.deepcopy(self.failure)}

    def _emit(self,kind,payload):
        if self._checkpoint is None:return
        self._checkpoint_healthy()
        self._checkpoint_sequence+=1
        try:
            self._checkpoint(kind,copy.deepcopy({**payload,'checkpoint_sequence':self._checkpoint_sequence}),self.checkpoint_view())
        except ProcessHold:
            self._held=True
            raise
        except BaseException:
            # A failed durable write leaves the last intent uncertain. Do not
            # continue actions or turn the persistence failure into a device reply.
            self._checkpoint_failed=True
            raise

    def _remember_reply(self,result):
        if not isinstance(result,dict):return
        if isinstance(result.get('state'),dict):
            self._last_station=copy.deepcopy(result['state']);self._station_time=self.now
        if 'id' in result and 'phase' in result:
            self._last_job={key:copy.deepcopy(result[key]) for key in ('id','command','phase','error_code') if key in result}
            self._job_signature=(result['id'],result['phase'])

    def snapshot(self):
        return {'rack':self.rack[:],'rotor':self.rotor[:],'gripper':self.gripper}

    def rack_location(self,slot):
        return {'kind':'rack','instance_id':self.rack_instance,'place_id':self.places_by_slot[slot]['place_id']}

    def handoff_state(self):
        consistent=self.snapshot()==self.world
        return {'pending_handoff':copy.deepcopy(self.pending_handoff),
                'world_inventory':copy.deepcopy(self.world),'inventory_consistent':consistent,
                'ownership':('confirmed' if consistent and self.pending_handoff is None else 'unresolved' if self.failure is not None else 'pending')}

    def begin_handoff(self,event,sample):
        self._checkpoint_healthy()
        if self.pending_handoff is not None:raise ValueError('Previous handoff remains unresolved')
        rack=self.rack_location(sample['rack_slot'])
        rotor={'kind':'rotor','instance_id':self.station_instance,'slot':sample['rotor_slot']}
        gripper={'kind':'gripper','instance_id':self.arm_instance}
        source,destination={'pick_rack':(rack,gripper),'seat_rotor':(gripper,rotor),
                            'take_rotor':(rotor,gripper),'place_rack':(gripper,rack)}[event]
        self.pending_handoff={'event':event,'sample_id':sample['id'],'source':source,'destination':destination,
                              'robot_confirmation':False,'station_confirmation':False if event in ('seat_rotor','take_rotor') else None}
        self._emit('handoff_intent',self.pending_handoff)

    def complete_handoff(self):
        self._checkpoint_healthy()
        self.operation='complete_handoff'
        pending=self.pending_handoff
        if not pending or not pending['robot_confirmation'] or pending['station_confirmation'] is False:
            raise ValueError('Handoff confirmations incomplete')
        # Update responsibility only after the requested handoff is fully confirmed.
        # The synthetic world is a separate observation, not a replacement ledger.
        candidate=self.snapshot()
        def position(location):
            if location['kind']=='gripper':return candidate,'gripper'
            if location['kind']=='rotor':return candidate['rotor'],location['slot']-1
            return candidate['rack'],self.slots_by_place[location['place_id']]-1
        source,source_key=position(pending['source']);destination,destination_key=position(pending['destination'])
        if source[source_key]!=pending['sample_id'] or destination[destination_key] is not None:
            raise ValueError('Handoff ledger source or destination mismatch')
        source[source_key]=None;destination[destination_key]=pending['sample_id']
        if candidate!=self.world:raise ValueError('Handoff ledger disagrees with synthetic world inventory')
        self.rack=candidate['rack'];self.rotor=candidate['rotor'];self.gripper=candidate['gripper']
        self.pending_handoff=None
        self._emit('handoff_completed',pending)

    def record(self,stage,**details):
        if 'rack_slot' in details:
            details.update(rack_place_id=self.rack_places[details['rack_slot']-1]['id'],
                           rack_instance=self.rack_instance,place_id=self.rack_location(details['rack_slot'])['place_id'])
        station=self.station_state()
        self._last_station=copy.deepcopy(station);self._station_time=self.now
        self.trace.append({'sequence':len(self.trace)+1,'time_s':self.now,'stage':stage,**details,
                           'inventory':self.snapshot(),**self.handoff_state(),'station':station})
        if stage!='heartbeat':self._emit('state_observed',{'stage':stage,**details})

    def command(self,name,**args):
        self._checkpoint_healthy()
        if self._held and name not in {'stop','heartbeat','status','rotation_feedback'}:
            raise ProcessHold('CF01 is held; only stop and observation are permitted')
        self.operation=name
        self._command_sequence+=1;sequence=self._command_sequence
        contract=next(c for c in self.bridge.contract['commands'] if c['id']==name)
        fields=dict(args)
        if name not in protocol.PUBLIC:fields['control_token']=self.token
        fields={protocol.wire(self.transport,k):v for k,v in fields.items()}
        intent={'command':name,'command_sequence':sequence,'arguments':args,'transport':self.transport}
        # Successful heartbeat detail is coalesced into the next compact view.
        # The enclosing observable command intent and external clock advances
        # remain durable; a failed heartbeat is always reported below.
        if name!='heartbeat':self._emit('command_intent',intent)
        if name=='stop':
            self._emit('stop_requested',intent)
            self.stop_attempted=True
        submitted_at=self.now
        result=self.bridge.dispatch(self.transport,name if self.transport=='ros2' else contract['name'],fields)
        self._remember_reply(result)
        if name!='heartbeat' or not isinstance(result,dict) or result.get('success') is not True:
            self._emit('command_reply',{'command':name,'command_sequence':sequence,'response':result})
        else:self._heartbeat_count+=1
        station_handoff=self.pending_handoff and self.pending_handoff['event']=={'confirm_seated':'seat_rotor','confirm_removed':'take_rotor'}.get(name)
        if station_handoff and (not isinstance(result,dict) or result.get('success') is not True):
            raise ValueError('Station acknowledgement missing or rejected during '+name)
        if name=='stop':
            if not isinstance(result,dict) or result.get('success') is not True:raise ValueError('Stop acknowledgement missing')
            self.stop_via_contract=True
            self._emit('stop_accepted',{'command_sequence':sequence,'response':result})
        if contract['observable']:
            result=self.wait_observable(name,result,submitted_at)
        elif not isinstance(result,dict) or result.get('success') is not True:
            raise ValueError('Command acknowledgement missing or rejected during '+name)
        if name=='acquire':
            if not isinstance(result.get('control_token'),str) or not result['control_token']:raise ValueError('Control token missing during acquire')
            self.token=result['control_token']
        if station_handoff:
            self.pending_handoff['station_confirmation']=True
        if name!='start':self.record(name,contract=self.transport,job_phase=result.get('phase'),command_state='submitted' if name=='stop' else 'completed')
        if name not in ('heartbeat','stop'):self._emit('command_completed',{'command':name,'command_sequence':sequence,'response':result})
        return result

    def wait_observable(self,name,result,submitted_at):
        """Wait on the observable contract, never infer command completion.

        Local deadlines use the test clock. An injected network station uses
        monotonic wall time and separately bounds its blocking transport calls.
        """
        interval=self.data['command_execution']['poll_interval_s']
        timeout=self.data['command_execution']['completion_timeout_s']
        if name=='start':timeout+=self.data['spin']['duration_s']+self.station_spec['mechanisms']['braking']['simulation_stop_s']
        deadline=submitted_at+timeout;job_id=None;braking_seen=False;running_seen=False
        while True:
            if self.now>deadline:
                self.operation=name
                raise TimeoutError('Command completion deadline exceeded during '+name)
            if (not isinstance(result,dict) or not isinstance(result.get('id'),str) or not result['id']
                or result.get('phase') not in ('running','braking','succeeded','failed','canceled','stopping')
                or job_id is not None and result['id']!=job_id):
                raise ValueError('Invalid observable response during '+name)
            first_response=job_id is None
            job_id=result['id'];phase=result['phase']
            if phase in ('failed','canceled','stopping') or phase=='braking' and name!='start':
                raise ValueError('Command did not complete: '+name+' ('+phase+')')
            if name=='start':
                if first_response:self.record('start',contract=self.transport,job_phase=phase,command_state='submitted')
                if phase=='running' and not running_seen:self.record('centrifuging',job_phase=phase);running_seen=True
                if phase=='braking' and not braking_seen:self.record('braking',job_phase=phase);braking_seen=True
            if phase=='succeeded':
                if name=='start':
                    state=result.get('state',{})
                    if not isinstance(state,dict) or not braking_seen or state.get('standstill_confirmed') is not True or state.get('parking_brake_held') is not True:
                        raise ValueError('Centrifuge completion not confirmed')
                return result
            self.operation=name
            if self.now>=deadline:raise TimeoutError('Command completion deadline exceeded during '+name)
            self.advance(min(interval,deadline-self.now))
            result=self.poll(job_id)

    def check_station(self,slot=None):
        self.operation='check_station'
        state=self.station_state()
        if slot is not None and (state['indexed_slot']!=slot or not state['index_confirmed']):
            raise ValueError('Station index confirmation disagrees with requested slot')
        slots=self.station_slots(state)
        for i,identity in enumerate(self.world['rotor'],1):
            sensed=slots[i]
            if sensed['present']!=(identity is not None):raise ValueError('Station presence disagrees with synthetic world inventory')
            if identity is not None:
                sample=next(s for s in self.samples if s['id']==identity)
                if not sensed['seated'] or sensed['mass_g']!=sample['mass_g']:raise ValueError('Station seating or fixture mass mismatch')

    def observe(self,event,sample=None,fields=()):
        # Independent fixture inventory uses the ACTUAL indexed slot, not the
        # requested sample ID. This is still synthetic, not physical identification.
        self._checkpoint_healthy();self.operation=event
        if event in ('pick_rack','seat_rotor','take_rotor','place_rack'):self.begin_handoff(event,sample)
        actual=None
        if sample:
            indexed=self.station_state()['indexed_slot']
            if event=='pick_rack':actual=self.world['rack'][sample['rack_slot']-1]
            elif event=='withdraw':actual=self.world['gripper'] or self.world['rotor'][indexed-1]
            elif event=='take_rotor':actual=self.world['rotor'][indexed-1]
            else:actual=self.world['gripper']
            if actual!=sample['id']:raise ValueError('Synthetic world identity mismatch during '+event)
        data=self.feedback(event,copy.deepcopy(sample)) if self.feedback else {**synthetic_feedback(event,None),'sample_id':actual}
        if not isinstance(data,dict):raise ValueError('Feedback must be an object during '+event)
        if sample and data.get('sample_id')!=actual:raise ValueError('Observed sample identity mismatch during '+event)
        if any(data.get(field) is not True for field in fields):raise ValueError('Missing positive confirmation during '+event)
        if sample:
            if event=='pick_rack':self.world['rack'][sample['rack_slot']-1]=None;self.world['gripper']=actual
            elif event=='seat_rotor':self.world['rotor'][indexed-1]=actual;self.world['gripper']=None
            elif event=='take_rotor':self.world['rotor'][indexed-1]=None;self.world['gripper']=actual
            elif event=='place_rack':
                if self.world['rack'][sample['rack_slot']-1] is not None:raise ValueError('Synthetic world rack slot occupied')
                self.world['rack'][sample['rack_slot']-1]=actual;self.world['gripper']=None
            if event in ('pick_rack','seat_rotor','take_rotor','place_rack'):self.pending_handoff['robot_confirmation']=True
        self._emit('robot_observed',{'event':event,'sample_id':sample['id'] if sample else None,'feedback':data})
        return data

    def clear(self,sample):
        self.observe('withdraw',sample,('workspace_clear',));self.robot_access('withdraw',sample)
        self.record('robot_clear',sample_id=sample['id'])

    def poll(self,job_id):
        self._checkpoint_healthy()
        self.operation='poll'
        result=self.bridge.poll(job_id);previous=self._job_signature
        self._remember_reply(result)
        valid=(isinstance(result,dict) and isinstance(result.get('id'),str)
               and result.get('phase') in ('running','braking','succeeded','failed','canceled','stopping'))
        if not valid or self._job_signature!=previous:
            self._emit('job_observed',{'job_id':job_id,'response':result})
        return result

    def advance(self,seconds):
        self._checkpoint_healthy()
        target=self.now+seconds
        interval=min(1.,self.station_spec['handling']['owner_timeout_s']/2)
        while self.now<target:
            before=self.now;following=min(target,before+interval)
            if self._advance_clock is None:self.now=following
            else:
                callback=self._advance_hold_clock if self._held and self._advance_hold_clock is not None else self._advance_clock
                try:callback(following-before)
                except ProcessHold:
                    self._held=True
                    raise
                except BaseException:
                    self._checkpoint_failed=True
                    raise
                actual=self.now
                valid=(actual>=following if self.station_backend is not None else math.isclose(actual-before,following-before,rel_tol=1e-12,abs_tol=1e-9))
                if actual<=before or not valid:
                    self._checkpoint_failed=True
                    raise ValueError('External clock did not advance by the requested duration')
            self.command('heartbeat')

    def wait_for_stop(self):
        """Observe braking under a recorded hold; do not infer stillness from receipt."""
        deadline=self.now+self.station_spec['mechanisms']['braking']['simulation_stop_s']+self.data['command_execution']['completion_timeout_s']
        interval=self.data['command_execution']['poll_interval_s']
        while True:
            self.record('stop_observed')
            if self._last_job is not None:self.poll(self._last_job['id'])
            state=self._last_station
            if state['standstill_confirmed'] is True and state['parking_brake_held'] is True:return
            if self.now>=deadline:raise TimeoutError('Controlled stop completion deadline exceeded')
            self.advance(min(interval,deadline-self.now))

    def report(self,passed,error=None):
        network=self.station_backend is not None
        return {'format':'solidcraftbot.cf01-batch-report/1','passed':passed,'mode':'network_mock_only' if network else 'local_mock_only',
                'transport_contract':self.transport,'network_executed':network,'hardware_executed':False,
                'transporter_executed':False,'robot_motion_for_loading_checked':False,'robot_motion_checked':False,
                'polling':'SiLA TLS/gRPC observable execution and typed status' if network else 'local MockProtocol.poll, no transport serialization',
                'station_inventory_check':'SiLA v2 typed RotorSlots; synthetic observations, no physical sensor evidence' if network else 'mock_internal: Simulator.slots; not available in state_si or a hardware contract',
                'stop_attempted':self.stop_attempted,'stop_via_contract':self.stop_via_contract,'stop_error':self.stop_error,
                'inventory_semantics':'Ledger of fully confirmed handoffs, not an assertion of physical location',
                'handoff_policy':self.data['handoff_policy'],**self.handoff_state(),'failure':self.failure,
                'initial_state':self.data['initial_state'],'mock_assumptions':self.data['mock_assumptions'],
                'command_execution':self.data['command_execution'],'time_semantics':'Server monotonic real time at 1x; client deadlines use monotonic wall time; synthetic robot observations' if network else 'Zero-time robot handoffs; explicit test clock during observable command waits, including spin and braking',
                'effective_profile_sha256':hashlib.sha256(json.dumps(self.data,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                'effective_profile':self.data,'rack_instance':self.rack_instance,'sample_mapping':[{**s,'rack_place_id':self.rack_places[s['rack_slot']-1]['id'],'rack_instance':self.rack_instance,'place_id':self.rack_location(s['rack_slot'])['place_id']} for s in self.samples],'rack_places':self.rack_places,'initial_order':self.initial,'final_order':self.rack[:],
                'order_restored':passed and self.spin_completed and self.rack==self.initial and all(x is None for x in self.rotor) and self.gripper is None,
                'spin_completed':self.spin_completed,'inventory':self.snapshot(),'error':error,'trace':self.trace,
                'source_files_sha256':{str(p.relative_to(ROOT)):cf.digest(p) for p in [Path(__file__),protocol.SOURCE,ROOT/'scripts/centrifuge_control.py',ROOT/'scripts/centrifuge_protocol.py',ROOT/'scripts/centrifuge_model.py',ROOT/'scripts/synthetic_workspace.py',ROOT/'scripts/rack_slots.py',*workspace.source_dependencies(workspace.load(assembly.validate_reference(self.data['workspace'])))]},
                'limitations':self.station_backend.profile['network_batch']['limitations'] if network else self.data['limitations'],
                **({'network':self.station_backend.evidence()} if network else {})}

    def run(self):
        self._checkpoint_healthy()
        try:
            self.observe('rack_ready',None,('rack_present',))
            self.record('rack_ready',external_delivery=True)
            self.command('acquire',client_id='synthetic-rack-batch')
            for sample in self.samples:
                self.current_sample=sample['id']
                r,c=sample['rack_slot']-1,sample['rotor_slot']-1
                if self.rack[r]!=sample['id'] or self.rotor[c] is not None or self.gripper is not None:raise ValueError('Loading inventory mismatch')
                self.command('index',slot=c+1);self.check_station(c+1);self.command('open_lid')
                self.observe('pick_rack',sample,('grasp_confirmed','source_empty'))
                self.complete_handoff();self.robot_access('begin_loading',sample)
                self.record('rack_to_gripper',sample_id=sample['id'],rack_slot=r+1,rotor_slot=c+1)
                seat=self.observe('seat_rotor',sample,('seated_confirmed','cap_closed_confirmed','released_confirmed'))
                self.command('confirm_seated',mass_g=sample['mass_g'],seated_confirmed=seat['seated_confirmed'],cap_closed_confirmed=seat['cap_closed_confirmed'])
                self.check_station(c+1);self.complete_handoff()
                self.record('gripper_to_rotor',sample_id=sample['id'],rack_slot=r+1,rotor_slot=c+1)
                self.clear(sample);self.command('close_lid')
            if any(self.rack) or self.gripper is not None or any(x is None for x in self.rotor):raise ValueError('Batch not completely loaded')
            self.current_sample=None
            done=self.command('start',**self.data['spin'])
            self.spin_completed=True;self.record('spin_complete',job_phase=done['phase'])
            for sample in self.samples:
                self.current_sample=sample['id']
                r,c=sample['rack_slot']-1,sample['rotor_slot']-1
                if self.rotor[c]!=sample['id'] or self.rack[r] is not None or self.gripper is not None:raise ValueError('Return inventory mismatch')
                self.command('index',slot=c+1);self.check_station(c+1);self.command('open_lid');self.command('present_tube')
                take=self.observe('take_rotor',sample,('grasp_confirmed','source_empty'));self.robot_access('begin_removal',sample)
                self.command('confirm_removed',grasp_confirmed=take['grasp_confirmed'],tube_absent=take['source_empty'])
                self.check_station(c+1);self.complete_handoff()
                self.record('rotor_to_gripper',sample_id=sample['id'],rack_slot=r+1,rotor_slot=c+1)
                self.clear(sample);self.command('retract_lift');self.command('close_lid')
                self.observe('place_rack',sample,('seated_confirmed','released_confirmed'))
                if self.rack[r] is not None:raise ValueError('Original rack slot is occupied')
                self.complete_handoff()
                self.record('gripper_to_original_rack_slot',sample_id=sample['id'],rack_slot=r+1,rotor_slot=c+1)
            if self.rack!=self.initial or any(self.rotor) or self.gripper is not None:raise ValueError('Original sample order not restored')
            if any(s['present'] for s in self.station_slots().values()):raise ValueError('Station sensor inventory disagrees with ledger')
            self.current_sample=None
            self.command('release');self.record('complete')
            return self.report(True)
        except Exception as error:
            if self._checkpoint_failed:raise
            self.failure={'operation':self.operation,'sample_id':self.current_sample,
                          'error_type':type(error).__name__,'error_code':getattr(error,'code',None),
                          'station_fault':(self._last_station or {}).get('fault_code') if self.station_backend is not None else self.sim.fault}
            self._emit('failed',{'reason':str(error),**self.failure})
            # Preserve the failure report even if the stop or status channel fails.
            try:
                self.command('stop')
                if self._held:self.wait_for_stop()
            except Exception as stop_error:
                if self._checkpoint_failed:raise
                self.stop_error=str(stop_error)
            try:self.record('failed',reason=str(error),**self.failure)
            except Exception:
                if self._checkpoint_failed:raise
                self.trace.append({'sequence':len(self.trace)+1,'time_s':self.now,'stage':'failed','reason':str(error),**self.failure,'inventory':self.snapshot(),**self.handoff_state(),'station':None})
            raise BatchError(str(error),self.report(False,str(error))) from error
