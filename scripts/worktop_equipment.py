"""Reference-based placement of box-shaped office equipment on native-source tops."""
import math
import relative_floorplan as floor


def anchor(item, room, catalog, frames, operations, scale):
    ref=item['worktop_anchor']
    if (set(ref)!={'instance','uv'} or item['xyz_mm']!=[0,0,0] or item['yaw_deg']!=0
            or any(k in item for k in ('wall_span','opening_anchor'))):
        raise ValueError('Worktop equipment requires an unambiguous support-relative pose')
    uv=ref['uv']
    if (not isinstance(uv,list) or len(uv)!=2
            or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in uv)):
        raise ValueError('Worktop fractions must lie in [0,1]')
    support=next((v for v in room['instances'] if v['id']==ref['instance']),None)
    definition=None if support is None else catalog['types'].get(support['type'])
    if (not isinstance(definition,dict) or definition.get('recipe')!='desktop'
            or ref['instance'] not in frames):
        raise ValueError('Equipment must reference an existing desktop instance')
    body=room['id']+'_'+support['id']+'_'+definition['part_ids']['top']
    top=next(v['shape'] for v in operations if v['body']==body and v['action']=='create')
    origin,xaxis,yaxis=frames[support['id']]
    local=[[sum((q[i]-origin[i])*axis[i] for i in (0,1))/scale for axis in (xaxis,yaxis)] for q in top['points']]
    xy=[min(q[i] for q in local)+uv[i]*(max(q[i] for q in local)-min(q[i] for q in local)) for i in (0,1)]
    base=[origin[i]+scale*(xy[0]*xaxis[i]+xy[1]*yaxis[i]) for i in (0,1)]+[top['offset']+top['depth']]
    def placed(x,y,z):
        return [base[i]+scale*(xaxis[i]*x+yaxis[i]*y) for i in (0,1)]+[base[2]+scale*z]
    return placed,{'instance':item['id'],'support_instance':support['id'],'support_body':body,
        'origin_mm':base,'x_axis':xaxis,'y_axis':yaxis,'uv':uv,'dimensions_measured':False},top['points']


def check(placed_parts, polygon, height):
    for op in placed_parts['operations']:
        shape=op['shape']
        if (op['action']!='create' or shape['kind']!='polygon_prism'
                or shape['offset']<height-1e-6
                or any(floor.point_membership(p,polygon)<0 for p in shape['points'])):
            raise ValueError('Office equipment must fit entirely over its supporting top')
