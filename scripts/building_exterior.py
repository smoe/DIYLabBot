"""Photo-informed envelope and open rails; all sizes are presentation assumptions."""
import math
import re
import relative_floorplan as floor
import building_roof as roof


def require(ok, message):
    if not ok: raise ValueError(message)


def validate(s):
    require(set(s)=={'status','front_wall','ground_front_wall','entry_opening','bay_count','frame_mm','glass_mm','glass_opacity','frame_color','glass_color','door_color','door_leaf_mm','guard_boundaries','guard_height_mm','guard_post_mm','guard_bar_mm','guard_bar_fractions','guard_max_post_spacing_mm','terrain_margin_mm','terrain_clearance_mm','terrain_color','landscape_layer_mm','concrete_color','side_cladding_color','side_window_walls','side_window_interval','side_window_height_fractions','sidewalk_width_mm','road_width_mm','sidewalk_color','road_color'},'Explicit exterior recipe required')
    require(s['status']=='photo_informed_unmeasured_concept','Declare photo-informed, unmeasured exterior')
    require(type(s['bay_count']) is int and 2<=s['bay_count']<=12,'Bounded illustrative facade bays required')
    for k in ['frame_mm','glass_mm','door_leaf_mm','guard_height_mm','guard_post_mm','guard_bar_mm','guard_max_post_spacing_mm','terrain_margin_mm','terrain_clearance_mm','landscape_layer_mm','sidewalk_width_mm','road_width_mm']:
        require(type(s[k]) in (int,float) and math.isfinite(s[k]) and 0<s[k]<10000,'Positive bounded presentation mm required: '+k)
    require(type(s['glass_opacity']) in (int,float) and 0<s['glass_opacity']<1,'Transparent glass required')
    for k in ['frame_color','glass_color','door_color','terrain_color','concrete_color','side_cladding_color','sidewalk_color','road_color']:require(re.fullmatch('#[0-9a-fA-F]{6}',s[k]) is not None,'RGB appearance required')
    require(isinstance(s['guard_bar_fractions'],list) and s['guard_bar_fractions'] and all(type(v) in (int,float) and 0<v<1 for v in s['guard_bar_fractions']) and s['guard_bar_fractions']==sorted(set(s['guard_bar_fractions'])),'Unique ordered horizontal guard fractions required')
    for key in ['side_window_interval','side_window_height_fractions']:
        require(isinstance(s[key],list) and len(s[key])==2 and all(type(v) in (int,float) and 0<v<1 for v in s[key]) and s[key][0]<s[key][1], 'Ordered bounded window fractions required')
    require(isinstance(s['side_window_walls'],list) and s['side_window_walls'] and len(set(s['side_window_walls']))==len(s['side_window_walls']), 'Explicit side-window paths required')
    require(s['landscape_layer_mm']<=50 and s['sidewalk_width_mm']<s['terrain_margin_mm'], 'Thin graphic landscape layer and fitting sidewalk required')
    require(isinstance(s['guard_boundaries'],list) and s['guard_boundaries'] and len(set(s['guard_boundaries']))==len(s['guard_boundaries']),'Unique source guard boundaries required')


