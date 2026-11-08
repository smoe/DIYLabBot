"""CF01 shared command contract, kinematic timeline and transport-neutral mock jobs.

No ROS, gRPC, SiLA server or hardware I/O is imported here.
"""
import copy
import json
import math
import uuid
import centrifuge_model as model

SOURCE=model.ROOT/'model/centrifuge-cf01.protocol.json'
PUBLIC={'status','rotation_feedback','events','stop','acquire'}


def load(path=SOURCE):
    data=json.loads(path.read_text(encoding='utf-8'))
    if data['format']!='solidcraftbot.centrifuge-protocol/1': raise ValueError('CF01 protocol contract required')
    frames=data['animation']['keyframes']; times=[f['time_s'] for f in frames]
    if times[0]!=0 or any(b<=a for a,b in zip(times,times[1:])) or times[-1]!=data['animation']['duration_s']:
        raise ValueError('Strictly increasing timeline from zero through duration required')
    if len({c['id'] for c in data['commands']})!=len(data['commands']): raise ValueError('Duplicate command')
    return data


def command_arguments(): return {c['id']:c['arguments'] for c in load()['commands']}


def frames(spec,p,protocol=None):
    result=[]
    for key in (protocol or load())['animation']['keyframes']:
        values={**model.pose(spec,p,key['pose']),**{k:model.evaluate(v,p) for k,v in key.get('coordinates',{}).items()}}
        model.validate_pose(model.expanded(spec,p),values)
        result.append({**key,'values':values})
    return result


def at_time(keys,time_s):
    if type(time_s) not in (int,float) or not math.isfinite(time_s): raise ValueError('Finite timeline time required')
    t=max(keys[0]['time_s'],min(keys[-1]['time_s'],time_s))
    for a,b in zip(keys,keys[1:]):
        if t<=b['time_s']:
            u=(t-a['time_s'])/(b['time_s']-a['time_s'])
            return {'time_s':t,'phase':b['phase'],'values':{k:a['values'][k]+(b['values'][k]-a['values'][k])*u for k in a['values']}}
    return {'time_s':t,'phase':keys[-1]['phase'],'values':copy.deepcopy(keys[-1]['values'])}


def motion_commands(spec,p,protocol=None):
    data=protocol or load(); keys=frames(spec,p,data); steps=round(data['animation']['duration_s']*10)
    return [{'command':'motion.study','params':{'name':'CF01RobotAccess','steps':steps,
             'keys':[{'joint':name,'points':[[round(f['time_s']*10),f['values'][name]] for f in keys]} for name in keys[0]['values']]}},
            {'command':'browser.visibility','params':{'folder':'sketches','visible':False}}]


def state_si(status):
    """One mapping for ROS and SiLA: SI numbers + validity, no sentinel NaNs."""
    r=status['rotation_sensor']; g=status['grip_frame']; m=status['mechanisms']
    return {'boot_id':status['boot_id'],'sequence':status['event_sequence'],'simulation_only':True,
        'hardware_qualified':False,'fault_code':status['fault'] or '',
        'lid_open':status['lid']=='open','lid_closed':status['lid']=='closed','lid_locked':status['lid_locked'],
        'lid_angle_rad':math.radians(m['lid_angle_deg']),
        'standstill_confirmed':status['standstill_confirmed'],'parking_brake_held':status['brake_held'],
        'robot_clear':status['robot_clear'],'feedback_age_s':status['feedback_age_s'],
        'encoder_healthy':r['healthy'],'encoder_age_s':r['age_s'],
        'speed_rad_s':0. if r['speed_rpm'] is None else r['speed_rpm']*2*math.pi/60,
        'speed_valid':r['healthy'] and r['speed_rpm'] is not None,
        'rotor_angle_rad':0. if r['angle_deg'] is None else math.radians(r['angle_deg']),
        'rotor_angle_valid':r['healthy'] and r['angle_deg'] is not None,
        'indexed_slot':status['indexed_slot'] or 0,'index_confirmed':status['index_confirmed'],
        'lift_m':status['lift_mm']/1000,'pickup_position_m':[v/1000 for v in g['position_mm']],
        'pickup_axis':g['tube_axis'][:],'pickup_frame_id':'cf01_station','pickup_valid':g['valid'],
        'lid_open_limit':m['lid_open_limit'],'lid_closed_limit':m['lid_closed_limit'],
        'lid_holding_brake_held':m['lid_holding_brake_held'],
        'locking_pin_retraction_m':[v/1000 for v in m['locking_pin_retraction_mm']]}


