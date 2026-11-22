"""BF01 own-state, anonymous-scan local follower; no peer poses or plans."""
import bisect
import copy
import math
from functools import lru_cache
import l01_local_traffic as local
import tr01_floor_motion as floor
from building_fleet_model import reference, resolved_sensor
from building_fleet_motion import Path, transition, perception_speed_limit, compile_motion, episode_dynamics, spatial_bounds, interval_extrema
F = floor.F


def _quantized_scalar_clock(curve,origin=0.,progress_events=()):
    end=max(.001,round(curve.times[-1]*1000)/1000)
    times={0.,end,*[round(t*1000)/1000 for t in curve.times]}
    times.update(round(k*.05,3)for k in range(1,math.ceil(end/.05))if k*.05<end)
    # Include source geometry boundaries before evaluating the PVA on the
    # quantized clock; waypoint events still do not introduce a stop.
    first,last=curve.points[0][F[0]][0],curve.points[-1][F[0]][0]
    for goal in progress_events:
        goal-=origin
        if not first<goal<last:continue
        lo,hi=0.,curve.times[-1]
        for _ in range(40):
            mid=(lo+hi)/2
            if curve.evaluate(mid)[F[0]][0]<goal:lo=mid
            else:hi=mid
        times.add(round((lo+hi)/2*1000)/1000)
    points=[]
    for t in sorted(t for t in times if 0<=t<=end):
        jet=curve.evaluate(curve.times[-1]if t==end else min(t,curve.times[-1]));p,v,a=[jet[f][0]for f in F[:3]]
        if t>curve.times[-1] and t!=end:
            dt=t-curve.times[-1];p+=v*dt+.5*a*dt*dt;v+=a*dt
        points.append(local.point(t,p,v,a))
    result=floor.motion.Curve(points);result._bf01_origin=origin;return result




@lru_cache(maxsize=512)
def _scalar_stop_state(velocity,acceleration,A,J,closing):
    """Fastest verified member of the scalar stopping family, not a limit guess."""
    candidates=[]
    for fraction in(.98,.95,.92,.9,.85,.8,.7,.6,.5,.25,.125):
        try:candidates.append(local.braking(velocity,acceleration,A*fraction,J*fraction))
        except ValueError:continue
    duration=max(.01,velocity/A,math.sqrt(max(0,velocity/J)),abs(acceleration)/J)
    for _ in range(24):
        duration=math.ceil(duration*100)/100
        if acceleration<0 and duration>3*velocity/(-acceleration)+1e-8:break
        distance=velocity*duration/2+acceleration*duration*duration/12
        if distance>0:candidates.append(floor.motion.Curve([local.point(0,0,velocity,acceleration),local.point(duration,distance,0,0)]))
        duration*=1.1
    candidates=[raw for raw in candidates if raw is not None]
    candidates.sort(key=lambda raw:raw.points[-1][F[0]][0]+closing*raw.times[-1])
    return{'raw':candidates,'next':0,'verified':[]}


def _scalar_stop_catalogue(velocity,acceleration,A,J,closing):
    # Pure mathematics cache, with no vehicle IDs, poses or observations.
    # Qualify slower candidates only when a particular own-path geometry
    # needs them; range derivation usually consumes just the first safe row.
    state=_scalar_stop_state(velocity,acceleration,A,J,closing);index=0
    while True:
        if index<len(state['verified']):
            yield state['verified'][index];index+=1;continue
        if state['next']>=len(state['raw']):return
        raw=state['raw'][state['next']];state['next']+=1
        clock=_quantized_scalar_clock(raw);bounds=floor.motion.bounds(clock)
        if bounds[F[1]]['min'][0]<-1e-8:continue
        if bounds[F[2]]['max_abs'][0]>A*.98 or bounds[F[3]]['max_abs'][0]>J*.98:continue
        points=[{'time_s':p['time_s'],F[0]:[p[F[0]][0],0,0],F[1]:[p[F[1]][0],0,0],F[2]:[p[F[2]][0],0,0]}for p in clock.points]
        if not floor.no_stop(floor.motion.Curve(points))['passed']:continue
        state['verified'].append({'distance_mm':clock.points[-1][F[0]][0],'duration_s':clock.times[-1],
            'clock':clock.points,'interval_bounds':None,
            'dynamics':{name:bounds[field]['max_abs'][0]for name,field in zip(('velocity','acceleration','jerk'),F[1:])}})



def _qualified_scalar_stop(velocity,acceleration,A,J,closing):
    row=next(_scalar_stop_catalogue(velocity,acceleration,A,J,closing),None)
    return {k:v for k,v in row.items()if k not in('clock','interval_bounds')}if row else None


@lru_cache(maxsize=32)
def qualified_perception_limit(sensor_values,limit_values,radius,localization):
    sensor=dict(sensor_values);limits=dict(limit_values)
    reaction=sensor['period_s']+sensor['latency_s']+sensor['stale_after_s']
    uncertainty=sensor['range_error_mm']+localization+sensor['range_mm']*math.sin(math.radians(sensor['angular_step_deg']))
    def check(speed):
        closing=max(speed,sensor['maximum_obstacle_closing_speed_mm_s'])
        stop=_qualified_scalar_stop(speed,0.,limits['acceleration'],limits['jerk'],closing)
        if stop is None:return math.inf,None
        required=radius+sensor['clearance_mm']+uncertainty+stop['distance_mm']+(speed+closing)*reaction+closing*stop['duration_s']
        return required,stop
    lo,hi=0.,limits['velocity'];best=None
    for _ in range(32):
        mid=(lo+hi)/2;required,stop=check(mid)
        if required<=sensor['range_mm']:lo=mid;best=(required,stop)
        else:hi=mid
    applied=lo*.995;required,stop=check(applied)
    return{'velocity_mm_s':lo,'applied_velocity_mm_s':applied,'required_range_mm':required,
           'reaction_s':reaction,'stop':stop,'localization_allowance_mm':localization,
           'basis':'actual quantized scalar stop family plus full observation/closing envelope',
           'global_maximum_proved':False,'hardware_qualified':False}




