"""Referenced roof polygons and an analytic, hollow barrel-glass illustration.

All millimetres are presentation assumptions. No structural, weather-sealing,
guard, drainage, headroom or fire-safety qualification is provided.
"""
import math

import relative_floorplan as floor


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value):
    require(type(value) in (int, float) and math.isfinite(value) and value > 0, 'Positive finite roof assumption required')
    return value


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def outer_contour(plan, selected):
    """Cancel shared source walls and follow the one positive exterior loop.

    Hole contours retain the opposite orientation and never receive a guard.
    No bounding rectangle or convex hull substitutes for the traced contour.
    """
    walls = {wall['id']: wall for wall in plan['walls']}; uses = {}
    for area in selected:
        for ref in area['boundary']:
            uses.setdefault(ref['wall'], []).append(ref['direction'])
    edges = []
    for name, directions in uses.items():
        require(len(directions) <= 2 and (len(directions) == 1 or sum(directions) == 0), 'Non-manifold selected roof boundary')
        if len(directions) == 2:
            continue
        wall = walls[name]; direction = directions[0]
        edges.append({'wall': name, 'direction': direction, 'start': wall['start' if direction == 1 else 'end'], 'end': wall['end' if direction == 1 else 'start']})
    outgoing = {}
    for edge in edges:
        outgoing.setdefault(edge['start'], []).append(edge)
    require(all(len(group) == 1 for group in outgoing.values()), 'Ambiguous roof contour junction')
    remaining = {edge['wall']: edge for edge in edges}; loops = []
    while remaining:
        start = next(iter(remaining.values())); current = start; loop = []
        while True:
            require(current['wall'] in remaining, 'Roof boundary must form closed simple loops')
            remaining.pop(current['wall']); loop.append(current)
            if current['end'] == start['start']:
                break
            require(current['end'] in outgoing, 'Open roof contour')
            current = outgoing[current['end']][0]
        points = [plan['vertices'][edge['start']] for edge in loop]
        if floor.signed_area(points) > 0:
            loops.append(loop)
    require(len(loops) == 1, 'Exactly one connected outer roof contour is supported')
    return loops[0]


def boundary_loops(plan, selected):
    walls = {w['id']: w for w in plan['walls']}; uses = {}
    for area in selected:
        for ref in area['boundary']: uses.setdefault(ref['wall'], []).append(ref['direction'])
    edges = []
    for name, directions in uses.items():
        require(len(directions) <= 2 and (len(directions) == 1 or sum(directions) == 0), 'Non-manifold glass area union')
        if len(directions) == 1:
            wall = walls[name]; d = directions[0]
            edges.append({'wall': name, 'start': wall['start' if d == 1 else 'end'], 'end': wall['end' if d == 1 else 'start']})
    outgoing = {}
    for edge in edges: outgoing.setdefault(edge['start'], []).append(edge)
    require(all(len(items) == 1 for items in outgoing.values()), 'Ambiguous glass union junction')
    remaining = {e['wall']: e for e in edges}; loops = []
    while remaining:
        first = next(iter(remaining.values())); edge = first; loop = []
        while True:
            require(edge['wall'] in remaining, 'Glass boundary must close')
            remaining.pop(edge['wall']); loop.append(edge)
            if edge['end'] == first['start']: break
            require(edge['end'] in outgoing, 'Open glass boundary')
            edge = outgoing[edge['end']][0]
        loops.append(loop)
    return loops


def simplify(points):
    result = []
    for point in points:
        if not result or math.dist(point, result[-1]) > 1e-8: result.append(point)
    if len(result) > 1 and math.dist(result[0], result[-1]) < 1e-8: result.pop()
    changed = True
    while changed and len(result) > 3:
        changed = False
        for i in range(len(result)):
            a,b,c = result[i-1],result[i],result[(i+1)%len(result)]
            u=[b[j]-a[j] for j in (0,1)];v=[c[j]-b[j] for j in (0,1)]
            if abs(u[0]*v[1]-u[1]*v[0]) <= 1e-7 and sum(u[j]*v[j] for j in (0,1)) >= 0:
                result.pop(i);changed=True;break
    return result


