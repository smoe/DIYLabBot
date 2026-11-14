"""Exact vertical IK branch and conservative continuous rigid-link bounds."""
import itertools
import json
import math
from pathlib import Path
import sys
import assembly_model as assembly
import robot_spec as robot
import h02_direct_pickup as local
import centrifuge_robot_pickup as pickup
import sample_motion as sm

ROOT=robot.ROOT
SOURCE=ROOT/'model/h02-arm-pickup.scene.json'
SCHEMA=ROOT/'model/h02-arm-pickup.schema.json'
motion=local.motion
I=sm.Interval
J=sm.Jet


def validate(s):
    if set(s)!=set(json.loads(SCHEMA.read_text())['properties']) or s['units']!={'length':'mm','angle':'deg','time':'s'}:
        raise ValueError('Explicit typed arm-pickup fields required')
    if s['format']!='solidcraftbot.h02-arm-pickup/1' or s['branch']!='planar_positive_elbow':raise ValueError('Unsupported arm pickup')
    for ref in s['sources'].values():assembly.validate_reference(ref)
    if s['arm_fixture']['yaw_deg']!=0 or s['arm_fixture']['position_mm'][0]!=0 or s['arm_fixture']['position_mm'][1]>=0 or s['arm_fixture']['position_mm'][2]!=0:
        raise ValueError('This analytic branch requires a level base behind the origin on -Y')
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in s['clearance_mm'].values()):raise ValueError('Positive clearance margins required')
    audit=s['continuous_audit']
    if type(audit['max_depth']) is not int or not 1<=audit['max_depth']<=20 or not math.isfinite(audit['numeric_guard_mm']) or audit['numeric_guard_mm']<=0:
        raise ValueError('Finite continuous audit budget and guard required')
    return s


def load():return validate(json.loads(SOURCE.read_text()))


def interval(value):return value if isinstance(value,I) else I(value)


def unary(x,f,f1,f2,f3):
    x=J.lift(x);a,v,b,c=x.d
    return J(f(a),f1(a)*v,f1(a)*b+f2(a)*v*v,f1(a)*c+3*f2(a)*v*b+f3(a)*v*v*v)


def power(x,n):
    if isinstance(x,I):
        if n==0:return I(1)
        if n<0:
            if x.lo<=0<=x.hi:raise ValueError('Singular interval')
            return power(I(math.nextafter(1/x.hi,-math.inf),math.nextafter(1/x.lo,math.inf)),-n)
        # Preserve even-power nonnegativity rather than multiplying dependent ranges.
        values=[x.lo**n,x.hi**n];lo=0 if n%2==0 and x.lo<=0<=x.hi else min(values)
        return I(math.nextafter(lo,-math.inf) if lo else 0,math.nextafter(max(values),math.inf))
    return x**n


def sqrt(x):
    if isinstance(x,I):
        if x.lo<=0:raise ValueError('Nonpositive square-root interval')
        return I(math.nextafter(math.sqrt(x.lo),-math.inf),math.nextafter(math.sqrt(x.hi),math.inf))
    return math.sqrt(x)


def atan(x):
    if isinstance(x,I):return I(math.nextafter(math.atan(x.lo),-math.inf),math.nextafter(math.atan(x.hi),math.inf))
    return math.atan(x)


def acos(x):
    if isinstance(x,I):
        if x.lo<=-1 or x.hi>=1:raise ValueError('IK singularity or unreachable interval')
        return I(math.nextafter(math.acos(x.hi),-math.inf),math.nextafter(math.acos(x.lo),math.inf))
    return math.acos(x)


def reciprocal(x):return unary(x,lambda a:power(a,-1),lambda a:-power(a,-2),lambda a:2*power(a,-3),lambda a:-6*power(a,-4))
def jsqrt(x):return unary(x,sqrt,lambda a:.5*power(sqrt(a),-1),lambda a:-.25*power(sqrt(a),-3),lambda a:.375*power(sqrt(a),-5))
def jatan(x):return unary(x,atan,lambda a:power(1+a*a,-1),lambda a:-2*a*power(1+a*a,-2),lambda a:(6*a*a-2)*power(1+a*a,-3))
def jacos(x):return unary(x,acos,lambda a:-power(sqrt(1-a*a),-1),lambda a:-a*power(sqrt(1-a*a),-3),lambda a:-(1+2*a*a)*power(sqrt(1-a*a),-5))


