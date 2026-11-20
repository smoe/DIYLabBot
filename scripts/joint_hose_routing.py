"""Portable fixed-material hose sections between link-mounted clips.

Each joint loop owns an invariant material length. Rigid link runs are compiled
once in their host coordinates. No global loop parameter can move material
through a clip. This module imports no CAD and selects no hardware.
"""
import copy
import hashlib
import json
import math

import arm_syringe_routing as framed
import pneumatic_hose as hose
import robot_spec as robot
import spatial_hose_carrier as curves

FORMAT = 'solidcraftbot.link-clipped-hose/1'
PROOF_FORMAT = 'solidcraftbot.arm-hose-routing-proof/1'
TOLERANCE_MM = 1e-7
RoutingEvidenceError = framed.RoutingEvidenceError


class SectionFitError(ValueError):
    def __init__(self, message, witness):
        super().__init__(message)
        self.witness = witness


def _number(value, label, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (positive and value <= 0)):
        raise ValueError('Invalid finite '+label)
    return float(value)


def _vector(value, values):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('A routing vector needs three coordinates')
    return [_number(robot.evaluate(v, values), 'routing coordinate') for v in value]


def _direction(matrix, vector):
    return [sum(matrix[i][j]*vector[j] for j in range(3)) for i in range(3)]


def _line(start, end):
    length = math.dist(start, end)
    if length <= 1e-9:
        raise ValueError('A supported material region must have positive length')
    return {'kind': 'line', 'start_mm': list(start), 'end_mm': list(end), 'length_mm': length}


def _exact_length(segment):
    """Measure the declared exact geometry rather than trusting its length tag."""
    start,end=hose._point(segment['start_mm']),hose._point(segment['end_mm'])
    if segment['kind']=='line':
        if set(segment)!={'kind','start_mm','end_mm','length_mm'}:raise ValueError('Foreign line geometry fields')
        length=math.dist(start,end)
    elif segment['kind']=='arc':
        required={'kind','start_mm','end_mm','through_mm','center_mm','axis','radius_mm','sweep_rad','length_mm'}
        if set(segment)!=required:raise ValueError('Missing or foreign circular-arc geometry fields')
        center=hose._point(segment['center_mm']);axis=hose._point(segment['axis'])
        radius=_number(segment['radius_mm'],'arc radius',True)
        sweep=_number(segment['sweep_rad'],'arc sweep',True)
        radial=hose._sub(start,center)
        if (abs(math.sqrt(hose._dot(axis,axis))-1)>1e-8 or abs(hose._dot(radial,axis))>TOLERANCE_MM
                or abs(math.sqrt(hose._dot(radial,radial))-radius)>TOLERANCE_MM
                or sweep>2*math.pi+1e-9):raise ValueError('Circular arc frame/radius is inconsistent with its geometry')
        expected_end=hose._add(center,hose._rotate(radial,axis,sweep))
        expected_middle=hose._add(center,hose._rotate(radial,axis,sweep/2))
        if max(math.dist(end,expected_end),math.dist(hose._point(segment['through_mm']),expected_middle))>TOLERANCE_MM:
            raise ValueError('Circular arc endpoint/through geometry differs from its radius and sweep')
        length=radius*sweep
    else:raise ValueError('Unknown exact hose segment kind')
    if length<=1e-9 or abs(length-_number(segment['length_mm'],'segment length',True))>TOLERANCE_MM:
        raise ValueError('Stored segment length differs from the actual exact curve')
    return length


def _path(segments, controls, radius, step):
    result = curves._path(segments, controls, radius, step)
    hose._joined_path(result)
    return result


def _transform(path, matrix, step):
    rows = []
    for segment in path['segments']:
        value = dict(segment)
        for key in ('start_mm', 'end_mm', 'through_mm', 'center_mm'):
            if key in value:
                value[key] = robot.transform(matrix, value[key])
        if 'axis' in value:
            value['axis'] = _direction(matrix, value['axis'])
        rows.append(value)
    return _path(rows, [], path['requested_bend_radius_mm'], step)