def offset_polygon(points, distances):
    """Bounded miter offset; source collinear transitions retain explicit steps."""
    lines=[]
    for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy);nx,ny=dy/length,-dx/length;d=distances[i]
        lines.append(([a[0]+nx*d,a[1]+ny*d],[b[0]+nx*d,b[1]+ny*d]))
    result=[]
    for i,(c,d) in enumerate(lines):
        a,b=lines[i-1];u=[b[j]-a[j] for j in (0,1)];v=[d[j]-c[j] for j in (0,1)];cross=u[0]*v[1]-u[1]*v[0]
        if abs(cross) < 1e-8:
            result.extend([b,c]);continue
        q=[c[j]-a[j] for j in (0,1)];t=(q[0]*v[1]-q[1]*v[0])/cross
        result.append([a[j]+t*u[j] for j in (0,1)])
    result=simplify(result)
    require(len(result)>=3 and floor.signed_area(result)>0, 'Offset glass footprint collapsed')
    for i,(a,b) in enumerate(zip(result,result[1:]+result[:1])):
        for j,(c,d) in enumerate(zip(result,result[1:]+result[:1])):
            if i==j or (i-j)%len(result) in (1,len(result)-1):continue
            require(not(floor.side(a,b,c)*floor.side(a,b,d)==-1 and floor.side(c,d,a)*floor.side(c,d,b)==-1),'Offset glass footprint intersects itself')
    return result


def complement_trapezoids(polygon):
    """Exact piecewise-linear complement inside the footprint bounding box."""
    xs=sorted(set(p[0] for p in polygon));bottom=min(p[1]for p in polygon);top=max(p[1]for p in polygon);result=[]
    for left,right in zip(xs,xs[1:]):
        if right-left<1e-8:continue
        middle=(left+right)/2
        edges=[(a,b) for a,b in zip(polygon,polygon[1:]+polygon[:1]) if min(a[0],b[0])<middle<max(a[0],b[0])]
        def y(edge,x):
            if isinstance(edge,(int,float)):return edge
            a,b=edge;return a[1]+(x-a[0])*(b[1]-a[1])/(b[0]-a[0])
        edges.sort(key=lambda e:y(e,middle));require(len(edges)%2==0,'Invalid glass mask parity')
        outside=[(bottom,edges[0])] if edges else [(bottom,top)]
        outside.extend((edges[i],edges[i+1]) for i in range(1,len(edges)-1,2))
        if edges:outside.append((edges[-1],top))
        for lo,hi in outside:
            points=simplify([[left,y(lo,left)],[right,y(lo,right)],[right,y(hi,right)],[left,y(hi,left)]])
            if len(points)>=3 and floor.signed_area(points)>1e-6:result.append(points)
    return result