class Program:
    def __init__(self,definition=None):
        self.definition=validate(definition) if definition is not None else load();s=self.definition
        self.local_scene=local.load(assembly.validate_reference(s['sources']['pickup']))
        self.arm=robot.load(assembly.validate_reference(s['sources']['robot']))
        self.spec=local.context(self.local_scene,'V15');self.p=local.parameters(self.spec)
        self.kin=pickup.Kinematics(self.arm,{'arm_fixture':s['arm_fixture'],'gripper':self.spec['grip']['gripper']})
        self.frames=self.kin.frames;origins=[[f[i][3] for i in range(3)] for f in self.frames]
        self.origins=origins;self.links=[v['id'] for v in self.arm['links']]
        expected_axes=[[0,0,1],[0,1,0],[0,1,0],[0,0,1],[0,1,0],[0,0,1]]
        expected_x=[[1,0,0],[0,0,-1],[0,0,-1],[0,1,0],[0,0,-1],[0,1,0]]
        if any(j['frame']['axis']!=a or j['frame']['x']!=x for j,a,x in zip(self.arm['joints'],expected_axes,expected_x)) or any(o[0]!=0 for o in origins) or self.kin.flange[:2]!=[0,0]:
            raise ValueError('Arm frames are not supported by the derived planar branch')
        self.upper=origins[2][2]-origins[1][2];self.fore=origins[4][2]-origins[2][2]
        self.end=self.kin.flange[2]+self.kin.length-origins[4][2]
        self.radial=-s['arm_fixture']['position_mm'][1];self.shoulder=origins[1][2]
        if min(self.upper,self.fore,self.end)<=0:raise ValueError('Positive source-derived link dimensions required')
        self.z0=self.local_scene['grasp_z_mm'];self.travel=self.local_scene['travel_mm'];self.duration=self.local_scene['duration_s']
        self.limits=json.loads(assembly.validate_reference(s['sources']['motion_limits']).read_text())['limits']
        self.curves={}
        for phase,ends in [('approach',(self.z0+self.travel,self.z0)),('closure',(self.p['jaw_travel'],0)),('extraction',(self.z0,self.z0+self.travel))]:
            self.curves[phase]=motion.Curve([{'time_s':t,'positions_rad':[v],'velocities_rad_s':[0.],'accelerations_rad_s2':[0.]}
                for t,v in zip([0.,self.duration],ends)])

    def angles(self,z):
        """Solve from the existing joint-frame origins, not copied arm lengths.

        R=U*sin(q2)+F*sin(q2+q3), W=U*cos(q2)+F*cos(q2+q3).
        q1=90°, q4=0°, q6=-90°, q5=180°-q2-q3 fixes Rx(180°).
        """
        z=J.lift(z);w=z-self.shoulder+self.end
        if isinstance(w.d[0],I):
            if w.d[0].lo<=0:raise ValueError('Planar branch requires positive W throughout')
        elif w.d[0]<=0:raise ValueError('Planar branch requires positive W')
        c=(self.radial**2+w*w-self.upper**2-self.fore**2)*(1/(2*self.upper*self.fore))
        elbow=jacos(c);sine=jsqrt(1-c*c)
        shoulder=jatan(self.radial*reciprocal(w))-jatan(self.fore*sine*reciprocal(self.upper+self.fore*c))
        return [J(math.pi/2),shoulder,elbow,J(0),math.pi-shoulder-elbow,J(-math.pi/2)]

    def state(self,phase,u):
        scalar=motion.evaluate(self.curves[phase],u*self.duration)
        v=[scalar[f][0] for f in motion.FIELDS]
        z=J(self.z0) if phase=='closure' else J(*v)
        q=self.angles(z);qdeg=[math.degrees(a.d[0]) for a in q]
        gap=v[0] if phase=='closure' else self.p['jaw_travel'] if phase=='approach' else 0.
        coordinates={'ToolZ':z.d[0]-self.z0,'TubeZ':z.d[0]-self.z0 if phase=='extraction' else 0.,'JawLeft':gap,'JawRight':gap}
        return {'phase':phase,'u':u,'joints_deg':qdeg,'coordinates':coordinates,'tool_z_mm':z.d[0],
                'joint_state':{f:[a.d[n] for a in q] for n,f in enumerate(motion.FIELDS)}}

    def ranges(self,phase,a,b):
        curve=self.curves[phase];h=self.duration;coeff=curve.segments[0][0]
        jets=[sm._polynomial_interval(motion.derivative(coeff,n),a,b,h**n) for n in range(4)]
        z=J(I(self.z0)) if phase=='closure' else J(*jets)
        return self.angles(z),jets[0]

    def audit(self):
        phases=[]
        for phase in self.curves:
            maxima=[0.]*3;lo=[math.inf]*6;hi=[-math.inf]*6
            for n in range(64):
                q,_=self.ranges(phase,n/64,(n+1)/64)
                for i,jet in enumerate(q):
                    x=interval(jet.d[0]);lo[i]=min(lo[i],x.lo);hi[i]=max(hi[i],x.hi)
                    for order in range(1,4):
                        x=interval(jet.d[order]);maxima[order-1]=max(maxima[order-1],abs(x.lo),abs(x.hi))
            caps=self.limits['arm_loaded' if phase=='extraction' else 'arm_empty'];names=['velocity_rad_s','acceleration_rad_s2','jerk_rad_s3']
            if any(v>caps[name] for v,name in zip(maxima,names)):raise ValueError('Continuous joint derivative limit exceeded')
            if any(math.degrees(a)<j['limits_deg'][0] or math.degrees(b)>j['limits_deg'][1] for a,b,j in zip(lo,hi,self.arm['joints'])):
                raise ValueError('Continuous joint-position limit exceeded')
            errors=[]
            for n in range(65):
                state=self.state(phase,n/64);target=pickup.tool_target([0,0,state['tool_z_mm']],0)
                errors.append(max(abs(v) for v in self.kin.residual(state['joints_deg'],target)))
            if max(errors)>1e-7:raise ValueError('Derived analytic branch disagrees with shared FK')
            phases.append({'phase':phase,'joint_ranges_deg':[[math.degrees(a),math.degrees(b)] for a,b in zip(lo,hi)],
                'maximum_joint_derivatives':dict(zip(names,maxima)),'limits':caps,'maximum_FK_residual':max(errors),
                'reachability':'positive-elbow analytic branch, strict acos domain over every interval',
                'continuous':True,'interior_stops':0 if phase!='closure' else None,
                'no_stop_reason':'|dz/du| = travel*30*u^2*(1-u)^2 > 0 and dq3/dz = -W/(U*F*sin(q3)) != 0 in the interior' if phase!='closure' else 'Required grasp-closing operation'})
        return {'passed':True,'phases':phases,'arm_overrides':{},'local_profile':local.motion_profile(self.spec,self.p),
                'numeric_scope':'Conservative binary64 interval enclosures, not a formal floating-point certificate'}

    def delta(self,phase,a,b,record):
        """Every point in a native body remains within this radius of midpoint.

        Telescoping rotation changes gives sum(R_j*|dq_j|). Each R_j is
        bounded by source frame-to-frame lengths plus the farthest native
        construction-box corner from the last joint origin. No endpoint-only
        or mesh-step approximation is used.
        """
        middle=self.state(phase,(a+b)/2);q,z=self.ranges(phase,a,b)
        if record['kind']=='arm':
            i=self.links.index(record['group'])
            if i==0:return 0.
            last=self.origins[i-1];radius=max(math.dist(c,last) for c in itertools.product(*zip(record['local_bbox']['min'],record['local_bbox']['max'])))
            result=0.
            for j in range(i-1,-1,-1):
                if j<i-1:radius+=math.dist(self.origins[j],self.origins[j+1])
                bound=interval(q[j].d[0]);mid=math.radians(middle['joints_deg'][j])
                result+=radius*min(2,max(abs(bound.lo-mid),abs(bound.hi-mid)))
            return result+1e-7
        if record['kind'] in ('tool','sample'):
            if phase=='closure':
                return max(abs(z.lo-middle['coordinates']['JawLeft']),abs(z.hi-middle['coordinates']['JawLeft'])) if record['group'] in ('FingerLeft','FingerRight') else 0.
            if record['kind']=='sample' and phase!='extraction':return 0.
            return max(abs(z.lo-middle['tool_z_mm']),abs(z.hi-middle['tool_z_mm']))+1e-7
        return 0.