def compile(s, plans, p, levels):
    validate(s); canonical=plans['OG3']; ground=plans['EG']; scale=p['display_scale']
    walls={w['id']:w for w in canonical['walls']};gwalls={w['id']:w for w in ground['walls']}
    require(s['front_wall'] in walls and s['ground_front_wall'] in gwalls,'Pinned graph facade anchors required')
    def ends(plan,w):return [[v*scale for v in plan['vertices'][w[k]]] for k in ('start','end')]
    a,b=ends(canonical,walls[s['front_wall']]);require(abs(a[0]-b[0])<1e-8,'Straight X-normal front required')
    x=a[0];y0,y1=sorted([a[1],b[1]]);grade=next(v['z_mm'] for v in levels if v['id']=='EG');top=levels[-1]['clear_top_mm']+p['slab_thickness_mm']
    r={'components':[{'id':'BuildingExterior','grounded':True}],'bodies':[],'operations':[]};omitted=[];door_map={};glass_ids=[];guard_ids=[];guard_groups=[];terrain_ids=[];frame_ids=[]
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
            n=body(level['id']+'__DoorLeaf_'+door['id'],'concept_open_wood_room_door',s['door_color']);prism(n+'_Leaf',n,pts,level['z_mm'],p['door_height_mm']);door_map[level['id']+'__'+door['id']]=n
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
    require(set(s['side_window_walls'])<={e['wall'] for e in canonical_edges},'Side bands must reference the actual outer facade')
    side_segments=[(canonical['vertices'][walls[n]['start']],canonical['vertices'][walls[n]['end']]) for n in s['side_window_walls']]
    surfaces={};opaque_ids=[];window_groups=[];window_probes=[]
    def strip(wa,wb,lo,hi,half):
        length=math.dist(wa,wb);normal=[-(wb[1]-wa[1])/length,(wb[0]-wa[0])/length]
        return [[wa[j]+fraction*(wb[j]-wa[j])+side*normal[j] for j in (0,1)] for fraction,side in [(lo,-half),(hi,-half),(hi,half),(lo,half)]]
    for level in levels:
        plan=plans[level['id']];wallmap={w['id']:w for w in plan['walls']}
        edges=roof.outer_contour(plan,[a for a in plan['areas'] if a['kind']!='void' and a['id'] not in {'R3_017','ExternalStairGround','ExternalLink'}])
        for edge in edges:
            wall=wallmap[edge['wall']];target=level['id']+'__Wall_'+wall['id']
            if target in omitted:continue
            wa,wb=ends(plan,wall);va,vb=[plan['vertices'][wall[k]] for k in ('start','end')]
            side=level['id']!='KG' and any(floor.on_segment(va,a,b) and floor.on_segment(vb,a,b) for a,b in side_segments)
            if wall['kind']=='wall':surfaces[target]={'color':s['side_cladding_color'] if side else s['concrete_color'],'opacity':1}
            elif level['id']!='KG' and wall['kind']=='unknown':
                n=body('FacadeClosure_'+level['id']+'_'+wall['id'],'concept_opaque_concrete_facade',s['concrete_color']);opaque_ids.append(n)
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
    clearance=s['terrain_clearance_mm'];margin=s['terrain_margin_mm'];layer=s['landscape_layer_mm'];bottom=grade-layer
    xmin=min(v[0] for v in canonical_points)*scale-clearance;xmax=max(v[0] for v in canonical_points)*scale+clearance;ymin=min(v[1] for v in canonical_points)*scale-clearance;ymax=max(v[1] for v in canonical_points)*scale+clearance
    lawn=body('Terrain_Lawn','illustrative_lawn_surface',s['terrain_color']);terrain_ids.append(lawn)
    box(lawn+'_Sheet',lawn,[xmin-margin,ymin-margin,bottom],[xmax-xmin+2*margin,ymax-ymin+2*margin,layer])
    prism(lawn+'_BuildingVoid',lawn,[[x*scale,y*scale] for x,y in canonical_points],bottom-layer,layer*3,'cut')
    walk=s['sidewalk_width_mm'];center=(elo+ehi)/2;road_width=s['road_width_mm'];site_ids=[lawn];site_regions=[]
    for name,origin,size,color,material in [
        ('Site_Sidewalk',[xmax,ymin,bottom],[walk,ymax-ymin,layer],s['sidewalk_color'],'sidewalk'),
        ('Site_Driveway',[xmax+walk,center-road_width/2,bottom],[margin-walk,road_width,layer],s['road_color'],'driveway'),
        ('Site_EntranceApron',[x+glass,center-road_width/2,bottom],[xmax-x-glass,road_width,layer],s['sidewalk_color'],'entrance_apron')]:
        n=body(name,'illustrative_'+material+'_surface',color);site_ids.append(n);box(n+'_Sheet',n,origin,size)
        box(n+'_LawnCut',lawn,[origin[0],origin[1],bottom-layer],[size[0],size[1],layer*3],'cut')
        site_regions.append({'body':n,'material':material,'origin_mm':origin,'size_mm':size})
    r['interface']={'body_ids':[v['id'] for v in r['bodies']],'omitted_body_ids':omitted,'door_leaves':door_map,'glass_body_ids':glass_ids,'frame_body_id':frame_id,'frame_body_ids':frame_ids,'guard_body_ids':guard_ids,'guard_groups':guard_groups,'terrain_body_ids':terrain_ids,'site_body_ids':site_ids,'site_regions':site_regions,'surface_layer_mm':layer,'surface_overrides':surfaces,'opaque_facade_body_ids':opaque_ids,'side_window_groups':window_groups,'window_probes':window_probes,'grade_z_mm':grade,'terrain_bottom_mm':bottom,'facade_plane_x_mm':x,'facade_y_bounds_mm':[y0,y1],'facade_top_mm':top,'door_color':s['door_color'],'dimensions_measured':False,'safety_qualified':False}
    return r