def validate_source(spec, p, arm):
    """Validate the explicit recipe; geometric feasibility belongs to design()."""
    recipe = spec['hose_routing']
    if recipe.get('format') != FORMAT or not isinstance(recipe.get('clips'), dict) or not recipe['clips']:
        raise ValueError('A link-clipped hose recipe with physical clips is required')
    for key in ('hoseBendRadius', 'hoseClipLength', 'clipFreeLead', 'hoseOuterRadius'):
        _number(p[key], key, True)
    if p['hoseBendRadius'] < 12:
        raise ValueError('The hard provisional bare-hose radius must remain at least12mm')
    _number(recipe['sample_step_mm'], 'routing sample step', True)
    links = {row['id'] for row in arm['links']}
    joints = {row['id']: row for row in arm['joints']}
    values = {**robot.parameters(arm), **p}
    bodies = {operation['body']: link['id'] for link in robot.expanded(arm)['links']
              for operation in link['recipe'] if operation['action'] == 'create'}
    body_ids = set()
    for name, clip in recipe['clips'].items():
        if (not isinstance(name, str) or not name or name in ('pump', 'tip')
                or set(clip) != {'link', 'body_id', 'host_body', 'center_mm', 'tangent', 'x_axis', 'mount'}
                or clip['link'] not in links or bodies.get(clip['host_body']) != clip['link']
                or not isinstance(clip['body_id'], str) or not clip['body_id']
                or clip['body_id'] in body_ids or clip['body_id'] in bodies
                or not isinstance(clip['mount'], dict) or not clip['mount'].get('kind')):
            raise ValueError('Invalid physical hose clip '+str(name))
        body_ids.add(clip['body_id'])
        _vector(clip['center_mm'], values)
        tangent = hose._unit(_vector(clip['tangent'], values))
        x = hose._unit(_vector(clip['x_axis'], values))
        if abs(hose._dot(tangent, x)) > 1e-8:
            raise ValueError('Clip tangent and x axis must be perpendicular')
    sequence = ['pump']
    ids = set()
    sections = recipe.get('sections')
    if not isinstance(sections, list) or not sections:
        raise ValueError('A hose needs ordered physical sections')
    for section in sections:
        if (not isinstance(section.get('id'), str) or not section['id'] or section['id'] in ids
                or section.get('from') != sequence[-1]
                or section.get('to') not in set(recipe['clips']) | {'tip'}):
            raise ValueError('Section sequence is incomplete, reordered or duplicated')
        ids.add(section['id']); sequence.append(section['to'])
        if section['kind'] == 'fixed_link':
            if (section.get('link') not in links or not isinstance(section.get('controls'), list)
                    or len(section['controls']) < 2 or not section.get('host_bodies')):
                raise ValueError('Fixed link runs need a host link, material witnesses and controls')
            for point in section['controls']:
                _vector(point, values)
            _number(section['max_offset_mm'], 'fixed-run maximum offset', True)
        elif section['kind'] == 'joint_loop':
            if (section.get('joint') not in joints
                    or section.get('parent_link') != joints[section['joint']]['parent']
                    or not 0 < _number(section['max_reach_mm'], 'joint-loop maximum reach') <= 80):
                raise ValueError('Joint loops require the actual parent frame and a bounded local envelope')
            axial = section.get('axial_range_mm')
            if (not isinstance(axial, list) or len(axial) != 2
                    or _number(axial[0], 'pocket lower axial bound') >= _number(axial[1], 'pocket upper axial bound')):
                raise ValueError('Joint loops need an explicit axial pocket')
            if 'loop_fit' in section:
                _policy(section)
            if 'target_length_mm' in section:
                _number(section['target_length_mm'], 'joint material target', True)
        else:
            raise ValueError('Unknown physical hose section kind')
    if sequence[-1] != 'tip' or set(sequence[1:-1]) != set(recipe['clips']) or len(sequence) != len(set(sequence)):
        raise ValueError('Every physical clip must be visited exactly once from pump to tip')
    if any(value is not False for value in recipe.get('qualification', {}).values()):
        raise ValueError('Clip fit, retention and continuous motion remain unqualified')
    return True


def frames(spec, p, link_frames, mounted, context):
    """Evaluate sockets and real clip grooves from the one source recipe."""
    values = {**context.get('parameters', {}), **p}
    interfaces = context['connection_interfaces']
    if callable(interfaces):
        interfaces = interfaces(spec, p, mounted)
    result = {'pump': framed._socket_frame(interfaces['pump'], False),
              'tip': framed._socket_frame(interfaces['tip'], True)}
    for name, clip in spec['hose_routing']['clips'].items():
        matrix = link_frames[clip['link']]
        tangent = hose._unit(_direction(matrix, _vector(clip['tangent'], values)))
        x = hose._unit(_direction(matrix, _vector(clip['x_axis'], values)))
        center = robot.transform(matrix, _vector(clip['center_mm'], values))
        result[name] = {'center_mm': center, 'tangent': tangent, 'x_axis': x,
            'y_axis': hose._cross(tangent, x), 'link': clip['link'],
            'body_id': clip['body_id'], 'host_body': clip['host_body'],
            'clamp_length_mm': p['hoseClipLength'],
            'start_mm': hose._sub(center, hose._mul(tangent, p['hoseClipLength']/2)),
            'end_mm': hose._add(center, hose._mul(tangent, p['hoseClipLength']/2))}
    return result


def _endpoints(section, evaluated, matrix):
    first, second = evaluated[section['from']], evaluated[section['to']]
    inv = robot.inverse(matrix)
    return (robot.transform(inv, first['end_mm']), robot.transform(inv, second['start_mm']),
            hose._unit(_direction(inv, first['tangent'])), hose._unit(_direction(inv, second['tangent'])))


def _fixed(section, evaluated, link_frames, p, values, step):
    matrix = link_frames[section['link']]
    start, end, t0, t1 = _endpoints(section, evaluated, matrix)
    controls = [_vector(point, values) for point in section['controls']]
    if max(math.dist(start, controls[0]), math.dist(end, controls[-1])) > TOLERANCE_MM:
        raise SectionFitError('Fixed controls do not meet the physical clip/socket exits', {'section': section['id']})
    lead = p['clipFreeLead']
    if len(controls) == 2:
        local = curves.biarc_path(start, end, t0, t1, p['hoseBendRadius'],
                                  endpoint_straights_mm=(lead, lead), sample_step_mm=step)
    else:
        local = hose.centerline(controls, p['hoseBendRadius'], step,
                                endpoint_straights_mm=(lead, lead))
        first = curves.path_position(local, 0)['tangent']
        last = curves.path_position(local, local['length_mm'])['tangent']
        if min(hose._dot(first,t0), hose._dot(last,t1)) < 1-1e-9:
            raise SectionFitError('A fixed run has the wrong clip-exit tangent', {'section': section['id']})
    return _transform(local, matrix, step)


