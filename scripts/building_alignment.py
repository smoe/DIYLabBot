"""Shared-envelope registration with fixed vertical cores, never a survey.

Boundary landmarks map by arc length. New boundary corners split shared walls;
interior displacements are the harmonic extension of the boundary displacement.
This keeps one graph for floors, walls, openings and validation in both CADs.
"""
import copy
import math
import json
from functools import lru_cache
import relative_floorplan as floor
import building_roof as roof


def require(ok, message):
    if not ok: raise ValueError(message)


def contour(plan, selected=None):
    return roof.outer_contour(plan, selected or [a for a in plan['areas'] if a['kind'] != 'void'])


def validate(source):
    require(set(source)=={'method','reference','fixed_areas','landmarks','ground_apron','external_ground_support_area'}, 'Explicit envelope registration required')
    require(source['method']=='boundary_arclength_harmonic_displacement' and source['reference']=='roof.opaque_area_ids', 'Supported shared envelope registration required')
    require(source['external_ground_support_area']=='ExternalStairGround','Explicit exterior landing support required')
    require(source['fixed_areas']==['LiftCore','NorthCore','R3_028'], 'Lift and internal stair cores must remain fixed')
    require(set(source['landmarks'])=={'KG','EG'}, 'Both independently traced floors require landmarks')
    for pairs in source['landmarks'].values():
        require(len(pairs)>=4 and all(isinstance(v,list) and len(v)==2 and all(isinstance(n,str) for n in v) for v in pairs), 'Ordered source/target landmarks required')
        require(len({v[0] for v in pairs})==len(pairs)==len({v[1] for v in pairs}), 'Unique landmarks required')
    require(source['ground_apron']=={'path':['E003','E009','E010','E011','E004'],'facade_wall':'EW074'}, 'Explicit foyer apron anchors required')


def apron(plan, recipe):
    """Close the traced foyer recess without moving its shared stair wall."""
    path=recipe['path']; old=[]
    for a,b in zip(path,path[1:]):
        w=next(w for w in plan['walls'] if {w['start'],w['end']}=={a,b});old.append((w,1 if w['start']==a else -1))
    facade=recipe['facade_wall'];inner='AlignmentInner_'+facade
    for w,_ in old:
        if w['id']==facade:
            w['id']=inner
            for area in plan['areas']:
                for ref in area['boundary']:
                    if ref['wall']==facade:ref['wall']=inner
        if w['id']!= 'W104':w['kind']='open_boundary'
    plan['walls'].append({'id':facade,'start':path[0],'end':path[-1],'kind':'wall'})
    plan['areas'].append({'id':'EnvelopeFoyerApron','label':'Foyer envelope alignment','kind':'corridor','confidence':'approximate','boundary':[{'wall':facade,'direction':1}]+[{'wall':w['id'],'direction':-direction} for w,direction in reversed(old)]})
    floor.validate(plan)


def chain(edges,start,end):
    ids=[e['start'] for e in edges];i=ids.index(start);j=ids.index(end)
    return (edges+edges)[i:j if j>i else j+len(edges)]


def stations(edges,vertices):
    values=[0.0]
    for e in edges:values.append(values[-1]+math.dist(vertices[e['start']],vertices[e['end']]))
    require(values[-1]>0,'Nonzero landmark interval required')
    return [v/values[-1] for v in values]


def at(edges,vertices,ts,t):
    k=next((i for i in range(len(edges)) if t<=ts[i+1]+1e-12),len(edges)-1)
    f=max(0,min(1,(t-ts[k])/(ts[k+1]-ts[k])));e=edges[k]
    return [vertices[e['start']][j]+f*(vertices[e['end']][j]-vertices[e['start']][j]) for j in (0,1)]


