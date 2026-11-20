"""Derived physical envelopes shared by BF01 navigation and motion.

The referenced TR01+camera source stays the sole construction authority.
Cutter primitives and nonphysical camera view cones never enlarge its hull.
"""
import math
import tr01_camera_model as camera


def vehicle_envelope(source=None):
    """Conservative physical primitive envelope, excluding viewing cones/cuts."""
    source = camera.expanded(camera.load()) if source is None else source
    lo,hi = [math.inf]*3,[-math.inf]*3
    physical={body['id'] for body in source['bodies'] if body['role'] != 'viewing_cone'}
    for op in source['operations']:
        if op['action'] != 'create' or op['body'] not in physical:
            continue
        shape = op['shape']; origin = shape['origin']
        if shape['kind'] == 'box':
            a,b = origin,[origin[k]+shape['size'][k] for k in range(3)]
        elif shape['kind'] == 'cylinder':
            axis = shape.get('axis',[0,0,1]); norm = math.sqrt(sum(v*v for v in axis)); axis=[v/norm for v in axis]
            radial=[shape['radius']*math.sqrt(max(0,1-v*v)) for v in axis]
            a=[origin[k]+min(0,axis[k]*shape['height'])-radial[k] for k in range(3)]
            b=[origin[k]+max(0,axis[k]*shape['height'])+radial[k] for k in range(3)]
        else:
            raise ValueError('Unsupported physical vehicle primitive')
        lo=[min(lo[k],a[k]) for k in range(3)];hi=[max(hi[k],b[k]) for k in range(3)]
    return {'min':lo,'max':hi,'length_mm':hi[0]-lo[0],'width_mm':hi[1]-lo[1],
            'height_mm':hi[2], 'radius_mm':max(math.hypot(x,y) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]))}