def wire(transport,key):
    if transport not in ('ros2','sila2'):raise ValueError('ros2 or sila2 transport required')
    return key if transport=='ros2' else ''.join(v[:1].upper()+v[1:] for v in key.split('_'))


class MockProtocol:
    """Executable adapter logic for future ROS actions / SiLA observable commands.

    Requests and polls stay local. The caller must keep sending heartbeats.
    Instant mock lid moves have no fabricated percentage or physical timing.
    """
    def __init__(self,simulator):
        self.sim=simulator; self.contract=load(); self.commands={c['id']:c for c in self.contract['commands']}
        self.jobs={}; self.active=None

    def dispatch(self,transport,name,parameters):
        """SDK-independent decoding of typed ROS goals/services or SiLA parameters."""
        from centrifuge_control import ControlError
        if transport not in ('ros2','sila2'):raise ValueError('ros2 or sila2 transport required')
        c=next((c for c in self.commands.values() if (c['id'] if transport=='ros2' else c['name'])==name),None)
        if c is None or c.get('local_only'):raise ControlError('UnknownCommand','Command is not in the transport contract')
        expected={wire(transport,k) for k in c['arguments']}
        if c['id'] not in PUBLIC:expected.add(wire(transport,'control_token'))
        if set(parameters)!=expected:raise ControlError('InvalidArgument','Exactly the declared typed fields are required')
        args={k:parameters[wire(transport,k)] for k in c['arguments']};token=parameters.get(wire(transport,'control_token'))
        if c['observable']:return self.begin(c['id'],token,**args)
        result=self.invoke(c['id'],token,**args)
        response={'success':True,'error_code':'','message':'','state':state_si(self.sim.execute('status'))}
        if c['id']=='acquire':response.update(control_token=result['token'],heartbeat_within_s=result['heartbeat_within_s'])
        return response

    def invoke(self,command,token=None,**arguments):
        from centrifuge_control import ControlError
        if self.active and self.jobs[self.active]['phase'] not in ('succeeded','canceled','failed') and command not in ('status','rotation_feedback','events','heartbeat','stop'):
            raise ControlError('Busy','One observable command at a time; poll or cancel the active execution')
        return self.sim.execute(command,token,**arguments)

    def begin(self,command,token=None,**arguments):
        if command not in self.commands or not self.commands[command]['observable']: raise ValueError('Observable command required')
        self.invoke(command,token,**arguments)
        job={'id':str(uuid.uuid4()),'command':command,'phase':'running','cancel_requested':False,
             'run_id':self.sim.run['id'] if command=='start' else None,'error_code':''}
        self.jobs[job['id']]=job; self.active=job['id']; return self.poll(job['id'])

    def cancel(self,job_id):
        job=self.jobs[job_id]
        if job['phase'] in ('succeeded','canceled','failed'): return self.poll(job_id)
        job['cancel_requested']=True; self.sim.execute('stop'); return self.poll(job_id)

    def poll(self,job_id):
        job=self.jobs[job_id]; status=self.sim.execute('status')
        still=status['standstill_confirmed'] and status['brake_held'] and status['speed_rpm']==0
        if job['phase'] not in ('succeeded','canceled','failed'):
            if status['fault']:
                job['error_code']=status['fault']; job['phase']='failed' if still else 'stopping'
            elif job['cancel_requested']: job['phase']='canceled' if still else 'stopping'
            elif job['command']=='start':
                run=status['run']
                if run and run['id']==job['run_id'] and run['phase']=='completed' and still: job['phase']='succeeded'
                elif run and run['phase']=='aborted' and still: job.update(phase='canceled')
                elif run and run['phase']=='braking': job['phase']='braking'
            else: job['phase']='succeeded'  # Core mock methods return only after their synthetic confirmation.
        if job['phase'] in ('succeeded','canceled','failed') and self.active==job_id: self.active=None
        return {**job,'progress':-1.,'state':state_si(status)}
