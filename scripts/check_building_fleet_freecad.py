"""Independent exact native BF01 clearance audit with interval motion inflation.

Pure contract/interval helpers import without CAD. Native shapes are loaded only
by check(), from the exact source/artifact-pinned walkthrough and camera proofs.
The checker does not generate missions, geometry, lift policy or motion points.
"""
import argparse
import bisect
import copy
import itertools
import hashlib
from fractions import Fraction
from types import SimpleNamespace
import json
import math
from pathlib import Path
import sys
import time
import export_building_walkthrough_freecad as native
from export_building_fleet_vehicle_freecad import checked_camera_report, kit
import tr01_floor_motion as floor
import building_fleet_model as fleet

ROOT=Path(__file__).resolve().parents[1]
_NATIVE_WORLD_CACHE={}


def finite(value):
    if type(value)not in (int,float)or not math.isfinite(value):raise ValueError('Finite numeric audit value required')
    return value


def reference(value):
    if type(value)is not dict or set(value)!={'path','sha256'}:raise ValueError('Pinned artifact reference required')
    path=native.project_path(value['path'])
    if native.digest(path)!=value['sha256']:raise ValueError('Changed audit artifact: '+value['path'])
    return path


def box_distance(a,b):
    return math.sqrt(sum(max(0,a['min'][k]-b['max'][k],b['min'][k]-a['max'][k])**2 for k in range(3)))