def _policy(section):
    policy = section.get('loop_fit')
    required = {'outward', 'shift_axis', 'heights_mm', 'shifts_mm', 'middle_modes',
                'handle_lengths_mm', 'families', 'subdivisions', 'length_increment_mm'}
    if not isinstance(policy, dict) or set(policy) != required:
        raise SectionFitError('Joint loop needs an explicit bounded family policy', {'section': section['id']})
    for key in ('heights_mm','shifts_mm','handle_lengths_mm'):
        if not isinstance(policy[key], list) or not policy[key]:
            raise ValueError('Empty finite loop candidate set')
        for value in policy[key]:
            _number(value, key)
        if sorted(set(policy[key])) != policy[key]:
            raise ValueError('Loop candidate sets must be unique and increasing')
    for key in ('outward','shift_axis'):
        hose._unit(_vector(policy[key], {}))
    if (set(policy['families'])-{'biarc_pair','quintic_biarcs'} or not policy['families']
            or set(policy['middle_modes'])-{'chord','average','up','down','minus_x','minus_y','plus_x','seed'}
            or not policy['middle_modes'] or min(policy['handle_lengths_mm']) <= 0
            or type(policy['subdivisions']) is not int or not 2 <= policy['subdivisions'] <= 16):
        raise ValueError('Unsupported bounded local-loop construction policy')
    _number(policy['length_increment_mm'], 'target length increment', True)
    return policy


def _bezier(points, t):
    values = [list(point) for point in points]
    while len(values) > 1:
        values = [hose._add(hose._mul(a,1-t),hose._mul(b,t)) for a,b in zip(values,values[1:])]
    return values[0]


def _loop(section, evaluated, link_frames, p, values, shape, step, context):
    matrix = link_frames[section['parent_link']]
    a,b,t0,t1 = _endpoints(section,evaluated,matrix)
    policy = _policy(section)
    if (shape.get('family') not in policy['families']
            or not min(policy['heights_mm']) <= _number(shape.get('height_mm'), 'selected loop height') <= max(policy['heights_mm'])
            or shape.get('shift_mm') not in policy['shifts_mm']):
        raise ValueError('Selected local-loop parameters are outside the declared family')
    lead = p['clipFreeLead']; radius = p['hoseBendRadius']
    start,end = hose._add(a,hose._mul(t0,lead)),hose._sub(b,hose._mul(t1,lead))
    outward = hose._unit(_vector(policy['outward'],values))
    shift_axis = hose._unit(_vector(policy['shift_axis'],values))
    offset = hose._add(hose._mul(outward,shape['height_mm']),hose._mul(shift_axis,shape['shift_mm']))
    rows = [_line(a,start)]
    if shape['family'] == 'biarc_pair':
        if set(shape) != {'family','height_mm','shift_mm','middle_mode'}:
            raise ValueError('Foreign local biarc shape parameters')
        mode = shape['middle_mode']
        if mode not in policy['middle_modes']:raise ValueError('Selected middle tangent is not in the source policy')
        if mode=='seed':
            seed=curves._biarc(start,end,t0,t1)
            seed_point,middle=curves._at(seed[0],1.)
            q=hose._add(seed_point,offset)
        else:
            q = hose._add(hose._mul(hose._add(start,end),.5),offset)
            middle = hose._unit(hose._sub(end,start)) if mode == 'chord' else hose._unit(hose._add(t0,t1)) if mode == 'average' else {
                'up':[0,0,1],'down':[0,0,-1],'minus_x':[-1,0,0],'minus_y':[0,-1,0],'plus_x':[1,0,0]}[mode]
        rows += curves.biarc_path(start,q,t0,middle,radius,sample_step_mm=step)['segments']
        rows += curves.biarc_path(q,end,middle,t1,radius,sample_step_mm=step)['segments']
    elif shape['family'] == 'quintic_biarcs':
        if set(shape) != {'family','height_mm','shift_mm','handle_mm'}:
            raise ValueError('Foreign local quintic shape parameters')
        handle = shape['handle_mm']
        if handle not in policy['handle_lengths_mm']:raise ValueError('Selected handle is not in the source policy')
        first,last = hose._add(start,hose._mul(t0,handle)),hose._sub(end,hose._mul(t1,handle))
        controls = [start,first,hose._add(first,offset),hose._add(last,offset),last,end]
        derivatives = [hose._mul(hose._sub(v,u),5) for u,v in zip(controls,controls[1:])]
        for index in range(policy['subdivisions']):
            lo,hi = index/policy['subdivisions'],(index+1)/policy['subdivisions']
            rows += curves.biarc_path(_bezier(controls,lo),_bezier(controls,hi),
                hose._unit(_bezier(derivatives,lo)),hose._unit(_bezier(derivatives,hi)),
                radius,sample_step_mm=step)['segments']
    else:
        raise ValueError('Unknown local-loop curve family')
    rows.append(_line(end,b))
    local = _path(rows,[a,b],radius,step)
    joint = next(row for row in context['arm']['joints'] if row['id'] == section['joint'])
    origin = _vector(joint['frame']['origin'], values)
    axis = hose._unit(_vector(joint['frame']['axis'], values))
    intervals = max(1, math.ceil(local['length_mm']/step));width = local['length_mm']/intervals
    reach, low, high = 0., math.inf, -math.inf
    for index in range(intervals):
        point = curves.path_position(local,(index+.5)*width)['point_mm'];delta = hose._sub(point,origin)
        axial = hose._dot(delta,axis)
        radial = math.sqrt(max(0.,hose._dot(delta,delta)-axial*axial))
        reach=max(reach,radial+width/2);low=min(low,axial-width/2);high=max(high,axial+width/2)
    if (reach > section['max_reach_mm']+TOLERANCE_MM or low < section['axial_range_mm'][0]-TOLERANCE_MM
            or high > section['axial_range_mm'][1]+TOLERANCE_MM):
        raise SectionFitError('Joint loop exceeds its source-defined joint-axis pocket',
            {'section':section['id'],'radial_upper_bound_mm':reach,'radial_limit_mm':section['max_reach_mm'],
             'axial_outer_bounds_mm':[low,high],'required_axial_range_mm':section['axial_range_mm']})
    world = _transform(local,matrix,step)
    world['local_reach'] = {'maximum_radial_reach_upper_bound_mm':reach,
        'required_maximum_radial_reach_mm':section['max_reach_mm'],
        'axial_range_outer_bound_mm':[low,high],'required_axial_range_mm':section['axial_range_mm'],
        'scope':'Static centerline joint-axis pocket over every exact-curve interval; no continuous pose coverage'}
    return world