def validate_source(source):
    require(set(source) == {'id', 'opaque_area_ids', 'glass_area_ids', 'local_opaque_access', 'atrium_area', 'guard_gap_opening', 'barrel', 'guard', 'status'}, 'Explicit roof contract required')
    require(source['status'] == 'illustrative_unqualified', 'Roof is an unqualified presentation assumption')
    for key in ('id', 'atrium_area', 'guard_gap_opening'):
        floor.identity(source[key])
    selected = source['opaque_area_ids']
    require(isinstance(selected, list) and selected and len(selected) == len(set(selected)), 'Unique source roof-area references required')
    for name in selected:
        floor.identity(name)
    require(isinstance(source['glass_area_ids'],list) and source['glass_area_ids'] and len(set(source['glass_area_ids']))==len(source['glass_area_ids']),'Unique covered source areas required')
    for name in source['glass_area_ids']:floor.identity(name)
    access=source['local_opaque_access']
    require(set(access)=={'area','opening','depth_parameter','status'} and access['depth_parameter']=='slab_thickness_mm' and access['status']=='illustrative_unqualified','Explicit local external-stair access deck required')
    floor.identity(access['area']);floor.identity(access['opening'])
    barrel = source['barrel']; guard = source['guard']
    require(set(barrel) == {'axis', 'profile_segments', 'max_sagitta_fraction_of_glass_thickness', 'rise_mm', 'riser_mm', 'overhang_mm', 'glass_thickness_mm', 'color', 'opacity'}, 'Explicit barrel assumptions required')
    require(set(guard) == {'height_mm', 'post_width_mm', 'rail_width_mm', 'max_post_spacing_mm', 'color'}, 'Explicit guard assumptions required')
    for key in ('rise_mm', 'riser_mm', 'overhang_mm', 'glass_thickness_mm'):
        positive(barrel[key])
    for key in ('height_mm', 'post_width_mm', 'rail_width_mm', 'max_post_spacing_mm'):
        positive(guard[key])
    require(barrel['axis']=='X' and type(barrel['profile_segments']) is int and 16<=barrel['profile_segments']<=256,'Explicit X-axis barrel and bounded profile resolution required')
    require(type(barrel['max_sagitta_fraction_of_glass_thickness']) in (int,float) and 0<barrel['max_sagitta_fraction_of_glass_thickness']<=.25,'Facet error must be bounded against glass thickness')
    require(type(barrel['opacity']) in (int, float) and math.isfinite(barrel['opacity']) and 0 < barrel['opacity'] < 1, 'Transparent glass illustration required')
    for color in (barrel['color'], guard['color']):
        require(isinstance(color, str) and len(color) == 7 and color[0] == '#' and all(c in '0123456789abcdefABCDEF' for c in color[1:]), 'Explicit roof color required')