class Controller(local.LocalController):
    """Own-state controller with anticipatory nonzero speed changes at zones.

    The exported Cartesian curve is independently checked after compilation;
    the shared compiled clock anticipates zones and corners. Protective stops
    and recovery clocks are independently bounded before execution. A failed
    export/clearance check rejects the build instead of relaxing a limit.
    """
    def __init__(self, path, source, zone_caps=(), own_start_s=0, radius_mm=None,
                 static_return=None, motion_program=None):
        from building_fleet_routes import vehicle_envelope
        self.path=path;self.source=source
        envelope=vehicle_envelope()
        if radius_mm is not None and(type(radius_mm)not in(int,float)or not math.isfinite(radius_mm)or radius_mm<envelope['radius_mm']-1e-9):raise ValueError('Own broad-phase radius cannot reduce the source physical envelope')
        if type(own_start_s)not in(int,float)or not math.isfinite(own_start_s)or own_start_s<0:raise ValueError('Nonnegative own start time required')
        self.radius=radius_mm if radius_mm is not None else envelope['radius_mm']
        self.half_length=max(abs(envelope['min'][0]),abs(envelope['max'][0]))
        self.half_width=max(abs(envelope['min'][1]),abs(envelope['max'][1]))
        linear = source['motion']['empty_linear_limits']
        limits = dict(zip(('velocity','acceleration','jerk'),
                          (linear['velocity_mm_s'],linear['acceleration_mm_s2'],linear['jerk_mm_s3'])))
        cfg = resolved_sensor(source)
        self.perception_limit=copy.deepcopy(qualified_perception_limit(tuple(sorted(cfg.items())),tuple(sorted(limits.items())),self.radius,source['geometry']['localization_tolerance_mm']))
        cfg['desired_speed_mm_s']=self.perception_limit['applied_velocity_mm_s']
        self.zone_caps = sorted(zone_caps)
        self.angular = reference(source,'angular_profile')['limits']['angular']
        self.static_return = static_return
        super().__init__(0,path.length,cfg,limits,self.radius)
        self.mode = 'waiting'; self.history = []; self.recorded = []; self.record_times = []
        self.heading_offset=0.
        self.events = []; self.plan_kind = None; self.target_speed = 0; self.now = own_start_s
        self._record(own_start_s)
        if any(type(at)not in(int,float)or type(cap)not in(int,float)or not math.isfinite(at)or not math.isfinite(cap)or at<0 or at>path.length or not 0<cap<=limits['velocity']for at,cap in self.zone_caps):raise ValueError('Finite own progress zone caps required')
        if len({at for at,_ in self.zone_caps})!=len(self.zone_caps):raise ValueError('Duplicate own speed-zone boundary')
        zone_values=[min(cfg['desired_speed_mm_s'],cap)for _,cap in self.zone_caps]
        if not self.zone_caps or self.zone_caps[0][0]>0:zone_values.append(cfg['desired_speed_mm_s'])
        self.zone_velocity_cap=max(zone_values)
        program=compile_motion(path,source,zone_caps=self.zone_caps)if motion_program is None else copy.deepcopy(motion_program)
        allowed={'points','scalar_clock','duration_s','dynamics','no_stop','perception_limit','piece_caps_mm_s','spatial_interval_bounds','timing','zone_bounds'}
        if type(program)is not dict or not {'points','scalar_clock'}<=set(program)or set(program)-allowed:raise ValueError('Only an own compiled motion program is accepted')
        self.nominal_clock=floor.motion.Curve(program['scalar_clock'])
        nodes=self.nominal_clock.points
        if self.nominal_clock.times[0]!=0 or any(len(p[field])!=1 for p in nodes for field in F[:3]):raise ValueError('Own scalar clock requires time zero and one-dimensional complete PVA')
        if abs(nodes[0][F[0]][0])>1e-9 or any(abs(p[f][0])>1e-8 for p in(nodes[0],nodes[-1])for f in F[1:3]):raise ValueError('Own scalar clock must start at zero and rest at both functional endpoints')
        if any(p[F[0]][0]<-1e-8 or p[F[0]][0]>path.length+1e-5 for p in nodes)or floor.motion.bounds(self.nominal_clock)[F[1]]['min'][0]<-1e-8:raise ValueError('Own scalar clock must remain monotone on its route')
        initial_heading=program['points'][0]['pose_mm_rad'][2]
        raw_heading=path.evaluate(0)[0][2]
        self.heading_offset=(initial_heading-raw_heading+math.pi)%(2*math.pi)-math.pi
        if min(abs(self.heading_offset),abs(abs(self.heading_offset)-math.pi))>1e-6:raise ValueError('Own vehicle heading must follow or reverse its path')
        self._record(own_start_s)
        if abs(self.nominal_clock.points[-1][F[0]][0]-path.length)>1e-5:raise ValueError('Own compiled clock must cover this path exactly')
        self._brake_cache=None;self.profile_checks=[];self._geometry_cache={}
        self.perception_audit={'checks':0,'minimum_range_margin_mm':None,'maximum_required_gap_mm':0.,'scope':'actual checked stop at each own decision state; discrete 0.05 s synthetic controller clock'}
        self.nominal_clock,self.nominal_clock_proof=self._bounded_start_clock(self.nominal_clock,0.)
        self.profile_checks.append({'kind':'nominal_clock','proof':self.nominal_clock_proof})
        self.continuation_stop_clock=None;self.step_end_s=None
        self._step_certificate=None;self._fallback=None

    @property
    def progress(self):
        return self.y

    def pose(self):
        pose=self.path.evaluate(self.y)[0];pose[2]+=self.heading_offset
        if self.recorded:
            previous=self.recorded[-1]['pose_mm_rad'][2]
            pose[2]=previous+(pose[2]-previous+math.pi)%(2*math.pi)-math.pi
        return pose

    def align_initial_heading(self,yaw):
        """Preserve an equivalent unwrapped own heading; never rotate in place."""
        if type(yaw)not in(int,float)or not math.isfinite(yaw):raise ValueError('Finite own initial heading required')
        if self.mode not in('waiting','arrived')or abs(self.v)>1e-8 or abs(self.a)>1e-8:raise ValueError('Initial heading alignment requires confirmed rest')
        if any(any(abs(v)>1e-8 for v in p['velocity_mm_rad_s']+p['acceleration_mm_rad_s2'])for p in self.recorded):raise ValueError('Heading alignment must precede the moving episode')
        delta=yaw-self.pose()[2]
        if abs(math.remainder(delta,2*math.pi))>1e-6:raise ValueError('Physical heading cannot change during unwrapped alignment')
        self.heading_offset+=delta
        for p in self.recorded:p['pose_mm_rad'][2]+=delta
        self._record(self.now)

    def _record(self,now):
        if abs(now*1000-round(now*1000))>1e-6:raise ValueError('Recorded controller time is not on the 1 ms grid')
        now=round(now,3)
        pose, velocity, acceleration = self.path.pva(self.y,self.v,self.a)
        pose[2]+=self.heading_offset
        if self.recorded:
            previous = self.recorded[-1]['pose_mm_rad'][2]
            pose[2] = previous+(pose[2]-previous+math.pi)%(2*math.pi)-math.pi
        item = {'time_s':now,'pose_mm_rad':pose,'velocity_mm_rad_s':velocity,
                'acceleration_mm_rad_s2':acceleration,'mode':self.mode,
                'hold_reason':self.reason if self.mode=='waiting' else 'functional_endpoint'if self.goal-self.y<1e-7 and self.v<1e-8 else None}
        if self.recorded and abs(self.recorded[-1]['time_s']-now) < 1e-9:
            self.recorded[-1] = item
        else:
            self.recorded.append(item); self.record_times.append(now)

    def _bounded_start_clock(self,raw,origin):
        if abs(raw.points[0][F[1]][0])>1e-8 or abs(raw.points[0][F[2]][0])>1e-8:raise ValueError('Retiming requires a confirmed resting episode start')
        base=raw;scales=[1.,1.005,1.01,1.02,1.04,1.08]
        for iteration in range(40):
            dilation=scales[iteration]
            raw=floor.motion.Curve([local.point(p['time_s']*dilation,p[F[0]][0],p[F[1]][0]/dilation,p[F[2]][0]/dilation**2)for p in base.points])
            quantized=self._quantized_clock(raw,origin);valid,bounds=self._admissible(quantized,origin)
            if valid:return quantized,{'dilation':dilation,'dynamics':bounds,'time_quantum_s':.001,'playback_factor':1,'selection':'first verified factor in an increasing finite search family; global optimum unproved'}
            limits={'linear':{**self.limits,'velocity':self.zone_velocity_cap},'angular':self.angular}
            ratio=max([1.001,*[(value/limits[kind][key])**(1/order)for kind in('linear','angular')for order,key in enumerate(('velocity','acceleration','jerk'),1)for value in[bounds[kind][key]]]])*1.001
            proposed=max(scales[-1]*1.001,dilation*ratio)
            scales.append(proposed)
        raise RuntimeError('Dense quantized own nominal motion cannot satisfy source bounds')

    def _quantized_clock(self,curve,origin):
        return _quantized_scalar_clock(curve,origin,[*self.path.ends,*[at for at,_ in self.zone_caps]])

    def _cartesian_curve(self,clock,origin):
        points=[];yaw=None
        for point in clock.points:
            pose,v,a=self.path.pva(origin+point[F[0]][0],point[F[1]][0],point[F[2]][0]);pose[2]+=self.heading_offset
            if yaw is not None:pose[2]=yaw+(pose[2]-yaw+math.pi)%(2*math.pi)-math.pi
            yaw=pose[2]
            points.append({'time_s':point['time_s'],'pose_mm_rad':pose,'velocity_mm_rad_s':v,'acceleration_mm_rad_s2':a})
        return floor.motion.Curve(floor.canonical(points))

    def _zone_cap_at(self,progress):
        value=self.settings['desired_speed_mm_s']
        for begin,cap in self.zone_caps:
            if begin>progress:break
            value=min(self.settings['desired_speed_mm_s'],cap)
        return value

    def _admissible(self,clock,origin):
        curve=self._cartesian_curve(clock,origin)
        bounds=episode_dynamics(curve,self.radius)
        linear={**self.limits,'velocity':self.zone_velocity_cap}
        valid=all(value<=limit[key]*(1+1e-6)for kind,limit in [('linear',linear),('angular',self.angular)]for key,value in bounds[kind].items())
        zone_maxima={}
        if self.zone_caps:
            for left,right in zip(clock.points,clock.points[1:]):
                ta,tb=left['time_s'],right['time_s'];sa,sb=origin+left[F[0]][0],origin+right[F[0]][0]
                cuts=[ta,tb]
                for at,_ in self.zone_caps:
                    if not sa<at<sb:continue
                    lo,hi=ta,tb
                    for _ in range(40):
                        mid=(lo+hi)/2
                        if origin+clock.evaluate(mid)[F[0]][0]<at:lo=mid
                        else:hi=mid
                    cuts.append((lo+hi)/2)
                cuts=sorted(cuts)
                for start,end in zip(cuts,cuts[1:]):
                    if end-start<1e-9:continue
                    cap=self._zone_cap_at(origin+clock.evaluate((start+end)/2)[F[0]][0])
                    raw=interval_extrema(curve,start,end,1)
                    speed=math.hypot(*[max(abs(raw['min'][k]),abs(raw['max'][k]))for k in range(2)])
                    if speed>cap*(1+1e-6):valid=False
                    zone_maxima[str(cap)]=max(zone_maxima.get(str(cap),0),speed)
        bounds['zone_velocity_maxima_mm_s']=zone_maxima
        valid=valid and floor.no_stop(curve)['passed']
        return valid,bounds

    def set_plan(self,curve,now,mode,kind=None):
        if abs(now*1000-round(now*1000))>1e-6:raise ValueError('Controller start time must lie on the 1 ms grid')
        continuation=getattr(curve,'_bf01_continuation',None)
        self._step_certificate=None
        if continuation is not None:
            if self.plan is not continuation:raise ValueError('Stale own final-braking continuation')
            self.mode=mode;self.plan_kind=kind;return
        if getattr(curve,'_bf01_origin',None)!=self.y:curve=self._quantized_clock(curve,self.y)
        self._brake_cache=None
        super().set_plan(curve,now,mode);self.plan_kind=kind
        if kind=='goal':
            self._final_tail_time=curve.times[0]
            for left,right in reversed(list(zip(curve.points,curve.points[1:]))):
                bound=floor.motion.bounds([left,right])
                if bound[F[2]]['max'][0]>1e-6 or bound[F[1]]['min'][0]<-1e-8:
                    self._final_tail_time=right['time_s'];break

    @staticmethod
    def _split_at(controls,u):
        rows=[controls]
        while len(rows[-1])>1:rows.append([[(1-u)*a+u*b for a,b in zip(x,y)]for x,y in zip(rows[-1],rows[-1][1:])])
        return[row[0]for row in rows],[row[-1]for row in reversed(rows)]

    def _spatial_enclosure(self,first,last):
        linear=[0.,0.,0.];angular=[0.,0.,0.]
        for index,piece in enumerate(self.path.pieces):
            before=0. if index==0 else self.path.ends[index-1];end=self.path.ends[index]
            if last<=before+1e-10 or first>=end-1e-10:continue
            if len(piece['controls'])==2:
                bound={'linear':[1.,0.,0.],'angular':[0.,0.,0.]}
                for k in range(3):linear[k]=max(linear[k],bound['linear'][k])
                continue
            count=max(1,math.ceil(piece['weight']/25))
            left=max(0,min(count-1,math.floor((first-before)/piece['weight']*count)))
            right=max(0,min(count-1,math.floor((last-before)/piece['weight']*count)))
            for block in range(left,right+1):
                key=(index,block)
                if key not in self._geometry_cache:
                    u0,u1=block/count,(block+1)/count;controls=piece['controls']
                    _,tail=self._split_at(controls,u0)
                    head,_=self._split_at(tail,(u1-u0)/(1-u0))
                    segment=Path.__new__(Path);segment.pieces=[];segment.ends=[];segment.length=0.
                    segment._add(head,piece['weight']/count)
                    self._geometry_cache[key]=spatial_bounds(segment.pieces[0],subdivisions=8)
                bound=self._geometry_cache[key]
                for k in range(3):
                    linear[k]=max(linear[k],bound['linear'][k]);angular[k]=max(angular[k],bound['angular'][k])
        return{'linear':linear,'angular':angular}

    def _analytic_stop_ok(self,clock,scalar_bounds):
        for index,(left,right)in enumerate(zip(clock.points,clock.points[1:])):
            raw=scalar_bounds[index]
            if raw[F[1]]['min'][0]<-1e-8:return False
            V,A,J=[raw[f]['max_abs'][0]for f in F[1:]]
            begin=self.y+left[F[0]][0];end=self.y+right[F[0]][0]
            geometry=self._spatial_enclosure(begin,end)
            for kind,limits in [('linear',self.limits),('angular',self.angular)]:
                d1,d2,d3=geometry[kind]
                actual=(d1*V,d2*V*V+d1*A,d3*V**3+3*d2*V*A+d1*J)
                for key,value in zip(('velocity','acceleration','jerk'),actual):
                    padding=1. if key=='velocity'or kind=='linear'and d2==d3==0 else .95
                    if value>limits[key]*padding:return False
            cap=min([self._zone_cap_at(begin),self._zone_cap_at(end),*[min(self.settings['desired_speed_mm_s'],c)for at,c in self.zone_caps if begin<at<end]])
            if geometry['linear'][0]*V>cap*(1+1e-6):
                ta,tb=left['time_s'],right['time_s'];cuts=[ta,tb]
                for at,_ in self.zone_caps:
                    if not begin<at<end:continue
                    lo,hi=ta,tb
                    for _ in range(35):
                        mid=(lo+hi)/2
                        if self.y+clock.evaluate(mid)[F[0]][0]<at:lo=mid
                        else:hi=mid
                    cuts.append((lo+hi)/2)
                cuts=sorted(cuts)
                for ca,cb in zip(cuts,cuts[1:]):
                    midpoint=self.y+clock.evaluate((ca+cb)/2)[F[0]][0];local_cap=self._zone_cap_at(midpoint)
                    endpoints=[]
                    for t in(ca,cb):
                        jet=clock.evaluate(t);endpoints.append(local.point(t,*[jet[f][0]for f in F[:3]]))
                    local_bound=floor.motion.bounds(endpoints)[F[1]]['max_abs'][0]
                    if geometry['linear'][0]*local_bound>local_cap*(1+1e-6):return False
        return True

    def _final_deceleration(self,require_monotone=True):
        # This suffix was already checked as part of the active own clock.
        # Its monotonic final-deceleration boundary is compiled once per plan;
        # scanning/refitting the entire future trajectory every tick is both
        # unnecessary and numerically weaker than preserving that exact clock.
        if self.plan is None or self.plan_kind!='goal':return None
        elapsed=self.now-self.plan_start
        if require_monotone and elapsed<getattr(self,'_final_tail_time',math.inf)-1e-9:return None
        duration=self.plan.times[-1]-elapsed
        distance=self.plan_origin+self.plan.points[-1][F[0]][0]-self.y
        closing=max(self._zone_cap_at(self.y),self.settings['maximum_obstacle_closing_speed_mm_s'])
        reaction=self.settings['period_s']+self.settings['latency_s']+self.settings['stale_after_s']
        required=self.settings['clearance_mm']+distance+(self._zone_cap_at(self.y)+closing)*reaction+closing*duration
        inflation=self.settings['range_error_mm']+self.settings['range_mm']*math.sin(math.radians(self.settings['angular_step_deg']))+self.source['geometry']['localization_tolerance_mm']
        if required>=self.settings['range_mm']-self.radius-inflation:return None
        points=[local.point(0,0,self.v,self.a)]
        for node in self.plan.points:
            if node['time_s']>elapsed+1e-8:points.append(local.point(node['time_s']-elapsed,self.plan_origin+node[F[0]][0]-self.y,node[F[1]][0],node[F[2]][0]))
        if len(points)<2:return None
        suffix=floor.motion.Curve(points);suffix._bf01_continuation=self.plan
        return suffix

    def _stop_observation_margin(self,clock):
        """Use the same actual observation budget for every stop family."""
        closing=max(self._zone_cap_at(self.y),self.settings['maximum_obstacle_closing_speed_mm_s'])
        reaction=self.settings['period_s']+self.settings['latency_s']+self.settings['stale_after_s']
        inflation=self.settings['range_error_mm']+self.settings['range_mm']*math.sin(math.radians(self.settings['angular_step_deg']))+self.source['geometry']['localization_tolerance_mm']
        required=(self.settings['clearance_mm']+clock.points[-1][F[0]][0]
            +(self._zone_cap_at(self.y)+closing)*reaction+closing*clock.times[-1])
        return self.settings['range_mm']-self.radius-inflation-required

    def _checked_brake(self,strict=False,*,candidate_ok=None):
        if self.v<1e-8 and abs(self.a)<1e-8:return None
        accept=(lambda clock:True)if candidate_ok is None else candidate_ok
        key=(self.y,self.v,self.a)
        if self._brake_cache is not None and self._brake_cache[0]==key:
            clock=self._brake_cache[1]
            if strict and not getattr(clock,'_bf01_continuation',None):
                valid,_=self._admissible(clock,self.y)
                if not valid:clock=None
            if clock is not None and accept(clock):return clock
        retained=self._fallback_suffix()
        if retained is not None and accept(retained):
            self._brake_cache=(key,retained)
            return retained
        if self.mode=='braking'and self.plan is not None and self.plan_kind=='protective_stop':
            elapsed=self.now-self.plan_start;points=[local.point(0,0,self.v,self.a)]
            for node in self.plan.points:
                if node['time_s']>elapsed+1e-8:points.append(local.point(node['time_s']-elapsed,self.plan_origin+node[F[0]][0]-self.y,node[F[1]][0],node[F[2]][0]))
            result=floor.motion.Curve(points)if len(points)>1 else None
            if result is not None and self._stop_observation_margin(result)<0:
                raise RuntimeError('Actual protective-stop continuation exceeds the unchanged observation budget')
            if result is not None and not accept(result):raise RuntimeError('Active protective stop does not meet the required continuation context')
            return result
        clock=None
        if clock is None:
            clock=self._final_deceleration()
            if clock is not None and(strict and not self._admissible(clock,self.y)[0]or not accept(clock)):
                clock=None
            if clock is None:
                rejected=[]
                closing=max(self._zone_cap_at(self.y),self.settings['maximum_obstacle_closing_speed_mm_s'])
                rows=_scalar_stop_catalogue(round(self.v,5),round(self.a,5),self.limits['acceleration'],self.limits['jerk'],closing)
                for row in rows:
                    if self.y+row['distance_mm']>self.goal+1e-5:continue
                    points=copy.deepcopy(row['clock']);points[0][F[1]]=[self.v];points[0][F[2]]=[self.a]
                    candidate=floor.motion.Curve(points)
                    if self._stop_observation_margin(candidate)<0:continue
                    if row['interval_bounds']is None:row['interval_bounds']=[floor.motion.bounds([a,b])for a,b in zip(row['clock'],row['clock'][1:])]
                    bounds=list(row['interval_bounds']);bounds[0]=floor.motion.bounds(points[:2])
                    if self._analytic_stop_ok(candidate,bounds):
                        if strict and not self._admissible(candidate,self.y)[0]:continue
                        if not accept(candidate):continue
                        clock=candidate;clock._bf01_origin=self.y;break
                    if all(bound[F[1]]['min'][0]>=-1e-8 for bound in bounds):rejected.append(candidate)
                if clock is None:
                    # Independent absolute derivative bounds can reject a
                    # valid correlated Cartesian PVA, especially in a short
                    # cabin curve. Only the actual quantized exported curve
                    # may accept such a candidate; all source limits, zones
                    # and the no-stop rule still apply without wider padding.
                    for candidate in rejected:
                        valid,actual=self._admissible(candidate,self.y)
                        if valid and self._stop_observation_margin(candidate)>=0 and accept(candidate):
                            clock=candidate;clock._bf01_origin=self.y
                            self.profile_checks.append({'kind':'exact_stop_fallback','progress_mm':self.y,
                                'velocity_mm_s':self.v,'acceleration_mm_s2':self.a,'dynamics':actual})
                            break
                if clock is None:
                    # The scalar family is finite. A tight yaw curve may
                    # require a longer, lower-acceleration stop even at very
                    # low linear speed. Search only within the unchanged
                    # observation budget, never past the own route endpoint.
                    _,velocity,acceleration=self.path.pva(self.y,self.v,self.a)
                    duration=max(.01,self.v/self.limits['acceleration'],
                        math.sqrt(self.v/self.limits['jerk']),abs(self.a)/self.limits['jerk'],
                        1.5*abs(velocity[2])/self.angular['acceleration'],
                        math.sqrt(6*abs(velocity[2])/self.angular['jerk']),
                        abs(acceleration[2])/self.angular['jerk'])
                    reaction=self.settings['period_s']+self.settings['latency_s']+self.settings['stale_after_s']
                    inflation=self.settings['range_error_mm']+self.settings['range_mm']*math.sin(math.radians(self.settings['angular_step_deg']))+self.source['geometry']['localization_tolerance_mm']
                    available=self.settings['range_mm']-self.radius-inflation-self.settings['clearance_mm']-(self._zone_cap_at(self.y)+closing)*reaction
                    while duration*closing<available:
                        duration=math.ceil(duration*1000)/1000
                        if self.a<0 and duration>3*self.v/(-self.a)+1e-8:break
                        distance=self.v*duration/2+self.a*duration*duration/12
                        if distance<=0 or self.y+distance>self.goal+1e-5 or distance+closing*duration>=available:break
                        raw=floor.motion.Curve([local.point(0,0,self.v,self.a),local.point(duration,distance,0,0)])
                        candidate=self._quantized_clock(raw,self.y)
                        scalar=floor.motion.bounds(candidate)
                        if (scalar[F[1]]['min'][0]>=-1e-8 and all(scalar[field]['max_abs'][0]<=self.limits[name]*(1+1e-6)
                                for field,name in zip(F[1:],('velocity','acceleration','jerk')))):
                            valid,actual=self._admissible(candidate,self.y)
                            if valid and self._stop_observation_margin(candidate)>=0 and accept(candidate):
                                clock=candidate;clock._bf01_origin=self.y
                                self.profile_checks.append({'kind':'exact_stop_extension','progress_mm':self.y,
                                    'velocity_mm_s':self.v,'acceleration_mm_s2':self.a,'dynamics':actual})
                                break
                        duration*=1.1
            if clock is None:
                # Last resort: the already bound, validated own goal clock
                # may have a short correlated suffix before its monotone
                # deceleration boundary. It is an actual stop only if its
                # remaining exported PVA and observation budget both pass.
                suffix=self._final_deceleration(require_monotone=False)
                if suffix is not None and floor.motion.bounds(suffix)[F[1]]['min'][0]>=-1e-8:
                    valid,actual=self._admissible(suffix,self.y)
                    if valid and self._stop_observation_margin(suffix)>=0 and accept(suffix):
                        clock=suffix
                        self.profile_checks.append({'kind':'validated_goal_suffix_stop','progress_mm':self.y,
                            'velocity_mm_s':self.v,'acceleration_mm_s2':self.a,'dynamics':actual})
            if clock is None:raise RuntimeError('No bounded own protective-stop enclosure; replan before execution')
            if self._stop_observation_margin(clock)<0:raise RuntimeError('Selected stop exceeds the unchanged observation budget')
            self._brake_cache=(key,clock)
        if strict and not getattr(clock,'_bf01_continuation',None):
            valid,bounds=self._admissible(clock,self.y)
            if not valid:raise RuntimeError('Analytic stop rejected by actual quantized Cartesian export; build rejected')
        return clock

    def own_pose_at(self, captured_s):
        if captured_s < 0:
            raise ValueError('Negative capture time')
        times = self.record_times
        i = bisect.bisect_right(times, captured_s)-1
        if i < 0 or captured_s > self.now+1e-8:
            raise ValueError('No own localization at the scan capture time')
        if i == len(times)-1 or times[i] == captured_s:
            return self.recorded[i]['pose_mm_rad'][:]
        curve = floor.motion.Curve(floor.canonical(self.recorded[i:i+2]))
        return curve.evaluate(captured_s)[F[0]]

    def _projection_window(self,lookahead_mm):
        """Cache only this vehicle's immutable future centreline samples."""
        end=self.goal if lookahead_mm is None else min(self.goal,self.y+lookahead_mm)
        key=(id(self.path),self.y,end)
        if getattr(self,'_projection_window_key',None)==key:return self._projection_segments
        if getattr(self,'_projection_path',None)is not self.path:
            self._sample_ends=[row[1]for row in self.path.samples];self._projection_path=self.path
        samples=self.path.samples;first=max(0,bisect.bisect_left(self._sample_ends,self.y)-1);segments=[]
        for a,b,pa,pb in samples[first:]:
            if a>end+1e-9:break
            if b<self.y-1e-9:continue
            left=max(a,self.y);right=min(b,end)
            if right<left:continue
            # Cached full-sample positions are the same Path.evaluate results
            # used previously. Only an actually clipped endpoint is evaluated.
            p=pa if left==a else self.path.evaluate(left)[0][:2]
            q=pb if right==b else self.path.evaluate(right)[0][:2]
            delta=[q[k]-p[k]for k in range(2)];norm=sum(v*v for v in delta)
            bounds=(min(p[0],q[0]),min(p[1],q[1]),max(p[0],q[0]),max(p[1],q[1]))
            roundoff=32*math.ulp(max(1.,*[abs(v)for v in p+q]))
            segments.append((left,right,p,delta,norm,bounds,roundoff))
        self._projection_window_key=key;self._projection_segments=segments
        return segments

    def project_ahead(self,point,lookahead_mm=None,maximum_lateral_mm=None):
        """Exact ordered nearest future sample, with a conservative broad phase.

        An optional lateral bound may discard results beyond that bound. The
        ordinary API retains the previous closest-point arithmetic and tie
        order. AABB lower bounds only omit candidates unable to improve it;
        their roundoff allowance does not alter any returned exact distance.
        """
        if maximum_lateral_mm is not None and(type(maximum_lateral_mm)not in(int,float)or not math.isfinite(maximum_lateral_mm)or maximum_lateral_mm<0):
            raise ValueError('Finite nonnegative projection lateral bound required')
        best=(math.inf,self.y);query_roundoff=32*math.ulp(max(1.,abs(point[0]),abs(point[1])))
        for left,right,p,delta,norm,bounds,roundoff in self._projection_window(lookahead_mm):
            threshold=best[0]if maximum_lateral_mm is None else min(best[0],maximum_lateral_mm)
            dx=max(bounds[0]-point[0],0.,point[0]-bounds[2])
            dy=max(bounds[1]-point[1],0.,point[1]-bounds[3])
            # L-infinity distance to the segment's AABB is a lower bound.
            # Outward allowance covers binary64 endpoint/residual arithmetic;
            # near ties always take the unchanged exact closest-point branch.
            lower=max(dx,dy)-max(roundoff,query_roundoff)
            if lower>threshold:continue
            u=max(0.,min(1.,sum((point[k]-p[k])*delta[k]for k in range(2))/norm))if norm else 0.
            distance=math.hypot(*(point[k]-p[k]-u*delta[k]for k in range(2)))
            if distance<best[0]:best=distance,left+u*(right-left)
        return best if maximum_lateral_mm is None or best[0]<=maximum_lateral_mm else(math.inf,self.y)

    def _future_rectangle_excludes(self,point,padding,lookahead_mm):
        """One-sided proof that an anonymous point misses the whole own sweep.

        Failure or finite-work exhaustion preserves the original hazard. The
        padding retains the complete source clearance and sensing uncertainty.
        No peer identity, pose, reservation or static-map assumption is used.
        """
        if (len(point)!=2 or any(type(v)not in(int,float)or not math.isfinite(v)for v in point)or
                type(padding)not in(int,float)or not math.isfinite(padding)or padding<0 or
                type(lookahead_mm)not in(int,float)or not math.isfinite(lookahead_mm)or lookahead_mm<0):return False
        end=min(self.goal,self.y+lookahead_mm);before=0.;evaluations=0
        def distance(pose,L):
            dx,dy=point[0]-pose[0],point[1]-pose[1];c,s=math.cos(pose[2]),math.sin(pose[2])
            return math.hypot(max(0.,abs(c*dx+s*dy)-L),max(0.,abs(-s*dx+c*dy)-self.half_width))
        pose=self.path.evaluate(self.y)[0]
        error=128*math.ulp(max(1.,*[abs(v)for v in point+pose[:2]],padding,self.radius))
        if end<self.y or math.nextafter(distance(pose,self.half_length)-error,-math.inf)<=padding:return False
        for piece,finish in zip(self.path.pieces,self.path.ends):
            left,right=max(before,self.y),min(finish,end);before=finish
            if right<=left:continue
            if len(piece['controls'])==2:
                a,b=self.path.evaluate(left)[0],self.path.evaluate(right)[0]
                pose=[(a[0]+b[0])/2,(a[1]+b[1])/2,a[2]]
                error=128*math.ulp(max(1.,*[abs(v)for v in point+a[:2]+b[:2]],padding,self.radius))
                # A constant-yaw translating rectangle sweeps exactly one
                # longer rectangle. This bound covers the complete segment.
                travel=math.nextafter(math.hypot(b[0]-a[0],b[1]-a[1]),math.inf)
                half_travel=math.nextafter(travel/2,math.inf)
                swept_length=math.nextafter(self.half_length+half_travel,math.inf)
                gap=distance(pose,swept_length)
                if math.nextafter(gap-error,-math.inf)<=padding:return False
                continue
            # Full-piece derivative hulls cover even a sub-ULP endpoint
            # remainder; the stopping helper's tolerant piece skips cannot
            # supply a strict sweep enclosure here.
            try:bounds=spatial_bounds(piece,subdivisions=8)
            except ValueError:return False
            if bounds['linear'][0]<=0 or not all(math.isfinite(v)for v in(bounds['linear'][0],bounds['angular'][0])):return False
            pending=[(left,right,0)]
            while pending:
                if evaluations>=1024:return False
                a,b,depth=pending.pop();mid=(a+b)/2;pose=self.path.evaluate(mid)[0]
                error=128*math.ulp(max(1.,*[abs(v)for v in point+pose[:2]],padding,self.radius))
                gap=distance(pose,self.half_length)
                if math.nextafter(gap-error,-math.inf)<=padding:return False
                # The rounded midpoint can equal an endpoint. Bound both
                # distances separately instead of assuming an exact half.
                half_span=max(math.nextafter(mid-a,math.inf),math.nextafter(b-mid,math.inf))
                rotation=math.nextafter(self.radius*bounds['angular'][0],math.inf)
                rate=math.nextafter(bounds['linear'][0]+rotation,math.inf)
                movement=math.nextafter(rate*half_span,math.inf)
                evaluations+=1
                if math.nextafter(gap-error-movement,-math.inf)>padding:continue
                if depth>=24 or evaluations>=1024:return False
                pending.extend([(a,mid,depth+1),(mid,b,depth+1)])
        return True

    def _observed_gap(self,scan,now):
        if scan is None:return 0.,'scan_missing_or_stale'
        if type(scan)is not dict or set(scan)!={'captured_s','returns_local_mm'}:raise ValueError('Only anonymous timestamped local scans are accepted')
        if type(scan['captured_s'])not in(int,float)or not math.isfinite(scan['captured_s'])or scan['captured_s']<0:raise ValueError('Finite scan capture time required')
        if type(scan['returns_local_mm'])is not list:raise ValueError('Anonymous scan vectors required')
        for ray in scan['returns_local_mm']:
            if type(ray)not in(list,tuple)or len(ray)!=2 or any(type(v)not in(int,float)or not math.isfinite(v)for v in ray):raise ValueError('Only finite anonymous local vectors are accepted')
            if math.hypot(*ray)>self.settings['range_mm']+self.settings['range_error_mm']:raise ValueError('Return exceeds the referenced sensor range')
        if scan['captured_s']>now+1e-9:raise ValueError('Future scan')
        if now-scan['captured_s']>self.settings['stale_after_s']:return 0.,'scan_missing_or_stale'
        if scan['captured_s']<self.record_times[0]-1e-9:return 0.,'scan_capture_localization_unavailable'
        pose=self.own_pose_at(scan['captured_s']);c,s=math.cos(pose[2]),math.sin(pose[2])
        inflation=self.settings['range_error_mm']+self.settings['range_mm']*math.sin(math.radians(self.settings['angular_step_deg']))+self.source['geometry']['localization_tolerance_mm']
        visible_gap=self.settings['range_mm']-self.radius-inflation
        gap=visible_gap;own=self.pose();travel=self.path.evaluate(self.y)[0][2];tc,ts=math.cos(travel),math.sin(travel)
        for side,forward in scan['returns_local_mm']:
            if self.static_return and self.static_return(pose,[side,forward]):continue
            point=[pose[0]+c*forward-s*side,pose[1]+s*forward+c*side]
            lateral,along=self.project_ahead(point,self.settings['range_mm']+self.radius,
                self.radius+self.settings['clearance_mm']+inflation)
            piece=min(len(self.path.pieces)-1,bisect.bisect_right(self.path.ends,along))
            straight=len(self.path.pieces[piece]['controls'])==2
            half_width=self.half_width if straight else self.radius
            half_length=self.half_length if straight else self.radius
            if along>self.y and lateral<=half_width+self.settings['clearance_mm']+inflation:
                candidate=along-self.y-half_length-inflation
                if (candidate<gap and not straight and self._future_rectangle_excludes(point,
                        self.settings['clearance_mm']+inflation,self.settings['range_mm']+self.radius)):
                    continue
                gap=min(gap,candidate)
            relative=[point[k]-own[k]for k in range(2)];ahead=relative[0]*tc+relative[1]*ts
            sideways=abs(-relative[0]*ts+relative[1]*tc)
            # Immediate body protection must not extrapolate the current
            # tangent indefinitely beyond a bend in the own future curve.
            # The future-path projection above retains every forward hazard
            # on that curve. This second test covers its current body only.
            body_distance=math.hypot(max(0.,ahead-self.half_length),max(0.,sideways-self.half_width))
            # The source uncertainty is a displacement radius, hence the
            # inflated rectangle has round corners. Axis-wise padding adds
            # false square corners. Keep boundary hazards conservatively;
            # the allowance covers world-coordinate cancellation and the
            # local rotations, including large translated source fixtures.
            roundoff=64*math.ulp(max(1.,*[abs(v)for v in point+own[:2]],self.half_length,self.half_width,inflation))
            if (ahead>=-roundoff and math.nextafter(body_distance,-math.inf)<=
                    self.settings['clearance_mm']+inflation+roundoff):
                gap=min(gap,ahead-self.half_length-inflation)
        return gap,'perception_range_budget'if gap==visible_gap else'local_obstacle'

    def _visible_gap(self):
        inflation=(self.settings['range_error_mm']+self.settings['range_mm']*
            math.sin(math.radians(self.settings['angular_step_deg']))+
            self.source['geometry']['localization_tolerance_mm'])
        return self.settings['range_mm']-self.radius-inflation

    def _clock_requirement(self,clock,origin):
        """Bound every suffix using one maximum source cap, never samples."""
        finish=origin+clock.points[-1][F[0]][0]
        cap=max([self._zone_cap_at(origin),self._zone_cap_at(finish),
            *[min(self.settings['desired_speed_mm_s'],value)for at,value in self.zone_caps
              if origin<=at<=finish]])
        closing=max(cap,self.settings['maximum_obstacle_closing_speed_mm_s'])
        up=lambda value:math.nextafter(value,math.inf)
        reaction=up(up(self.settings['period_s']+self.settings['latency_s'])+self.settings['stale_after_s'])
        required=up(up(up(self.settings['clearance_mm']+clock.points[-1][F[0]][0])+
            up(up(cap+closing)*reaction))+up(closing*clock.times[-1]))
        return required,cap,closing

    def _remaining_observation(self,anchor):
        up=lambda value:math.nextafter(value,math.inf)
        down=lambda value:math.nextafter(value,-math.inf)
        moved=up(self.y-anchor['origin_mm']);age=up(self.now-anchor['time_s'])
        return down(down(anchor['gap_mm']-moved)-up(anchor['closing_mm_s']*age))

    def _valid_stop_clock(self,clock,origin):
        if clock is None:return False
        if (clock.times[0]!=0 or abs(clock.points[0][F[0]][0])>1e-9 or
                any(abs(t*1000-round(t*1000))>1e-6 for t in clock.times)or
                abs(clock.points[0][F[1]][0]-self.v)>1e-8 or
                abs(clock.points[0][F[2]][0]-self.a)>1e-8 or
                any(abs(clock.points[-1][f][0])>1e-8 for f in F[1:3])or
                origin+clock.points[-1][F[0]][0]>self.goal+1e-5):return False
        scalar=floor.motion.bounds(clock)
        if scalar[F[1]]['min'][0]<-1e-8:return False
        if any(scalar[f]['max_abs'][0]>self.limits[k]*(1+1e-6)
                for f,k in zip(F[1:],('velocity','acceleration','jerk'))):return False
        return self._admissible(clock,origin)[0]

    def _fallback_suffix(self):
        """Keep the last proved stop, including its original observation age."""
        saved=getattr(self,'_fallback',None)
        if saved is None or saved['path']is not self.path:return None
        elapsed=round(self.now-saved['start_s'],3);clock=saved['clock']
        if not 0<=elapsed<clock.times[-1]:return None
        jet=clock.evaluate(elapsed)
        expected=(saved['origin_mm']+jet[F[0]][0],jet[F[1]][0],jet[F[2]][0])
        if expected!=(self.y,self.v,self.a):return None
        points=[local.point(0,0,self.v,self.a)]
        for node in clock.points:
            absolute=round(saved['start_s']+node['time_s'],3)
            if absolute>self.now+1e-9:
                points.append(local.point(round(absolute-self.now,3),
                    saved['origin_mm']+node[F[0]][0]-self.y,node[F[1]][0],node[F[2]][0]))
        if len(points)<2:return None
        suffix=floor.motion.Curve(points);suffix._bf01_origin=self.y
        required,_,closing=self._clock_requirement(suffix,self.y)
        anchor=saved['anchor'];available=self._remaining_observation(anchor)
        if (closing>anchor['closing_mm_s'] or required>available or
                not self._valid_stop_clock(suffix,self.y)):
            raise RuntimeError('Stored own stop suffix lost its unchanged proof')
        suffix._bf01_fallback_anchor=copy.deepcopy(anchor)
        return suffix

    def _planned_prefix(self,end):
        """Actual own scalar clock jets, including a short ramp's coast tail."""
        finish=end;plan_end=None
        if self.plan is not None:
            plan_end=round(self.plan_start+self.plan.times[-1],3)
            if self.plan_kind in('goal','protective_stop'):finish=min(finish,plan_end)
        cuts={finish}
        if self.plan is not None:
            cuts.update(round(self.plan_start+p['time_s'],3)for p in self.plan.points
                        if self.now<round(self.plan_start+p['time_s'],3)<finish)
            if self.now<plan_end<finish:cuts.add(plan_end)
        points=[local.point(0,0,self.v,self.a)]
        for at in sorted(t for t in cuts if t>self.now+1e-9):
            if self.plan is None:
                dt=at-self.now;state=(self.y+self.v*dt+.5*self.a*dt*dt,self.v+self.a*dt,self.a)
            elif at<=plan_end:
                jet=self.plan.evaluate(round(at-self.plan_start,3))
                state=(self.plan_origin+jet[F[0]][0],jet[F[1]][0],jet[F[2]][0])
            else:
                jet=self.plan.points[-1];dt=at-plan_end
                state=(self.plan_origin+jet[F[0]][0]+jet[F[1]][0]*dt+.5*jet[F[2]][0]*dt*dt,
                       jet[F[1]][0]+jet[F[2]][0]*dt,jet[F[2]][0])
            points.append(local.point(round(at-self.now,3),state[0]-self.y,state[1],state[2]))
        return floor.motion.Curve(points)if len(points)>1 else None

    def _preview_stop(self,end,gap,scan):
        """A whole next prefix plus an exact-PVA end stop; no future scan."""
        if scan is None or end-scan['captured_s']>self.settings['stale_after_s']+1e-9:return None
        prefix=self._planned_prefix(end)
        if prefix is None:return None
        tail=prefix.points[-1];duration=prefix.times[-1]
        if abs(tail[F[1]][0])<1e-8 and abs(tail[F[2]][0])<1e-8:
            combined=prefix
        else:
            probe=copy.copy(self);probe.y=self.y+tail[F[0]][0]
            probe.v=tail[F[1]][0];probe.a=tail[F[2]][0];probe.now=round(self.now+duration,3)
            probe._fallback=None;probe._brake_cache=None;probe._geometry_cache={}
            probe.profile_checks=[]
            selected=[]
            def complete_candidate(stop):
                points=copy.deepcopy(prefix.points)
                points.extend(local.point(round(duration+p['time_s'],3),tail[F[0]][0]+p[F[0]][0],
                    p[F[1]][0],p[F[2]][0])for p in stop.points[1:])
                clock=floor.motion.Curve(points);clock._bf01_origin=self.y
                required,_,_=self._clock_requirement(clock,self.y)
                if required>=min(gap,self._visible_gap())or not self._valid_stop_clock(clock,self.y):return False
                selected.append((stop,clock));return True
            try:stop=probe._checked_brake(strict=True,candidate_ok=complete_candidate)
            except RuntimeError:return None
            if stop is None:return None
            combined=next(clock for candidate,clock in selected if candidate is stop)
            combined._bf01_profile_checks=copy.deepcopy(probe.profile_checks)
        combined._bf01_origin=self.y
        return combined

    def _approve_step(self,clock,end,gap,scan,*,inherited=False):
        """Commit only a complete witness; the old fallback survives failure."""
        if clock is None:return False
        required,cap,closing=self._clock_requirement(clock,self.y)
        if inherited:
            anchor=copy.deepcopy(getattr(clock,'_bf01_fallback_anchor',None))
            if anchor is None:return False
            available=self._remaining_observation(anchor)
            if closing>anchor['closing_mm_s']or required>available:return False
        else:
            if (scan is None or end-scan['captured_s']>self.settings['stale_after_s']+1e-9
                    or gap<=required or self._visible_gap()<required):return False
            anchor={'time_s':self.now,'captured_s':scan['captured_s'],'origin_mm':self.y,
                    'gap_mm':min(gap,self._visible_gap()),'closing_mm_s':closing,'cap_mm_s':cap}
        if not self._valid_stop_clock(clock,self.y):return False
        self.continuation_stop_clock=clock;self.step_end_s=end
        self._step_certificate={'start_s':self.now,'end_s':end,'origin_mm':self.y,
            'state':(self.y,self.v,self.a),'plan':self.plan,'path':self.path,'clock':clock}
        self._fallback={'clock':clock,'start_s':self.now,'origin_mm':self.y,
                        'path':self.path,'anchor':anchor}
        if not inherited:self.profile_checks.extend(getattr(clock,'_bf01_profile_checks',[]))
        return True

    def _goal_plan(self,now):
        if self.v>1e-7 or abs(self.a)>1e-7:raise RuntimeError('A resumed episode must begin at a confirmed stop')
        if self.goal-self.y<1e-5:self.mode='arrived';return
        if self.y<1e-8:
            self.set_plan(self.nominal_clock,now,'driving','goal');return
        # Rejoin a future own nominal phase with matching position, velocity
        # and acceleration. This also permits recovery from inside a corner;
        # it does not request a reversing path or invent a new endpoint stop.
        candidates=[p for p in self.nominal_clock.points if p[F[0]][0]>self.y+5 and p[F[1]][0]>1e-6 and abs(p[F[2]][0])<1e-8]
        for target in candidates:
            distance=target[F[0]][0]-self.y;speed=target[F[1]][0]
            duration=max(.02,distance/self.zone_velocity_cap)
            for _ in range(18):
                duration=math.ceil(duration*1000)/1000
                ramp=floor.motion.Curve([local.point(0,0,0,0),local.point(duration,distance,speed,0)])
                raw=floor.motion.bounds(ramp)
                if raw[F[1]]['min'][0]>=-1e-8 and all(raw[f]['max_abs'][0]<=self.limits[k]*(1+1e-6)for f,k in zip(F[1:],('velocity','acceleration','jerk'))):
                    check=self._quantized_clock(ramp,self.y);valid,bounds=self._admissible(check,self.y)
                    if valid:
                        points=copy.deepcopy(check.points);join=points[-1]['time_s']
                        for node in self.nominal_clock.points:
                            if node['time_s']>target['time_s']+1e-9:
                                points.append(local.point(join+node['time_s']-target['time_s'],node[F[0]][0]-self.y,node[F[1]][0],node[F[2]][0]))
                        self.profile_checks.append({'kind':'resume_rejoin','progress_mm':self.y,'join_progress_mm':target[F[0]][0],'dynamics':bounds})
                        recovered,proof=self._bounded_start_clock(floor.motion.Curve(points),self.y)
                        self.profile_checks.append({'kind':'resume_whole_clock','proof':proof})
                        self.set_plan(recovered,now,'driving','goal');return
                duration*=1.2
        # A terminal suffix without a positive-speed rejoin can be retimed
        # from rest. Only this recovery episode is slowed to satisfy its actual
        # complete path; the ordinary nominal profile stays unchanged.
        distance=self.goal-self.y;raw=floor.motion.Curve(floor.motion.rest_to_rest(distance,self.zone_velocity_cap,self.limits['acceleration']*.98,self.limits['jerk']*.98))
        for iteration in range(30):
            check=self._quantized_clock(raw,self.y);valid,bounds=self._admissible(check,self.y)
            if valid:
                self.profile_checks.append({'kind':'terminal_resume','progress_mm':self.y,'dynamics':bounds})
                self.set_plan(check,now,'driving','goal');return
            factor=1.25
            raw=floor.motion.Curve([local.point(p['time_s']*factor,p[F[0]][0],p[F[1]][0]/factor,p[F[2]][0]/factor**2)for p in raw.points])
        raise RuntimeError('No bounded forward recovery from the confirmed stopped pose')

    def decide(self, now, scan, grant_permits=True, *, step_end_s=None):
        if type(grant_permits) is not bool:
            raise ValueError('Own resource grant must be explicit')
        end=round(now+.05,3)if step_end_s is None else step_end_s
        if (type(end)not in(int,float)or not math.isfinite(end)or not 0<end-now<=.050000001
                or abs(end*1000-round(end*1000))>1e-6 or abs(now-self.now)>1e-8):
            raise ValueError('Own next step must be contiguous, on the 1 ms grid and no longer than 50 ms')
        end=round(end,3);self.step_end_s=end;self.continuation_stop_clock=None;self._step_certificate=None
        initial_mode=self.mode
        candidate=copy.deepcopy(scan)if scan is not None else self.last_scan
        gap,reason=self._observed_gap(candidate,now)
        if scan is not None:self.last_scan=candidate
        stop = self._checked_brake()
        duration = stop.times[-1] if stop else 0
        distance = stop.evaluate(duration)[F[0]][0] if stop else 0
        closing = max(self._zone_cap_at(self.y),self.settings['maximum_obstacle_closing_speed_mm_s'])
        reaction = self.settings['period_s']+self.settings['latency_s']+self.settings['stale_after_s']
        required = self.settings['clearance_mm']+distance+(self._zone_cap_at(self.y)+closing)*reaction+closing*duration
        def launch_requirement():
            launch_speed=self._zone_cap_at(self.y)
            launch=_qualified_scalar_stop(launch_speed,0.,self.limits['acceleration'],self.limits['jerk'],closing)
            if launch is None:raise RuntimeError('Proposed launch has no qualified stopping envelope')
            launch_time=launch['duration_s'];launch_distance=launch['distance_mm']
            return self.settings['clearance_mm']+launch_distance+(launch_speed+closing)*reaction+closing*launch_time
        if initial_mode in('waiting','braking'):required=max(required,launch_requirement())
        obstructed = not grant_permits or gap <= required
        if self.mode == 'arrived':
            return {'mode':self.mode,'reason':'functional_endpoint'}
        def braking_now(why):
            nonlocal stop
            self.clear_since=None;self.reason=why
            if stop is None:
                self.plan=None;self.mode='waiting';return
            stop=self._checked_brake(strict=True)
            inherited=hasattr(stop,'_bf01_fallback_anchor')
            if self.plan_kind!='protective_stop':
                self.set_plan(stop,now,'braking','protective_stop');self.stops+=1
                self.events.append({'time_s':now,'event':'protective_stop','reason':why})
            if not self._approve_step(stop,end,gap,candidate,inherited=inherited):
                raise RuntimeError('No retained or newly proved own stopping fallback for this step')
        if obstructed:
            braking_now(reason if grant_permits else 'resource_wait')
        else:
            if self.clear_since is None:
                self.clear_since = now
            if self.mode == 'waiting' and now-self.clear_since < self.settings['clear_observation_s']:
                self.reason = 'fresh_clear_observation'
            elif self.mode=='braking':
                if stop is None:raise RuntimeError('Moving protective stop lost its retained clock')
                if not self._approve_step(stop,end,gap,candidate,
                        inherited=hasattr(stop,'_bf01_fallback_anchor')):
                    raise RuntimeError('Active protective stop lost its proved suffix')
            else:
                launching=self.mode=='waiting'
                if launching:
                    self._goal_plan(now)
                elif self.plan is None and self.plan_kind=='goal':
                    raise RuntimeError('Driving lost its precompiled own motion clock')
                if self.mode!='arrived':
                    proposed=self._preview_stop(end,gap,candidate)
                    if proposed is not None and self._approve_step(proposed,end,gap,candidate):
                        self.reason='clear_scan'
                        if launching:self.events.append({'time_s':now,'event':'resumed',
                            'clear_observation_s':now-self.clear_since})
                    elif launching:
                        # The proposed goal has not moved. Do not advertise a
                        # resume or discard a previous valid fallback.
                        self.plan=None;self.mode='waiting';self.reason='next_step_stop_unproven'
                    else:braking_now('next_step_stop_unproven')
        if self.mode in('waiting','braking')or initial_mode in('waiting','braking'):
            required=max(required,launch_requirement())
        if self.continuation_stop_clock is not None:
            required=max(required,self._clock_requirement(self.continuation_stop_clock,self.y)[0])
        visible=self._visible_gap();self.perception_audit['checks']+=1
        self.perception_audit['minimum_range_margin_mm']=visible-required if self.perception_audit['minimum_range_margin_mm']is None else min(self.perception_audit['minimum_range_margin_mm'],visible-required)
        self.perception_audit['maximum_required_gap_mm']=max(self.perception_audit['maximum_required_gap_mm'],required)
        return {'mode':self.mode,'reason':self.reason,'scan_age_s':now-self.last_scan['captured_s'] if self.last_scan else None,
                'observed_gap_mm':gap if math.isfinite(gap) else None,'required_gap_mm':required}

    def advance(self, start, end):
        if end <= start or end-start > .050000001 or abs(end*1000-round(end*1000))>1e-6:
            raise ValueError('BF01 uses positive integration steps no larger than 0.05 s')
        if abs(start-self.now)>1e-8:
            raise ValueError('Controller intervals must be contiguous')
        end=round(end,3);certificate=getattr(self,'_step_certificate',None)
        moving=self.plan is not None or abs(self.v)>1e-8 or abs(self.a)>1e-8
        if moving:
            if (certificate is None or certificate['start_s']!=round(start,3)or end>certificate['end_s']
                    or certificate['state']!=(self.y,self.v,self.a)or certificate['plan']is not self.plan
                    or certificate['path']is not self.path):
                raise RuntimeError('Positive own advance requires its unchanged proved step certificate')
            clock=certificate['clock'];origin=certificate['origin_mm'];duration=round(end-start,3)
            for knot in clock.points:
                t=round(start+knot['time_s'],3)
                if start+1e-9<t<end-1e-9:
                    self.y=origin+knot[F[0]][0];self.v=knot[F[1]][0];self.a=knot[F[2]][0]
                    self._record(t)
            jet=clock.evaluate(min(duration,clock.times[-1]))
            self.y=origin+jet[F[0]][0];self.v=jet[F[1]][0];self.a=jet[F[2]][0]
        if self.plan:
            plan_end=round(self.plan_start+self.plan.times[-1],3)
            if end>=plan_end-1e-9:
                kind=self.plan_kind;self.plan=None
                if kind=='goal'or self.goal-self.y<1e-5:
                    self.mode='arrived';self.v=self.a=0
                elif kind=='protective_stop':
                    self.mode='waiting';self.v=self.a=0
                else:
                    # A positive-speed ramp ending between integration ticks
                    # continues coasting over the remainder. Clamping its pose
                    # while retaining velocity would contradict its own PVA.
                    self.mode='driving'
        if self.y>self.goal+1e-5 or self.v < -1e-6:
            raise RuntimeError('Controller left its monotone own route')
        self.now=end;self._step_certificate=None;self._record(end)
        return {'progress_mm':self.y,'velocity_mm_s':self.v,'acceleration_mm_s2':self.a,
                'pose_mm_rad':self.pose(),'mode':self.mode}