def collision_pairs(program,records):
    pairs=[];excluded=[];d=program.definition['clearance_mm']
    for index,a in enumerate(records):
        for b in records[index+1:]:
            ak,bk=a['kind'],b['kind'];category=None
            if ak==bk=='arm':
                distance=abs(program.links.index(a['group'])-program.links.index(b['group']))
                if distance<=1:reason='same rigid link' if distance==0 else 'adjacent assembly interface'
                else:category='self'
            elif 'arm' in (ak,bk):
                arm=a if ak=='arm' else b;other=b if arm is a else a
                if other['kind']=='tool':
                    if arm['group']==program.links[-1]:reason='flange/tool mounting interface'
                    else:category='arm_tool'
                elif other['kind']=='bench' and arm['group']==program.links[0]:reason='base/support mounting interface'
                else:category='environment'
            elif (ak in ('tool','sample') and bk in ('bench','control')) or (bk in ('tool','sample') and ak in ('bench','control')):category='environment'
            else:continue  # Local tool/holder/tube scopes use the existing full swept audit.
            if category:pairs.append({'a':a['id'],'b':b['id'],'category':category,'required_mm':d[category]})
            else:excluded.append({'a':a['id'],'b':b['id'],'reason':reason})
    return pairs,excluded


def bbox_distance(a,b):return math.sqrt(sum(max(0,a['min'][i]-b['max'][i],b['min'][i]-a['max'][i])**2 for i in range(3)))


