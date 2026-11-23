"""Canonical BF01 runtime and exported-program support/geometry boundary.

Static certificates are shared only for immutable source geometry. Port
permission always carries its own numeric compiled lift timeline and grant.
An attached vehicle has a separate rigid cabin-floor support invariant; that
invariant grants no permission to cross a closed or off-floor port.
"""
import copy
import json
import math
from pathlib import Path

import building_fleet_clearance as clearance
import building_fleet_model as model
import building_fleet_support as support
from building_fleet_lift_geometry import PortSupportContext
from building_fleet_lift_checks import posed_mesh, source_surface_contract
from check_building_fleet_freecad import timeline_from_manifest
import tr01_floor_motion as floor


class GeometryChecks:
    def __init__(self, source, navigation):
        self.source=model.validate(copy.deepcopy(source));self.nav=navigation
        if navigation.config!=self.source:raise ValueError('Source-matched navigation required')
        self.base={};self.variants={};self.results=[]

    def certificate(self, level, own_waiting_slot=None, context=None):
        if context is not None and(not isinstance(context,PortSupportContext)or context.level!=level or context.source!=self.source):
            raise ValueError('Only a source-matched typed port context may remove the semantic shaft mask')
        if level not in self.base:
            self.base[level]=clearance.ClearanceCertificate(self.nav.mesh,level,self.source,
                checked_navigation=self.nav)
        key=(level,own_waiting_slot,context is not None)
        if key not in self.variants:
            cert=copy.copy(self.base[level]);cert.obstacles=[];cert.obstacle_names=[]
            for poly,name in zip(self.base[level].obstacles,self.base[level].obstacle_names):
                if name=='ExcludedArea.LiftCore'and context is not None:continue
                cert.obstacles.append(poly);cert.obstacle_names.append(name)
            for slot,polygon in enumerate(self.nav.waiting_bay_polygons[level]):
                if slot==own_waiting_slot:continue
                cert.obstacles.append(polygon);cert.obstacle_names.append('ReservedLiftWaitingBay.'+level+'.'+str(slot))
            cert.obstacle_index=clearance.PolygonIndex(cert.obstacles)
            cert.obstacle_ids={id(poly):i for i,poly in enumerate(cert.obstacles)}
            self.variants[key]=cert
        cert=copy.copy(self.variants[key]);cert.lift_context=context
        return cert

    def own_slot(self, grants, level, *, allow_arrival=False):
        grant=grants.get('waiting_place',{})if isinstance(grants,dict)else{}
        if grant.get('status')!='granted'or grant.get('level')!=level:return None
        if grant.get('role')not in('start','destination'):
            raise ValueError('A conditional or unknown waiting role grants no physical bay access')
        if grant['role']=='destination'and not allow_arrival:
            raise ValueError('An arrival bay is accessible only during its allocated alighting curve')
        slot=grant.get('slot')
        if type(slot)is not int or not 0<=slot<len(self.nav.waits[level]):raise ValueError('Own source waiting slot required')
        if grant.get('pose_mm')!=self.nav.waits[level][slot]:raise ValueError('Own waiting grant differs from source pose')
        return slot

    def exported_slot(self, events, identity, when, level, *, allow_arrival=False):
        """Replay physical permission separately from conditional capacity fences.

        The independent lifecycle audit binds these events to original issued
        missions and actual body clearance. This geometric boundary still
        refuses to turn a conditional successor reservation into free space.
        """
        roles={}
        for event in events:
            if event['vehicle_id']!=identity or event['time_s']>when+1e-8:continue
            key=event['level'],event['slot'];kind=event['event']
            if kind=='waiting_granted':
                role=event['role']
                if role not in('start','destination','lookahead_destination'):
                    raise ValueError('Unknown waiting reservation role')
                if key in roles:raise ValueError('A waiting bay cannot be granted twice')
                roles[key]=role
            elif kind=='waiting_released':
                if roles.pop(key,None)!='start':raise ValueError('Only a current source bay can be released')
            elif kind=='waiting_promoted':
                if roles.get(key)!='destination':raise ValueError('Observed promotion needs the actual arrival bay')
                roles[key]='start'
            elif kind=='waiting_role_activated':
                if event['role']!='destination'or roles.get(key)!='lookahead_destination':
                    raise ValueError('Only a conditional successor can activate as the next arrival bay')
                roles[key]='destination'
        slots={slot for (lev,slot),role in roles.items()if lev==level and
               (role=='start'or allow_arrival and role=='destination')}
        if len(slots)>1:raise ValueError('Multiple physical own waiting bays on one floor')
        return next(iter(slots),None)

    def __call__(self, action, curve, observed):
        identity=observed['vehicle_id'];level=action['level']
        grants=observed.get('own_grants_at_start')or observed['own_grants']
        slot=self.own_slot(grants,level,allow_arrival=(action.get('lift_phase')or{}).get('kind')=='alighting');context=None
        if action.get('lift_phase'):
            grant=grants.get('lift',{});stage=action['lift_phase']
            port=stage['start_port'if stage['kind']=='boarding'else'destination_port']
            if (grant.get('status')!='assigned'or grant.get('slot')!=stage['slot']
                    or any(grant.get(k)!=stage[k]for k in('start_port','destination_port'))
                    or port!=action.get('port_id')):
                raise ValueError('A port curve requires this own allocated lift stage')
            ready='boarding_ready'if stage['kind']=='boarding'else'exit_ready'
            if grant.get(ready)is not True:raise ValueError('Own observed fully-open lift stage required')
            timeline=timeline_from_manifest(self.nav.mesh.manifest,observed['lift_schedule'])
            context=PortSupportContext(self.nav.mesh,self.source,port,timeline,vehicle_id=identity)
        proof=self.certificate(level,slot,context).check(curve)
        proof['scope_phase']=observed['phase']
        proof['own_waiting_slot']=slot
        # A nominal partial schedule holds the last observed state. It is a
        # conditional planning check, never a substitute for exported replay.
        proof['complete_exported_schedule_checked']=False
        return proof

    def attached_support(self, episode, lift):
        first=episode['points'][0]['pose_mm_rad'];start=episode['start_s']
        if any(p['pose_mm_rad']!=first or any(v!=0 for field in floor.PUBLIC[1:]for v in p[field])for p in episode['points']):
            raise ValueError('Cabin attachment requires fixed local XY/yaw with zero PVA')
        actual=posed_mesh(self.nav.mesh,lift.values(start));contract=source_surface_contract()
        group=next(g for g in actual.scene['groups']if g['id']=='LiftCabinFloorFinish')
        top=lift.z(start)+contract['height_offset_mm'];error=actual.scene['maximum_float32_error_mm']
        triangles=[[p[:2]for p in tri]for tri in actual.triangles(group)if all(abs(p[2]-top)<=max(error,1e-7)for p in tri)]
        cert=self.certificate(episode['level_id'])
        proof=support.support_covers(triangles,first[:2],first[2],cert.L+cert.reserve+cert.mesh_error,
            cert.W+cert.reserve+cert.mesh_error,model.support_settings(self.source)['gap']['maximum'],
            body_ids=[group['id']]*len(triangles),curve_ref={'scope':'rigid_cabin_attachment','time_s':[start,episode['end_s']]})
        if proof.get('rule_applied'):raise ValueError('A parked cabin vehicle cannot rely on a bridged edge')
        return {**proof,'body_id':group['id'],'source_derived_height_offset_mm':contract['height_offset_mm'],
                'invariant':'Fixed local footprint on the real cabin finish; vehicle and finish share absolute compiled cabin FK for the entire interval',
                'port_permission':False}

    def exported(self, program, source, navigation, trajectories, lift, *, native_report=None, program_reference=None):
        if source!=self.source or navigation is not self.nav:raise ValueError('Export geometry source mismatch')
        rows=[];applications=[];heights=[]
        covered=[];lift_covered=[]
        for trajectory in trajectories:
            for index,episode in enumerate(trajectory.episodes):
                if episode['attached_cabin']:
                    proof=self.attached_support(episode,lift)
                else:
                    context=None
                    if episode.get('lift_phase'):
                        context=PortSupportContext(self.nav.mesh,source,episode['port_id'],lift,vehicle_id=trajectory.identity)
                    # Replay own timestamped reservation events. Events are
                    # independently checked against real occupancy/resources.
                    slot=self.exported_slot(program.get('waiting_events',[]),trajectory.identity,
                        episode['start_s'],episode['level_id'],
                        allow_arrival=episode.get('lift_phase')=='alighting')
                    proof=self.certificate(episode['level_id'],slot,context).check(episode['curve'])
                rows.append({'vehicle_id':trajectory.identity,'time_s':[episode['start_s'],episode['end_s']],
                             'mode':episode['mode'],'proof':proof})
                covered.append({'vehicle_id':trajectory.identity,'episode':index})
                if episode['attached_cabin']or episode.get('lift_phase'):lift_covered.append(covered[-1].copy())
                applications.extend(proof.get('support_applications',proof.get('applications',[])))
                if proof.get('lift_support'):heights.extend(proof['lift_support']['height_applications'])
                if not proof['passed']:break
            if rows and not rows[-1]['proof']['passed']:break
        passed=len(rows)==sum(len(t.episodes)for t in trajectories)and all(r['proof']['passed']for r in rows)
        collision={'passed':False,'reason':'A separately pinned complete native BRep programme audit is required'}
        if native_report is not None:
            import export_building_walkthrough_freecad as native
            report=model.read_json(native_report)
            native.verify_pins(report.get('source_files_sha256',{}))
            # A standalone curve report cannot qualify the complete programme.
            from check_building_fleet_freecad import reference
            if report.get('format')!='solidcraftbot.building-fleet-native-audit/1'or report.get('audit_scope')!='full_fleet_program':
                raise ValueError('A complete native fleet audit is required')
            if program_reference is None or report.get('program')!=program_reference:
                raise ValueError('Native proof must bind the exact exported program path and bytes')
            required={**program['source_files_sha256'],
                'scripts/check_building_fleet_freecad.py':model.digest(model.ROOT/'scripts/check_building_fleet_freecad.py')}
            if any(report.get('source_files_sha256',{}).get(k)!=v for k,v in required.items()):
                raise ValueError('Native proof omits its full current source closure')
            minima=report.get('minimum_interval_lower_bounds_mm',{})
            if (report.get('failures')!=[]or type(report.get('counts',{}).get('intervals'))is not int
                    or report['counts']['intervals']<1 or any(type(minima.get(k))not in(int,float)
                        or not math.isfinite(minima[k])or minima[k]<self.nav.reserve for k in('static_mm','vehicle_mm'))):
                raise ValueError('Complete native interval metrics at the unchanged reserve are required')
            native_program=model.read_json(reference(report['program']))
            if native_program!=program:raise ValueError('Native audit belongs to another programme')
            collision={'passed':report.get('passed')is True,'native_report':{
                'path':str(Path(native_report).resolve().relative_to(model.ROOT)),
                'sha256':model.digest(native_report)},'metrics':report.get('minimum_interval_lower_bounds_mm',{}),
                'covered_episodes':[{'vehicle_id':t.identity,'episode':i}for t in trajectories for i in range(len(t.episodes))]}
        return {'support':{'passed':passed,'episodes_checked':len(rows),'episodes':rows,
                           'support_rule_applications':applications,'lift_height_applications':heights,'covered_episodes':covered},
                'collision':collision,'lift':{'passed':passed,'support_episode_count':len(rows),
                    'covered_episodes':lift_covered,
                    'port_gates':'Actual compiled source FK and full door opening; rigid cabin support does not grant port access'}}
