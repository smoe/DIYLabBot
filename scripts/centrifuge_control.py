"""CF01 deterministic MOCK control API. No hardware IO or network server exists."""
import argparse
import copy
import json
import math
import sys
import time
import uuid
import centrifuge_model as model
from centrifuge_protocol import command_arguments

COMMAND_ARGUMENTS = command_arguments()


def request_schema():
    variants=[]
    for command,arguments in COMMAND_ARGUMENTS.items():
        props={'command':{'const':command},**{k:{'type':v} for k,v in arguments.items()}}
        required=['command',*arguments]
        if command not in ('status','rotation_feedback','events','stop','acquire'):
            props['token']={'type':'string','minLength':1}; required.append('token')
        if 'slot' in props: props['slot'].update(minimum=1,maximum=12)
        for key in ('rcf_x_g','duration_s','mass_g'):
            if key in props: props[key]['exclusiveMinimum']=0
        if 'rcf_x_g' in props: props['rcf_x_g']['maximum']=16000
        variants.append({'type':'object','properties':props,'required':required,'additionalProperties':False})
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','title':'CF01 local JSONL mock request v1',
            'description':'Simulation only. No network, SiLA or hardware transport is implemented. See docs/centrifuge-cf01.md.', 'oneOf':variants}


class ControlError(ValueError):
    def __init__(self,code,message): super().__init__(message); self.code=code


def require(condition,code,message):
    if not condition: raise ControlError(code,message)


def positive(value,name):
    require(type(value) in (int,float) and math.isfinite(value) and value>0,'InvalidArgument',name+' must be finite and positive')
    return value


