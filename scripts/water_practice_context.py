"""Default L01 geometry equivalence across explicit composition-pin changes.

Original native reports stay immutable. This only admits the named pin/formula
changes when complete numeric room operations and all layout poses agree.
"""
import hashlib
import json
import subprocess
import sys

EQUIVALENCE_CANDIDATES={
    'model/lab-layout-l01.shared.json','model/lab-room-l01.shared.json',
    'model/furnishings/l01.furnishings.json','model/tr01-l01.motion.json',
    'model/tr01-l01-workcell.protocol.json','scripts/lab_layout_model.py'}

SNAPSHOT='''import sys,json
sys.path.insert(0,sys.argv[1]+'/scripts')
import lab_room_model as room,lab_layout_model as layout
s=room.load();p=room.parameters(s);e=room.expanded(s,p)
scene=layout.load(validate_builds=False);context=layout.parameters(scene)
result={'bodies':e['bodies'],'operations':[{**o,'shape':room.numeric_shape(o['shape'],p)} for o in e['operations']],
        'placements':{i['id']:layout.matrix(i,context) for i in scene['instances']}}
def normalize(v):
 if type(v) in (float,int):return float(round(v,6))
 if isinstance(v,list):return [normalize(x) for x in v]
 if isinstance(v,dict):return {k:normalize(x) for k,x in v.items()}
 return v
print(json.dumps(normalize(result),sort_keys=True,separators=(',',':')))
'''


def snapshot(root):
    return json.loads(subprocess.check_output([sys.executable,'-c',SNAPSHOT,str(root)],text=True))


def without_pins(value):
    if isinstance(value,dict):return {k:without_pins(v) for k,v in value.items() if k!='source_sha256'}
    if isinstance(value,list):return [without_pins(v) for v in value]
    return value


def verify(context,root,changed):
    if set(changed)-EQUIVALENCE_CANDIDATES:raise ValueError('Unsupported changed L01 sources: '+str(changed))
    for name in changed:
        if name.endswith('.json') and name!='model/furnishings/l01.furnishings.json':
            if without_pins(json.loads((context/name).read_text()))!=without_pins(json.loads((root/name).read_text())):
                raise ValueError('Changed L01 semantics beyond composition pins: '+name)
    old,new=snapshot(context),snapshot(root)
    if old!=new:raise ValueError('Default native L01 context is no longer geometrically equivalent')
    digest=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'passed':True,'scope':'Default room geometry and all layout poses only; not parameter variants',
            'numeric_rounding_mm':1e-6,'original_snapshot_sha256':digest(old),'current_snapshot_sha256':digest(new),
            'changed_sources':changed}
