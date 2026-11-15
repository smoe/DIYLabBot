"""Source-composed H02 -> existing rack; C2 paths, bounded PVA and native scopes."""
import copy
import functools
import json
import math
from pathlib import Path
import h02_arm_pickup as base
from cf01_unload_path import CornerPath

ROOT=base.ROOT;SOURCE=ROOT/'model/h02-rack-transfer.scene.json';SCHEMA=ROOT/'model/h02-rack-transfer.schema.json'
I=base.I;J=base.J;motion=base.motion


def hull(values):return I(min(base.interval(v).lo for v in values),max(base.interval(v).hi for v in values))


def union(jets):return J(*(hull([v.d[n] for v in jets]) for n in range(4)))


def curve_jets(curve,a,b):
    pieces=[]
    for i,segment in enumerate(curve.segments):
        left=max(a,curve.times[i]);right=min(b,curve.times[i+1])
        if right<left:continue
        h=curve.times[i+1]-curve.times[i]
        pieces.append(J(*(base.sm._polynomial_interval(motion.derivative(segment[0],n),(left-curve.times[i])/h,(right-curve.times[i])/h,h**n) for n in range(4))))
    if not pieces:raise ValueError('Curve interval is outside its episode')
    return union(pieces)


class Route:
    def __init__(self,start,end,height,trim):
        mid=[0,end[1]/2,height]
        corners=[CornerPath(start,[0,0,height],mid,0,0,trim),CornerPath(mid,[0,end[1],height],end,0,0,trim)]
        self.pieces=[];offset=0.
        for c in corners:
            lengths=[c.first_length,7*trim/3,c.last_length]
            controls=[[c.start,c.controls[0]],c.controls,[c.controls[-1],c.end]]
            for length,points in zip(lengths,controls):
                self.pieces.append((offset,offset+length,points));offset+=length
        self.length=offset

    @staticmethod
    def bernstein(points,u):
        def split(values,t):
            levels=[values]
            while len(levels[-1])>1:levels.append([a+t*(b-a) for a,b in zip(levels[-1],levels[-1][1:])])
            return [v[0] for v in levels],[v[-1] for v in reversed(levels)]
        if not isinstance(u,I):return split(points,u)[0][-1]
        lo=max(0.,u.lo);hi=min(1.,u.hi)
        if lo==1:return I(points[-1])
        _,right=split(points,lo);left,_=split(right,(hi-lo)/(1-lo))
        return I(math.nextafter(min(left),-math.inf),math.nextafter(max(left),math.inf))

    def evaluate(self,s):
        s=J.lift(s);position=base.interval(s.d[0]);values=[[],[]]
        for left,right,controls in self.pieces:
            lo=max(left,position.lo);hi=min(right,position.hi)
            if hi<lo:continue
            u=I((lo-left)/(right-left),(hi-left)/(right-left)) if isinstance(s.d[0],I) else (min(right,max(left,s.d[0]))-left)/(right-left)
            for k in range(2):
                points=[p[k+1] for p in controls];f=[]
                for order in range(4):
                    f.append(self.bernstein(points,u)/(right-left)**order if not isinstance(u,I) else self.bernstein(points,u)*(1/(right-left)**order))
                    points=[(len(points)-1)*(b-a) for a,b in zip(points,points[1:])] if len(points)>1 else [0.]
                _,v,a,j=s.d
                values[k].append(J(f[0],f[1]*v,f[1]*a+f[2]*v*v,f[1]*j+3*f[2]*v*a+f[3]*v*v*v))
            if not isinstance(s.d[0],I):break
        if not all(values):raise ValueError('Progress outside spatial route')
        return [union(v) if isinstance(s.d[0],I) else v[0] for v in values]