def compile(source, plan, p, levels):
    validate_source(source)
    scale = positive(p['display_scale']); slab = positive(p['slab_thickness_mm'])
    areas = {area['id']: area for area in plan['areas']}; wallmap = {wall['id']: wall for wall in plan['walls']}
    require(set(source['opaque_area_ids']) <= set(areas) and source['atrium_area'] in areas, 'Existing canonical roof areas required')
    require(source['atrium_area'] not in source['opaque_area_ids'], 'The atrium must remain a roof aperture under the curved glass')
    selected = [areas[name] for name in source['opaque_area_ids']]
    require(all(area['kind'] != 'void' for area in selected), 'Void areas cannot receive an opaque roof slab')
    contour = outer_contour(plan, selected)
    opening = next((item for item in plan['openings'] if item['id'] == source['guard_gap_opening']), None)
    require(opening is not None and opening['wall'] in {edge['wall'] for edge in contour}, 'Guard access gap must reference the actual outer contour')
    base = levels[-1]['clear_top_mm']; roof_z = base+slab
    result = {'components': [{'id': source['id'], 'grounded': True}], 'bodies': [], 'operations': []}
    def body(name, role, color, opacity=1):
        result['bodies'].append({'id': name, 'component': source['id'], 'role': role, 'appearance': {'color': color, 'opacity': opacity}})
        return name
    def op(name, target, shape, action='create'):
        result['operations'].append({'id': name, 'body': target, 'action': action, 'shape': shape})
    def prism(name, target, points, z, depth, action='create'):
        op(name, target, {'kind': 'polygon_prism', 'plane': 'XY', 'points': points, 'offset': z, 'depth': depth, 'fixed': True}, action)
    def box(name, target, origin, size, action='create'):
        op(name, target, {'kind': 'box', 'origin': origin, 'size': size}, action)
    def probe(name, points, z, depth, targets, expectation):
        item = {'id': name, 'kind': 'polygon_prism', 'points_mm': points, 'offset_mm': z, 'depth_mm': depth,
                'target_bodies': targets, 'expectation': expectation}
        if len(targets) == 1:
            item['target_body'] = targets[0]
        if expectation != 'empty':
            item['expected_volume_mm3'] = abs(floor.signed_area(points))*depth
        return item
    covered_ids=source['glass_area_ids'];require(set(covered_ids)<=set(areas),'Existing covered source areas required')
    require(source['atrium_area'] in covered_ids and {a['id']for a in plan['areas']if a['kind']=='corridor'}<=set(covered_ids),'Glass must cover Atrium and every source corridor')
    loops=boundary_loops(plan,[areas[name]for name in covered_ids])
    require(len(loops)==1,'The explicitly filled glass union must be one footprint without holes')
    glass_edges=loops[0];polygon=[[v*scale for v in plan['vertices'][edge['start']]]for edge in glass_edges]
    require(floor.signed_area(polygon)>0,'Positive glass footprint required')
    remaining=[area for area in selected if area['id']not in covered_ids];opaque=[]
    for area in remaining:
        name=body('RoofSlab_'+area['id'],'concept_roof_slab','#b7c1c6');opaque.append(name)
        prism(name+'_Profile',name,[[x*scale,y*scale]for x,y in floor.outline(plan,area)],base,slab)
    # Preserve only the local external stair contact; never a full opaque corridor roof.
    access=source['local_opaque_access'];entry=next((o for o in plan['openings']if o['id']==access['opening']),None)
    require(entry is not None and access['area']in covered_ids and access['area']in source['opaque_area_ids'],'Source-bound local roof access required')
    aw=wallmap[entry['wall']];aa,bb=[[v*scale for v in plan['vertices'][aw[k]]]for k in ('start','end')]
    require(abs(aa[0]-bb[0])<1e-7,'Local access deck requires the existing vertical source facade')
    alo,ahi=sorted(aa[1]+u*(bb[1]-aa[1])for u in entry['interval']);margin=min(p['display_thickness']*.1,(ahi-alo)*.1)
    access_points=rectangle(aa[0],alo+margin,aa[0]+slab,ahi-margin)
    require(all(floor.point_membership(q,[[x*scale,y*scale]for x,y in floor.outline(plan,areas[access['area']])])>=0 for q in access_points),'Local access deck leaves its referenced corridor')
    access_body=body('RoofSlab_'+access['area'],'concept_roof_access_deck','#b7c1c6');opaque.append(access_body)
    prism(access_body+'_LocalAccess',access_body,access_points,base,slab)
    barrel=source['barrel'];t=barrel['glass_thickness_mm'];over=barrel['overhang_mm'];rise=barrel['rise_mm'];riser=barrel['riser_mm']
    incident={}
    for area in plan['areas']:
        for ref in area['boundary']:incident.setdefault(ref['wall'],set()).add(area['id'])
    roof_area_ids={a['id']for a in remaining};distances=[over if incident[e['wall']]&roof_area_ids else 0 for e in glass_edges]
    glazing=offset_polygon(polygon,distances);inner=offset_polygon(glazing,[-t]*len(glazing))
    require(len(inner)==len(glazing) and all(floor.point_membership(q,glazing)==1 for q in inner),'Inset glazing rim must remain inside its mask')
    left,right=min(q[0]for q in glazing),max(q[0]for q in glazing);front,rear=min(q[1]for q in glazing),max(q[1]for q in glazing)
    cy=(front+rear)/2;half=(rear-front)/2;length=right-left
    require(t<min(rise,riser,over,length/4,half/4)and rise<half,'Positive hollow shallow barrel required')
    radius=(half*half+rise*rise)/(2*rise);edge_z=roof_z+riser;cz=edge_z+rise-radius
    count=barrel['profile_segments'];profile=[[front+(rear-front)*i/count,cz+math.sqrt(max(0.,radius**2-(front+(rear-front)*i/count-cy)**2))]for i in range(count+1)]
    sagitta=max(radius-math.sqrt(max(0.,radius**2-math.dist(a,b)**2/4))for a,b in zip(profile,profile[1:]))
    require(sagitta<=t*barrel['max_sagitta_fraction_of_glass_thickness'],'Skirt faceting exceeds its glass-thickness error budget')
    glass=body('RoofBarrelGlass','concept_curved_glass_roof',barrel['color'],barrel['opacity'])
    op(glass+'_OuterCylinder',glass,{'kind':'cylinder','radius':radius,'height':length,'origin':[left,cy,cz],'axis':[1,0,0]})
    op(glass+'_InnerCylinder',glass,{'kind':'cylinder','radius':radius-t,'height':length+2,'origin':[left-1,cy,cz],'axis':[1,0,0]},'cut')
    box(glass+'_LowerClip',glass,[left-1,cy-radius-1,cz-radius-1],[length+2,2*radius+2,roof_z-(cz-radius)+1],'cut')
    # Complement masks use only the established portable polygon-prism cuts.
    mask_cuts=complement_trapezoids(glazing)
    mask_cuts += [rectangle(left-1,cy-radius-1,right+1,front),rectangle(left-1,rear,right+1,cy+radius+1)]
    for i,points in enumerate(mask_cuts):prism(glass+'_Mask_'+str(i),glass,points,roof_z-1,edge_z+rise-roof_z+2,'cut')
    skirt=body('RoofGlassSkirt','concept_glass_roof_skirt',barrel['color'],barrel['opacity'])
    prism(skirt+'_OuterRim',skirt,glazing,roof_z,edge_z+rise-roof_z+1)
    prism(skirt+'_Inset',skirt,inner,roof_z-1,edge_z+rise-roof_z+3,'cut')
    # This closure is facetted, while the cap above remains an exact cylinder.
    skirt_profile=[[y,z-t/4]for y,z in profile]
    above=[*skirt_profile,[rear,edge_z+rise+2],[front,edge_z+rise+2]]
    op(skirt+'_FacetTop',skirt,{'kind':'polygon_prism','plane':'YZ','points':above,'offset':left-1,'depth':length+2,'fixed':True},'cut')
    guard = source['guard']; guard_ids = []; contour_data = []; gap = None
    post = guard['post_width_mm']; rail = guard['rail_width_mm']; height = guard['height_mm']
    require(rail < height and post < guard['max_post_spacing_mm'], 'Guard posts and rail require positive usable dimensions')
    for edge in contour:
        wall = wallmap[edge['wall']]; a, b = [[v*scale for v in plan['vertices'][wall[key]]] for key in ('start', 'end')]
        length_edge = math.dist(a, b); tangent = [(b[i]-a[i])/length_edge for i in (0, 1)]; normal = [-tangent[1], tangent[0]]
        intervals = [(0., 1.)]
        if edge['wall'] == opening['wall']:
            lo, hi = opening['interval']; margin = post/(2*length_edge)
            require(0 <= lo < hi <= 1, 'Valid source guard opening interval required')
            intervals = [(0., max(0., lo-margin)), (min(1., hi+margin), 1.)]
            gap = {'opening': opening['id'], 'wall': wall['id'], 'points_mm': [[a[i]+u*(b[i]-a[i]) for i in (0, 1)] for u in (lo, hi)]}
        contour_data.append({**edge, 'points_mm': [a, b]})
        for segment, (lo, hi) in enumerate(intervals):
            if hi-lo <= 1e-12:
                continue
            start = [a[i]+lo*(b[i]-a[i]) for i in (0, 1)]; end = [a[i]+hi*(b[i]-a[i]) for i in (0, 1)]
            def strip(center0, center1, width):
                return [[center0[i]-normal[i]*width/2 for i in (0, 1)], [center1[i]-normal[i]*width/2 for i in (0, 1)],
                        [center1[i]+normal[i]*width/2 for i in (0, 1)], [center0[i]+normal[i]*width/2 for i in (0, 1)]]
            name = body('RoofGuard_'+wall['id']+'_'+str(segment), 'concept_roof_perimeter_guard', guard['color']); guard_ids.append(name)
            prism(name+'_Rail', name, strip(start, end, rail), roof_z+height-rail, rail)
            n = max(1, math.ceil(math.dist(start, end)/guard['max_post_spacing_mm']))
            for index in range(n+1):
                center = [start[i]+index/n*(end[i]-start[i]) for i in (0, 1)]
                ends = [[center[i]+sign*tangent[i]*post/2 for i in (0, 1)] for sign in (-1, 1)]
                prism(name+'_Post'+str(index), name, strip(*ends, post), roof_z, height, 'join')
    require(gap is not None, 'The external fire-stair roof gap must survive contour derivation')
    inset=min(t/4,over/4,slab/4);supports=[]
    for i,(edge,distance)in enumerate(zip(glass_edges,distances)):
        if distance<=2*inset:continue
        a,b=polygon[i],polygon[(i+1)%len(polygon)];dx,dy=b[0]-a[0],b[1]-a[1];ll=math.hypot(dx,dy);normal=[dy/ll,-dx/ll];trim=min(ll*.1,over*.1)
        start=[a[j]+trim/ll*(b[j]-a[j])for j in(0,1)];end=[b[j]-trim/ll*(b[j]-a[j])for j in(0,1)]
        points=[[q[j]+normal[j]*dd for j in(0,1)]for q,dd in[(start,inset),(end,inset),(end,distance-inset),(start,distance-inset)]]
        if floor.signed_area(points)<0:points.reverse()
        supports.append(probe('RoofEave_'+edge['wall']+'_Support',points,base+inset,slab-2*inset,opaque,'union_filled'))
    # Pick a true interior source point, not the union bounding-box centre.
    seed=max((a for a in areas.values()if a['id']in covered_ids),key=lambda a:abs(floor.signed_area(floor.outline(plan,a))))
    seed_poly=[[x*scale,y*scale]for x,y in floor.outline(plan,seed)];center=[sum(q[i]for q in seed_poly)/len(seed_poly)for i in(0,1)]
    if floor.point_membership(center,polygon)!=1:
        candidates=[[left+(right-left)*(i+.5)/31,front+(rear-front)*(j+.5)/31]for i in range(31)for j in range(31)]
        center=next(q for q in candidates if floor.point_membership(q,polygon)==1)
    interior=probe('RoofGlass_HollowInterior',rectangle(center[0]-t,center[1]-t,center[0]+t,center[1]+t),roof_z+t,riser/2,[glass,skirt],'empty')
    cy_probe=cy;cx_probe=(left+right)/2
    # A source-derived X with room at crown Y is found from the actual mask.
    candidates=[left+(right-left)*(i+.5)/101 for i in range(101)]
    cx_probe=next(x for x in candidates if all(floor.point_membership(q,inner)==1 for q in rectangle(x-t,cy-t,x+t,cy+t)))
    crown=probe('RoofGlass_CrownMaterial',rectangle(cx_probe-t/8,cy-t/8,cx_probe+t/8,cy+t/8),edge_z+rise-.75*t,.5*t,[glass],'filled')
    rim_a,rim_b=glazing[0],glazing[1];rim_i,rim_j=inner[0],inner[1]
    rim_center=[sum(v[i]for v in[rim_a,rim_b,rim_i,rim_j])/4 for i in(0,1)]
    rim_half=min(t/16,1.)
    skirt_material=probe('RoofGlass_SkirtMaterial',rectangle(rim_center[0]-rim_half,rim_center[1]-rim_half,rim_center[0]+rim_half,rim_center[1]+rim_half),roof_z+t,riser/2,[skirt],'filled')
    aperture_probes=[probe('RoofGlass_'+name+'_Aperture',[[x*scale,y*scale]for x,y in floor.outline(plan,areas[name])],base+inset,slab-2*inset,[target for target in opaque if target!=access_body],'empty')for name in covered_ids]
    corridor_coverage=[probe('RoofGlass_'+name+'_Coverage',[[x*scale,y*scale]for x,y in floor.outline(plan,areas[name])],roof_z,edge_z+rise-roof_z+1,[glass],'filled')for name in covered_ids if areas[name]['kind']=='corridor']
    for item,name in zip(corridor_coverage,[name for name in covered_ids if areas[name]['kind']=='corridor']):
        item['area_id']=name;item.pop('expected_volume_mm3',None)
    require(all(cz+math.sqrt((radius-t)**2-(y-cy)**2)>roof_z for item in corridor_coverage for x,y in item['points_mm']),'Corridor cap thickness formula requires inner curve above roof datum')
    for item,name in zip(aperture_probes,covered_ids):item['area_id']=name
    mask_exclusions=[probe('RoofGlass_MaskExclusion_'+str(i),points,roof_z,edge_z+rise-roof_z+1,[glass,skirt],'empty')for i,points in enumerate(mask_cuts)]
    local_access=probe('RoofGlass_LocalAccessDeck',access_points,base,slab,[access_body],'filled')
    ga, gb = gap['points_mm']; d = math.dist(ga, gb); normal = [-(gb[1]-ga[1])/d, (gb[0]-ga[0])/d]
    gap_points = [[point[i]+sign*normal[i]*post for i in (0, 1)] for point, sign in [(ga, -1), (gb, -1), (gb, 1), (ga, 1)]]
    gap_probe = probe('RoofGuard_ExternalStairGap', gap_points, roof_z+1, height-2, guard_ids, 'empty')
    result['interface'] = {'roof_z_mm': roof_z, 'slab_bottom_mm': base, 'slab_top_mm': roof_z, 'opaque_body_ids': opaque,
        'glass_body_id': glass, 'guard_body_ids': guard_ids, 'body_ids': [body['id'] for body in result['bodies']],
        'component_id': source['id'], 'detail_visibility_ids': [body['id'] for body in result['bodies']], 'source_outer_contour': contour_data, 'guard_gap': gap,
        'barrel': {'axis':'X','profile_axis':'Y','radius_mm':radius,'inner_radius_mm':radius-t,'center_cross_mm':cy,'center_y_mm':cy,'center_z_mm':cz,
                   'x_bounds_mm':[left,right],'y_bounds_mm':[front,rear],'edge_z_mm':edge_z,'crown_z_mm':edge_z+rise,
                   'rise_mm':rise,'riser_mm':riser,'overhang_mm':over,'glass_thickness_mm':t,'profile_points_mm':profile,
                   'footprint_points_mm':polygon,'glazing_footprint_points_mm':glazing,'profile_segments':count,'skirt_max_sagitta_mm':sagitta,
                   'skirt_max_sagitta_fraction':barrel['max_sagitta_fraction_of_glass_thickness'],'cap_geometry':'analytic_cylindrical_shell','skirt_geometry':'facetted_boundary_glazing'},
        'covered_area_ids':list(covered_ids),'covered_corridor_area_ids':[name for name in covered_ids if areas[name]['kind']=='corridor'],
        'footprint_points_mm':polygon,'glass_body_ids':[glass,skirt],'glass_skirt_body_id':skirt,
        'guard':dict(guard),'eave_support_probes':supports,'material_probes':[crown,skirt_material,local_access],
        'empty_probes':[interior,gap_probe,*aperture_probes,*mask_exclusions],'glass_interior_probe':interior,
        'corridor_coverage_probes':corridor_coverage,'local_opaque_exceptions':[{'body_id':access_body,'area_id':access['area'],'source_opening':access['opening'],'points_mm':access_points,'offset_mm':base,'depth_mm':slab}],
        'aperture_coverage_probes':aperture_probes,'glass_mask_exclusion_probes':mask_exclusions,'local_access_deck':{'body_id':access_body,'area':access['area'],'points_mm':access_points,'offset_mm':base,'depth_mm':slab,'expected_volume_mm3':floor.signed_area(access_points)*slab},
        'metric_scale_known': False, 'structural_qualified': False, 'weather_sealing_qualified': False, 'safety_qualified': False,
        'limitations': ['Exact referenced glass union, analytic cylindrical cap and bounded facetted skirt are presentation geometry, not surveyed construction.',
                       'Eave support checks concern opaque-roof volume below the overhang only, not load transfer or sealing.',
                       'Guard dimensions and its source-referenced access gap are illustrative and not normative fall or fire protection.']}
    return result
