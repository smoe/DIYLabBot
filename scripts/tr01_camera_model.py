"""Opt-in, empty TR01 awareness kit; the referenced transporter is immutable."""
from pathlib import Path
import copy
import hashlib
import json
import math
import re
import sample_transport_model as transport
import robot_spec

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/tr01-awareness-camera.shared.json'
SCHEMA = ROOT/'model/tr01-awareness-camera.schema.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schema_check(value, schema, document=None):
    """Strict local subset used by the kit and the existing camera contract."""
    document = schema if document is None else document
    if '$ref' in schema:
        file, _, fragment = schema['$ref'].partition('#')
        target = json.loads((ROOT/'model'/file).read_text()) if file else document
        sub = target
        for key in fragment.strip('/').split('/') if fragment else []:
            sub = sub[key]
        schema_check(value, sub, target)
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'number': type(value) in (int, float) and math.isfinite(value),
             'integer': type(value) is int, 'null': value is None, 'boolean': type(value) is bool}
    if types and not any(valid[t] for t in types): raise ValueError('Schema type: '+str(types))
    if 'const' in schema and json.dumps(value, sort_keys=True) != json.dumps(schema['const'], sort_keys=True):
        raise ValueError('Schema constant')
    if 'enum' in schema and value not in schema['enum']: raise ValueError('Schema enumeration')
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        if set(schema.get('required', []))-set(value): raise ValueError('Missing schema fields')
        for key, item in value.items():
            if key in properties: schema_check(item, properties[key], document)
            elif schema.get('additionalProperties') is False: raise ValueError('Unknown field: '+key)
            elif isinstance(schema.get('additionalProperties'), dict): schema_check(item, schema['additionalProperties'], document)
    elif isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', float('inf')): raise ValueError('Array length')
        for item in value: schema_check(item, schema.get('items', {}), document)
    elif isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or ('pattern' in schema and not re.fullmatch(schema['pattern'], value)):
            raise ValueError('Invalid string')
    elif type(value) in (int, float):
        if not math.isfinite(value): raise ValueError('Nonfinite number')
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf): raise ValueError('Numeric range')
        if value <= schema.get('exclusiveMinimum', -math.inf) or value >= schema.get('exclusiveMaximum', math.inf): raise ValueError('Numeric range')


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text())
    validate(spec)
    return spec


def validate(spec):
    schema_check(spec, json.loads(SCHEMA.read_text()))
    ref = spec['transport']
    path = (ROOT/ref['source']).resolve()
    if not path.is_relative_to(ROOT) or digest(path) != ref['source_sha256']: raise ValueError('Changed transporter source')
    base = transport.load(path)
    if not any(v['id'] == spec['variant'] for v in base['variants']): raise ValueError('Missing variant')
    camera = spec['camera']
    if camera['frame']['axis'] != [1,0,0] or camera['frame']['x'] != [0,-1,0]: raise ValueError('Forward optical frame required')
    if camera['purpose'] != 'awareness': raise ValueError('Awareness camera required')
    p = parameters(spec)
    for parameter, definition in spec['parameters'].items():
        if not definition['range'][0] <= p[parameter] <= definition['range'][1]: raise ValueError('Parameter outside declared range: '+parameter)
    for v in camera['body_size_mm']+[camera['lens']['radius_mm'],camera['lens']['length_mm'],camera['view']['range_mm'],camera['view']['far_radius_mm']]:
        if robot_spec.evaluate(v,p) <= 0: raise ValueError('Positive camera dimensions required')
    if any(camera['connection'][k] is not None for k in ['interface','cable','strain_relief','max_frame_age_ms']): raise ValueError('Hardware not selected')
    if camera['connection']['controller'] != 'TR01_unselected_controller' or camera['connection']['route_links'] != ['Car']: raise ValueError('Invalid kit connection')
    expanded(spec)
    return spec


def parameters(spec, overrides=None):
    base = transport.load(ROOT/spec['transport']['source'])
    p = transport.parameters(base)
    source = transport.expanded(base,p,next(v for v in base['variants'] if v['id']==spec['variant']))
    operations = {o['id']:o['shape'] for o in source['operations']}
    chassis, sensor = operations['ChassisBlank'], operations['NavigationSensor']
    p.update(chassis_top=chassis['origin'][2]+chassis['size'][2],
             navigation_top=sensor['origin'][2]+sensor['height'],
             navigation_front=sensor['origin'][0]+sensor['radius'])
    overrides = {} if overrides is None else overrides
    if set(overrides)-set(spec['parameters']): raise ValueError('Unknown kit parameter override')
    for name, definition in spec['parameters'].items():
        value = overrides.get(name, definition['expression'])
        if type(value) not in (int,float) or not math.isfinite(value): raise ValueError('Finite kit parameter required')
        if not definition['range'][0] <= value <= definition['range'][1]: raise ValueError('Parameter range: '+name)
        p[name] = value
    return p