def _check(path, section, link_frames, mounted, context):
    callback = context.get('external_clearance_check')
    if callback is None:
        raise RoutingEvidenceError('A source-only external clearance callback is required')
    trial = dict(path)
    trial['length_accounting'] = {'parts':[{'id':section['id'],'kind':'bare_span',
        'length_mm':path['length_mm'],'segment_start_index':0,'segment_count':len(path['segments'])}]}
    result = callback(trial,link_frames,mounted)
    if not isinstance(result,dict) or type(result.get('passed')) is not bool or not result.get('scope'):
        raise RoutingEvidenceError('Malformed section clearance evidence')
    try:
        json.dumps(result,allow_nan=False)
    except (TypeError,ValueError) as error:
        raise RoutingEvidenceError('Non-finite section clearance evidence') from error
    return result


def compile_sections(spec,p,link_frames,mounted,context,design):
    """Rebuild exact curves from source and per-section shape parameters."""
    recipe = spec['hose_routing'];step = recipe['sample_step_mm']
    evaluated = frames(spec,p,link_frames,mounted,context)
    state_id = context.get('state_id')
    selected = design.get('states',{}).get(state_id,{}).get('sections',{})
    values = {**context.get('parameters',{}),**p}
    segments,parts,records,stations = [],[],[],{}
    total = 0.
    def append(name,kind,path):
        nonlocal total
        start = len(segments);segments.extend(path['segments'])
        parts.append({'id':name,'kind':kind,'length_mm':path['length_mm'],
                      'segment_start_index':start,'segment_count':len(path['segments'])})
        total += path['length_mm']
    interfaces = context['connection_interfaces']
    if callable(interfaces):interfaces=interfaces(spec,p,mounted)
    def socket(name):
        points=[interfaces[name][key] for key in ('material_end_mm','socket_mouth_mm','unsupported_exit_mm','bend_start_mm')]
        kinds=['inserted','socket_strain_relief','connector_straight_lead']
        if name=='tip':points.reverse();kinds.reverse()
        for a,b,kind in zip(points,points[1:],kinds):append(name+'_'+kind,kind,_path([_line(a,b)],[],p['hoseBendRadius'],step))
    socket('pump')
    for section in recipe['sections']:
        if section['kind']=='fixed_link':
            path=_fixed(section,evaluated,link_frames,p,values,step);shape=None
        else:
            if section['id'] not in selected:
                raise SectionFitError('No independently selected local-loop shape for this state',
                    {'section':section['id'],'state':state_id})
            shape=selected[section['id']]['shape_parameters']
            path=_loop(section,evaluated,link_frames,p,values,shape,step,context)
        target=design['section_lengths_mm'][section['id']]
        if abs(path['length_mm']-target)>TOLERANCE_MM:
            raise SectionFitError('A physical section changed material length',
                {'section':section['id'],'expected_mm':target,'actual_mm':path['length_mm']})
        start=len(segments);append(section['id'],'bare_span',path)
        records.append({key:section[key] for key in ('id','kind','from','to','link','joint','parent_link') if key in section}|
            {'target_length_mm':target,'actual_length_mm':path['length_mm'],
             'segment_start_index':start,'segment_count':len(path['segments']),
             **({'shape_parameters':shape,'local_reach':path['local_reach']} if shape else {})})
        after=section['to']
        if after!='tip':
            clip=evaluated[after];stations[after]=total+p['hoseClipLength']/2
            append(after,'clip_straight',_path([_line(clip['start_mm'],clip['end_mm'])],[],p['hoseBendRadius'],step))
    socket('tip')
    control_order=['pump']+[section['to'] for section in recipe['sections']]
    controls=[evaluated[name]['center_mm'] for name in control_order]
    crossings={};crossing_indices={};joints={row['id']:row for row in context['arm']['joints']}
    for section in recipe['sections']:
        if section['kind']!='joint_loop':continue
        joint=joints[section['joint']];parent=link_frames[joint['parent']]
        origin=robot.transform(parent,_vector(joint['frame']['origin'],values))
        axis=hose._unit(_direction(parent,_vector(joint['frame']['axis'],values)))
        if section['to']=='tip':
            point=interfaces['tip']['unsupported_exit_mm'];frame_id='tip.unsupported_exit_mm'
            crossing_indices[joint['id']]=len(controls);controls.append(point)
        else:
            point=evaluated[section['to']]['center_mm'];frame_id=section['to']
            crossing_indices[joint['id']]=control_order.index(section['to'])
        delta=hose._sub(point,origin);radial=hose._sub(delta,hose._mul(axis,hose._dot(delta,axis)))
        crossings[joint['id']]={'frame_id':frame_id,'point_mm':point,'axis_origin_mm':origin,
            'axis_direction':axis,'radial_standoff_mm':math.sqrt(hose._dot(radial,radial))}
    result=_path(segments,controls,p['hoseBendRadius'],step)
    role=lambda kind:sum(v['length_mm'] for v in parts if v['kind']==kind)
    result.update({'routing_format':FORMAT,'routing_frames':evaluated,
        'clip_frames':{name:evaluated[name] for name in recipe['clips']},
        'clip_material_stations_mm':stations,'section_records':records,
        'framed_crossings':crossings,'crossing_control_indices':crossing_indices,
        'length_accounting':{'inserted_mm':role('inserted'),'socket_strain_relief_mm':role('socket_strain_relief'),
            'connector_straight_leads_mm':role('connector_straight_lead'),'clip_supported_mm':role('clip_straight'),
            'carrier_supported_mm':0.,'free_bare_spans_mm':role('bare_span'),
            'external_guide_straights_included_in_free_mm':0.,'total_mm':total,
            'sum_error_mm':total-result['length_mm'],'parts':parts,
            'scope':'Independent fixed-material sections and non-sliding clip stations; every physical region counted once'}})
    validate_material_path(result,p,design)
    return result