def shape_bounds(shape):
    bb=shape.BoundBox
    return {'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]}


def native_envelope(bounds,App,Part):
    """A full closed native prism enclosing the complete native source AABB.

    Round construction coordinates outward, then require actual native prism
    bounds to enclose the source bounds with no tolerance allowance.
    """
    lo=[finite(v)for v in bounds['min']];hi=[finite(v)for v in bounds['max']]
    if len(lo)!=3 or len(hi)!=3 or any(a>=b for a,b in zip(lo,hi)):raise ValueError('Nondegenerate native solid bounds required')
    origin=[math.nextafter(v,-math.inf)for v in lo];sizes=[]
    for minimum,maximum in zip(origin,hi):
        exact=Fraction(maximum)-Fraction(minimum);size=float(exact)
        if Fraction(size)<exact:size=math.nextafter(size,math.inf)
        sizes.append(size)
    prism=Part.makeBox(*sizes,App.Vector(*origin));actual=shape_bounds(prism)
    if any(actual['min'][i]>lo[i]or actual['max'][i]<hi[i]for i in range(3)):raise ValueError('Native enclosing prism lost source containment')
    return prism


def inflate_box(bounds,amount):
    amount=finite(amount)
    if amount<0:raise ValueError('Nonnegative spatial inflation required')
    return {'min':[v-amount for v in bounds['min']],'max':[v+amount for v in bounds['max']]}


class SpatialIndex:
    """Conservative3D AABB supercover; oversized bodies retained globally."""
    def __init__(self,bounds,cell_mm=2000,maximum_cells=4096):
        self.cell=finite(cell_mm)
        if self.cell<=0 or type(maximum_cells)is not int or maximum_cells<1:raise ValueError('Positive index settings required')
        self.maximum_cells=maximum_cells;self.cells={};self.global_names=[]
        for name,bb in bounds.items():
            cells=self.cover(bb)
            if cells is None:self.global_names.append(name)
            else:
                for cell in cells:self.cells.setdefault(cell,[]).append(name)

    def cover(self,bb):
        axes=[range(math.floor(bb['min'][i]/self.cell),math.floor(bb['max'][i]/self.cell)+1)for i in range(3)]
        if math.prod(len(axis)for axis in axes)>self.maximum_cells:return None
        return itertools.product(*axes)

    def query(self,bb):
        cells=self.cover(bb)
        if cells is None:return set(self.global_names)|{name for names in self.cells.values()for name in names}
        return set(self.global_names)|{name for cell in cells for name in self.cells.get(cell,[])}


def curve_extrema(curve,start,end,order=0):
    """Use shared polynomial extrema only on the overlapping source segments."""
    if start>=end or start<curve.times[0]-1e-9 or end>curve.times[-1]+1e-9:raise ValueError('Curve interval out of range')
    first=max(0,bisect.bisect_right(curve.times,start)-1);last=min(len(curve.segments),bisect.bisect_left(curve.times,end)+1)
    window=SimpleNamespace(times=curve.times[first:last+1],segments=curve.segments[first:last])
    return floor.extrema(window,start,end,order)


def parts_distance(first,second,counters,counter_key):
    """Exact union distance with certified native-AABB branch and bound.

    No positive clearance is inferred from a skipped overlapping box: a pair
    is omitted only when its box lower bound cannot improve an exact distance
    already obtained from another pair. This avoids a large compound extrema
    solve over unrelated cassette bores.
    """
    pairs=sorted((box_distance(a[1],b[1]),i,j)for i,a in enumerate(first)for j,b in enumerate(second))
    best=math.inf
    for lower,i,j in pairs:
        if lower>=best:break
        distance=first[i][0].distToShape(second[j][0])[0];counters[counter_key]+=1
        best=min(best,distance)
        if best==0:break
    if math.isinf(best):raise ValueError('Nonempty native physical shape parts required')
    return best


def quintic_fraction(start,end,t):
    start,end,t=map(finite,(start,end,t))
    if end<=start:raise ValueError('Positive schedule duration required')
    u=max(0,min(1,(t-start)/(end-start)))
    return 10*u**3-15*u**4+6*u**5


class LiftTimeline:
    """Evaluate the compiled source schedule with indexed state snapshots."""
    def __init__(self,config,schedule):
        self.config=copy.deepcopy(config);config=self.config;self.schedule=copy.deepcopy(schedule)
        previous=-math.inf
        for row in self.schedule:
            if row['kind']not in ('travel','doors'):raise ValueError('Unknown compiled lift segment')
            start,end=finite(row['start_s']),finite(row['end_s'])
            if start<previous or end<=start:raise ValueError('Ordered positive lift segments required')
            previous=end
            if row['kind']=='doors' and row['target']not in ('open','closed'):raise ValueError('Door endpoint required')
        self.doors={o['id']:o for o in config.get('door_objects',[])}
        if any(name not in self.doors for port in config['ports']for name in port.get('door_object_ids',[])):raise ValueError('Full source lift-door object map required')
        state={name:o['states']['closed']for name,o in self.doors.items()}
        state[config['object_id']]=config['reference_z_mm']
        for port in config['ports']:
            if port['active']and port['level_id']==config['reference_level']:
                for name in port.get('door_object_ids',[]):state[name]=self.doors[name]['states']['open']
        self._initial=dict(state);self._starts=[];self._before=[];self._after=[]
        for row in self.schedule:
            self._starts.append(row['start_s']);self._before.append(dict(state))
            self._apply(state,row,1.)
            self._after.append(dict(state))
        self._event_times=sorted({v for row in self.schedule for v in (row['start_s'],row['end_s'])})

    def _apply(self,state,row,u):
        if row['kind']=='travel':state[self.config['object_id']]=row['from_z_mm']+(row['to_z_mm']-row['from_z_mm'])*u
        else:
            for port in self.config['ports']:
                if port['active']and port['level_id']==row['level']:
                    for name in port.get('door_object_ids',[]):
                        obj=self.doors[name];initial=state[name];target=obj['states'][row['target']]
                        state[name]=initial+(target-initial)*u

    def values(self,t):
        finite(t);index=bisect.bisect_right(self._starts,t)-1
        if index<0:return dict(self._initial)
        row=self.schedule[index]
        if t>=row['end_s']:return dict(self._after[index])
        state=dict(self._before[index]);self._apply(state,row,quintic_fraction(row['start_s'],row['end_s'],t))
        return state

    def events(self,start,end):
        """Return only compiled critical events strictly inside the interval."""
        return self._event_times[bisect.bisect_right(self._event_times,start):bisect.bisect_left(self._event_times,end)]

    def z(self,t):return self.values(t)[self.config['object_id']]

    def z_bound(self,start,end,mid):
        times=[start,end,*self.events(start,end)];z=self.z(mid)
        return max(abs(self.z(t)-z)for t in times)


def timeline_from_manifest(manifest,schedule):
    # Door objects are flattened into manifest.objects by the normal exporter;
    # the public elevator interface intentionally keeps only their source IDs.
    config=dict(manifest['elevator'],door_objects=[o for o in manifest['objects']if o.get('mechanism')=='lift_door'])
    return LiftTimeline(config,schedule)


class Trajectory:
    def __init__(self,row,levels,lift):
        self.identity=row['vehicle_id'];self.episodes=[];self.starts=[];self.levels=levels;self.lift=lift
        for episode in row['episodes']:
            start,end=finite(episode['start_s']),finite(episode['end_s'])
            if end<=start or (self.episodes and abs(start-self.episodes[-1]['end_s'])>1e-9):raise ValueError('Continuous positive episode coverage required')
            if episode['mode']not in ('hold','driving','lift')or type(episode['attached_cabin'])is not bool:raise ValueError('Known episode mode and cabin binding required')
            if episode['mode']=='hold'and not episode.get('hold_reason'):raise ValueError('Stationary hold requires explicit reason')
            if any(len(point[field])!=3 for point in episode['points']for field in floor.PUBLIC):raise ValueError('Planar PVA vector dimension must be3')
            curve=floor.motion.Curve(floor.canonical(episode['points']))
            if episode['mode']in ('hold','lift'):
                first=episode['points'][0]['pose_mm_rad']
                if any(point['pose_mm_rad']!=first or any(v!=0 for field in floor.PUBLIC[1:]for v in point[field])for point in episode['points']):raise ValueError('Hold/lift XY and yaw must remain fixed with zero PVA')
            if abs(curve.times[0]-start)>1e-9 or abs(curve.times[-1]-end)>1e-9:raise ValueError('Episode PVA times must span its interval')
            if episode['level_id']not in levels:raise ValueError('Source-derived floor required')
            if self.episodes:
                previous=self.episodes[-1]['points'][-1]
                if any(any(abs(a-b)>1e-7 for a,b in zip(previous[field],episode['points'][0][field]))for field in floor.PUBLIC):raise ValueError('Episode PVA discontinuity')
            if episode['attached_cabin']and episode['mode']=='driving':raise ValueError('Driving cannot be cabin-attached')
            self.starts.append(start);self.episodes.append(dict(episode,curve=curve))
        if not self.episodes:raise ValueError('Nonempty trajectory required')

    def episode(self,t):
        if t<self.starts[0]-1e-9 or t>self.episodes[-1]['end_s']+1e-9:raise ValueError('Trajectory does not cover audit time')
        return self.episodes[max(0,min(len(self.episodes)-1,bisect.bisect_right(self.starts,t)-1))]

    def pose(self,t):
        e=self.episode(t);state=e['curve'].evaluate(t)[floor.F[0]]
        z=self.lift.z(t)if e['attached_cabin']else self.levels[e['level_id']]['z_mm']
        return state[:2]+[z,state[2]]

    def inflation(self,start,end,radius,include_z=True):
        mid=(start+end)/2;e=self.episode(mid)
        if start<e['start_s']-1e-9 or end>e['end_s']+1e-9:raise ValueError('Audit interval crosses episode boundary')
        centre=e['curve'].evaluate(mid)[floor.F[0]];bounds=curve_extrema(e['curve'],start,end)
        delta=[max(abs(bounds[k][i]-centre[i])for k in ('min','max'))for i in range(3)]
        z=self.lift.z_bound(start,end,mid)if e['attached_cabin']and include_z else 0
        return math.nextafter(math.hypot(delta[0],delta[1],z)+radius*delta[2],math.inf)


def checked_walkthrough(path):
    report=json.loads(path.read_text())
    if report.get('passed')is not True or report.get('format')!='solidcraftbot.building-walkthrough-build/1':raise ValueError('Successful current walkthrough report required')
    native.verify_pins(report['source_files_sha256'])
    native.verify_pins({report['files'][k]:h for k,h in report['artifact_sha256'].items()})
    reports={k:native.checked_report(v['report'],k)for k,v in report['native_builds'].items()}
    for k,v in report['native_builds'].items():
        if native.digest(native.project_path(v['report']))!=v['report_sha256']:raise ValueError('Changed native proof')
    manifest=json.loads(native.project_path(report['files']['manifest']).read_text());mesh=json.loads(native.project_path(report['files']['native_mesh']).read_text())['scenes']['building']
    return report,reports,manifest,{g['id']for g in mesh['groups']}


def _world_input_key(reports,manifest,expected,bindings,App,geo):
    """Revalidate bytes before every use of a process-local native snapshot."""
    for report in reports.values():
        native.verify_pins(report['source_files_sha256'])
        native.verify_pins({report['files'][name]:digest for name,digest in report['artifact_sha256'].items()})
    payload={'reports':reports,'manifest':manifest,'expected':sorted(expected),'bindings':bindings}
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest(),id(App),id(geo)


def _world_rows(snapshot):
    # Shapes in the private snapshot are read-only. Placement, cutting and any
    # other mutating operation must operate on a copied shape. Audit rows and
    # their bounds are separate mutable containers for each invocation.
    return {name:{'shape':shape,'bounds':{key:list(values)for key,values in bounds},'role':role}
        for name,shape,bounds,role in snapshot}


def native_world(reports,manifest,expected,App,geo):
    """Load pinned BReps once per process; return isolated per-audit rows.

    Large source documents take minutes to restore. Reuse only the unchanged
    original shapes, never a world after door posing or contact-layer cutting.
    Every reuse still verifies all source/artifact bytes and exact bindings.
    """
    bindings=native.native_equipment_bindings(manifest.get('laboratories',[]))
    key=_world_input_key(reports,manifest,expected,bindings,App,geo)
    if key in _NATIVE_WORLD_CACHE:return _world_rows(_NATIVE_WORLD_CACHE[key])
    world={}
    for kind,report in reports.items():
        doc=App.openDocument(str(native.project_path(report['files']['freecad'])))
        try:
            for obj in geo.features(doc):
                name=obj.SourceBody;shape=geo.world_shape(obj).copy()
                if kind=='building':matches=[None]
                else:matches=[(lab,device)for lab,device in bindings if name.startswith(device['id']+'__')]
                for match in matches:
                    identity=name
                    if match:
                        lab,device=match;matrix=device['transform'];native.validate_rigid(matrix);m=App.Matrix(*[v for row in matrix for v in row]);shape=shape.copy();shape.Placement=App.Placement(m).multiply(shape.Placement)
                        identity=device['body_prefix']+name[len(device['id']+'__'):]
                    if identity in world:raise ValueError('Duplicate native audit body')
                    if shape.isNull()or not shape.isValid()or not shape.Solids:raise ValueError('Invalid native audit body: '+identity)
                    world[identity]={'shape':shape,'bounds':shape_bounds(shape),'role':str(getattr(obj,'ModelRole','native_geometry'))}
        finally:App.closeDocument(doc.Name)
    if set(world)!=expected:raise ValueError('Native audit does not cover the exact walkthrough bodies')
    if _world_input_key(reports,manifest,expected,bindings,App,geo)!=key:raise ValueError('Native inputs changed during document restoration')
    snapshot=tuple((name,row['shape'],tuple((axis,tuple(values))for axis,values in row['bounds'].items()),row['role'])for name,row in world.items())
    _NATIVE_WORLD_CACHE.clear();_NATIVE_WORLD_CACHE[key]=snapshot
    return _world_rows(snapshot)


def object_transform(obj,value,App):
    joint=obj['joint'];delta=value-obj['states'][obj['reference_state']]
    if joint['type']=='prismatic':return App.Placement(App.Vector(*[delta*v for v in joint['axis']]),App.Rotation())
    if joint['type']!='revolute':raise ValueError('Unsupported presentation articulation')
    origin=App.Vector(*joint['origin_mm']);rotation=App.Rotation(App.Vector(*joint['axis']),delta)
    return App.Placement(origin-rotation.multVec(origin),rotation)


def audit(program_path,output,maximum_step_s=30.,minimum_step_s=.001,maximum_depth=18,*,_curve_probe=False):
    started=time.monotonic();program_path=native.project_path(program_path);program=fleet.read_json(program_path);native.verify_pins(program['source_files_sha256']);before=native.digest(program_path)
    spec=fleet.load()
    if not _curve_probe:
        if program.get('format')!='solidcraftbot.building-fleet-program/1'or program.get('complete')is not True:
            raise ValueError('Complete compiled fleet programme required for a full native audit')
        if type(program.get('seed'))is not int or program['seed']!=spec['missions']['seed']:
            raise ValueError('Full native audit seed must match the current source configuration')
    expected={'BF01'}if _curve_probe else {'BF%02d'%i for i in range(1,21)}
    if len(program.get('trajectories',[]))!=len(expected)or {r['vehicle_id']for r in program['trajectories']}!=expected:raise ValueError('Complete expected native audit trajectory set required')
    if _curve_probe and program.get('scope')!='standalone_curve_only':raise ValueError('Separate native curve-probe scope required')
    for v in [maximum_step_s,minimum_step_s]:
        if not 0<finite(v)<=30:raise ValueError('Bounded positive audit step required')
    if minimum_step_s>maximum_step_s or type(maximum_depth)is not int or not 1<=maximum_depth<=24:raise ValueError('Bounded refinement settings required')
    walk=reference(program['artifacts']['walkthrough_report']);camera=reference(program['artifacts']['camera_report']);walk_report,reports,manifest,expected=checked_walkthrough(walk);camera_report=checked_camera_report(camera)
    sensor=json.loads((ROOT/spec['sources']['sensor']['path']).read_text());reserve=sensor['controller']['clearance_mm']+spec['geometry']['localization_tolerance_mm']
    levels={v['id']:v for v in program['levels']}if isinstance(program['levels'],list)else program['levels']
    expected_levels={v['id']:v['z_mm']for v in manifest['levels']}
    if set(levels)!=set(expected_levels)or any(levels[k]['z_mm']!=z for k,z in expected_levels.items()):raise ValueError('Program levels differ from source heights')
    lift=timeline_from_manifest(manifest,program['lift_schedule']);trajectories=[Trajectory(r,levels,lift)for r in program['trajectories']]
    import FreeCAD as App
    import Part
    sys.path.insert(0,str(ROOT/'scripts/freecad'));import solidcraftbot_freecad as geo
    world=native_world(reports,manifest,expected,App,geo);doc=App.openDocument(str(native.project_path(camera_report['files']['freecad'])))
    try:
        meta={body['id']:body for body in kit.expanded(kit.load())['bodies']};objects_in_vehicle=geo.features(doc)
        if len(objects_in_vehicle)!=len(meta)or {str(o.SourceBody)for o in objects_in_vehicle}!=set(meta):raise ValueError('Native physical vehicle coverage differs from source')
        vehicle_parts=[];physical_body_ids=[]
        for obj in objects_in_vehicle:
            identity=str(obj.SourceBody);body=meta[identity]
            if str(obj.ModelRole)!=body['role']:raise ValueError('Native vehicle role differs from source: '+identity)
            if body['role']=='viewing_cone':continue
            shape=geo.world_shape(obj).copy()
            if shape.isNull()or not shape.isValid()or not shape.Solids:raise ValueError('Invalid native physical vehicle body: '+identity)
            vehicle_parts.append(shape);physical_body_ids.append(identity)
        vehicle=Part.makeCompound(vehicle_parts)
    finally:App.closeDocument(doc.Name)
    bounds=shape_bounds(vehicle);radius=math.hypot(max(abs(v)for v in [bounds['min'][0],bounds['max'][0]]),max(abs(v)for v in [bounds['min'][1],bounds['max'][1]]))
    vehicle_envelope=native_envelope(bounds,App,Part)
    support_exclusions=[]
    for name,body in world.items():
        if body['role']=='concept_existing_elevator_cabin':
            bb=body['bounds'];cut_top=manifest['elevator']['reference_z_mm']+spec['geometry']['floor_band_start_mm'];low=bb['min'][2]-1
            contact=Part.makeBox(bb['max'][0]-bb['min'][0]+2,bb['max'][1]-bb['min'][1]+2,cut_top-low,App.Vector(bb['min'][0]-1,bb['min'][1]-1,low))
            body['shape']=body['shape'].cut(contact);body['bounds']=shape_bounds(body['shape'])
            if body['shape'].isNull()or not body['shape'].isValid():raise ValueError('Invalid source contact-layer separation')
            support_exclusions.append({'body':name,'maximum_z_in_reference_mm':cut_top,'basis':'source_floor_band_start_mm; only the supporting contact layer excluded'})
    objects={o['id']:o for o in manifest['objects']};body_chains={}
    for obj in objects.values():
        chain=[obj];parent=obj.get('parent_object_id')
        while parent:chain.append(objects[parent]);parent=objects[parent].get('parent_object_id')
        for name in obj['moving_body_ids']:body_chains[name]=chain
    default_values={name:o['states'][o.get('initial_state',o['reference_state'])]for name,o in objects.items()}
    count={'intervals':0,'exact_body_distances':0,'exact_vehicle_distances':0,'envelope_body_distances':0,'envelope_vehicle_distances':0,'envelope_certificates':0,'broadphase_rejections':0,'refinements':0};minimum={'static_mm':math.inf,'vehicle_mm':math.inf};failures=[]
    def moved_body(name,t,base=None,values=None):
        shape=(world[name]['shape']if base is None else base).copy()
        values={**default_values,**lift.values(t)}if values is None else values
        for obj in body_chains.get(name,[]):shape.Placement=object_transform(obj,values[obj['id']],App).multiply(shape.Placement)
        return shape
    def obstacle_inflation(name,start,end,exclude_cabin=False,states=None):
        mid=(start+end)/2
        if states is None:
            times=[start,end,*lift.events(start,end),mid]
            states={t:{**default_values,**lift.values(t)}for t in times}
        amount=0
        for obj in body_chains.get(name,[]):
            if exclude_cabin and obj['id']==manifest['elevator']['object_id']:continue
            delta=max(abs(values[obj['id']]-states[mid][obj['id']])for values in states.values())
            if obj['joint']['type']=='prismatic':amount+=delta
            else:
                origin=obj['joint']['origin_mm'];bb=world[name]['bounds'];r=math.sqrt(sum(max(abs(bb[k][i]-origin[i])for k in ('min','max'))**2 for i in range(3)));amount+=r*math.radians(delta)
        return amount
    # Freeze static initial articulations once. Only the lift assembly and its
    # door leaves change during a compiled BF01 run.
    dynamic={name for name,chain in body_chains.items()if any(o['id']==manifest['elevator']['object_id']or o.get('mechanism')=='lift_door'for o in chain)}
    hidden=set(manifest.get('hidden_body_ids',[]))
    world={name:body for name,body in world.items()if body['role']!='viewing_cone'and name not in hidden}
    for name,body in world.items():
        if name not in dynamic:
            shape=moved_body(name,0)if name in body_chains else body['shape']
            body.update(shape=shape,bounds=shape_bounds(shape))
    dynamic &= set(world)
    index=SpatialIndex({name:body['bounds']for name,body in world.items()if name not in dynamic})
    exact_cache={};envelope_cache={}
    dynamic_envelopes={name:native_envelope(world[name]['bounds'],App,Part)for name in dynamic}
    def interval(start,end,depth):
        mid=(start+end)/2;count['intervals']+=1;vehicles=[];access_issues=[]
        inflations={t.identity:t.inflation(start,end,radius)for t in trajectories}
        if max(inflations.values())>reserve/2 and depth<maximum_depth and end-start>minimum_step_s:
            count['refinements']+=1
            return interval(start,mid,depth+1)and interval(mid,end,depth+1)
        placed_parts={};placements={}
        def physical_parts(identity):
            if identity not in placed_parts:
                parts=[];placement=placements[identity]
                for local in vehicle_parts:
                    part=local.copy();part.Placement=placement.multiply(part.Placement);parts.append((part,shape_bounds(part)))
                placed_parts[identity]=parts
            return placed_parts[identity]
        for trajectory in trajectories:
            pose=trajectory.pose(mid);placement=App.Placement(App.Vector(*pose[:3]),App.Rotation(App.Vector(0,0,1),math.degrees(pose[3])))
            placements[trajectory.identity]=placement
            shape=vehicle_envelope.copy();shape.Placement=placement.multiply(shape.Placement)
            bb=shape_bounds(shape);movement=inflations[trajectory.identity];episode=trajectory.episode(mid)
            if episode['attached_cabin']:
                cabin=manifest['elevator']['cabin_bounds_mm']
                if any(bb['min'][axis]<cabin['min'][axis]+reserve or bb['max'][axis]>cabin['max'][axis]-reserve for axis in (0,1)):raise ValueError('Cabin-attached vehicle is outside cabin envelope')
            elif 'shaft_bounds_mm'in manifest['elevator']:
                shaft=manifest['elevator']['shaft_bounds_mm']
                overlaps_xy=all(bb['max'][axis]+movement>=shaft['min'][axis]and bb['min'][axis]-movement<=shaft['max'][axis]for axis in (0,1))
                if overlaps_xy:
                    ports=[port for port in manifest['elevator']['ports']if port['active']and port['level_id']==episode['level_id']]
                    for t in (start,mid,end):
                        values=lift.values(t)
                        if abs(lift.z(t)-pose[2])>1e-7 or not any(all(abs(values[name]-lift.doors[name]['states']['open'])<1e-7 for name in port.get('door_object_ids',[]))for port in ports):
                            # Refine broadphase overlap before rejecting a safe
                            # vehicle outside the shaft; the base geometry still
                            # certifies any actual approach through an openport.
                            access_issues.append({'vehicle':trajectory.identity,'body':'UnboardedLiftShaft','reason':'Interval may enter shaft without stationary cabin and fully open active doors'})
                            break
            vehicles.append((trajectory,shape,bb,movement,pose))
        near=access_issues;accepted={'static_mm':math.inf,'vehicle_mm':math.inf}
        states={t:{**default_values,**lift.values(t)}for t in {start,end,mid,*lift.events(start,end)}}
        dynamic_bounds={name:shape_bounds(moved_body(name,mid,base=dynamic_envelopes[name],values=states[mid]))for name in dynamic}
        dynamic_shapes={};obstacle_movements={}
        def dynamic_shape(name):
            if name not in dynamic_shapes:dynamic_shapes[name]=moved_body(name,mid,values=states[mid])
            return dynamic_shapes[name]
        def body_movement(name,exclude_cabin=False):
            key=(name,exclude_cabin)
            if key not in obstacle_movements:obstacle_movements[key]=obstacle_inflation(name,start,end,exclude_cabin,states)
            return obstacle_movements[key]
        for trajectory,shape,bb,movement,pose in vehicles:
            candidates=set(index.query(inflate_box(bb,reserve+movement)))|dynamic
            count['broadphase_rejections']+=len(world)-len(candidates)
            for name in sorted(candidates):
                body=world[name];ob=dynamic_bounds[name]if name in dynamic else body['bounds'];omove=body_movement(name)if name in dynamic else 0
                # Ground-contact layers below the source20mm band are not side
                # obstacles. The navigation compiler separately proves support.
                relative_z=lift.z_bound(start,end,mid)if trajectory.episode(mid)['attached_cabin']else 0
                shared_cabin=trajectory.episode(mid)['attached_cabin']and any(o['id']==manifest['elevator']['object_id']for o in body_chains.get(name,[]))
                if ob['max'][2]+(0 if shared_cabin else omove)<=pose[2]+spec['geometry']['floor_band_start_mm']-(0 if shared_cabin else relative_z):continue
                relative_movement=trajectory.inflation(start,end,radius,include_z=False)if shared_cabin else movement
                if shared_cabin:omove=body_movement(name,exclude_cabin=True)
                lower=box_distance(bb,ob)-relative_movement-omove
                if lower>=reserve:
                    accepted['static_mm']=min(accepted['static_mm'],lower);count['broadphase_rejections']+=1;continue
                key=(trajectory.identity,name,*pose)
                obstacle=dynamic_shape(name)if name in dynamic else body['shape']
                if name not in dynamic and key in envelope_cache:enclosing_distance=envelope_cache[key]
                else:
                    enclosing_distance=shape.distToShape(obstacle)[0];count['envelope_body_distances']+=1
                    if name not in dynamic:envelope_cache[key]=enclosing_distance
                envelope_lower=math.nextafter(enclosing_distance-relative_movement-omove,-math.inf)
                if envelope_lower>=reserve:
                    accepted['static_mm']=min(accepted['static_mm'],envelope_lower);count['envelope_certificates']+=1;continue
                if name not in dynamic and key in exact_cache:distance=exact_cache[key]
                else:
                    distance=parts_distance(physical_parts(trajectory.identity),[(obstacle,ob)],count,'exact_body_distances')
                    if name not in dynamic:exact_cache[key]=distance
                lower=math.nextafter(distance-relative_movement-omove,-math.inf)
                if lower<reserve:near.append({'vehicle':trajectory.identity,'body':name,'lower_mm':lower,'sample_mm':distance})
                else:accepted['static_mm']=min(accepted['static_mm'],lower)
            # An attached vehicle follows the same absolute cabin displacement;
            # this exact equality is checked independently of localised XY.
            if trajectory.episode(mid)['attached_cabin']and abs(pose[2]-lift.z(mid))>1e-8:raise AssertionError('Lost absolute cabin binding')
        for i,(a,shape,bb,movement,pose)in enumerate(vehicles):
            for b,other,ob,other_movement,_ in vehicles[i+1:]:
                same_cabin=a.episode(mid)['attached_cabin']and b.episode(mid)['attached_cabin']
                pair_movement=a.inflation(start,end,radius,include_z=False)+b.inflation(start,end,radius,include_z=False)if same_cabin else movement+other_movement
                lower=box_distance(bb,ob)-pair_movement
                if lower>=reserve:
                    accepted['vehicle_mm']=min(accepted['vehicle_mm'],lower);count['broadphase_rejections']+=1;continue
                enclosing_distance=shape.distToShape(other)[0];count['envelope_vehicle_distances']+=1
                envelope_lower=math.nextafter(enclosing_distance-pair_movement,-math.inf)
                if envelope_lower>=reserve:
                    accepted['vehicle_mm']=min(accepted['vehicle_mm'],envelope_lower);count['envelope_certificates']+=1;continue
                distance=parts_distance(physical_parts(a.identity),physical_parts(b.identity),count,'exact_vehicle_distances');lower=math.nextafter(distance-pair_movement,-math.inf)
                if lower<reserve:near.append({'vehicle':a.identity,'other_vehicle':b.identity,'lower_mm':lower,'sample_mm':distance})
                else:accepted['vehicle_mm']=min(accepted['vehicle_mm'],lower)
        if near:
            if depth>=maximum_depth or end-start<=minimum_step_s:
                failures.append({'start_s':start,'end_s':end,'failures':near});return False
            count['refinements']+=1
            return interval(start,mid,depth+1)and interval(mid,end,depth+1)
        for key,value in accepted.items():minimum[key]=min(minimum[key],value)
        return True
    end=min(t.episodes[-1]['end_s']for t in trajectories);start=max(t.starts[0]for t in trajectories)
    if any(abs(t.starts[0]-start)>1e-9 or abs(t.episodes[-1]['end_s']-end)>1e-9 for t in trajectories):raise ValueError('All trajectories must cover the same whole program')
    knots=sorted({start,end,*[v for t in trajectories for e in t.episodes for v in (e['start_s'],e['end_s'])],*[v for row in program['lift_schedule']for v in (row['start_s'],row['end_s'])if start<=v<=end]});passed=True
    for a,b in zip(knots,knots[1:]):
        n=max(1,math.ceil((b-a)/maximum_step_s))
        for i in range(n):
            if not interval(a+(b-a)*i/n,a+(b-a)*(i+1)/n,0):passed=False;break
        if not passed:break
    native.verify_pins(program['source_files_sha256']);checked_camera_report(camera);checked_walkthrough(walk)
    if native.digest(program_path)!=before:raise ValueError('Program changed during native audit')
    result={'format':'solidcraftbot.building-fleet-native-curve-audit/1'if _curve_probe else 'solidcraftbot.building-fleet-native-audit/1','passed':passed,'program':{'path':str(program_path.relative_to(ROOT)),'sha256':before},'source_files_sha256':{**program['source_files_sha256'],str(Path(__file__).relative_to(ROOT)):native.digest(__file__)},'audit_scope':'standalone_curve_only'if _curve_probe else 'full_fleet_program','minimum_clearance_mm':reserve,'native_body_count':len(expected),'physical_vehicle_body_ids':sorted(physical_body_ids),'physical_vehicle_body_count':len(physical_body_ids),'vehicle_envelope':{'source_native_bounds_mm':bounds,'envelope_native_bounds_mm':shape_bounds(vehicle_envelope),'full_closed_prism':True,'source_containment_checked':True,'placement_basis':'identical source rigid placement for enclosing prism and physical-part fallback'},'support_contact_exclusions':support_exclusions,'minimum_interval_lower_bounds_mm':{k:None if math.isinf(v)else v for k,v in minimum.items()},'counts':count,'failures':failures,'elapsed_s':time.monotonic()-started,'qualification':{'hardware_executed':False,'navigation_qualified':False,'person_safety_qualified':False},'scope':'Conservative full closed native enclosing prisms, with exact native physical-part fallback where their distance is insufficient, evaluated at interval midpoints and reduced by polynomial-extrema vehicle translation/yaw and compiled lift/door motion bounds. Unresolved intervals fail. Complete walkthrough bodies include identically bound L01 equipment. Supporting surfaces below navigation20mm band excluded from obstacle separation; ground support, shaft authorization and resource/lift sequencing require their separate compiler proofs.'}
    output=native.project_path(output);output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise FileExistsError(output)
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if not passed:raise AssertionError('Native interval clearance audit failed; see '+str(output))
    return result


def audit_curve(motion_path,walkthrough_report,camera_report,level_id,output):
    """Audit an actual exported source-pinned curve; never a full-fleet claim."""
    motion_path=native.project_path(motion_path);walkthrough_report=native.project_path(walkthrough_report);camera_report=native.project_path(camera_report);motion=fleet.read_json(motion_path)
    points=motion['points'];curve=floor.motion.Curve(floor.canonical(points));_,_,manifest,_=checked_walkthrough(walkthrough_report)
    pins={**fleet.source_pins(fleet.load()),**fleet.protected_pins(),str(motion_path.relative_to(ROOT)):native.digest(motion_path),'scripts/check_building_fleet_freecad.py':native.digest(__file__)}
    for name in ['model/building-fleet-l01-route.shared.json','model/building-fleet-l01-route.schema.json','scripts/building_fleet_l01.py','ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py']:
        if (ROOT/name).is_file():pins[name]=native.digest(ROOT/name)
    program={'format':'solidcraftbot.building-fleet-native-curve-probe/1','scope':'standalone_curve_only','source_files_sha256':pins,'artifacts':{'walkthrough_report':{'path':str(walkthrough_report.relative_to(ROOT)),'sha256':native.digest(walkthrough_report)},'camera_report':{'path':str(camera_report.relative_to(ROOT)),'sha256':native.digest(camera_report)}},'levels':manifest['levels'],'lift_schedule':[],'trajectories':[{'vehicle_id':'BF01','episodes':[{'level_id':level_id,'mode':'driving','start_s':curve.times[0],'end_s':curve.times[-1],'points':points,'attached_cabin':False,'hold_reason':None}]}]}
    output=native.project_path(output);wrapper=output.with_name(output.stem+'-curve-input.json');wrapper.parent.mkdir(parents=True,exist_ok=True)
    if wrapper.exists():raise FileExistsError(wrapper)
    wrapper.write_text(json.dumps(program,indent=2,allow_nan=False)+'\n')
    return audit(wrapper,output,_curve_probe=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('program');parser.add_argument('--out',required=True);parser.add_argument('--curve-only',action='store_true');parser.add_argument('--walkthrough-report');parser.add_argument('--camera-report');parser.add_argument('--level',default='OG3');args=parser.parse_args()
    if args.curve_only:
        if not args.walkthrough_report or not args.camera_report:parser.error('Curve audit needs both native report references')
        return audit_curve(args.program,args.walkthrough_report,args.camera_report,args.level,args.out)
    return audit(args.program,args.out)


if __name__=='__main__':
    import check_building_fleet_freecad as checker
    checker.main()