class Program(base.Program):
    source_path=SOURCE;schema_path=SCHEMA;program_kind='h02-rack-transfer'
    def __init__(self,definition=None):
        super().__init__();self.transfer=copy.deepcopy(definition) if definition else json.loads(SOURCE.read_text())
        d=self.transfer
        if set(d)!=set(json.loads(SCHEMA.read_text())['properties']) or d['format']!='solidcraftbot.h02-rack-transfer/1':raise ValueError('Typed rack-transfer composition required')
        if d['units']!=self.definition['units'] or d['empty_limits']!='arm_empty':raise ValueError('Explicit units and mechanical empty limits required')
        caps=d['sample_caps']
        if any(not isinstance(caps[k],(int,float)) or not math.isfinite(caps[k]) or caps[k]<=0 for k in ['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3']):raise ValueError('Finite positive sample caps required')
        if not 0<=d['route']['release_yaw_deg']<=90:raise ValueError('Unsupported release yaw')
        if len(d['rack_instance']['position_mm'])!=3 or any(not math.isfinite(x) for x in d['rack_instance']['position_mm']):raise ValueError('Finite rack placement required')
        if d['route']['clock']!='shared_s_curve_joint_scaled' or not 0<=d['route']['time_weight']<=8:raise ValueError('Unsupported clock metric')
        for ref in d['sources'].values():base.assembly.validate_reference(ref)
        if base.assembly.validate_reference(d['sources']['pickup'])!=base.SOURCE:raise ValueError('Existing H02 arm source required')
        if d['events']!={'grasp_confirmation':'test_fixture','rack_support_confirmation':'test_fixture'}:raise ValueError('Explicit synthetic grasp/support observations required')
        self.rack_definition=json.loads(base.assembly.validate_reference(d['sources']['rack']).read_text());r=d['rack_instance']
        if r['yaw_deg']!=0 or r['position_mm'][2]!=0:raise ValueError('This planar fixture requires a level unrotated rack')
        if r['selected_slot'] in r['occupied_slots'] or len(set(r['occupied_slots']))!=len(r['occupied_slots']):raise ValueError('Destination must be empty and occupancy unique')
        rack={**self.rack_definition,**r};scene={'rack':rack,'transport_requirement':{'position_target_mm':1}}
        self.rack=base.pickup.rack_geometry(scene,{'tube_radius':self.spec['hp']['tube_radius'],'tube_length':self.spec['hp']['collar_z']+2-self.spec['hp']['tube_bottom_z']})
        if any(type(i)is not int or not 1<=i<=self.rack['capacity'] for i in r['occupied_slots']):raise ValueError('Invalid occupied rack slot')
        if type(r['selected_slot']) is not int or not 1<=r['selected_slot']<=self.rack['capacity']:raise ValueError('Invalid selected rack slot')
        slot=self.rack['slots'][r['selected_slot']-1];bottom=base.robot.transform(self.rack['frame'],slot['tube_bottom_mm'])
        self.seat=[bottom[0],bottom[1],bottom[2]+self.z0-self.spec['hp']['tube_bottom_z']]
        if abs(self.seat[0])>1e-9 or self.seat[1]>=0:raise ValueError('Selected rack slot must lie on this arm plane behind H02')
        self.route=Route([0,0,self.z0],self.seat,d['route']['clearance_z_mm'],d['route']['corner_trim_mm'])
        self.loaded_caps=self.local_scene['motion_limits'] if d['loaded_limits']=='h02_local' else self.limits['sample_translation'] if d['loaded_limits']=='shared_sample_transport' else {k:d['sample_caps'][k] for k in ['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3']} if d['loaded_limits']=='explicit_sample_caps' else None
        if self.loaded_caps is None:raise ValueError('Select a supported loaded limit reference')
        shape=next(o['shape'] for o in base.local.expanded(self.spec,self.p)['operations'] if o['body']=='Selected_MouthKeepout')
        self.protected_radius=max(self.spec['hp']['collar_radius'],shape['radius'])
        self.curves={};self.durations={};self.phase_reports={};self.local_certified=False
        for phase,distance in [('approach',-self.travel),('closure',-self.p['jaw_travel']),('extraction',self.route.length),('release',self.p['jaw_travel']),('withdraw',self.travel)]:
            if phase=='extraction':caps=self.loaded_caps
            elif phase in ('closure','release'):caps=self.local_scene['motion_limits']
            else:caps={'velocity_mm_s':1,'acceleration_mm_s2':4,'jerk_mm_s3':40} # Unit clock; retimed to mechanical joint bounds below.
            points=motion.rest_to_rest(distance,caps['velocity_mm_s'],caps['acceleration_mm_s2'],caps['jerk_mm_s3'])
            if phase in ('approach','withdraw'):
                points=motion.rest_to_rest(math.copysign(1,distance),1,4,40)
                for point in points:
                    for field in motion.FIELDS[:3]:point[field]=[v*abs(distance) for v in point[field]]
            if phase=='extraction':points=self._metric_clock()
            self.curves[phase]=motion.Curve(points);self.durations[phase]=points[-1]['time_s']
            factor=self._factor(phase)
            points=motion.scale(points,factor);self.curves[phase]=motion.Curve(points);self.durations[phase]=points[-1]['time_s']
            self.phase_reports[phase]={'loaded':phase=='extraction','duration_s':points[-1]['time_s'],'uniform_scale':factor,'bounds':self._audit_phase(phase)}
        self.total_duration=sum(self.durations.values());self._bounds_cache={}
        self.native_poses=[('approach','approach',0),('grasp','closure',1),('transfer','extraction',.5),('seated','extraction',1),('released','release',1),('clear','withdraw',1)]
        self.coordinate_limits={name:[self.seat[1],0] if name.endswith('Y') else [min(0,self.seat[2]-self.z0),max(self.transfer['route']['clearance_z_mm'],self.z0+self.travel,self.seat[2]+self.travel)-self.z0] for name in ['ToolY','ToolZ','TubeY','TubeZ']}
        self.coordinate_limits.update(ToolYaw=[0,self.transfer['route']['release_yaw_deg']],TubeYaw=[0,self.transfer['route']['release_yaw_deg']])
        self.coordinate_names=['ToolY','ToolZ','TubeY','TubeZ','ToolYaw','TubeYaw','JawLeft','JawRight']

    def _metric_clock(self):
        self.metric_strength=self.transfer['route']['time_weight']
        length=self.route.length*(1+self.metric_strength/2)
        return motion.rest_to_rest(length,self.loaded_caps['velocity_mm_s'],self.loaded_caps['acceleration_mm_s2'],self.loaded_caps['jerk_mm_s3'])

    def progress(self,m):
        length=self.route.length;k=self.metric_strength
        def invert(value):
            lo=0.;hi=length
            for _ in range(48):
                s=(lo+hi)/2;metric=s+k*(s/2-length*math.sin(2*math.pi*s/length)/(4*math.pi))
                if metric<value:lo=s
                else:hi=s
            return (lo+hi)/2
        value=m.d[0];s=I(invert(value.lo),invert(value.hi)) if isinstance(value,I) else invert(value)
        angle=s*(math.pi/length)
        sine=angle.sin() if isinstance(angle,I) else math.sin(angle);cosine=angle.cos() if isinstance(angle,I) else math.cos(angle)
        weight=1+k*sine*sine
        first=base.power(weight,-1);wp=2*k*math.pi/length*sine*cosine
        wpp=2*k*(math.pi/length)**2*(cosine*cosine-sine*sine)
        second=-wp*base.power(weight,-3);third=3*wp*wp*base.power(weight,-5)-wpp*base.power(weight,-4)
        _,v,a,j=m.d
        return J(s,first*v,first*a+second*v*v,first*j+3*second*v*a+third*v*v*v)

    def at_time(self,t):
        t=max(0.,min(self.total_duration,t));start=0.
        if t==self.total_duration:return 'withdraw',1.
        for phase,duration in self.durations.items():
            if t<start+duration or phase=='withdraw':return phase,(t-start)/duration
            start+=duration

    def _position(self,phase,s):
        if phase=='extraction':return self.route.evaluate(self.progress(s))
        if phase=='approach':return [J(0),J(self.z0+self.travel)+s]
        if phase=='withdraw':return [J(self.seat[1]),J(self.seat[2])+s]
        return [J(0 if phase=='closure' else self.seat[1]),J(self.z0 if phase=='closure' else self.seat[2])]

    def yaw(self,phase,scalar):
        if phase in ('approach','closure'):return J(0.)
        if phase in ('release','withdraw'):return J(self.transfer['route']['release_yaw_deg'])
        progress=self.progress(scalar);start=self.route.pieces[1][0];end=self.route.pieces[-1][0];v=progress.d[0]
        if isinstance(v,I):
            if v.hi<=start:return J(I(0.))
            if v.lo>=end:return J(I(self.transfer['route']['release_yaw_deg']))
            u=I(max(0.,(v.lo-start)/(end-start)),min(1.,(v.hi-start)/(end-start)))
        else:
            if v<=start:return J(0.)
            if v>=end:return J(self.transfer['route']['release_yaw_deg'])
            u=(v-start)/(end-start)
        points=[0.,0.,0.,0.,1.,1.,1.,1.];f=[]
        for order in range(4):
            f.append(Route.bernstein(points,u)*(self.transfer['route']['release_yaw_deg']/(end-start)**order))
            points=[(len(points)-1)*(b-a) for a,b in zip(points,points[1:])]
        _,speed,accel,jerk=progress.d
        result=J(f[0],f[1]*speed,f[1]*accel+f[2]*speed*speed,f[1]*jerk+3*f[2]*speed*accel+f[3]*speed*speed*speed)
        if isinstance(v,I) and (v.lo<start or v.hi>end):result=J(result.d[0],*(hull([0,x]) for x in result.d[1:]))
        return result

    def _evaluate(self,phase,scalar):
        y,z=self._position(phase,scalar);q=self.angles(z,y-self.definition['arm_fixture']['position_mm'][1]);yaw=self.yaw(phase,scalar);q[-1]=q[-1]-yaw*(math.pi/180);return q,y,z

    def _bounds(self,phase,a,b):
        key=(phase,a,b)
        if hasattr(self,'_bounds_cache') and key in self._bounds_cache:return self._bounds_cache[key]
        s=curve_jets(self.curves[phase],a*self.durations[phase],b*self.durations[phase]);q,y,z=self._evaluate(phase,s);result=q,y,z,s
        if hasattr(self,'_bounds_cache'):self._bounds_cache[key]=result
        return result

    def ranges(self,phase,a,b):
        q,y,z,s=self._bounds(phase,a,b);return q,s.d[0]

    def _audit_phase(self,phase):
        joints=[0.]*3;linear=[0.]*3;angular=[0.]*3;sample=[0.]*3
        for n in range(256):
            q,y,z,s=self._bounds(phase,n/256,(n+1)/256);yaw=self.yaw(phase,s)
            for order in range(1,4):
                rotation=base.interval(yaw.d[order]);angular[order-1]=max(angular[order-1],abs(rotation.lo),abs(rotation.hi))
                joints[order-1]=max(joints[order-1],*[max(abs(base.interval(v.d[order]).lo),abs(base.interval(v.d[order]).hi)) for v in q])
                linear[order-1]=max(linear[order-1],math.hypot(*[max(abs(base.interval(v.d[order]).lo),abs(base.interval(v.d[order]).hi)) for v in [y,z]]))
            rates=[max(abs(base.interval(yaw.d[k]).lo),abs(base.interval(yaw.d[k]).hi))*math.pi/180 for k in [1,2,3]]
            v,a,j=rates;r=self.protected_radius
            extra=[r*v,r*(a+v*v),r*(j+3*v*a+v**3)]
            for n in range(3):
                translation=math.hypot(*[max(abs(base.interval(x.d[n+1]).lo),abs(base.interval(x.d[n+1]).hi)) for x in [y,z]])
                sample[n]=max(sample[n],translation+extra[n])
            for v,j in zip(q,self.arm['joints']):
                if base.interval(v.d[0]).lo<math.radians(j['limits_deg'][0])-1e-9 or base.interval(v.d[0]).hi>math.radians(j['limits_deg'][1])+1e-9:raise ValueError('Transfer joint position limit exceeded: '+str((phase,j['id'],math.degrees(base.interval(v.d[0]).lo),math.degrees(base.interval(v.d[0]).hi),j['limits_deg'])))
        return {'joint':joints,'translation':linear,'rotation':angular,'sample_translation':sample,'protected_radius_mm':self.protected_radius,'scope':'Conservative interval PVA over the complete exact Cartesian/analytic-IK composition'}

    def _factor(self,phase):
        bounds=self._audit_phase(phase);caps=self.limits['arm_loaded' if phase=='extraction' else 'arm_empty'];names=['velocity_rad_s','acceleration_rad_s2','jerk_rad_s3']
        ratios=[(v/caps[k])**(1/n) for n,(v,k) in enumerate(zip(bounds['joint'],names),1)]
        if phase=='extraction':ratios.extend((v/self.loaded_caps[k])**(1/n) for n,(v,k) in enumerate(zip(bounds['sample_translation'],['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3']),1))
        if phase=='extraction':ratios.extend((v/self.limits['sample_rotation'][k])**(1/n) for n,(v,k) in enumerate(zip(bounds['rotation'],['velocity_deg_s','acceleration_deg_s2','jerk_deg_s3']),1))
        return max(ratios)*1.00001 if phase not in ('closure','release') else 1.

    def state(self,phase,u):
        if phase not in self.curves:raise ValueError('Unknown transfer phase')
        raw=motion.evaluate(self.curves[phase],u*self.durations[phase]);s=J(*(raw[f][0] for f in motion.FIELDS));q,y,z=self._evaluate(phase,s);yaw=self.yaw(phase,s)
        gap=self.p['jaw_travel']+s.d[0] if phase=='closure' else s.d[0] if phase=='release' else 0 if phase=='extraction' else self.p['jaw_travel']
        held=phase=='extraction';seated=phase in ('release','withdraw')
        tube=[self.seat[1],self.seat[2]-self.z0] if seated else [y.d[0],z.d[0]-self.z0] if held else [0.,0.]
        return {'phase':phase,'u':u,'joints_deg':[math.degrees(a.d[0]) for a in q],
            'joint_state':{f:[v.d[n] for v in q] for n,f in enumerate(motion.FIELDS)},'tool_yaw_deg':yaw.d[0],'tool_y_mm':y.d[0],'tool_z_mm':z.d[0],'tool_position_mm':[0,y.d[0],z.d[0]],
            'coordinates':{'ToolY':y.d[0],'ToolZ':z.d[0]-self.z0,'ToolYaw':yaw.d[0],'TubeYaw':yaw.d[0] if held else self.transfer['route']['release_yaw_deg'] if seated else 0,'TubeY':tube[0],'TubeZ':tube[1],'JawLeft':gap,'JawRight':gap},
            'tool_pva':{f:[0,y.d[n],z.d[n]] for n,f in enumerate(base.sm.LINEAR)},
            'tube_owner':'rack' if seated else 'gripper' if held else 'H02','sample_id':'H02.Tube01','rack_place_id':self.rack['slots'][self.transfer['rack_instance']['selected_slot']-1]['id']}

    def audit(self):
        for phase,report in self.phase_reports.items():
            caps=self.limits['arm_loaded' if phase=='extraction' else 'arm_empty']
            if any(v>caps[k]+1e-8 for v,k in zip(report['bounds']['joint'],['velocity_rad_s','acceleration_rad_s2','jerk_rad_s3'])):raise ValueError('Joint PVA cap exceeded')
            if phase=='extraction' and any(v>self.limits['sample_rotation'][k]+1e-7 for v,k in zip(report['bounds']['rotation'],['velocity_deg_s','acceleration_deg_s2','jerk_deg_s3'])):raise ValueError('Loaded rotation cap exceeded')
            if phase=='extraction' and any(v>self.loaded_caps[k]+1e-7 for v,k in zip(report['bounds']['sample_translation'],['velocity_mm_s','acceleration_mm_s2','jerk_mm_s3'])):raise ValueError('Loaded translation cap exceeded')
            for n in range(33):
                s=self.state(phase,n/32);target=base.pickup.tool_target(s['tool_position_mm'],0,-s['tool_yaw_deg'])
                if max(abs(v) for v in self.kin.residual(s['joints_deg'],target))>1e-7:raise ValueError('Analytic transfer IK disagrees with FK')
        return {'passed':True,'phases':self.phase_reports,'duration_s':self.total_duration,'continuous_loaded_transport':True,
            'no_stop_reason':'Positive S-curve clock speed and nonopposing C2 corner tangents; clearance and entry marks do not stop',
            'global_time_optimality_proved':False,'performance_acceptance':self.transfer['performance'],'limits':self.limits,'loaded_scalar_limits':self.loaded_caps}

    def delta(self,phase,a,b,record):
        if record['kind']=='arm':return super().delta(phase,a,b,record)
        if record['kind'] in ('tool','sample'):
            _,y,z,s=self._bounds(phase,a,b);mid=self.state(phase,(a+b)/2)
            if record['kind']=='sample' and phase!='extraction':return 0.
            radius=math.hypot(*[max(abs(base.interval(v.d[0]).lo-mid['tool_position_mm'][i]),abs(base.interval(v.d[0]).hi-mid['tool_position_mm'][i])) for i,v in [(1,y),(2,z)]])
            yaw=self.yaw(phase,s);yr=base.interval(yaw.d[0]);rotation=max(abs(yr.lo-mid['tool_yaw_deg']),abs(yr.hi-mid['tool_yaw_deg']))*math.pi/180
            reach=max(math.hypot(x,y) for x in [record['local_bbox']['min'][0],record['local_bbox']['max'][0]] for y in [record['local_bbox']['min'][1],record['local_bbox']['max'][1]])
            if record['group'] in ('FingerLeft','FingerRight'):reach+=self.p['jaw_travel']
            radius+=reach*min(2,rotation)
            if phase in ('closure','release') and record['group'] in ('FingerLeft','FingerRight'):
                value=base.interval(s.d[0]);center=motion.evaluate(self.curves[phase],(a+b)/2*self.durations[phase])[motion.FIELDS[0]][0]
                radius+=max(abs(value.lo-center),abs(value.hi-center))
            return radius+1e-7
        return 0.

    def extra_parts(self,variant):
        spec=base.local.context(self.local_scene,variant);p=base.local.parameters(spec);source=base.local.expanded(spec,p)
        tube=next(o['shape'] for o in source['operations'] if o['body']=='Selected_ReferenceTube')
        mouth=next(o['shape'] for o in source['operations'] if o['body']=='Selected_MouthKeepout')
        envelope=base.local.filled_tube_shape(spec,tube)
        parts=[]
        def add(name,group,shape,cuts,translation,role,kind,hidden=False):
            parts.append({'id':name,'group':group,'shape':copy.deepcopy(shape),'cuts':copy.deepcopy(cuts),'translation':translation,'role':role,'kind':kind,'hidden':hidden,
                'appearance':{'color':'#61b99a' if group=='Rack' else '#79b7b0','opacity':.15 if hidden else 1}})
        origin=self.transfer['rack_instance']['position_mm']
        for b in self.rack['parts']:add(b['id'].replace('.','_'),'Rack',b['shape'],b['cuts'],origin,b['role'],'fixture')
        for index in self.transfer['rack_instance']['occupied_slots']:
            slot=self.rack['slots'][index-1];bottom=base.robot.transform(self.rack['frame'],slot['tube_bottom_mm']);shift=[bottom[0],bottom[1],bottom[2]-spec['hp']['tube_bottom_z']]
            add('Rack_Slot%02d_ReferenceTube'%index,'Rack',tube,[],shift,'occupied_rack_tube','fixture')
            add('Rack_Slot%02d_MouthKeepout'%index,'Rack',mouth,[],shift,'occupied_rack_mouth_keepout','fixture',True)
        add('CarriedEnvelope','Tube',envelope,[],[0,0,0],'collision_envelope','sample',True)
        return parts

    def collision_pairs(self,records):
        pairs,excluded=base.collision_pairs(self,records);known={tuple(sorted((p['a'],p['b']))) for p in pairs}
        for i,a in enumerate(records):
            for b in records[i+1:]:
                key=tuple(sorted((a['id'],b['id'])))
                if key in known:continue
                if not ({a['kind'],b['kind']} & {'tool','sample'}) or not ({a['kind'],b['kind']} & {'fixture'}):continue
                moving=a if a['kind'] in ('tool','sample') else b;fixed=b if moving is a else a
                required=self.definition['tool_clearance_mm'] if 'tool_clearance_mm' in self.definition else self.local_scene['tool_clearance_mm']
                if moving['kind']=='sample':
                    if fixed['id'] in ('Selected_LowerSeat','Rack_Base'):required=0.
                    elif fixed['id'].startswith('Selected_'):required=.1
                    else:required=1.
                pairs.append({'a':a['id'],'b':b['id'],'category':'environment','required_mm':required});known.add(key)
        return pairs,excluded

    def pair_bound(self,pair,phase,a,b,frame):
        x,y=pair['a'],pair['b'];sample=next((v for v in [x,y] if v in ['Selected_ReferenceTube','Selected_MouthKeepout','CarriedEnvelope']),None)
        fixed=y if sample==x else x
        if sample is None:return None
        q,py,pz,s=self._bounds(phase,a,b)
        if phase!='extraction':
            position=self.state(phase,(a+b)/2)['coordinates'];py=J(I(position['TubeY']));pz=J(I(position['TubeZ']+self.z0))
        yr=base.interval(py.d[0]);zr=base.interval(pz.d[0]);guard=self.definition['continuous_audit']['numeric_guard_mm']
        if fixed=='Rack_Base':
            bottom=zr.lo-self.z0+self.spec['hp']['tube_bottom_z'];top=self.rack_definition['base_thickness_mm']
            if sample=='Selected_MouthKeepout':return None
            return 0. if bottom>=top-guard else bottom-top
        if fixed.startswith('Selected_') and fixed not in ['Selected_ReferenceTube','Selected_MouthKeepout']:
            if abs(yr.lo)<1e-9 and abs(yr.hi)<1e-9 and zr.lo>=self.z0-1e-9 and zr.hi<=self.z0+self.travel+1e-9:
                if not self.local_certified:raise ValueError('Local native swept-volume evidence required before discharge')
                return 0. if fixed=='Selected_LowerSeat' else .2-guard if sample!='Selected_MouthKeepout' else None
        return None

    def extra_probes(self):
        result=[]
        for group in ['Tool','Tube']:
            for axis in range(4):
                point=[0,0,self.z0]
                if axis:point[axis-1]+=10
                result.append({'id':'FK_'+group+'_'+str(axis),'group':group,'point':point,'world_template':True})
        return result

    def probe_frame(self,group,state):
        c=state['coordinates'];m=base.pickup.placement([0,c[group+'Y'],c[group+'Z']],c[group+'Yaw'])
        return m