def validate_material_path(path,p,design=None):
    """Independently sum exact segment ranges, section targets and clip stations."""
    hose._path(path);hose._joined_path(path)
    segments=path['segments'];geometric_lengths=[_exact_length(row) for row in segments]
    prefix=[0.]
    for length in geometric_lengths:prefix.append(prefix[-1]+length)
    coverage=[0]*len(segments);at=0.;stations={};ids=set();lengths={};part_ranges={}
    next_index=0
    for part in path['length_accounting']['parts']:
        start,count=part['segment_start_index'],part['segment_count']
        if (part['id'] in ids or type(start)is not int or type(count)is not int
                or count<=0 or start!=next_index or start+count>len(segments)):
            raise ValueError('Duplicated or invalid physical material region')
        next_index=start+count
        ids.add(part['id']);exact=sum(geometric_lengths[start:start+count]);part_ranges[part['id']]=(start,count)
        if abs(exact-part['length_mm'])>TOLERANCE_MM:raise ValueError('Material region differs from its segments')
        for index in range(start,start+count):coverage[index]+=1
        if part['kind']=='clip_straight':
            if any(v['kind']!='line' for v in segments[start:start+count]):raise ValueError('A straight clip support cannot contain a bend')
            stations[part['id']]=prefix[start]+exact/2
        if part['kind']=='bare_span':lengths[part['id']]=exact
        at+=exact
    if any(v!=1 for v in coverage) or abs(at-path['length_mm'])>TOLERANCE_MM:
        raise ValueError('The material regions must partition the complete physical cut')
    roles={'inserted':'inserted_mm','socket_strain_relief':'socket_strain_relief_mm',
           'connector_straight_lead':'connector_straight_leads_mm','clip_straight':'clip_supported_mm',
           'bare_span':'free_bare_spans_mm'}
    account=path['length_accounting']
    if any(part['kind']not in roles for part in account['parts']):raise ValueError('Unknown physical material kind')
    for kind,key in roles.items():
        if abs(_number(account[key],key)-sum(v['length_mm'] for v in account['parts'] if v['kind']==kind))>TOLERANCE_MM:
            raise ValueError('Material category differs from its exact physical regions')
    if (account['carrier_supported_mm']!=0 or abs(account['total_mm']-at)>TOLERANCE_MM
            or abs(account['sum_error_mm'])>TOLERANCE_MM):raise ValueError('Invalid clipped-mode material total')
    if len(path['section_records'])!=len(lengths) or {v['id'] for v in path['section_records']}!=set(lengths):
        raise ValueError('Exact physical section coverage is required')
    for row in path['section_records']:
        start,count=row['segment_start_index'],row['segment_count'];exact=sum(geometric_lengths[start:start+count])
        if (row['id']not in lengths or part_ranges.get(row['id'])!=(start,count)
                or max(abs(exact-row['actual_length_mm']),abs(exact-row['target_length_mm']),abs(exact-lengths[row['id']]))>TOLERANCE_MM):
            raise ValueError('A fixed material section length changed')
    if set(stations)!=set(path['clip_material_stations_mm']) or any(abs(v-path['clip_material_stations_mm'][n])>TOLERANCE_MM for n,v in stations.items()):
        raise ValueError('A non-sliding physical clip changed its material station')
    if any(row['kind']=='arc' and row['radius_mm']<p['hoseBendRadius']-1e-9 for row in segments):
        raise ValueError('A hose bend is below the hard radius')
    if design is not None:
        if set(lengths)!=set(design['section_lengths_mm']) or any(abs(v-design['section_lengths_mm'][n])>TOLERANCE_MM for n,v in lengths.items()):
            raise ValueError('Material migrated between separately clamped sections')
        expected=design.get('clip_material_stations_mm')
        if expected is not None and (set(expected)!=set(stations) or any(abs(v-expected[n])>TOLERANCE_MM for n,v in stations.items())):
            raise ValueError('Clip stations differ from the fixed-material design')
    return {'passed':True,'section_lengths_mm':lengths,'clip_material_stations_mm':stations,'total_length_mm':at}