def probes(program):
    result=[]
    for i,link in enumerate(program.links):
        origin=program.origins[i-1] if i else [0,0,0]
        for axis in range(4):
            point=origin[:]
            if axis:point[axis-1]+=10
            result.append({'id':'FK_'+str(i)+'_'+str(axis),'group':link,'point':point})
    result.append({'id':'FK_TCP','group':program.links[-1],
                   'point':[0,0,program.kin.flange[2]+program.kin.length]})
    return result


def probe_error(program,state,centers,records=()):
    frames=program.kin.forward(state['joints_deg']);errors=[]
    for item in probes(program):
        expected=robot.transform(frames[item['group']],item['point'])
        errors.append(math.dist(expected,centers[item['id']]))
    for record in records:
        if record['kind']!='arm':continue
        index=program.links.index(record['group']);origin=program.origins[index-1] if index else [0,0,0]
        actual=centers['FK_'+str(index)+'_0'];expected=robot.transform(frames[record['group']],origin)
        error0=math.dist(actual,expected);column_errors=[]
        for axis in range(3):
            v=origin[:];v[axis]+=10;target=robot.transform(frames[record['group']],v)
            observed=centers['FK_'+str(index)+'_'+str(axis+1)]
            column_errors.append(math.sqrt(sum(((observed[k]-actual[k])-(target[k]-expected[k]))**2 for k in range(3)))/10)
        radius=[max(abs(record['local_bbox'][edge][i]-origin[i]) for edge in ['min','max']) for i in range(3)]
        errors.append(error0+sum(a*b for a,b in zip(radius,column_errors)))
    expected=[0,0,state['tool_z_mm']+program.kin.length-3]
    errors.append(math.dist(expected,centers['ToolMount']))
    return max(errors)