def solve(matrix,rhs):
    """Small positive graph Laplacian, two displacement right-hand sides."""
    n=len(matrix)
    for k in range(n):
        pivot=max(range(k,n),key=lambda j:abs(matrix[j][k]));require(abs(matrix[pivot][k])>1e-14,'Disconnected registration graph')
        matrix[k],matrix[pivot]=matrix[pivot],matrix[k];rhs[k],rhs[pivot]=rhs[pivot],rhs[k]
        for i in range(k+1,n):
            f=matrix[i][k]/matrix[k][k]
            for j in range(k+1,n):matrix[i][j]-=f*matrix[k][j]
            for j in (0,1):rhs[i][j]-=f*rhs[k][j]
    out=[[0.,0.] for _ in range(n)]
    for i in reversed(range(n)):
        for axis in (0,1):out[i][axis]=(rhs[i][axis]-sum(matrix[i][j]*out[j][axis] for j in range(i+1,n)))/matrix[i][i]
    return out


def _register(plan,canonical,selected,source,level):
    validate(source);result=copy.deepcopy(plan)
    if level=='EG':
        apron(result,source['ground_apron'])
        result['areas']=[a for a in result['areas'] if a['id']!='ExternalStairGround']
        used={r['wall'] for a in result['areas'] for r in a['boundary']}
        result['walls']=[w for w in result['walls'] if w['id'] in used]
        result['openings']=[o for o in result['openings'] if o['wall'] in used]
        used={w[k] for w in result['walls'] for k in ('start','end')}
        result['vertices']={n:v for n,v in result['vertices'].items() if n in used}
    edges=contour(result);target=contour(canonical,selected);pairs=source['landmarks'][level]
    require(set(a for a,b in pairs)<= {e['start'] for e in edges} and set(b for a,b in pairs)<={e['start'] for e in target}, 'Landmarks must lie on both envelopes')
    # Corner insertion preserves the exact reference polyline, not just its bounds.
    fixed={};splits={};vertices=result['vertices']
    for (a,b),(c,d) in zip(pairs,pairs[1:]+pairs[:1]):
        left=chain(edges,a,c);right=chain(target,b,d);lt=stations(left,vertices);rt=stations(right,canonical['vertices'])
        for i,e in enumerate(left):fixed[e['start']]=at(right,canonical['vertices'],rt,lt[i])
        for t in rt[1:-1]:
            i=next(i for i in range(len(left)) if t<=lt[i+1]+1e-12)
            f=(t-lt[i])/(lt[i+1]-lt[i]);e=left[i]
            if f<1e-9 or f>1-1e-9:continue
            wall=next(w for w in result['walls'] if w['id']==e['wall'])
            f=f if wall['start']==e['start'] else 1-f
            splits.setdefault(wall['id'],[]).append((f,at(right,canonical['vertices'],rt,t)))
    newwalls=[];replacements={}
    for w in result['walls']:
        cut=sorted(splits.get(w['id'],[]));nodes=[w['start']]
        for k,(t,point) in enumerate(cut):
            name=w['id']+'_AlignV'+str(k);vertices[name]=[vertices[w['start']][j]+t*(vertices[w['end']][j]-vertices[w['start']][j]) for j in (0,1)];fixed[name]=point;nodes.append(name)
        nodes.append(w['end']);names=[];bounds=[0]+[t for t,_ in cut]+[1]
        for k,(a,b) in enumerate(zip(nodes,nodes[1:])):
            name=w['id'] if k==0 else w['id']+'_Align'+str(k);names.append(name);newwalls.append({**w,'id':name,'start':a,'end':b})
        replacements[w['id']]=(names,bounds)
    result['walls']=newwalls
    for area in result['areas']:
        boundary=[]
        for ref in area['boundary']:
            names,_=replacements[ref['wall']]
            boundary.extend({'wall':n,'direction':ref['direction']} for n in (names if ref['direction']==1 else reversed(names)))
        area['boundary']=boundary
    openings=[]
    for o in result['openings']:
        names,bounds=replacements[o['wall']];parts=[]
        for i,name in enumerate(names):
            a=max(o['interval'][0],bounds[i]);b=min(o['interval'][1],bounds[i+1])
            if b-a>1e-10:parts.append({**o,'wall':name,'interval':[(a-bounds[i])/(bounds[i+1]-bounds[i]),(b-bounds[i])/(bounds[i+1]-bounds[i])]})
        for i,part in enumerate(parts):part['id']=o['id'] if i==0 else o['id']+'_Align'+str(i)
        openings.extend(parts)
    result['openings']=openings
    # Core displacements are exactly zero; no floor-specific scale reaches them.
    for area in result['areas']:
        if area['id'] in source['fixed_areas']:
            for ref in area['boundary']:
                wall=next(w for w in result['walls'] if w['id']==ref['wall'])
                name=wall['start' if ref['direction']==1 else 'end']
                require(name not in fixed or math.dist(fixed[name],vertices[name])<1e-10,'Envelope conflicts with fixed vertical core')
                fixed[name]=vertices[name][:]
    neighbors={n:{} for n in vertices}
    for w in result['walls']:
        a,b=w['start'],w['end'];weight=1/max(math.dist(vertices[a],vertices[b]),1e-8)
        neighbors[a][b]=weight;neighbors[b][a]=weight
    # Triangulate each source face so narrow rooms cannot shear independently
    # across an unconnected face diagonal during registration.
    for area in result['areas']:
        nodes=floor.area_vertices(result,area)[:]
        while len(nodes)>3:
            ear=None
            for k,b in enumerate(nodes):
                a,c=nodes[k-1],nodes[(k+1)%len(nodes)]
                if ((vertices[b][0]-vertices[a][0])*(vertices[c][1]-vertices[a][1])-(vertices[b][1]-vertices[a][1])*(vertices[c][0]-vertices[a][0]))<=1e-12:continue
                tri=[vertices[a],vertices[b],vertices[c]]
                if any(floor.point_membership(vertices[n],tri)>=0 for n in nodes if n not in (a,b,c)):continue
                ear=k;weight=1/max(math.dist(vertices[a],vertices[c]),1e-8)
                neighbors[a][c]=weight;neighbors[c][a]=weight
                break
            require(ear is not None,'Source room triangulation failed: '+area['id'])
            nodes.pop(ear)
    unknown=[n for n in vertices if n not in fixed];indices={n:i for i,n in enumerate(unknown)}
    matrix=[[0.]*len(unknown) for _ in unknown];rhs=[[0.,0.] for _ in unknown]
    for name,i in indices.items():
        matrix[i][i]=sum(neighbors[name].values())
        for other,w in neighbors[name].items():
            if other in indices:matrix[i][indices[other]]-=w
            else:
                for axis in (0,1):rhs[i][axis]+=w*(fixed[other][axis]-vertices[other][axis])
    delta=solve(matrix,rhs)
    for name,i in indices.items():vertices[name]=[vertices[name][axis]+delta[i][axis] for axis in (0,1)]
    vertices.update(fixed)
    if level=='EG':
        boundary=chain(contour(result),'E113','E120')
        result['walls'].append({'id':'AlignmentStairOuter','start':'E120','end':'E113','kind':'open_boundary'})
        result['areas'].append({'id':'ExternalStairGround','label':'External stair ground footprint','kind':'stairwell','confidence':'approximate','boundary':[{'wall':e['wall'],'direction':-e['direction']} for e in reversed(boundary)]+[{'wall':'AlignmentStairOuter','direction':-1}]})
    floor.validate(result)
    return result


@lru_cache(maxsize=8)
def _cached(plan_json, canonical_json, selected_ids, source_json, level):
    canonical=json.loads(canonical_json)
    result=_register(json.loads(plan_json),canonical,[a for a in canonical['areas'] if a['id'] in selected_ids],json.loads(source_json),level)
    return json.dumps(result)


def register(plan, canonical, selected, source, level):
    # Key the actual geometry, not just metadata pins; callers receive fresh maps.
    return json.loads(_cached(json.dumps(plan,sort_keys=True),json.dumps(canonical,sort_keys=True),tuple(a['id'] for a in selected),json.dumps(source,sort_keys=True),level))