def _pose(value):
    if isinstance(value,dict):return value['frames'],value['mounted']
    return value


def _families(section):
    policy=_policy(section)
    for family in policy['families']:
        branches=policy['middle_modes'] if family=='biarc_pair' else policy['handle_lengths_mm']
        for branch in branches:
            for shift in policy['shifts_mm']:
                yield {'family':family,'shift_mm':shift,
                       **({'middle_mode':branch} if family=='biarc_pair' else {'handle_mm':branch})}


def _sample_loops(section,poses,evaluated,p,values,step,context):
    result={}
    for name,(link_frames,mounted) in poses.items():
        groups=[]
        for branch in _families(section):
            samples=[]
            for height in _policy(section)['heights_mm']:
                try:
                    path=_loop(section,evaluated[name],link_frames,p,values,{**branch,'height_mm':height},step,context)
                    samples.append({'height_mm':height,'length_mm':path['length_mm'],
                                    'reach_mm':path['local_reach']['maximum_radial_reach_upper_bound_mm']})
                except ValueError:samples.append({'height_mm':height,'length_mm':None})
            groups.append({'branch':branch,'samples':samples})
        result[name]=groups
    return result


def _support_probe(path,section,evaluated,p,step):
    """Screen neighbouring material without counting fictitious probe length."""
    first,last=evaluated[section['from']],evaluated[section['to']]
    before=[];after=[]
    if 'body_id'in first:
        before.append(_line(hose._sub(first['start_mm'],hose._mul(first['tangent'],p['clipFreeLead'])),first['start_mm']))
    before.append(_line(first['start_mm'],first['end_mm']))
    after.append(_line(last['start_mm'],last['end_mm']))
    if 'body_id'in last:
        after.append(_line(last['end_mm'],hose._add(last['end_mm'],hose._mul(last['tangent'],p['clipFreeLead']))))
    probe=_path(before+path['segments']+after,[],p['hoseBendRadius'],step)
    result=hose.self_clearance_diagnostics(probe,p['hoseOuterRadius'])
    result['screening_probe_only']=True
    result['scope']+=' Includes the two real support straights and clip-only source-parameter tangent continuations as a selection probe; these extra probe lengths are not material accounting.'
    return result


def _clip_keepouts(path,section,evaluated,p):
    """Keep nonlocal curve portions outside each endpoint groove's outer wall.

    The intended source-parameter exit/entry straight is the only excluded curve interval.
    Every other interval whose axial projection overlaps the finite groove
    must clear its conservative outside radius, with adaptive distance bounds.
    Actual split-clamp CSG and supports still require the native body checks.
    """
    required=2*p['hoseOuterRadius']+p['clipHoseGap']+p['clipWall']
    observations={};all_passed=True
    for endpoint in ('from','to'):
        name=section[endpoint];frame=evaluated[name]
        if 'body_id'not in frame:continue
        begin=p['clipFreeLead'] if endpoint=='from' else 0.
        end=path['length_mm']-p['clipFreeLead'] if endpoint=='to' else path['length_mm']
        intervals=max(1,math.ceil((end-begin)/2.));width=(end-begin)/intervals
        minimum=math.inf;witness=None;passed=True;checked=0
        for index in range(intervals):
            stack=[(begin+index*width,begin+(index+1)*width)]
            while stack:
                lo,hi=stack.pop();half=(hi-lo)/2;station=(lo+hi)/2
                point=curves.path_position(path,station)['point_mm'];delta=hose._sub(point,frame['center_mm'])
                axial=hose._dot(delta,frame['tangent']);groove=p['hoseClipLength']/2
                if axial+half < -groove or axial-half > groove:continue
                radial=math.sqrt(max(0.,hose._dot(delta,delta)-axial*axial))
                margin=radial-half-required;checked+=1
                candidate={'clip':name,'arc_length_mm':station,'interval_mm':[lo,hi],
                    'point_mm':point,'axial_mm':axial,'radial_mm':radial,
                    'required_radial_mm':required,'margin_lower_bound_mm':margin}
                if margin>=0:
                    if margin<minimum:minimum=margin;witness=candidate
                    continue
                if -groove<=axial<=groove and radial<required:
                    passed=False;witness=candidate;break
                if hi-lo<=.05:
                    passed=False;witness={**candidate,'classification':'inconclusive_at_minimum_interval'};break
                mid=(lo+hi)/2;stack.extend([(lo,mid),(mid,hi)])
            if not passed:break
        observations[name]={'passed':passed,'checked_intervals':checked,
            'minimum_margin_lower_bound_mm':minimum if math.isfinite(minimum) else None,'witness':witness}
        all_passed &= passed
    return {'passed':all_passed,'required_radial_clearance_mm':required,'clips':observations,
        'scope':'Conservative outer groove-cylinder reservation for nonlocal hose portions; intended local exit/entry straights excluded. No split-clamp or retention qualification.'}