class Simulator:
    """All measurements are synthetic. Qualification is absent by default.

    Tests may inject synthetic ratings; these NEVER qualify a real assembly.
    Sensor values and ownership are separate: an owner cannot bypass feedback.
    """
    def __init__(self,spec=None,clock=time.monotonic,qualification=None,auto_feedback=True,initial_slots=None):
        self.spec=spec or model.load(); self.p=model.parameters(self.spec); self.clock=clock
        self.boot_id=str(uuid.uuid4()); self.owner=None; self.deadline=0; self.fault=None
        self.lid='closed'; self.locked=True; self.rpm=0; self.zero_speed=True; self.brake=True
        self.robot_clear=True; self.indexed_slot=None; self.encoder_deg=0; self.index_ok=False; self.lift_mm=0
        self.slots={i:{'present':True,'seated':True,'mass_g':None} for i in range(1,13)}
        if initial_slots is not None:self.slots=copy.deepcopy(initial_slots)
        self.run=None; self.qualification=copy.deepcopy(qualification); self.auto_feedback=auto_feedback
        self.feedback_time=self.clock(); self.encoder_feedback_time=self.clock(); self.encoder_healthy=True; self.encoder_homed=False; self.events=[]
        self.stopping=None; self.parking_brake_healthy=True; self.brake_release_confirmed=True; self.brake_engage_confirmed=True
        self.lid_drive_healthy=True; self.lid_brake_healthy=True; self.lid_holding_brake=True; self.obstruction=False
        self.pins_retracted_confirmed=True; self.pins_locked_confirmed=True
        self.lid_angle_deg=0; self.lid_open_switch=False; self.lid_closed_switch=True; self.latch_positions=[0,0]

    def event(self,kind,**values): self.events.append({'id':len(self.events)+1,'time_s':self.clock(),'kind':kind,**values})

    def _sync(self):
        now=self.clock()
        if self.auto_feedback: self.feedback_time=now; self.encoder_feedback_time=now
        if self.owner and now>self.deadline and self.fault is None: self._trip('OwnerTimeout')
        if self.clock()-self.feedback_time>self.spec['handling']['sensor_max_age_s'] and self.rpm!=0: self._trip('StaleFeedback')
        if (not self.encoder_healthy or now-self.encoder_feedback_time>self.spec['handling']['sensor_max_age_s']) and self.rpm!=0:
            self._trip('RotationSensorFault')
        if self.run and self.run['phase']=='running' and now>=self.run['ends_s']:
            self._begin_braking('completed',self.run['ends_s'])
        if self.stopping:
            progress=max(0,min(1,(now-self.stopping['started_s'])/self.spec['mechanisms']['braking']['simulation_stop_s']))
            self.rpm=self.stopping['initial_rpm']*(1-progress)
            if progress>=1:
                terminal=self.stopping['terminal'];self.stopping=None;self.rpm=0;self.zero_speed=True
                if self.parking_brake_healthy and self.brake_engage_confirmed:
                    self.brake=True;self.event('CF01.brake.held')
                else:
                    self.brake=False;self.fault='ParkingBrakeFault';terminal='faulted'
                if self.run:self.run['phase']=terminal;self.event('CF01.run.'+terminal,run_id=self.run['id'])

    def _begin_braking(self,terminal,started=None):
        if self.stopping:
            if terminal=='faulted':self.stopping['terminal']='faulted'
            return
        if self.rpm==0:return
        self.stopping={'initial_rpm':self.rpm,'started_s':self.clock() if started is None else started,'terminal':terminal}
        self.zero_speed=False;self.brake=False
        if self.run:self.run['phase']='braking'
        self.event('CF01.braking',method='synthetic drive deceleration; parking pads released',terminal=terminal)

    def _trip(self,reason):
        if self.fault is not None:return
        self.fault=reason
        # The model requests a stop. A physical driver must observe independent
        # standstill; neither a stop request nor an encoder fault proves it.
        self._begin_braking('faulted')
        self.event('CF01.fault',reason=reason)

    def _fresh(self):
        require(0<=self.clock()-self.feedback_time<=self.spec['handling']['sensor_max_age_s'],'StaleFeedback','Fresh independent feedback required')
        require(self.encoder_healthy,'RotationSensorFault','Healthy spindle encoder feedback required')
        require(0<=self.clock()-self.encoder_feedback_time<=self.spec['handling']['sensor_max_age_s'],'StaleRotationFeedback','Fresh spindle encoder feedback required')
    def _still(self):
        self._fresh(); require(self.parking_brake_healthy,'ParkingBrakeFault','Healthy parking brake required')
        require(self.rpm==0 and self.zero_speed and self.brake,'NotStationary','Standstill and holding brake feedback required')
    def _clear(self): require(self.robot_clear,'WorkspaceOccupied','Robot must be clear')
    def _parked(self): require(self.lift_mm==0 and all(s['seated'] or not s['present'] for s in self.slots.values()),'TubeRaised','Ejector parked and tubes seated required')
    def _closed(self): require(self.lid=='closed' and self.locked and self.lid_closed_switch and self.pins_locked_confirmed and self.latch_positions==[0,0],'LidUnlocked','Closed limit and both locked pins required')
    def _access(self):
        self._still(); require(self.lid=='open','LidNotOpen','Fully open lid required')
        require(self.lid_open_switch and self.lid_holding_brake and self.lid_brake_healthy,'LidAccessFault','Open limit and held lid required')
        require(self.indexed_slot is not None,'NotIndexed','Index a numbered pocket first')
        require(self.index_ok and abs(self.encoder_deg+(self.indexed_slot-1)*30)<=self.spec['handling']['index_tolerance_deg'],'IndexMismatch','Encoder must confirm selected pocket at pickup')
    def _owner(self,token): require(self.owner is not None and token==self.owner['token'],'InvalidToken','Valid token scoped to current boot required')

    def _release_brake(self):
        require(self.parking_brake_healthy and self.brake_release_confirmed,'BrakeReleaseUnconfirmed','Confirm parking caliper released before drive enable')
        self.brake=False;self.event('CF01.brake.release')

    def _powered_lid(self,opened):
        require(self.lid_drive_healthy and self.lid_brake_healthy,'LidDriveFault','Healthy lid drive and holding brake required')
        require(not self.obstruction,'LidObstructed','Workspace/obstruction feedback prevents lid motion')
        if opened:
            require(self.pins_retracted_confirmed,'LatchReleaseUnconfirmed','Both locking pins must retract before lid drive enable')
            self.latch_positions=[self.p['latch_travel']]*2;self.locked=False;self.event('CF01.lid.pins_retracted')
        self.lid_holding_brake=False;self.event('CF01.lid.holding_brake_release')
        self.event('CF01.lid.motor_move',target_deg=105 if opened else 0)
        self.lid_angle_deg=105 if opened else 0;self.lid='open' if opened else 'closed'
        self.lid_open_switch=opened;self.lid_closed_switch=not opened
        self.lid_holding_brake=True;self.event('CF01.lid.open_limit' if opened else 'CF01.lid.closed_limit')
        self.event('CF01.lid.holding_brake_engaged')
        if not opened:
            require(self.pins_locked_confirmed,'LatchLockUnconfirmed','Confirm both pins engaged after powered closure')
            self.latch_positions=[0,0];self.locked=True;self.event('CF01.lid.pins_locked')

    def status(self):
        bottom,axis=model.pocket(self.spec,self.p,1)
        grip=model.plus(bottom,axis,self.p['tube_length']-8+self.lift_mm)
        item=self.slots.get(self.indexed_slot,{})
        grip_valid=(self.lid=='open' and self.indexed_slot is not None and self.index_ok
                    and abs(self.encoder_deg+(self.indexed_slot-1)*30)<=self.spec['handling']['index_tolerance_deg']
                    and self.lift_mm>0 and item.get('present') is True and item.get('seated') is False
                    and self.rpm==0 and self.zero_speed and self.brake and self.fault is None
                    and 0<=self.clock()-self.feedback_time<=self.spec['handling']['sensor_max_age_s']
                    and self.encoder_healthy and 0<=self.clock()-self.encoder_feedback_time<=self.spec['handling']['sensor_max_age_s']
                    and self.lid_open_switch and self.lid_holding_brake and self.lid_brake_healthy)
        e=self.spec['services']['rotation']; age=self.clock()-self.encoder_feedback_time
        healthy=self.encoder_healthy and 0<=age<=self.spec['handling']['sensor_max_age_s']
        rotation={'id':e['id'],'source':'synthetic','healthy':healthy,'age_s':age,'speed_rpm':self.rpm if healthy else None,
                  'angle_deg':self.encoder_deg if healthy and self.index_ok else None,'z_homed':self.encoder_homed,
                  'counts_per_revolution':e['counts_per_revolution'],
                  'quadrature_count':round(self.encoder_deg*e['counts_per_revolution']/360) if healthy and self.index_ok else None,
                  'independent_standstill_monitor_implemented':False}
        return {'mode':'SIMULATION_ONLY','boot_id':self.boot_id,'fault':self.fault,'lid':self.lid,'lid_locked':self.locked,
                'speed_rpm':self.rpm,'standstill_confirmed':self.zero_speed,'brake_held':self.brake,'robot_clear':self.robot_clear,
                'feedback_age_s':self.clock()-self.feedback_time,'indexed_slot':self.indexed_slot,'encoder_deg':self.encoder_deg,'index_confirmed':self.index_ok,'lift_mm':self.lift_mm,
                'slots':copy.deepcopy(self.slots),'run':copy.deepcopy(self.run),'event_sequence':len(self.events),'rotation_sensor':rotation,
                'grip_frame':{'id':'CF01.pickup','parent':'CF01.station','position_mm':grip,'tube_axis':axis,'valid':grip_valid},
                'mechanisms':{'spindle_motor_id':'CF01.MOTOR','motor_enabled':self.rpm!=0,'electrical_braking':self.stopping is not None,
                    'parking_brake_held':self.brake,'parking_brake_healthy':self.parking_brake_healthy,
                    'lid_drive_id':'CF01.LID_DRIVE','lid_angle_deg':self.lid_angle_deg,'lid_open_limit':self.lid_open_switch,
                    'lid_closed_limit':self.lid_closed_switch,'lid_holding_brake_held':self.lid_holding_brake,
                    'locking_pin_retraction_mm':self.latch_positions[:],'manual_lid_step_required':False},
                'hardware_qualified':False}

    def execute(self,command,token=None,**args):
        self._sync()
        require(command in COMMAND_ARGUMENTS,'UnknownCommand','Unknown command: '+str(command))
        require(not (set(args)-set(COMMAND_ARGUMENTS[command])),'InvalidArgument','Unexpected command arguments')
        if command=='status': return self.status()
        if command=='rotation_feedback': return self.status()['rotation_sensor']
        if command=='events': return copy.deepcopy(self.events)
        if command=='stop':
            self._begin_braking('aborted')
            self.event('CF01.stop'); return self.status()
        if command=='acquire':
            require(self.owner is None,'OwnershipConflict','Station already reserved')
            client=args.get('client_id'); require(isinstance(client,str) and bool(client.strip()),'InvalidArgument','client_id required')
            self.owner={'client_id':client,'token':str(uuid.uuid4())}; self.deadline=self.clock()+self.spec['handling']['owner_timeout_s']
            self.event('CF01.reserve',client_id=client); return {'token':self.owner['token'],'boot_id':self.boot_id,'heartbeat_within_s':self.spec['handling']['owner_timeout_s']}
        self._owner(token)
        if command=='heartbeat':
            self.deadline=self.clock()+self.spec['handling']['owner_timeout_s']; return {'fault':self.fault,'expires_in_s':self.spec['handling']['owner_timeout_s']}
        if command=='reset_fault':
            self._still(); self._clear(); self._parked()
            self.fault=None; self.deadline=self.clock()+self.spec['handling']['owner_timeout_s']; self.event('CF01.recovery'); return self.status()
        require(self.fault is None or command in ('lower_tube','retract_lift'),'RecoveryRequired','Latched fault requires explicit recovery')
        self._fresh()
        if command=='release':
            self._still(); self._clear(); self._parked(); self.owner=None; self.event('CF01.release')
        elif command=='open_lid':
            self._still(); self._clear(); self._powered_lid(True);self.event('CF01.access')
        elif command=='close_lid':
            self._still(); self._clear(); self._parked(); self._powered_lid(False);self.event('CF01.close')
        elif command=='index':
            self._still(); self._clear(); self._parked(); self._closed()
            slot=args.get('slot'); require(type(slot) is int and 1<=slot<=12,'InvalidArgument','slot must be 1..12')
            self._release_brake()
            # Motor trajectory and encoder settling are idealized, not a real move.
            self.indexed_slot=slot; self.encoder_deg=-(slot-1)*30; self.index_ok=True; self.encoder_homed=True
            self.event('CF01.index',slot=slot,peak_speed_rpm=self.spec['handling']['index_limit_rpm'],rotor_angle_deg=self.encoder_deg)
            require(self.parking_brake_healthy and self.brake_engage_confirmed,'ParkingBrakeFault','Confirm parking caliper holds indexed rotor')
            self.brake=True;self.event('CF01.brake.held')
        elif command=='present_tube':
            self._access(); self._clear(); self._parked(); item=self.slots[self.indexed_slot]
            require(item['present'],'EmptySlot','No tube in selected slot')
            self.lift_mm=self.p['lift_travel']; item['seated']=False; self.event('CF01.present',slot=self.indexed_slot)
        elif command=='confirm_removed':
            self._access(); item=self.slots[self.indexed_slot]
            require(self.lift_mm>0 and item['present'],'InvalidState','Present a tube first')
            require(args.get('grasp_confirmed') is True and args.get('tube_absent') is True,'UnconfirmedTransfer','Both grasp and tube absence feedback required')
            item.update(present=False,seated=False,mass_g=None); self.event('CF01.take',slot=self.indexed_slot)
        elif command=='confirm_seated':
            self._access(); item=self.slots[self.indexed_slot]
            require(self.lift_mm==0,'TubeRaised','Park lift before loading a tube')
            require(args.get('seated_confirmed') is True and args.get('cap_closed_confirmed') is True,'UnconfirmedTransfer','Seat and closed-cap feedback required')
            mass=positive(args.get('mass_g'),'measured total tube mass_g')
            item.update(present=True,seated=True,mass_g=mass); self.event('CF01.load',slot=self.indexed_slot)
        elif command=='retract_lift':
            self._access(); self._clear(); item=self.slots[self.indexed_slot]
            require(not item['present'] or item['seated'],'UnconfirmedTransfer','Confirm removed tube before retracting')
            self.lift_mm=0; self.event('CF01.park')
        elif command=='lower_tube':
            self._access(); self._clear(); item=self.slots[self.indexed_slot]
            require(self.lift_mm>0 and item['present'],'InvalidState','Raised tube required')
            require(args.get('seated_confirmed') is True,'UnconfirmedTransfer','Mock completion requires positive seat feedback')
            self.lift_mm=0; item['seated']=True; self.event('CF01.lower',slot=self.indexed_slot)
        elif command=='start':
            self._still(); self._clear(); self._parked(); self._closed()
            rcf=positive(args.get('rcf_x_g'),'rcf_x_g'); duration=positive(args.get('duration_s'),'duration_s')
            require(rcf<=self.spec['rotor']['target_rcf_x_g'],'LimitExceeded','Concept target is at most 16000 x g')
            q=self.qualification
            require(isinstance(q,dict) and q.get('simulation_fixture') is True,'UnqualifiedAssembly','No qualified rotor/tube/drive/containment profile; hardware spin unavailable')
            required=['rotor_rpm','drive_rpm','assembly_rcf_x_g','tube_rcf_x_g','tube_mass_limit_g','pair_tolerance_g']
            for key in required: positive(q.get(key),key)
            rpm=model.rpm_for_rcf(rcf,self.p['bottom_radius'])
            require(rpm<=min(q['rotor_rpm'],q['drive_rpm']) and rcf<=min(q['assembly_rcf_x_g'],q['tube_rcf_x_g']),'LimitExceeded','Synthetic qualification limits exceeded')
            require(any(s['present'] for s in self.slots.values()),'InvalidLoad','Empty rotor')
            for slot in range(1,7):
                a,b=self.slots[slot],self.slots[slot+6]
                require(a['present']==b['present'],'UnbalancedLoad','Opposite occupied pockets required')
                if not a['present']: continue
                ma=positive(a['mass_g'],'mass_g slot '+str(slot)); mb=positive(b['mass_g'],'mass_g slot '+str(slot+6))
                require(max(ma,mb)<=q['tube_mass_limit_g'] and abs(ma-mb)<=q['pair_tolerance_g'],'UnbalancedLoad','Pair mass mismatch or excessive mass')
            self._release_brake();self.rpm=rpm; self.zero_speed=False; self.indexed_slot=None; self.index_ok=False
            self.run={'id':str(uuid.uuid4()),'phase':'running','rcf_x_g':rcf,'target_rpm':rpm,'duration_s':duration,'ends_s':self.clock()+duration}
            self.event('CF01.spin',run_id=self.run['id'])
        else: raise ControlError('UnknownCommand','Unknown command: '+str(command))
        return self.status()