def certify(program,records,provider):
    """Provider returns actual native BReps/boxes/distances at requested poses."""
    pairs,excluded=collision_pairs(program,records);lookup={r['id']:r for r in records};accepted=[];failures=[];poses=0
    guard=program.definition['continuous_audit']['numeric_guard_mm'];maximum=program.definition['continuous_audit']['max_depth']
    pending=[(phase,0.,1.,0) for phase in program.curves]
    while pending:
        requests=[(phase,(a+b)/2,b-a) for phase,a,b,depth in pending]
        snapshots=provider(requests);poses+=len(requests);following=[]
        if len(snapshots)!=len(requests):raise ValueError('Incomplete native frame batch')
        for (phase,a,b,depth),frame in zip(pending,snapshots):
            if set(frame['boxes'])!=set(lookup):raise ValueError('Incomplete native body set')
            if not math.isfinite(frame['fk_error_mm']) or frame['fk_error_mm']>1e-5:raise ValueError('Native TCP/frame disagrees with source IK')
            for box in frame['boxes'].values():
                if any(not math.isfinite(v) for edge in ['min','max'] for v in box[edge]) or any(a>b for a,b in zip(box['min'],box['max'])):
                    raise ValueError('Invalid native bounds')
            delta={r['id']:program.delta(phase,a,b,r) for r in records};minimum=math.inf;categories={};unresolved=[];hit=[]
            plane=program.definition['support_plane'];origin=plane['origin_mm'];size=plane['size_mm']
            for record in records:
                if record['kind'] not in ('arm','tool','sample') or record['group']==program.links[0]:continue
                bounds=frame['boxes'][record['id']];radius=delta[record['id']]+guard
                if any(bounds['min'][i]-radius<origin[i] or bounds['max'][i]+radius>origin[i]+size[i] for i in [0,1]):
                    unresolved.append({'body':record['id'],'reason':'support-plane XY witness does not enclose continuous body bounds'})
            for pair in pairs:
                x,y=pair['a'],pair['b'];excursion=delta[x]+delta[y]+guard+2*frame['fk_error_mm']
                lower=max(0,bbox_distance(frame['boxes'][x],frame['boxes'][y])-guard)
                if lower-excursion>=pair['required_mm']:distance=lower;method='native_bbox'
                else:distance=frame['distance'](x,y);method='native_distance'
                if not math.isfinite(distance) or distance<0:raise ValueError('Invalid native distance')
                bound=distance-excursion-pair['required_mm'];minimum=min(minimum,bound)
                categories[pair['category']]=min(categories.get(pair['category'],math.inf),distance-excursion)
                if distance+1e-7<pair['required_mm'] and not frame.get('coarse_lower_bounds_only',False):hit.append({**pair,'distance_mm':distance})
                elif bound<0:unresolved.append({**pair,'distance_mm':distance,'motion_radius_mm':excursion})
            if hit:failures.append({'phase':phase,'u':(a+b)/2,'collisions_or_margin_failures':hit})
            elif unresolved:
                if depth>=maximum:failures.append({'phase':phase,'interval':[a,b],'unresolved':unresolved})
                else:following.extend([(phase,a,(a+b)/2,depth+1),(phase,(a+b)/2,b,depth+1)])
            else:accepted.append({'phase':phase,'interval':[a,b],'depth':depth,'minimum_margin_beyond_required_mm':minimum,
                                  'minimum_clearance_lower_bound_mm':categories})
        if failures:break
        pending=following
    return {'passed':not failures,'continuous_intervals':accepted,'failures':failures,'native_pose_count':poses,
        'pair_count':len(pairs),'exclusions':excluded,'maximum_depth':max((v['depth'] for v in accepted),default=0),
        'method':'Native distances minus conservative per-body all-point joint-motion bounds; unresolved intervals fail closed',
        'formal_floating_point_certificate':False}
