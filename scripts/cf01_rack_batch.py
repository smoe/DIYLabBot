"""Order-preserving Rack -> CF01 -> original Rack slots, using local protocol mocks.

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
    if data['initial_state']!={'rotor':'empty','rack':'samples','mass_source':'fictitious_profile','handoff_time_s':0}:raise ValueError('Explicit synthetic initial state required')
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
    def __init__(self,data=None,transport='ros2',feedback=None):
        self.data=copy.deepcopy(data or load());validate(self.data)
        if transport not in ['ros2','sila2']:raise ValueError('Supported local contract decoding: ros2 or sila2')
        self.transport=transport;self.feedback=feedback;self.now=0.;self.trace=[];self.token=None
        self.sim=Simulator(clock=lambda:self.now,qualification=self.data['simulation_qualification'],
                           initial_slots={i:{'present':False,'seated':False,'mass_g':None} for i in range(1,13)})
        self.bridge=protocol.MockProtocol(self.sim)
        self.samples=sorted(self.data['samples'],key=lambda s:s['rack_slot'])
        rack=workspace.read(workspace.load(assembly.validate_reference(self.data['workspace']))['devices']['Rack']['source'])
        self.rack_places=rack_slots.places(rack)
        self.initial=[s['id'] for s in self.samples];self.rack=self.initial[:];self.rotor=[None]*12;self.gripper=None
        self.world={'rack':self.initial[:],'rotor':[None]*12,'gripper':None}
        self.stop_error=None;self.spin_completed=False

    def snapshot(self):
        return {'rack':self.rack[:],'rotor':self.rotor[:],'gripper':self.gripper}

    def record(self,stage,**details):
        if 'rack_slot' in details:details['rack_place_id']=self.rack_places[details['rack_slot']-1]['id']
        self.trace.append({'sequence':len(self.trace)+1,'time_s':self.now,'stage':stage,**details,
                           'inventory':self.snapshot(),'world_inventory':copy.deepcopy(self.world),'station':protocol.state_si(self.sim.execute('status'))})

    def command(self,name,**args):
        contract=next(c for c in self.bridge.contract['commands'] if c['id']==name)
        fields=dict(args)
        if name not in protocol.PUBLIC:fields['control_token']=self.token
        fields={protocol.wire(self.transport,k):v for k,v in fields.items()}
        result=self.bridge.dispatch(self.transport,name if self.transport=='ros2' else contract['name'],fields)
        if name=='acquire':self.token=result['control_token']
        if result.get('phase') in ['failed','canceled','stopping']:raise ValueError('Command did not complete: '+name)
        self.record(name,contract=self.transport,job_phase=result.get('phase'))
        return result

    def check_station(self,slot=None):
        state=self.sim.execute('status')
        if slot is not None and (state['indexed_slot']!=slot or not state['index_confirmed']):
            raise ValueError('Station index confirmation disagrees with requested slot')
        for i,identity in enumerate(self.world['rotor'],1):
            sensed=self.sim.slots[i]
            if sensed['present']!=(identity is not None):raise ValueError('Station presence disagrees with synthetic world inventory')
            if identity is not None:
                sample=next(s for s in self.samples if s['id']==identity)
                if not sensed['seated'] or sensed['mass_g']!=sample['mass_g']:raise ValueError('Station seating or fixture mass mismatch')

    def observe(self,event,sample=None,fields=()):
        # Independent fixture inventory uses the ACTUAL indexed slot, not the
        # requested sample ID. This is still synthetic, not physical identification.
        actual=None
        if sample:
            if event=='pick_rack':actual=self.world['rack'][sample['rack_slot']-1]
            elif event=='withdraw':actual=self.world['gripper'] or self.world['rotor'][self.sim.indexed_slot-1]
            elif event=='take_rotor':actual=self.world['rotor'][self.sim.indexed_slot-1]
            else:actual=self.world['gripper']
            if actual!=sample['id']:raise ValueError('Synthetic world identity mismatch during '+event)
        data=self.feedback(event,copy.deepcopy(sample)) if self.feedback else {**synthetic_feedback(event,None),'sample_id':actual}
        if not isinstance(data,dict):raise ValueError('Feedback must be an object during '+event)
        if sample and data.get('sample_id')!=actual:raise ValueError('Observed sample identity mismatch during '+event)
        if any(data.get(field) is not True for field in fields):raise ValueError('Missing positive confirmation during '+event)
        if sample:
            if event=='pick_rack':self.world['rack'][sample['rack_slot']-1]=None;self.world['gripper']=actual
            elif event=='seat_rotor':self.world['rotor'][self.sim.indexed_slot-1]=actual;self.world['gripper']=None
            elif event=='take_rotor':self.world['rotor'][self.sim.indexed_slot-1]=None;self.world['gripper']=actual
            elif event=='place_rack':
                if self.world['rack'][sample['rack_slot']-1] is not None:raise ValueError('Synthetic world rack slot occupied')
                self.world['rack'][sample['rack_slot']-1]=actual;self.world['gripper']=None
        return data

    def clear(self,sample):
        self.observe('withdraw',sample,('workspace_clear',));self.sim.robot_clear=True
        self.record('robot_clear',sample_id=sample['id'])

    def advance(self,seconds):
        target=self.now+seconds
        interval=min(1.,self.sim.spec['handling']['owner_timeout_s']/2)
        while self.now<target:
            self.now=min(target,self.now+interval)
            self.command('heartbeat')

    def report(self,passed,error=None):
        return {'format':'solidcraftbot.cf01-batch-report/1','passed':passed,'mode':'local_mock_only',
                'transport_contract':self.transport,'network_executed':False,'hardware_executed':False,
                'transporter_executed':False,'robot_motion_for_loading_checked':False,'robot_motion_checked':False,
                'polling':'local MockProtocol.poll, no transport serialization','stop_via_contract':True,'stop_error':self.stop_error,
                'initial_state':self.data['initial_state'],'time_semantics':'Zero-time abstract handoffs; test clock advances only during spin and braking',
                'effective_profile_sha256':hashlib.sha256(json.dumps(self.data,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                'effective_profile':self.data,'sample_mapping':[{**s,'rack_place_id':self.rack_places[s['rack_slot']-1]['id']} for s in self.samples],'rack_places':self.rack_places,'initial_order':self.initial,'final_order':self.rack[:],
                'order_restored':passed and self.spin_completed and self.rack==self.initial and all(x is None for x in self.rotor) and self.gripper is None,
                'spin_completed':self.spin_completed,'inventory':self.snapshot(),'error':error,'trace':self.trace,
                'source_files_sha256':{str(p.relative_to(ROOT)):cf.digest(p) for p in [Path(__file__),protocol.SOURCE,ROOT/'scripts/centrifuge_control.py',ROOT/'scripts/centrifuge_protocol.py',ROOT/'scripts/centrifuge_model.py',ROOT/'scripts/synthetic_workspace.py',ROOT/'scripts/rack_slots.py',*workspace.source_dependencies(workspace.load(assembly.validate_reference(self.data['workspace'])))]},
                'limitations':self.data['limitations']}

    def run(self):
        try:
            self.observe('rack_ready',None,('rack_present',))
            self.record('rack_ready',external_delivery=True)
            self.command('acquire',client_id='synthetic-rack-batch')
            for sample in self.samples:
                r,c=sample['rack_slot']-1,sample['rotor_slot']-1
                if self.rack[r]!=sample['id'] or self.rotor[c] is not None or self.gripper is not None:raise ValueError('Loading inventory mismatch')
                self.command('index',slot=c+1);self.check_station(c+1);self.command('open_lid')
                self.observe('pick_rack',sample,('grasp_confirmed','source_empty'))
                self.rack[r]=None;self.gripper=sample['id'];self.sim.robot_clear=False
                self.record('rack_to_gripper',sample_id=sample['id'],rack_slot=r+1,rotor_slot=c+1)
                seat=self.observe('seat_rotor',sample,('seated_confirmed','cap_closed_confirmed','released_confirmed'))
                self.command('confirm_seated',mass_g=sample['mass_g'],seated_confirmed=seat['seated_confirmed'],cap_closed_confirmed=seat['cap_closed_confirmed'])
                self.check_station(c+1)
                self.rotor[c]=self.gripper;self.gripper=None
                self.record('gripper_to_rotor',sample_id=sample['id'],rack_slot=r+1,rotor_slot=c+1)
                self.clear(sample);self.command('close_lid')
            if any(self.rack) or self.gripper is not None or any(x is None for x in self.rotor):raise ValueError('Batch not completely loaded')
            job=self.command('start',**self.data['spin']);self.record('centrifuging',job_phase=job['phase'])
            self.advance(self.data['spin']['duration_s'])
            braking=self.bridge.poll(job['id']);self.record('braking',job_phase=braking['phase'])
            if braking['phase']!='braking':raise ValueError('Expected explicit braking phase, got '+braking['phase'])
            self.advance(self.sim.spec['mechanisms']['braking']['simulation_stop_s'])
            done=self.bridge.poll(job['id'])
            if done['phase']!='succeeded' or not done['state']['standstill_confirmed'] or not done['state']['parking_brake_held']:raise ValueError('Centrifuge completion not confirmed')
            self.spin_completed=True;self.record('spin_complete',job_phase=done['phase'])
            for sample in self.samples:
                r,c=sample['rack_slot']-1,sample['rotor_slot']-1
                if self.rotor[c]!=sample['id'] or self.rack[r] is not None or self.gripper is not None:raise ValueError('Return inventory mismatch')
                self.command('index',slot=c+1);self.check_station(c+1);self.command('open_lid');self.command('present_tube')
                take=self.observe('take_rotor',sample,('grasp_confirmed','source_empty'));self.sim.robot_clear=False
                self.command('confirm_removed',grasp_confirmed=take['grasp_confirmed'],tube_absent=take['source_empty'])
                self.check_station(c+1)
                self.rotor[c]=None;self.gripper=sample['id']
                self.record('rotor_to_gripper',sample_id=sample['id'],rack_slot=r+1,rotor_slot=c+1)
                self.clear(sample);self.command('retract_lift');self.command('close_lid')
                self.observe('place_rack',sample,('seated_confirmed','released_confirmed'))
                if self.rack[r] is not None:raise ValueError('Original rack slot is occupied')
                self.rack[r]=self.gripper;self.gripper=None
                self.record('gripper_to_original_rack_slot',sample_id=sample['id'],rack_slot=r+1,rotor_slot=c+1)
            if self.rack!=self.initial or any(self.rotor) or self.gripper is not None:raise ValueError('Original sample order not restored')
            if any(s['present'] for s in self.sim.slots.values()):raise ValueError('Station sensor inventory disagrees with ledger')
            self.command('release');self.record('complete')
            return self.report(True)
        except Exception as error:
            # Preserve the failure report even if the stop or status channel fails.
            try:self.command('stop')
            except Exception as stop_error:self.stop_error=str(stop_error)
            try:self.record('failed',reason=str(error))
            except Exception:
                self.trace.append({'sequence':len(self.trace)+1,'time_s':self.now,'stage':'failed','reason':str(error),'inventory':self.snapshot(),'station':None})
            raise BatchError(str(error),self.report(False,str(error))) from error