def demo():
    # Explicitly fictitious test limits, never copied into the hardware source.
    now=[0.];sim=Simulator(clock=lambda:now[0],qualification={'simulation_fixture':True,'rotor_rpm':15000,'drive_rpm':15000,'assembly_rcf_x_g':16000,'tube_rcf_x_g':16000,'tube_mass_limit_g':3.0,'pair_tolerance_g':0.01})
    token=sim.execute('acquire',client_id='robot-demo')['token']; trace=[]
    for slot in range(1,13):
        for command,args in [('close_lid',{}),('index',{'slot':slot}),('open_lid',{}),('confirm_seated',{'mass_g':2.0,'seated_confirmed':True,'cap_closed_confirmed':True})]:
            sim.execute(command,token,**args)
    sim.execute('close_lid',token); run=sim.execute('start',token,rcf_x_g=16000,duration_s=30)
    trace.append({'step':'mock spin start','run':run['run']}); sim.execute('stop')
    now[0]+=sim.spec['mechanisms']['braking']['simulation_stop_s']+0.1;sim.execute('status')
    for command,args in [('index',{'slot':3}),('open_lid',{}),('present_tube',{}),('confirm_removed',{'grasp_confirmed':True,'tube_absent':True}),('retract_lift',{})]:
        state=sim.execute(command,token,**args); trace.append({'step':command,'slot':state['indexed_slot'],'lift_mm':state['lift_mm']})
    return {'mode':'SIMULATION_ONLY','qualification':'fictitious test fixture; no hardware capability established','trace':trace,'events':sim.events}


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--demo',action='store_true'); args=parser.parse_args()
    if args.demo: print(json.dumps(demo(),indent=2)); return
    sim=Simulator()
    for line in sys.stdin:
        try:
            request=json.loads(line); command=request.pop('command'); response={'ok':True,'result':sim.execute(command,**request)}
        except ControlError as error: response={'ok':False,'error':{'code':error.code,'message':str(error)}}
        except (ValueError,KeyError,TypeError) as error: response={'ok':False,'error':{'code':'InvalidRequest','message':str(error)}}
        print(json.dumps(response),flush=True)


if __name__=='__main__': main()
