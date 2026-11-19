"""Rigid-frame playback and conservative displacement bounds for native audits."""
import functools
import itertools
import math

import ps01_logistics_motion as model
from h02_arm_pickup import certify, bbox_distance
from h02_native_pose_boxes import transformed

s=model.s


class Program:
    def __init__(self, data, scene):
        s.require(data['format']=='solidcraftbot.ps01-logistics-motion-program/1','Unsupported motion export')
        s.require(data['definition']==model.load() and data.get('compiler_sources_sha256')==model.compiler_pins(),
                  'Exported motion source/compiler pins are stale')
        for direction in ('load','unload'):
            for item in data[direction]['phases'].values():
                actual=model.motion.bounds(item['points'])
                for field,values in actual.items():
                    for key,series in values.items():
                        s.require(len(series)==len(item['joint_bounds'][field][key]) and
                            all(abs(a-b)<=1e-8*(1+abs(a)) for a,b in zip(series,item['joint_bounds'][field][key])),
                            'Exported joint bounds differ from the actual curve')
                caps=s.bound(data['definition']['arm_limits'])['limits']['arm_loaded' if item['loaded'] else 'arm_empty']
                for field,key in zip(model.F[1:],('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')):
                    s.require(max(actual[field]['max_abs'])<=caps[key]*(1+1e-8),'Exported arm motion exceeds its source limits')
        self.data,self.scene=data,scene
        self.link_ids={station:[link['id'] for link in s.robot.expanded(scene.kin(station).arm)['links']] for station in scene.stations}
        self.curves={};self.metadata={};self.links=['L0_Base']
        self.definition={'continuous_audit':{'numeric_guard_mm':1e-5,'max_depth':18},
            'support_plane':{'origin_mm':[-1000,-1600,0],'size_mm':[5000,3300,1]},
            'clearance_mm':{'self':.1,'environment':.1,'arm_tool':.1,'seating_contact':-.002}}
        for direction in ('load','unload'):
            move=data[direction]
            for phase in ('approach','close','carried','release','withdraw'):
                name=direction+'.'+phase
                source=move['jaw_motion'] if phase in ('close','release') else move['phases'][phase]
                self.curves[name]=model.motion.Curve(source['points'])
                self.metadata[name]=(direction,phase)
            if direction=='load':
                self.curves['travel']=model.motion.Curve(data['travel']['points']);self.metadata['travel']=('travel','travel')
        self.cid=data['load']['carrier_id']
        self.park_q={identity:model.upright_ik(scene.kin(identity),scene.park(identity),scene.arms[identity+'.PS01TransferArm']['joints_deg']) for identity in scene.stations}

    @functools.lru_cache(maxsize=8192)
    def state(self, phase, u):
        direction,part=self.metadata[phase];scene=self.scene
        joints={key:value[:] for key,value in self.park_q.items()};gaps={key:scene.hp['open_gap'] for key in scene.stations}
        vehicle=scene.car_frame(self.data['load']['station'] if direction=='load' else self.data['unload']['station'])
        frame=scene.initial_placements[self.cid]
        if direction=='travel':
            distance=self.curves[phase].evaluate(u*self.curves[phase].times[-1])[model.F[0]][0]
            route=self.data['travel'];a,b=route['from_xy_mm'],route['to_xy_mm'];length=math.dist(a,b)
            vehicle=s.workspace.pose([a[0]+(b[0]-a[0])*distance/length,a[1]+(b[1]-a[1])*distance/length,0],0)
            frame=s.robot.multiply(vehicle,s.workspace.pose(scene.car_surface,0))
        else:
            move=self.data[direction];identity=move['station'];kin=scene.kin(identity)
            if part in ('close','release'):
                key='approach' if part=='close' else 'carried'
                joints[identity]=[math.degrees(v) for v in move['phases'][key]['points'][-1][model.F[0]]]
                value=self.curves[phase].evaluate(u*self.curves[phase].times[-1])[model.F[0]][0]
                gaps[identity]=scene.hp['open_gap']-value if part=='close' else scene.hp['carrier_d']+value
            else:
                joints[identity]=[math.degrees(v) for v in self.curves[phase].evaluate(u*self.curves[phase].times[-1])[model.F[0]]]
                gaps[identity]=scene.hp['carrier_d'] if part=='carried' else scene.hp['open_gap']
            if part=='carried':
                frame=s.robot.multiply(kin.tool(joints[identity]),move['attachment'])
            else:
                frame=move['target_frame'] if part in ('release','withdraw') else move['source_frame']
        return {'joints':joints,'gaps':gaps,'vehicle':vehicle,'cargo':frame,'cover_on':direction=='travel'}

    def matrix(self, record, phase, u):
        st=self.state(phase,u);kind=record['kind']
        if record['source_body']=='LT01TransportCover' and not st['cover_on']:
            # The fixture person removes the cover before arm access. Its
            # manual relocation is not presented as an automated motion.
            return s.workspace.pose([-750,-1100,0],0)
        if kind=='arm' and record.get('station'):
            return self.arm_frames(record['station'],phase,u)[record['link']]
        if kind=='tool':
            identity=record['station'];base=self.tool_frame(identity,phase,u)
            shift=record.get('jaw_sign',0)*(st['gaps'][identity]-self.scene.hp['open_gap'])/2
            return s.robot.multiply(base,s.workspace.pose([shift,0,0],0))
        if kind=='sample':
            return st['cargo']
        if kind=='vehicle':
            return st['vehicle']
        return record['matrix']

    @functools.lru_cache(maxsize=16384)
    def arm_frames(self,station,phase,u):
        return self.scene.kin(station).forward(self.state(phase,u)['joints'][station])

    @functools.lru_cache(maxsize=16384)
    def tool_frame(self,station,phase,u):
        kin=self.scene.kin(station)
        base=self.arm_frames(station,phase,u)[kin.arm['flange_reference']['link']]
        return s.robot.multiply(base,s.workspace.pose([kin.flange[0],kin.flange[1],kin.flange[2]+kin.length],0))

    @functools.lru_cache(maxsize=8192)
    def ranges(self,phase,a,b):
        curve=self.curves[phase]
        return model.motion.bounds(model.validation._slice(curve,a*curve.times[-1],b*curve.times[-1]))[model.F[0]]

    def delta(self,phase,a,b,record):
        direction,part=self.metadata[phase];kind=record['kind'];mid=self.state(phase,(a+b)/2)
        if kind not in ('arm','tool','sample','vehicle'):
            return 0.
        if record['source_body']=='LT01TransportCover' and direction!='travel':return 0.
        if direction=='travel':
            if kind not in ('sample','vehicle'):
                return 0.
            v=self.curves[phase].evaluate((a+b)/2*self.curves[phase].times[-1])[model.F[0]][0];r=self.ranges(phase,a,b)
            return max(abs(r['min'][0]-v),abs(r['max'][0]-v))+1e-8
        move=self.data[direction];identity=move['station']
        if kind=='vehicle' or kind in ('arm','tool') and record.get('station')!=identity:
            return 0.
        if part in ('close','release'):
            if kind!='tool' or not record.get('jaw_sign'):
                return 0.
            r=self.ranges(phase,a,b);v=self.curves[phase].evaluate((a+b)/2*self.curves[phase].times[-1])[model.F[0]][0]
            return max(abs(r['min'][0]-v),abs(r['max'][0]-v))/2+1e-8
        if kind=='sample' and part!='carried':
            return 0.
        kin=self.scene.kin(identity);r=self.ranges(phase,a,b)
        angular=[max(abs(lo-math.radians(v)),abs(hi-math.radians(v))) for lo,hi,v in zip(r['min'],r['max'],mid['joints'][identity])]
        origins=[[f[i][3] for i in range(3)] for f in kin.frames]
        box=record['local_bbox'];corners=list(itertools.product(*zip(box['min'],box['max'])))
        if kind=='arm':
            links=self.link_ids[identity];index=links.index(record['link'])
            if index==0:
                return 0.
            radius=max(math.dist(c,origins[index-1]) for c in corners);total=0.
            for j in range(index-1,-1,-1):
                if j<index-1:
                    radius+=math.dist(origins[j],origins[j+1])
                total+=radius*min(2,angular[j])
            return total+1e-8
        # Full carried/tool envelope through every upstream joint. The triangle
        # inequality intentionally overbounds rather than sampling extrema.
        radius=sum(math.dist(a,b) for a,b in zip(origins,origins[1:]))+math.dist(origins[-1],kin.flange)+kin.length
        radius+=max(math.dist(c,[0,0,0]) for c in corners)+self.scene.hp['foot_h']
        return sum(radius*min(2,v) for v in angular)+1e-8

    def collision_pairs(self,records):
        self.records={r['id']:r for r in records}
        pairs=[];exclusions=[];links=next(iter(self.link_ids.values()))
        for i,a in enumerate(records):
            for b in records[i+1:]:
                ak,bk=a['kind'],b['kind'];reason=None;category='environment'
                moving={'arm','tool','sample','vehicle'}
                if ak not in moving and bk not in moving:
                    continue
                if a['group']==b['group'] and ak==bk and ak in ('sample','vehicle','tool'):
                    if ak=='vehicle' and any(r['source_body'].startswith('LT01') for r in (a,b)):
                        # New nest/cover against the retained TR01 structure and
                        # occupied neighboring bay. Support contacts may touch,
                        # but native positive-volume interference is forbidden.
                        category='seating_contact'
                    else:continue
                if ak==bk=='arm' and a.get('station')==b.get('station'):
                    distance=abs(links.index(a['link'])-links.index(b['link']))
                    if distance<=1:
                        reason='same/adjacent arm construction interface'
                    else:
                        category='self'
                arm=a if ak=='arm' else b if bk=='arm' else None
                other=b if arm is a else a
                if arm and not reason:
                    if other['kind']=='tool' and other['station']==arm['station'] and arm['link']==links[-1]:
                        reason='own flange/tool mounting interface'
                    elif other['group']==arm['station']+'.Bench' and arm['link']==links[0]:
                        reason='own base/worktop mounting interface'
                sample=a if ak=='sample' else b if bk=='sample' else None
                other=b if sample is a else a
                if sample:
                    if sample['source_body'].startswith('Foot') and (other['source_body'] in ('Dock','LT01ReceiverBase') or other['source_body'].startswith('Pad_')):
                        category='seating_contact'
                    if sample['source_body']=='Base' and other['kind']=='tool' and other.get('jaw_sign'):
                        category='seating_contact'
                if reason:
                    exclusions.append({'a':a['id'],'b':b['id'],'reason':reason})
                else:
                    pairs.append({'a':a['id'],'b':b['id'],'category':category,'required_mm':self.definition['clearance_mm'][category]})
        return pairs,exclusions

    def pair_bound(self,pair,phase,a,b,frame):
        fixed=self.relative_fixed(pair,phase,a,b)
        if not fixed:
            swept=self.translation_sweep_bound(pair,phase,a,b,frame)
            if swept is not None:return swept
        excursion=0. if fixed else self.relative_excursion(pair,phase,a,b)
        if excursion is None:return None
        lower=bbox_distance(frame['boxes'][pair['a']],frame['boxes'][pair['b']])
        distance=lower if lower>pair['required_mm']+excursion+.01 else frame['distance'](pair['a'],pair['b'])
        return distance-excursion-self.definition['continuous_audit']['numeric_guard_mm']

    def translation_sweep_bound(self,pair,phase,a,b,frame):
        """Native boxes swept along the actual one-dimensional translation.

        Jaw sliding preserves the support plane, and straight TR01 travel
        preserves corridor-side separation. A radial displacement ball would
        lose those separating planes and could never certify sliding contact.
        """
        direction,part=self.metadata[phase]
        if part not in ('close','release','travel'):return None
        mid=(a+b)/2;curve=self.curves[phase]
        value=curve.evaluate(mid*curve.times[-1])[model.F[0]][0];ranges=self.ranges(phase,a,b)
        def swept(record):
            vector=[0.,0.,0.]
            if part=='travel' and record['kind'] in ('vehicle','sample'):
                route=self.data['travel'];start,end=route['from_xy_mm'],route['to_xy_mm'];length=math.dist(start,end)
                vector=[(end[0]-start[0])/length,(end[1]-start[1])/length,0.]
            elif part in ('close','release') and record['kind']=='tool' and record['station']==self.data[direction]['station']:
                pose=self.tool_frame(record['station'],phase,mid)
                gain=record.get('jaw_sign',0)*(-1 if part=='close' else 1)/2
                vector=[pose[i][0]*gain for i in range(3)]
            box=frame['boxes'][record['id']]
            shifts=[[v*(ranges[edge][0]-value) for edge in ('min','max')] for v in vector]
            return {'min':[box['min'][i]+min(shifts[i]) for i in range(3)],
                    'max':[box['max'][i]+max(shifts[i]) for i in range(3)]}
        x,y=(swept(self.records[pair[k]]) for k in ('a','b'))
        plane=max(v for i in range(3) for v in (x['min'][i]-y['max'][i],y['min'][i]-x['max'][i]))
        guard=self.definition['continuous_audit']['numeric_guard_mm']+2*frame['fk_error_mm']
        if plane>=0:return bbox_distance(x,y)-guard
        if pair['category']=='seating_contact' and plane>=-1e-7:
            frame['distance'](pair['a'],pair['b']) # native overlap check at the witness pose
            return plane-guard
        return None

    def relative_excursion(self,pair,phase,a,b):
        """Cancel a common upstream rigid transform, then bound only its suffix.

        Distances are invariant under a shared rigid rotation/translation. This
        is the same serial-chain triangle bound as delta(), evaluated in the
        earlier link's frame; no sampled clearance is promoted to a proof.
        """
        direction,part=self.metadata[phase]
        if part not in ('approach','carried','withdraw'):return None
        x,y=(self.records[pair[k]] for k in ('a','b'))
        identity=self.data[direction]['station']
        if x['kind']!= 'arm':x,y=y,x
        if x['kind']!='arm' or x.get('station')!=identity:return None
        kin=self.scene.kin(identity);links=self.link_ids[identity]
        first=links.index(x['link'])
        if y['kind']=='arm' and y.get('station')==identity:
            last=links.index(y['link'])
            if first>last:x,y=y,x;first,last=last,first
            corners=list(itertools.product(*zip(y['local_bbox']['min'],y['local_bbox']['max'])))
        elif y['kind']=='tool' and y['station']==identity or y['kind']=='sample' and part=='carried':
            last=6;offset=[kin.flange[0],kin.flange[1],kin.flange[2]+kin.length]
            corners=list(itertools.product(*zip(y['local_bbox']['min'],y['local_bbox']['max'])))
            if y['kind']=='sample':
                corners=[s.robot.transform(self.data[direction]['attachment'],p) for p in corners]
            else:
                gap=self.state(phase,(a+b)/2)['gaps'][identity]
                shift=y.get('jaw_sign',0)*(gap-self.scene.hp['open_gap'])/2
                corners=[[p[0]+shift,p[1],p[2]] for p in corners]
            corners=[[p[i]+offset[i] for i in range(3)] for p in corners]
        else:return None
        if first==last:return 0.
        ranges=self.ranges(phase,a,b);q=self.state(phase,(a+b)/2)['joints'][identity]
        angular=[max(abs(lo-math.radians(v)),abs(hi-math.radians(v))) for lo,hi,v in zip(ranges['min'],ranges['max'],q)]
        origins=[[f[i][3] for i in range(3)] for f in kin.frames]
        radius=max(math.dist(p,origins[last-1]) for p in corners);total=0.
        for j in range(last-1,first-1,-1):
            if j<last-1:radius+=math.dist(origins[j],origins[j+1])
            total+=radius*min(2.,angular[j])
        return total+1e-8

    def relative_fixed(self,pair,phase,a,b):
        x,y=(self.records[pair[k]] for k in ('a','b'))
        if not self.moving(x,phase) and not self.moving(y,phase):return True
        direction,part=self.metadata[phase];kinds={x['kind'],y['kind']}
        if direction=='travel' and kinds<={'sample','vehicle'}:return True
        if part=='carried' and kinds=={'sample','tool'}:
            tool=x if x['kind']=='tool' else y
            return tool['station']==self.data[direction]['station']
        return False

    def moving(self,record,phase):
        direction,part=self.metadata[phase];kind=record['kind']
        if direction=='travel':return kind in ('sample','vehicle')
        if kind=='sample':return part=='carried'
        if kind not in ('arm','tool') or record.get('station')!=self.data[direction]['station']:return False
        if part in ('close','release'):return kind=='tool' and bool(record.get('jaw_sign'))
        return kind!='arm' or record['link']!='L0_Base'