def expanded(spec, overrides=None):
    base = transport.load(ROOT/spec['transport']['source']);p=parameters(spec,overrides)
    out = transport.expanded(base,p,next(v for v in base['variants'] if v['id']==spec['variant']))
    removed = {b['id'] for b in out['bodies'] if b['role']=='closed_tube_reference_envelope'}
    out['bodies'] = [b for b in out['bodies'] if b['id'] not in removed]
    out['operations'] = [o for o in out['operations'] if o['body'] not in removed]
    c=spec['camera'];ev=lambda v:robot_spec.evaluate(v,p)
    origin=[ev(x) for x in c['frame']['origin']];w,h,d=map(ev,c['body_size_mm']);lens={k:ev(v) for k,v in c['lens'].items()}
    def body(name,role,kind,origin,color=None,opacity=1,**shape):
        out['bodies'].append({'id':name,'component':'Car','role':role,'appearance':{'color':color or c['color'],'opacity':opacity}})
        out['operations'].append({'id':name,'body':name,'action':'create','shape':{'kind':kind,'origin':origin,**shape}})
    body(c['id']+'_Body','camera_envelope','box',[origin[0]-lens['length_mm']-d,-w/2,origin[2]-h/2],size=[d,w,h])
    body(c['id']+'_Lens','camera_envelope','cylinder',[origin[0]-lens['length_mm'],0,origin[2]],radius=lens['radius_mm'],height=lens['length_mm'],axis=[1,0,0])
    for i,box in enumerate(c['mount_boxes']):
        body(c['id']+'_Mount'+str(i),'camera_mount','box',list(map(ev,box['origin'])),size=list(map(ev,box['size'])))
    view=c['view'];distance=ev(view['range_mm'])
    body(c['id']+'_View','viewing_cone','cone',[origin[0]+distance,0,origin[2]],radius=ev(view['far_radius_mm']),top_radius=0,height=distance,axis=[-1,0,0],opacity=view['opacity'])
    # Geometry checks from the same lowered operations; conservative AABBs here,
    # independent exact BRep distances are checked by the native adapter.
    physical=[o for o in out['operations'] if o['body'].startswith(c['id']) and not o['body'].endswith('_View')]
    for op in physical:
        s=op['shape'];size=s['size'] if s['kind']=='box' else [s['height'],2*s['radius'],2*s['radius']]
        if min(size)<=0 or not all(math.isfinite(v) for v in s['origin']+size): raise ValueError('Invalid camera primitive')
        # The kit must remain below the named load deck and ahead of cassettes.
        top=s['origin'][2]+(size[2] if s['kind']=='box' else s['radius'])
        if top>=p['floor_deck_z']-12: raise ValueError('Camera intrudes into cassette/cover region')
    out.update(camera_frame={'id':c['id']+'.Optical','origin_mm':origin,'axis':[1,0,0],'x':[0,-1,0]},
               omitted_load_bodies=sorted(removed),parameters=p)
    return out


def solidcraft_commands(source):
    commands=[]
    for o in source['operations']:
        s=o['shape'];args={'name':o['id'],'operation':'new' if o['action']=='create' else o['action']}
        if o['action']=='create':args['body_name']=o['body']
        else:args['targets']=[o['body']]
        if s['kind']=='box':args.update(corner=s['origin'],**dict(zip(['length','width','height'],s['size'])))
        else:
            args.update(base=s['origin'],axis=s['axis'],radius=s['radius'],height=s['height'])
            if s['kind']=='cone':args['top_radius']=s['top_radius']
        commands.append({'command':'solid.'+s['kind'],'params':args})
    commands.append({'command':'component.create','params':{'name':'Car','parent':'root','activate':False,'grounded':True}})
    commands.append({'command':'component.move_bodies','params':{'component':'Car','bodies':[b['id'] for b in source['bodies']]}})
    commands += [{'command':'appearance.assign','params':{'bodies':[b['id']],**b['appearance']}} for b in source['bodies']]
    return commands