def _solve_target(section,name,target,groups,evaluated,pose,p,values,step,context):
    link_frames,mounted=pose;brackets=[];rejections=[]
    for group in groups:
        for a,b in zip(group['samples'],group['samples'][1:]):
            if a['length_mm']is not None and b['length_mm']is not None and (a['length_mm']-target)*(b['length_mm']-target)<=0:
                brackets.append((max(a['reach_mm'],b['reach_mm']),group['branch'],a,b))
    for _,branch,a,b in sorted(brackets,key=lambda row:row[0]):
        lo,hi=a['height_mm'],b['height_mm'];sign=a['length_mm']-target
        try:
            for _ in range(40):
                h=(lo+hi)/2;shape={**branch,'height_mm':h};path=_loop(section,evaluated,link_frames,p,values,shape,step,context)
                if (path['length_mm']-target)*sign>0:lo=h
                else:hi=h
            shape={**branch,'height_mm':(lo+hi)/2};path=_loop(section,evaluated,link_frames,p,values,shape,step,context)
            if abs(path['length_mm']-target)>TOLERANCE_MM:continue
        except ValueError:continue
        # Reject an obvious finite-groove reservation hit before the quadratic
        # self screens. The candidate order and accepted set stay unchanged.
        keepouts=_clip_keepouts(path,section,evaluated,p)
        if not keepouts['passed']:
            rejections.append({'classification':'clip_outer_wall_reservation','shape_parameters':shape,'check':keepouts});continue
        selfcheck=hose.self_clearance_diagnostics(path,p['hoseOuterRadius'],sample_step_mm=.5)
        if not selfcheck['passed']:
            rejections.append({'classification':'self_crossing','shape_parameters':shape,'check':selfcheck});continue
        support_check=_support_probe(path,section,evaluated,p,step)
        if not support_check['passed']:
            rejections.append({'classification':'adjacent_support_crossing','shape_parameters':shape,'check':support_check});continue
        external=_check(path,section,link_frames,mounted,context)
        if not external['passed']:
            rejections.append({'classification':'source_envelope_proximity','shape_parameters':shape,'check':external});continue
        return {'shape_parameters':shape,'length_mm':path['length_mm'],'local_reach':path['local_reach'],
                'checks':{'passed':True,'self_clearance':selfcheck,'adjacent_support_self_clearance':support_check,
                          'clip_outer_wall_keepouts':keepouts,'external_clearance':external}},None
    return None,{'state':name,'section':section['id'],'target_length_mm':target,
                 'geometric_brackets':len(brackets),'rejections':rejections}


