"""Photo-informed envelope and open rails; all sizes are presentation assumptions."""
import math
import re
import relative_floorplan as floor
import building_doors as doors
import building_roof as roof


def require(ok, message):
    if not ok: raise ValueError(message)


def validate(s):
    require(set(s)-{'doors','side_window_walls_by_level'}=={'status','front_wall','ground_front_wall','entry_opening','bay_count','frame_mm','glass_mm','glass_opacity','frame_color','glass_color','door_color','door_leaf_mm','guard_boundaries','guard_height_mm','guard_post_mm','guard_bar_mm','guard_bar_fractions','guard_max_post_spacing_mm','terrain_margin_mm','terrain_clearance_mm','terrain_color','landscape_layer_mm','concrete_color','side_cladding_color','side_window_walls','side_window_interval','side_window_height_fractions','sidewalk_width_mm','road_width_mm','sidewalk_color','road_color','entrance_flank_color','entrance_flank_walls','left_sidewalk_walls','left_sidewalk_entry_opening','left_hardstanding_end_fraction'},'Explicit exterior recipe required')
    require(s['status']=='photo_informed_unmeasured_concept','Declare photo-informed, unmeasured exterior')
    require(type(s['bay_count']) is int and 2<=s['bay_count']<=12,'Bounded illustrative facade bays required')
    for k in ['frame_mm','glass_mm','door_leaf_mm','guard_height_mm','guard_post_mm','guard_bar_mm','guard_max_post_spacing_mm','terrain_margin_mm','terrain_clearance_mm','landscape_layer_mm','sidewalk_width_mm','road_width_mm']:
        require(type(s[k]) in (int,float) and math.isfinite(s[k]) and 0<s[k]<10000,'Positive bounded presentation mm required: '+k)
    require(type(s['glass_opacity']) in (int,float) and 0<s['glass_opacity']<1,'Transparent glass required')
    for k in ['frame_color','glass_color','door_color','terrain_color','concrete_color','side_cladding_color','sidewalk_color','road_color','entrance_flank_color']:require(re.fullmatch('#[0-9a-fA-F]{6}',s[k]) is not None,'RGB appearance required')
    require(isinstance(s['guard_bar_fractions'],list) and s['guard_bar_fractions'] and all(type(v) in (int,float) and 0<v<1 for v in s['guard_bar_fractions']) and s['guard_bar_fractions']==sorted(set(s['guard_bar_fractions'])),'Unique ordered horizontal guard fractions required')
    for key in ['side_window_interval','side_window_height_fractions']:
        require(isinstance(s[key],list) and len(s[key])==2 and all(type(v) in (int,float) and 0<v<1 for v in s[key]) and s[key][0]<s[key][1], 'Ordered bounded window fractions required')
    require(isinstance(s['side_window_walls'],list) and s['side_window_walls'] and len(set(s['side_window_walls']))==len(s['side_window_walls']), 'Explicit side-window paths required')
    additions=s.get('side_window_walls_by_level',{})
    require(isinstance(additions,dict) and set(additions)<={'OG1','OG2','OG3'},'Side-window additions require explicit upper-storey bindings')
    for names in additions.values():
        require(isinstance(names,list) and names and all(isinstance(name,str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*',name) for name in names)
                and len(names)==len(set(names)) and not set(names)&set(s['side_window_walls']), 'Unique additional side-window paths required')
    require(type(s['left_hardstanding_end_fraction']) in (int,float) and 0<s['left_hardstanding_end_fraction']<1, 'Bounded illustrative left hardstanding extent required')
    require(s['landscape_layer_mm']<=50 and s['sidewalk_width_mm']<s['terrain_margin_mm'], 'Thin graphic landscape layer and fitting sidewalk required')
    require(isinstance(s['guard_boundaries'],list) and s['guard_boundaries'] and len(set(s['guard_boundaries']))==len(s['guard_boundaries']),'Unique source guard boundaries required')


def compile(s, plans, p, levels, omitted_wall_ids=()):
    validate(s); canonical=plans['OG3']; ground=plans['EG']; scale=p['display_scale']
    walls={w['id']:w for w in canonical['walls']};gwalls={w['id']:w for w in ground['walls']}
    require(s['front_wall'] in walls and s['ground_front_wall'] in gwalls,'Pinned graph facade anchors required')
    def ends(plan,w):return [[v*scale for v in plan['vertices'][w[k]]] for k in ('start','end')]
    a,b=ends(canonical,walls[s['front_wall']]);require(abs(a[0]-b[0])<1e-8,'Straight X-normal front required')
    x=a[0];y0,y1=sorted([a[1],b[1]]);grade=next(v['z_mm'] for v in levels if v['id']=='EG');top=levels[-1]['clear_top_mm']+p['slab_thickness_mm']
    door_policy,door_catalog=doors.load(s['doors']) if 'doors' in s else (None,None)
    if door_policy is not None:
        doors.validate_overrides(door_policy, plans)
        for field in ('include_areas','exclude_areas'):
            for level,ids in door_policy[field].items():
                require(level in plans and set(ids)<={area['id'] for area in plans[level]['areas']},'Unknown explicitly selected door room')
    r={'components':[{'id':'BuildingExterior','grounded':True}],'bodies':[],'operations':[]};omitted=list(omitted_wall_ids);door_map={};door_bindings={};glass_ids=[];guard_ids=[];guard_groups=[];terrain_ids=[];frame_ids=[]
    def body(n,role,color,opacity=1):
        r['bodies'].append({'id':n,'component':'BuildingExterior','role':role,'appearance':{'color':color,'opacity':opacity}});return n
    def box(n,target,origin,size,action='create'):
        require(all(v>0 for v in size),'Positive exterior box required')
        r['operations'].append({'id':n,'body':target,'action':action,'shape':{'kind':'box','origin':origin,'size':size}})
    def prism(n,target,points,z,h,action='create'):
        if floor.signed_area(points)<0:points=list(reversed(points))
        r['operations'].append({'id':n,'body':target,'action':action,'shape':{'kind':'polygon_prism','plane':'XY','points':points,'offset':z,'depth':h,'fixed':True}})
    # Replace source placeholder walls only in this building composition.
    for level in levels:
        if level['id']=='KG':continue
        names=[s['ground_front_wall']] if level['id']=='EG' else [s['front_wall'],*s['guard_boundaries']]
        omitted.extend(level['id']+'__Wall_'+n for n in names)
    entry=next((o for o in ground['openings'] if o['id']==s['entry_opening']),None)
    require(entry is not None and entry['wall']==s['ground_front_wall'],'Existing ground entrance required')
    ea,eb=ends(ground,gwalls[entry['wall']]);elo,ehi=sorted(ea[1]+t*(eb[1]-ea[1]) for t in entry['interval'])
    frame=s['frame_mm'];glass=s['glass_mm'];pitch=(y1-y0)/s['bay_count'];require(pitch>3*frame and y0<=elo<ehi<=y1,'Facade proportions must fit shared source')
    frame_id=body('FoyerFacadeFrame','concept_dark_facade_frame',s['frame_color'])
    frame_ids.append(frame_id)
    box(frame_id+'_First',frame_id,[x-frame/2,y0-frame/2,grade],[frame,frame,top-grade])
    box(frame_id+'_Header',frame_id,[x-frame/2,y0-frame/2,top-frame],[frame,y1-y0+frame,frame],'join')
    for i in range(1,s['bay_count']+1):
        target=frame_id if i==s['bay_count'] else body('FoyerMullion_'+str(i),'concept_dark_facade_frame',s['frame_color'])
        if target!=frame_id:frame_ids.append(target)
        box(frame_id+'_Mullion'+str(i),target,[x-frame/2,y0+i*pitch-frame/2,grade],[frame,frame,top-grade],'join' if target==frame_id else 'create')
    above=[v for v in levels if v['id']!='KG']
    for level in above:
        z=level['z_mm'];h=p['floor_pitch_mm']
        for fraction in [0,.25,.75]:
            zz=z+fraction*h
            # Do not bridge the entrance with a low transom.
            if level['id']=='EG' and zz<grade+p['door_height_mm']:continue
            target=body('FoyerTransom_'+level['id']+'_'+str(int(fraction*100)),'concept_dark_facade_frame',s['frame_color']);frame_ids.append(target)
            box(target+'_Box',target,[x-frame/2,y0-frame/2,zz],[frame,y1-y0+frame,frame])
        for i in range(s['bay_count']):
            n=body('FoyerGlass_'+level['id']+'_'+str(i),'concept_front_glass',s['glass_color'],s['glass_opacity']);glass_ids.append(n)
            box(n+'_Pane',n,[x-glass/2,y0+i*pitch+frame/2,z+frame/2],[glass,pitch-frame,h-frame])
            if level['id']=='EG' and y0+(i+1)*pitch>elo and y0+i*pitch<ehi:
                box(n+'_Entrance',n,[x-frame,elo,grade],[frame*2,ehi-elo,p['door_height_mm']],'cut')
    # Same source colour for all room door leaves. They are shown open so the
    # established opening witnesses and floor topology are retained.
    for level in levels:
        plan=plans[level['id']];wallmap={w['id']:w for w in plan['walls']}
        for door in plan['openings']:
            if door['kind']!='door':continue
            target=level['id']+'__Wall_'+door['wall']
            if target in omitted:continue
            wa,wb=ends(plan,wallmap[door['wall']]);dx,dy=wb[0]-wa[0],wb[1]-wa[1];length=math.hypot(dx,dy);u=[dx/length,dy/length];normal=[-u[1],u[0]]
            owner=next(area for area in plan['areas'] if any(v['wall']==door['wall'] for v in area['boundary']))
            direction=next(v['direction'] for v in owner['boundary'] if v['wall']==door['wall']);normal=[v*direction for v in normal]
            hinge=[wa[j]+door['interval'][0]*(wb[j]-wa[j]) for j in (0,1)];width=(door['interval'][1]-door['interval'][0])*length;t=s['door_leaf_mm']
            pts=[[hinge[j]+along*u[j]+depth*normal[j] for j in (0,1)] for along,depth in [(-t,0),(0,0),(0,width),(-t,width)]]
            n=level['id']+'__DoorLeaf_'+door['id']
            if door_policy is None:
                body(n,'concept_open_wood_room_door',s['door_color']);prism(n+'_Leaf',n,pts,level['z_mm'],p['door_height_mm'])
            else:
                selection=doors.select(door_policy,plan,canonical,level['id'],door)
                if 'pose' in selection:
                    placement=doors.handed_frame(plan,door,selection['pose'],scale);selection['placement']=placement
                    hinge,u,normal=placement['hinge_mm'],placement['closed_axis'],placement['opening_axis']
                pieces=doors.geometry(door_catalog,selection,n,hinge,u,normal,width,p['door_height_mm'],level['z_mm'],s)
                for key in ('bodies','operations'):r[key].extend(pieces[key])
                door_bindings[level['id']+'__'+door['id']]=selection
            door_map[level['id']+'__'+door['id']]=n
    # Very open metal balustrades along the source's corridor/atrium edges.
    for level in levels:
        if not level['id'].startswith('OG'):continue
        for wall_id in s['guard_boundaries']:
            require(wall_id in walls,'Existing guard edge required');wa,wb=ends(canonical,walls[wall_id]);dx,dy=wb[0]-wa[0],wb[1]-wa[1];length=math.hypot(dx,dy);u=[dx/length,dy/length];normal=[-u[1],u[0]];count=math.ceil(length/s['guard_max_post_spacing_mm']);post=s['guard_post_mm'];bar=s['guard_bar_mm'];z=level['z_mm'];height=s['guard_height_mm']
            n='AtriumGuard_'+level['id']+'_'+wall_id;members=[]
            def member(tag,along,run,zz,hh,thick):
                pts=[[wa[j]+distance*u[j]+side*normal[j] for j in (0,1)] for distance,side in [(along,-thick/2),(along+run,-thick/2),(along+run,thick/2),(along,thick/2)]]
                if floor.signed_area(pts)<0:pts.reverse()
                target=body(n+'_'+tag,'concept_open_metal_balustrade_member',s['frame_color']);members.append(target);guard_ids.append(target)
                r['operations'].append({'id':target+'_Profile','body':target,'action':'create','shape':{'kind':'polygon_prism','plane':'XY','points':pts,'offset':zz,'depth':hh,'fixed':True}})
            member('Post0',-post/2,post,z,height,post)
            member('Handrail',-post/2,length+post,z+height-bar,bar,post)
            for i in range(1,count+1):member('Post'+str(i),i*length/count-post/2,post,z,height,post)
            for i,fraction in enumerate(s['guard_bar_fractions']):member('Bar'+str(i),-post/2,length+post,z+height*fraction,bar,bar)
            guard_groups.append({'id':n,'level_id':level['id'],'boundary':wall_id,'body_ids':members})
    # Opaque concrete entrance flanks and storey-height cladding around the
    # bounded side window bands. Canonical paths are reused after registration;
    # the original room graphs and all vertical core positions remain intact.
    canonical_edges=roof.outer_contour(canonical,[a for a in canonical['areas'] if a['kind']!='void' and a['id'] not in {'R3_017','ExternalLink'}])
    canonical_points=[canonical['vertices'][e['start']] for e in canonical_edges]
    window_paths=set(s['side_window_walls'])|{name for names in s.get('side_window_walls_by_level',{}).values() for name in names}
    require(window_paths<={e['wall'] for e in canonical_edges},'Side bands must reference the actual outer facade')
    require(isinstance(s['entrance_flank_walls'],list) and s['entrance_flank_walls'] and len(set(s['entrance_flank_walls']))==len(s['entrance_flank_walls']) and set(s['entrance_flank_walls'])<={e['wall'] for e in canonical_edges}, 'Explicit entrance flank boundaries required')
    flank_segments=[(canonical['vertices'][walls[n]['start']],canonical['vertices'][walls[n]['end']]) for n in s['entrance_flank_walls']]
    side_segments=[(canonical['vertices'][walls[n]['start']],canonical['vertices'][walls[n]['end']]) for n in s['side_window_walls']]
    surfaces={};opaque_ids=[];window_groups=[];window_probes=[]
    def strip(wa,wb,lo,hi,half):
        length=math.dist(wa,wb);normal=[-(wb[1]-wa[1])/length,(wb[0]-wa[0])/length]
        return [[wa[j]+fraction*(wb[j]-wa[j])+side*normal[j] for j in (0,1)] for fraction,side in [(lo,-half),(hi,-half),(hi,half),(lo,half)]]
    for level in levels:
        plan=plans[level['id']];wallmap={w['id']:w for w in plan['walls']}
        level_segments=side_segments+[(canonical['vertices'][walls[n]['start']],canonical['vertices'][walls[n]['end']])
                                     for n in s.get('side_window_walls_by_level',{}).get(level['id'],[])]
        edges=roof.outer_contour(plan,[a for a in plan['areas'] if a['kind']!='void' and a['id'] not in {'R3_017','ExternalStairGround','ExternalLink'}])
        for edge in edges:
            wall=wallmap[edge['wall']];target=level['id']+'__Wall_'+wall['id']
            if target in omitted:continue
            wa,wb=ends(plan,wall);va,vb=[plan['vertices'][wall[k]] for k in ('start','end')]
            side=level['id']!='KG' and any(floor.on_segment(va,a,b) and floor.on_segment(vb,a,b) for a,b in level_segments)
            painted=level['id']!='KG' and any(floor.on_segment(va,a,b) and floor.on_segment(vb,a,b) for a,b in flank_segments)
            concrete=s['entrance_flank_color'] if painted else s['concrete_color']
            if wall['kind']=='wall':surfaces[target]={'color':s['side_cladding_color'] if side else concrete,'opacity':1}
            elif level['id']!='KG' and wall['kind']=='unknown':
                n=body('FacadeClosure_'+level['id']+'_'+wall['id'],'concept_opaque_concrete_facade',concrete);opaque_ids.append(n)
                prism(n+'_Panel',n,strip(wa,wb,0,1,p['display_thickness']/2),level['z_mm'],p['clear_height_mm'])
            else:continue
            if not side or wall['kind']!='wall' or any(o['kind']=='door' and o['wall']==wall['id'] for o in plan['openings']):continue
            length=math.dist(wa,wb);lo,hi=s['side_window_interval'];frame=s['frame_mm'];width=(hi-lo)*length
            if width<=4*frame:continue
            bottom=level['z_mm']+s['side_window_height_fractions'][0]*p['clear_height_mm'];height=(s['side_window_height_fractions'][1]-s['side_window_height_fractions'][0])*p['clear_height_mm']
            name='SideWindow_'+level['id']+'_'+wall['id']
            prism(name+'_WallCut',target,strip(wa,wb,lo,hi,p['display_thickness']*.7),bottom,height,'cut')
            frame_id_side=body(name+'_Frame','concept_side_window_frame',s['frame_color']);frame_ids.append(frame_id_side)
            prism(frame_id_side+'_Outer',frame_id_side,strip(wa,wb,lo,hi,frame/2),bottom,height)
            prism(frame_id_side+'_Inner',frame_id_side,strip(wa,wb,lo+frame/length,hi-frame/length,frame),bottom+frame,height-2*frame,'cut')
            pane=body(name+'_Glass','concept_side_band_glass',s['glass_color'],s['glass_opacity']);glass_ids.append(pane)
            prism(pane+'_Pane',pane,strip(wa,wb,lo+frame/length,hi-frame/length,glass/2),bottom+frame,height-2*frame)
            inset=min(frame/4,width/10);window_probes.append({'id':name+'_Aperture','target_body':target,'kind':'polygon_prism','points_mm':strip(wa,wb,lo+inset/length,hi-inset/length,p['display_thickness']*.4),'offset_mm':bottom+inset,'depth_mm':height-2*inset,'display_inset_mm':inset,'visualization_only':True})
            window_groups.append({'id':name,'level_id':level['id'],'wall':wall['id'],'target_body':target,'glass_body':pane,'frame_body':frame_id_side,'z_bounds_mm':[bottom,bottom+height]})
    # A leaf-thin green graphic surface follows the registered footprint. Paved
    # access areas are separate, equally thin surfaces, never an earth volume.
    clearance=s['terrain_clearance_mm'];margin=max(s['terrain_margin_mm'],s['sidewalk_width_mm']+s['road_width_mm']);layer=s['landscape_layer_mm'];bottom=grade-layer
    xmin=min(v[0] for v in canonical_points)*scale-clearance;xmax=max(v[0] for v in canonical_points)*scale+clearance;ymin=min(v[1] for v in canonical_points)*scale-clearance;ymax=max(v[1] for v in canonical_points)*scale+clearance
    lawn=body('Terrain_Lawn','illustrative_lawn_surface',s['terrain_color']);terrain_ids.append(lawn)
    box(lawn+'_Sheet',lawn,[xmin-margin,ymin-margin,bottom],[xmax-xmin+2*margin,ymax-ymin+2*margin,layer])
    prism(lawn+'_BuildingVoid',lawn,[[x*scale,y*scale] for x,y in canonical_points],bottom-layer,layer*3,'cut')
    # Follow the existing left-hand facade only as far as its observed EG door.
    path_ids=s['left_sidewalk_walls']
    require(isinstance(path_ids,list) and path_ids and len(set(path_ids))==len(path_ids) and set(path_ids)<={e['wall'] for e in canonical_edges}, 'Explicit left sidewalk facade route required')
    contour_edges={edge['wall']:edge for edge in canonical_edges}
    route=[contour_edges[n] for n in path_ids]
    require(all(a['end']==b['start'] for a,b in zip(route,route[1:])), 'Connected left sidewalk route required')
    side_entry=next((o for o in ground['openings'] if o['id']==s['left_sidewalk_entry_opening']),None)
    require(side_entry is not None and side_entry['kind']=='door', 'Observed left side entrance required')
    entry_a,entry_b=ends(ground,gwalls[side_entry['wall']]);start,end=ends(canonical,route[0]);delta=[end[i]-start[i] for i in (0,1)]
    fractions=[sum((entry_a[i]+f*(entry_b[i]-entry_a[i])-start[i])*delta[i] for i in (0,1))/sum(v*v for v in delta) for f in side_entry['interval']]
    require(all(0<f<1 for f in fractions), 'Side entrance must project onto the start of the sidewalk route')
    chain=[[start[i]+min(fractions)*delta[i] for i in (0,1)]]+[ends(canonical,w)[1] for w in route]
    walk=s['sidewalk_width_mm'];road_width=s['road_width_mm'];margin=max(margin,walk+road_width)
    normals=[]
    for a,b in zip(chain,chain[1:]):
        length=math.dist(a,b);normals.append([(b[1]-a[1])/length,-(b[0]-a[0])/length])
    outer=[]
    for i,q in enumerate(chain):
        before=normals[max(0,i-1)];after=normals[min(i,len(normals)-1)];factor=walk/(1+sum(a*b for a,b in zip(before,after)))
        outer.append([q[j]+factor*(before[j]+after[j]) for j in (0,1)])
    side_polygon=chain+list(reversed(outer));site_ids=[lawn];site_regions=[]
    # The front paving reaches the recessed glass; the road lies beyond it.
    front_origin=[x,ymin,bottom];front_size=[xmax+walk-x,ymax-ymin,layer]
    for name,origin,size,color,material in [
        ('Site_EntranceApron',front_origin,front_size,s['sidewalk_color'],'entrance_apron'),
        ('Site_Driveway',[xmax+walk,ymin,bottom],[road_width,ymax-ymin,layer],s['road_color'],'driveway')]:
        n=body(name,'illustrative_'+material+'_surface',color);site_ids.append(n);box(n+'_Sheet',n,origin,size)
        prism(n+'_BuildingVoid',n,[[x*scale,y*scale] for x,y in canonical_points],bottom-layer,layer*3,'cut')
        box(n+'_LawnCut',lawn,[origin[0],origin[1],bottom-layer],[size[0],size[1],layer*3],'cut')
        site_regions.append({'body':n,'material':material,'origin_mm':origin,'size_mm':size})
    n=body('Site_Sidewalk','illustrative_sidewalk_surface',s['sidewalk_color']);site_ids.append(n)
    prism(n+'_Sheet',n,side_polygon,bottom,layer)
    box(n+'_FrontOverlap',n,[front_origin[0],front_origin[1],bottom-layer],[front_size[0],front_size[1],layer*3],'cut')
    prism(n+'_LawnCut',lawn,side_polygon,bottom-layer,layer*3,'cut')
    lo=[min(q[i] for q in side_polygon) for i in (0,1)];hi=[max(q[i] for q in side_polygon) for i in (0,1)]
    site_regions.append({'body':n,'material':'sidewalk','origin_mm':lo+[bottom],'size_mm':[hi[i]-lo[i] for i in (0,1)]+[layer],'points_mm':side_polygon,'entry_opening':side_entry['id'],'facade_walls':path_ids})
    # The aerial view shows a broad left court/access surface, not a lawn buffer.
    # Its crop boundary is an explicit unmeasured display assumption.
    court_origin=[xmin-margin,ymin-margin,bottom]
    court_size=[xmax-xmin+2*margin,margin+s['left_hardstanding_end_fraction']*(ymax-ymin),layer]
    n=body('Site_LeftHardstanding','illustrative_left_hardstanding_surface',s['road_color']);site_ids.append(n)
    box(n+'_Sheet',n,court_origin,court_size)
    prism(n+'_BuildingVoid',n,[[x*scale,y*scale] for x,y in canonical_points],bottom-layer,layer*3,'cut')
    for name,origin,size in [('Front',front_origin,front_size),('Road',[xmax+walk,ymin,bottom],[road_width,ymax-ymin,layer])]:
        box(n+'_'+name+'Cut',n,[origin[0],origin[1],bottom-layer],[size[0],size[1],layer*3],'cut')
    prism(n+'_WalkCut',n,side_polygon,bottom-layer,layer*3,'cut')
    box(n+'_LawnCut',lawn,[court_origin[0],court_origin[1],bottom-layer],[court_size[0],court_size[1],layer*3],'cut')
    site_regions.append({'body':n,'material':'left_hardstanding','origin_mm':court_origin,'size_mm':court_size,'boundary_measured':False})
    r['interface']={'body_ids':[v['id'] for v in r['bodies']],'omitted_body_ids':omitted,'door_leaves':door_map,'door_bindings':door_bindings,'glass_body_ids':glass_ids,'frame_body_id':frame_id,'frame_body_ids':frame_ids,'guard_body_ids':guard_ids,'guard_groups':guard_groups,'terrain_body_ids':terrain_ids,'site_body_ids':site_ids,'site_regions':site_regions,'surface_layer_mm':layer,'surface_overrides':surfaces,'opaque_facade_body_ids':opaque_ids,'side_window_groups':window_groups,'window_probes':window_probes,'grade_z_mm':grade,'terrain_bottom_mm':bottom,'facade_plane_x_mm':x,'facade_y_bounds_mm':[y0,y1],'facade_top_mm':top,'door_color':s['door_color'],'dimensions_measured':False,'safety_qualified':False}
    return r
