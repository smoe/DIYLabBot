"""Derive an opt-in empty-arm browser command from the existing L01 instance.

No arm geometry, construction frame or instance pose is copied into this source.
Endpoint curves use the common quintic PVA evaluator; the stop time warp has
conservative chain-rule derivative bounds. Collision qualification is separate.
"""
import json
import math
from pathlib import Path
import lab_layout_model as layout
import robot_spec as robot
from sample_motion import motion

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/walkthrough-robot-commands.json'


def load():
    s = json.loads(SOURCE.read_text())
    if set(s) != {'format','laboratory','instance','label','demo_offset_deg','stop_ramp_s','empty_joint_limits','basis','human_comparison'}:
        raise ValueError('Unexpected robot command profile fields')
    if any(not isinstance(s[k],str) or not s[k] for k in ('laboratory','instance','label','basis')) or s['human_comparison'] is not None:
        raise ValueError('Named simulation instance and explicit missing human comparison required')
    if s['format'] != 'solidcraftbot.walkthrough-robot-commands/1':
        raise ValueError('Unknown robot command profile')
    if len(s['demo_offset_deg']) != 6 or any(type(x) not in (int, float) or not math.isfinite(x) for x in s['demo_offset_deg']):
        raise ValueError('Six finite demo offsets required')
    if type(s['stop_ramp_s']) not in (int,float) or not 0.1 <= s['stop_ramp_s'] <= 2:
        raise ValueError('Bounded positive stop ramp required')
    if set(s['empty_joint_limits']) != {'velocity_deg_s', 'acceleration_deg_s2', 'jerk_deg_s3'} or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in s['empty_joint_limits'].values()):
        raise ValueError('Positive empty-arm limits required')
    return s


def points(start, end, duration):
    return [{'time_s': t, 'positions_rad': [math.radians(v) for v in q],
             'velocities_rad_s': [0.]*6, 'accelerations_rad_s2': [0.]*6}
            for t, q in ((0., start), (duration, end))]


def curve_bounds(start, end, duration, ramp):
    b = motion.bounds(points(start, end, duration))
    v, a, j = [list(map(math.degrees, b[field]['max_abs'])) for field in motion.FIELDS[1:]]
    # During braking: dt_virtual/dt in [0,1], |d2t/dt2|<=1.5/B,
    # |d3t/dt3|<=6/B². This bounds any stop instant and either direction.
    return {'velocity_deg_s': v,
            'acceleration_deg_s2': [a[i]+v[i]*1.5/ramp for i in range(6)],
            'jerk_deg_s3': [j[i]+3*a[i]*1.5/ramp+v[i]*6/ramp**2 for i in range(6)]}


def duration(start, end, s):
    if start == end:
        return 0.
    lo, hi = 0.001, 60.
    for _ in range(45):
        t = (lo+hi)/2
        b = curve_bounds(start, end, t, s['stop_ramp_s'])
        if all(max(b[k]) <= limit for k, limit in s['empty_joint_limits'].items()): hi=t
        else: lo=t
    return hi*1.000001


def compile(interface):
    s = load()
    lab = next(l for l in interface['laboratories'] if l['id'] == s['laboratory'])
    source = json.loads((ROOT/lab['layout_source']['source']).read_text())
    item = next(i for i in source['instances'] if i['id'] == s['instance'] and i['asset']=='arm')
    device = next(d for d in lab['device_instances'] if d['id']==item['id'])
    spec = layout.instance_source(source, item)
    expanded = robot.expanded(spec)
    p = robot.parameters(spec)
    reference = item['joints_deg']
    demo = [a+b for a,b in zip(reference, s['demo_offset_deg'])]
    for joint, a, b in zip(spec['joints'], reference, demo):
        if not joint['limits_deg'][0] <= min(a,b) <= max(a,b) <= joint['limits_deg'][1]:
            raise ValueError('Robot demo outside joint limits')
    fk = robot.forward(spec, reference)
    prefix = lab['id']+'.'+item['id']
    by_link = {link['id']: [device['body_prefix']+op['body'] for op in link['recipe'] if op['action']=='create' and op['role']!='viewing_cone' and op['body'] not in item.get('exclude_bodies',[])] for link in expanded['links']}
    objects = []
    for index, joint in enumerate(spec['joints']):
        frame = robot.multiply(device['world_pose'], robot.multiply(fk[joint['parent']],robot.frame(joint,p)))
        target = [frame[i][3] for i in range(3)]
        objects.append({'id':prefix+'.'+joint['id'], 'scene':'building', 'level_id':lab['level_id'],
            'mechanism':'robot_joint', 'robot_id':prefix, 'label':s['label'],
            'joint':{'type':'revolute','origin_mm':target,'axis':[frame[i][2] for i in range(3)]},
            'moving_body_ids':by_link[joint['child']], 'states':{'reference':reference[index]},
            'reference_state':'reference', 'state_labels':{'reference':'Ausgangsstellung'},
            'commands':{}, 'duration_s':1.,
            **({'parent_object_id':objects[-1]['id']} if objects else {})})
    target = robot.transform(robot.multiply(device['world_pose'],fk[spec['joints'][-1]['child']]),
                             [robot.evaluate(v,p) for v in spec['flange_reference']['point']])
    eye = robot.transform(device['world_pose'],[700,-900,800])
    objects[0]['viewpoint']={'eye_mm':eye,'target_mm':target}
    T = duration(reference,demo,s)
    robot_config = {'id':prefix, 'label':s['label'], 'scene':'building','level_id':lab['level_id'],
        'joint_object_ids':[o['id'] for o in objects], 'reference_deg':reference,'demo_deg':demo,
        'joint_limits_deg':[j['limits_deg'] for j in spec['joints']],
        'trigger_body_ids':[v for values in by_link.values() for v in values],
        'duration_s':T,'stop_ramp_s':s['stop_ramp_s'], 'limits':s['empty_joint_limits'],
        'derivative_bounds':curve_bounds(reference,demo,T,s['stop_ramp_s']),
        'basis':s['basis'], 'human_comparison':s['human_comparison'],
        'qualification':{'hardware':False,'collision':False,'human_speed_comparison':False},
        'commands':{'demo':'Demobewegung','home':'Grundstellung','stop':'Stopp'}}
    return objects,[robot_config]


def dependencies():
    return [SOURCE,Path(__file__),ROOT/'scripts/templates/quintic_motion.js',
            ROOT/'scripts/walkthrough_robots.js',ROOT/'scripts/sample_motion.py',
            ROOT/'ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py']