def design(spec,p,poses,context):
    """Demonstrate separate constant material targets; failed searches stay blocked."""
    recipe=spec['hose_routing'];step=recipe['sample_step_mm'];values={**context.get('parameters',{}),**p}
    poses={name:_pose(value) for name,value in poses.items()}
    if set(poses)!=set(spec['states']):raise ValueError('Every current named state is required')
    evaluated={name:frames(spec,p,*pose,context) for name,pose in poses.items()}
    proof={'format':PROOF_FORMAT,'passed':False,'status':'blocked','section_lengths_mm':{},'states':{
        name:{'passed':False,'joints_deg':spec['states'][name]['joints_deg'],'sections':{}} for name in poses},
        'failures':[],'search':{},'qualification':{'global_minimum_verified':False,
            'continuous_motion_verified':False,'clip_retention_verified':False,
            'pressure_flow_or_dosing_verified':False,'hardware_execution_implemented':False},
        'scope':'Separately fixed material lengths at named static poses; finite local curve families, not continuous motion or hardware qualification'}
    loop_data={}
    for section in recipe['sections']:
        if section['kind']=='fixed_link':
            lengths=[]
            for name,(link_frames,mounted) in poses.items():
                try:path=_fixed(section,evaluated[name],link_frames,p,values,step)
                except ValueError as error:
                    proof['failures'].append({'section':section['id'],'state':name,'error':str(error),'witness':getattr(error,'witness',None)});return proof
                check=_check(path,section,link_frames,mounted,context)
                if not check['passed']:
                    proof['failures'].append({'section':section['id'],'state':name,'classification':'fixed_run_source_proximity','check':check});return proof
                lengths.append(path['length_mm'])
                proof['states'][name]['sections'][section['id']]={'length_mm':path['length_mm'],'checks':{'passed':True,'external_clearance':check}}
            if max(lengths)-min(lengths)>TOLERANCE_MM:raise RoutingEvidenceError('Rigid link run changed length under FK')
            proof['section_lengths_mm'][section['id']]=lengths[0]
            continue
        try:samples=_sample_loops(section,poses,evaluated,p,values,step,context)
        except SectionFitError as error:
            proof['failures'].append({'section':section['id'],'error':str(error),'witness':error.witness});return proof
        loop_data[section['id']]=samples
        available={name:[v['length_mm'] for group in groups for v in group['samples'] if v['length_mm']is not None] for name,groups in samples.items()}
        if any(not v for v in available.values()):
            proof['failures'].append({'section':section['id'],'classification':'no_geometric_candidates','states':[n for n,v in available.items() if not v]});return proof
        lower=max(min(v) for v in available.values());upper=min(max(v) for v in available.values())
        increment=_policy(section)['length_increment_mm']
        targets=[section['target_length_mm']] if 'target_length_mm'in section else [increment*i for i in range(math.ceil(lower/increment),math.floor(upper/increment)+1)]
        trials=[];found=False
        for target in targets:
            selected={};failure=None
            for name,pose in poses.items():
                selected[name],failure=_solve_target(section,name,target,samples[name],evaluated[name],pose,p,values,step,context)
                if failure:break
            trials.append({'target_length_mm':target,'passed_state_count':len([v for v in selected.values() if v]),'failure':failure})
            if failure is None:
                proof['section_lengths_mm'][section['id']]=target
                for name,value in selected.items():proof['states'][name]['sections'][section['id']]=value
                found=True;break
        proof['search'][section['id']]={'sampled_geometric_hull_mm':[lower,upper],'trials':trials,
            'scope':'Hull is diagnostic; only the separately solved selected target is demonstrated'}
        if not found:
            proof['failures'].append({'section':section['id'],'classification':'no_common_fixed_material_target','trials':trials});return proof
    base=dict(proof['section_lengths_mm']);support=2*(p['hoseInsertionDepth']+p['strainReliefLength']+p['connectorStraightLead'])+len(recipe['clips'])*p['hoseClipLength']
    base_total=sum(base.values())+support;items=spec['hose_length_design']['allowances'];allowance=sum(_number(v['value_mm'],'cut allowance') for v in items)
    resolution=spec['hose_length_design']['cut_resolution_mm'];cut=math.ceil((base_total+allowance-1e-9)/resolution)*resolution
    allocation=next(section for section in reversed(recipe['sections']) if section['kind']=='joint_loop')
    extra=cut-base_total;target=base[allocation['id']]+extra
    for name,pose in poses.items():
        value,failure=_solve_target(allocation,name,target,loop_data[allocation['id']][name],evaluated[name],pose,p,values,step,context)
        if failure:
            proof['failures'].append({'classification':'allowance_allocation_not_feasible',**failure});return proof
        proof['states'][name]['sections'][allocation['id']]=value
    proof['section_lengths_mm'][allocation['id']]=target
    proof.update({'base_section_lengths_mm':base,'hose_length_mm':cut,'cut_selection':{
        'base_physical_length_mm':base_total,'allowances':items,'allowance_total_mm':allowance,
        'rounding_mm':cut-base_total-allowance,'cut_resolution_mm':resolution,
        'allocation_section':allocation['id'],'allocated_extra_mm':extra,'selected_cut_mm':cut,
        'scope':'All extra cut material is assigned once to one independently solved joint span; no sliding through clips'}})
    for name,(link_frames,mounted) in poses.items():
        path=compile_sections(spec,p,link_frames,mounted,{**context,'state_id':name},proof)
        selfcheck=hose.self_clearance_diagnostics(path,p['hoseOuterRadius'])
        callback=context['external_clearance_check'];external=callback(path,link_frames,mounted)
        if not isinstance(external,dict) or type(external.get('passed'))is not bool or not external.get('scope'):
            raise RoutingEvidenceError('Malformed whole-route clearance evidence')
        json.dumps(external,allow_nan=False)
        if not selfcheck['passed'] or not external['passed']:
            proof['failures'].append({'state':name,'classification':'whole_route_check','self_clearance':selfcheck,'external_clearance':external});return proof
        proximity_callback=context.get('proximity_check')
        if proximity_callback is None:raise RoutingEvidenceError('A source material closeness callback is required')
        proximity=proximity_callback(path,link_frames,mounted)
        if not isinstance(proximity,dict) or type(proximity.get('passed'))is not bool:
            raise RoutingEvidenceError('Malformed source material closeness evidence')
        json.dumps(proximity,allow_nan=False)
        if not proximity['passed']:
            proof['failures'].append({'state':name,'classification':'whole_route_closeness','check':proximity});return proof
        if 'clip_material_stations_mm'not in proof:proof['clip_material_stations_mm']=path['clip_material_stations_mm']
        validate_material_path(path,p,proof)
        proof['states'][name].update({'passed':True,'path':path,
            'checks':{'passed':True,'self_clearance':selfcheck,'external_clearance':external,'proximity':proximity}})
    proof['passed']=True;proof['status']='demonstrated'
    return proof
