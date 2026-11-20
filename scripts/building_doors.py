"""One portable room-door definition, two glazing types and independent materials."""
import json
import math
import re
from pathlib import Path
import assembly_model as assembly
import relative_floorplan as floor

ROOT=Path(__file__).resolve().parents[1]
LEVELS=frozenset({'KG','EG','OG1','OG2','OG3'})


def require(ok,message):
    if not ok:raise ValueError(message)


def read(ref):
    path=assembly.validate_reference(ref,root=ROOT)
    return json.loads(path.read_text())


def load(ref):
    policy=read(ref);catalog=read(policy['catalog']);validate(policy,catalog)
    return policy,catalog


def dependencies(ref):
    policy,catalog=load(ref)
    return [ROOT/ref['source'],ROOT/policy['catalog']['source'],Path(__file__),
        ROOT/'model/building-doors.schema.json',ROOT/'model/room-door-catalog.schema.json',
        *([ROOT/policy['laboratory_corridor_rule']['room_assignments']['source']]
          if 'laboratory_corridor_rule' in policy else [])]


def validate(policy,catalog):
    require(set(policy)-{'opening_overrides','laboratory_corridor_rule'}=={'format','catalog','default_type','default_material','level_materials','round_window_levels','large_outer_room_rule','include_areas','exclude_areas','exclude_label_terms','provenance'},'Explicit door-selection fields required')
    require(set(catalog)=={'format','units','status','types','window','materials'},'Explicit door-catalog fields required')
    require(policy['format']=='solidcraftbot.building-doors/1','Unsupported building-door policy')
    require(catalog['format']=='solidcraftbot.room-door-catalog/1' and catalog['units']=={'length':'mm','angle':'deg'},'Typed room-door catalog required')
    require(catalog['types']=={'plain':{'round_window':False},'round_window':{'round_window':True}},'Exactly two supported door types required')
    require({'wood','steel'}<=set(catalog['materials'])<={'wood','steel','glass','blue_black_steel'},'Supported wood, steel and optional glass profiles required')
    require(policy['default_type'] in catalog['types'] and policy['default_material'] in catalog['materials'],'Unknown default door type or material')
    require(all(v in catalog['materials'] for v in policy['level_materials'].values()),'Unknown floor door material')
    require(len(set(policy['round_window_levels']))==len(policy['round_window_levels']) and set(policy['round_window_levels'])<={'EG','OG1','OG2','OG3'},'Explicit above-ground window selection required')
    rule=policy['large_outer_room_rule'];ratio=rule['minimum_area_ratio']
    require(type(ratio) in (int,float) and math.isfinite(ratio) and 0<ratio<=1,'Positive relative room-area threshold required')
    for key in ('include_areas','exclude_areas'):
        require(set(policy[key])<={'KG','EG','OG1','OG2','OG3'},'Unknown door-selection floor')
        require(all(isinstance(ids,list) and len(ids)==len(set(ids)) for ids in policy[key].values()),'Unique room selections required')
    for level,ids in policy['include_areas'].items():require(not set(ids)&set(policy['exclude_areas'].get(level,[])),'Contradictory explicit room door selections')
    w=catalog['window']
    require(set(w)=={'diameter_mm','center_height_mm','glass_thickness_mm','radial_glass_clearance_mm','rim_width_mm','rim_thickness_mm','edge_margin_mm','glass_color','glass_opacity','rim_color'},'Explicit window dimensions and finish required')
    require(all(re.fullmatch('#[0-9a-fA-F]{6}',w[k]) for k in ('glass_color','rim_color')),'RGB door-detail colours required')
    for name,value in w.items():
        if name.endswith('_mm'):require(type(value) in (int,float) and math.isfinite(value) and value>0,'Positive finite window dimension: '+name)
    require(w['radial_glass_clearance_mm']<w['diameter_mm']/2,'Glass clearance removes the pane')
    require(type(w['glass_opacity']) in (int,float) and 0<w['glass_opacity']<1,'Transparent viewing pane required')
    require(catalog['materials']['wood']=={'thickness_source':'exterior.door_leaf_mm','color_source':'exterior.door_color','mass_kg':None},'Wood reuses the existing shared finish and thickness')
    require(set(policy['level_materials'])<={'KG','EG','OG1','OG2','OG3'},'Unknown material floor')
    steel=catalog['materials']['steel'];require(set(steel)=={'thickness_mm','color','mass_kg'} and re.fullmatch('#[0-9a-fA-F]{6}',steel['color']),'Explicit steel profile required')
    require(type(steel['thickness_mm']) in (int,float) and math.isfinite(steel['thickness_mm']) and steel['thickness_mm']>0 and steel['mass_kg'] is None,'Steel thickness is illustrative; mass remains unknown')
    if 'glass' in catalog['materials']:
        glass=catalog['materials']['glass']
        require(set(glass)=={'thickness_mm','color','opacity','mass_kg'} and isinstance(glass['color'],str) and re.fullmatch('#[0-9a-fA-F]{6}',glass['color']),'Explicit full-glass profile required')
        require(type(glass['thickness_mm']) in (int,float) and math.isfinite(glass['thickness_mm']) and glass['thickness_mm']>0 and glass['mass_kg'] is None,'Glass thickness is illustrative; mass remains unknown')
        require(type(glass['opacity']) in (int,float) and 0<glass['opacity']<1,'Transparent full-glass leaf required')
    if 'blue_black_steel' in catalog['materials']:
        variant=catalog['materials']['blue_black_steel']
        require(set(variant)=={'base_material','color'} and variant['base_material']=='steel' and isinstance(variant['color'],str) and re.fullmatch('#[0-9a-fA-F]{6}',variant['color']), 'Explicit steel finish variant required')
    if 'laboratory_corridor_rule' in policy:
        rule=policy['laboratory_corridor_rule']
        require(isinstance(rule,dict) and set(rule)=={'room_assignments','opens_into','hinge','basis'},'Explicit laboratory corridor opening rule required')
        require(rule['opens_into']=='corridor' and rule['hinge']=='preserve_source_interval_start', 'Laboratory doors open into the corridor at their existing source jamb')
        require(isinstance(rule['basis'],str) and rule['basis'].strip(),'Laboratory door direction basis required')
        laboratory_assignments(rule)
    overrides=policy.get('opening_overrides',[])
    require(isinstance(overrides,list),'Explicit per-opening door overrides required')
    identities=set()
    for override in overrides:
        require(isinstance(override,dict) and set(override)-{'pose'}=={'level_id','opening_id','type','material','basis'},'Explicit per-opening door override fields required')
        require(isinstance(override['level_id'],str) and override['level_id'] in LEVELS,'Unknown override level')
        require(isinstance(override['opening_id'],str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*',override['opening_id']),'Stable override opening ID required')
        require(isinstance(override['type'],str) and override['type'] in catalog['types'],'Unknown override door type')
        require(isinstance(override['material'],str) and override['material'] in catalog['materials'],'Unknown override door material')
        require(override['material']!='glass' or override['type']=='plain','A full-glass leaf uses the plain geometry type')
        require(isinstance(override['basis'],str) and override['basis'].strip(),'Per-opening override basis required')
        identity=(override['level_id'],override['opening_id'])
        require(identity not in identities,'Duplicate per-opening door override')
        identities.add(identity)
        if 'pose' in override:
            pose=override['pose'];require(isinstance(pose,dict) and set(pose)=={'approach_from','hinge_side','opens_into'} and pose['hinge_side'] in {'left','right'} and all(isinstance(pose[k],str) and pose[k] for k in ('approach_from','opens_into')), 'Explicit door approach, hinge side and opening region required')


def laboratory_assignments(rule):
    """Read room identities from the furnishing source, without copying its geometry."""
    source=read(rule['room_assignments'])
    require(source.get('format')=='solidcraftbot.building-laboratories/1','Referenced laboratory room assignments required')
    result=set()
    for item in source['laboratories']+source.get('basic_laboratories',[]):
        identity=(item['level'],item['area'])
        require(identity not in result and item['level'] in LEVELS,'Unique laboratory room assignments required')
        result.add(identity)
    return result


def laboratory_corridor_pose(policy,plan,level,door):
    rule=policy.get('laboratory_corridor_rule')
    if rule is None:return None
    rooms=laboratory_assignments(rule)
    adjacent=[area for area in plan['areas'] if any(edge['wall']==door['wall'] for edge in area['boundary'])]
    labs=[area for area in adjacent if (level,area['id']) in rooms]
    if not labs:return None
    corridors=[area for area in adjacent if area['kind']=='corridor']
    if not labs or not corridors:return None
    require(len(labs)==len(corridors)==1 and len(adjacent)==2,'Unambiguous laboratory-to-corridor boundary required')
    lab,corridor=labs[0]['id'],corridors[0]['id']
    # Keep the existing physical jamb. Only the opening side changes; no hinge
    # handedness is inferred from a global north/south direction or a room centre.
    wall=next(w for w in plan['walls'] if w['id']==door['wall'])
    a,b=[plan['vertices'][wall[k]] for k in ('start','end')]
    hinge=[a[i]+door['interval'][0]*(b[i]-a[i]) for i in (0,1)]
    for side in ('left','right'):
        pose={'approach_from':lab,'hinge_side':side,'opens_into':corridor}
        if math.dist(handed_frame(plan,door,pose,1)['hinge_mm'],hinge)<1e-8:
            return {'pose':pose,'laboratory_corridor':{'laboratory':lab,'corridor':corridor},'pose_basis':rule['basis']}
    raise ValueError('Existing laboratory door jamb could not be retained')



def level_overrides(policy,plan,level):
    """Bind override IDs to the actual derived level, never to a guessed name."""
    require(level in LEVELS,'Unknown door-selection level')
    openings={opening['id']:opening for opening in plan.get('openings',[])}
    result={}
    for override in policy.get('opening_overrides',[]):
        if override['level_id']!=level:continue
        opening=openings.get(override['opening_id'])
        require(opening is not None and opening['kind']=='door','Unknown or non-door override opening: '+level+'__'+override['opening_id'])
        result[override['opening_id']]=override
        if 'pose' in override:handed_frame(plan,opening,override['pose'],1)
    return result


def validate_overrides(policy,plans):
    """Check all overrides, including a level with no generated door leaves."""
    require(isinstance(plans,dict) and set(plans)<=LEVELS,'Known level plans required for door overrides')
    require({override['level_id'] for override in policy.get('opening_overrides',[])}<=set(plans),'Override level has no actual plan')
    for level,plan in plans.items():level_overrides(policy,plan,level)


def handed_frame(plan,door,pose,scale):
    require(pose.get('hinge_side') in {'left','right'} and type(scale) in (int,float) and math.isfinite(scale) and scale>0,'Known hinge side and positive finite scale required')
    wall=next(w for w in plan['walls'] if w['id']==door['wall']);a,b=[plan['vertices'][wall[k]] for k in ('start','end')];length=math.dist(a,b);u=[(b[i]-a[i])/length for i in (0,1)];left=[-u[1],u[0]]
    adjacent={area['id']:area for area in plan['areas'] if any(e['wall']==wall['id'] for e in area['boundary'])}
    def inside(region):
        if region=='exterior':
            require(len(adjacent)==1,'Exterior pose requires an exterior boundary');return [-v for v in inside(next(iter(adjacent)))]
        require(region in adjacent,'Door pose region must be adjacent to its opening: '+region)
        area=adjacent[region];direction=next(e['direction'] for e in area['boundary'] if e['wall']==wall['id']);winding=1 if floor.signed_area(floor.outline(plan,area))>0 else -1
        return [v*direction*winding for v in left]
    approach=inside(pose['approach_from']);opening=inside(pose['opens_into']);right=[-approach[1],approach[0]];alignment=sum(v*w for v,w in zip(right,u));high=alignment>0 if pose['hinge_side']=='right' else alignment<0
    fraction=door['interval'][1 if high else 0];hinge=[(a[i]+fraction*(b[i]-a[i]))*scale for i in (0,1)];closed=[v*(-1 if high else 1) for v in u]
    return {'hinge_mm':hinge,'closed_axis':closed,'opening_axis':opening,'approach_normal':approach,'right_vector':right,'open_angle_deg':90,'pose_measured':False,**pose}


def material_profile(catalog,name):
    profile=catalog['materials'][name]
    return {**catalog['materials'][profile['base_material']],'color':profile['color']} if 'base_material' in profile else profile


def select(policy,plan,canonical,level,door):
    overrides=level_overrides(policy,plan,level)
    areas=[a for a in plan['areas'] if any(edge['wall']==door['wall'] for edge in a['boundary'])]
    ids={a['id'] for a in areas};material=policy['level_materials'].get(level,policy['default_material'])
    excluded=bool(ids&set(policy['exclude_areas'].get(level,[]))) or any(term.casefold() in a['label'].casefold() for term in policy['exclude_label_terms'] for a in areas)
    chosen=policy['default_type'];reason='default_plain_unclassified_or_small_side_room'
    if excluded:chosen='plain';reason='explicit_room_or_label_exclusion'
    elif level in policy['round_window_levels']:
        if ids&set(policy['include_areas'].get(level,[])):chosen='round_window';reason='owner_confirmed_room'
        else:
            rule=policy['large_outer_room_rule'];reference=floor.outline(canonical,rule['reference_area']);band=floor.outline(canonical,rule['band_reference_area'])
            threshold=abs(floor.signed_area(reference))*rule['minimum_area_ratio'];low=min(p[1] for p in band);high=max(p[1] for p in band)
            for area in areas:
                if area['kind']!='room':continue
                pts=floor.outline(plan,area)
                if abs(floor.signed_area(pts))>=threshold and (max(p[1] for p in pts)<=low+1e-9 or min(p[1] for p in pts)>=high-1e-9):
                    chosen='round_window';reason='owner_large_outer_room_rule';break
    result={'type':chosen,'material':material,'level_id':level,'area_ids':sorted(ids),'reason':reason,'mass_kg':None}
    override=overrides.get(door.get('id'))
    if override is not None:
        result.update(type=override['type'],material=override['material'],reason='owner_opening_override',override_basis=override['basis'])
        if 'pose' in override:result['pose']=dict(override['pose'])
    corridor_pose=laboratory_corridor_pose(policy,plan,level,door)
    if corridor_pose is not None:
        require('pose' not in result or result['pose']==corridor_pose['pose'],'Opening override conflicts with outward laboratory corridor rule')
        result.update(corridor_pose)
    return result


def geometry(catalog,selection,name,hinge,u,normal,width,height,z,legacy,component='BuildingExterior'):
    require(selection['type'] in catalog['types'] and selection['material'] in catalog['materials'],'Unsupported door variant')
    material=selection['material'];profile=material_profile(catalog,material)
    require(material!='glass' or selection['type']=='plain','A full-glass leaf uses the plain geometry type')
    thickness=legacy['door_leaf_mm'] if material=='wood' else profile['thickness_mm'];color=legacy['door_color'] if material=='wood' else profile['color']
    require(width>0 and height>0 and thickness>0,'Positive door dimensions required')
    result={'bodies':[],'operations':[]}
    def body(id,role,color,opacity=1):result['bodies'].append({'id':id,'component':component,'role':role,'appearance':{'color':color,'opacity':opacity}})
    def op(id,target,shape,action='create'):result['operations'].append({'id':id,'body':target,'action':action,'shape':shape})
    def cylinder(id,target,along,radius,depth,action='create'):
        op(id,target,{'kind':'cylinder','origin':[center[0]+along*u[0],center[1]+along*u[1],z+w['center_height_mm']],
            'radius':radius,'height':depth,'axis':[u[0],u[1],0]},action)
    body(name,'concept_open_'+material+'_room_door',color,profile.get('opacity',1))
    points=[[hinge[j]+along*u[j]+across*normal[j] for j in (0,1)] for along,across in [(-thickness,0),(0,0),(0,width),(-thickness,width)]]
    if floor.signed_area(points)<0:points.reverse()
    op(name+'_Leaf',name,{'kind':'polygon_prism','plane':'XY','points':points,'offset':z,'depth':height,'fixed':True})
    selection.update(leaf_body_id=name,leaf_thickness_mm=thickness,width_mm=width,height_mm=height,detail_body_ids=[],dimensions_measured=False)
    if material=='glass':selection['full_leaf_glazing']=True
    if selection['type']=='plain':return result
    w=catalog['window'];radius=w['diameter_mm']/2;rim_radius=radius+w['rim_width_mm']
    require(2*(rim_radius+w['edge_margin_mm'])<width and rim_radius+w['edge_margin_mm']<w['center_height_mm']<height-rim_radius-w['edge_margin_mm'],'Viewing window does not fit its door leaf: '+name)
    require(w['glass_thickness_mm']<thickness,'Pane must fit within the leaf thickness')
    center=[hinge[j]+width*normal[j]/2 for j in (0,1)]
    cylinder(name+'_ViewingOpening',name,-thickness-1,radius,thickness+2,'cut')
    pane=name+'_ViewingGlass';body(pane,'concept_round_door_glass',w['glass_color'],w['glass_opacity'])
    cylinder(pane+'_Pane',pane,-(thickness+w['glass_thickness_mm'])/2,radius-w['radial_glass_clearance_mm'],w['glass_thickness_mm']);selection['detail_body_ids'].append(pane)
    for suffix,along in [('Front',0),('Back',-thickness-w['rim_thickness_mm'])]:
        rim=name+'_ViewingRim'+suffix;body(rim,'concept_round_door_rim',w['rim_color']);cylinder(rim+'_Outer',rim,along,rim_radius,w['rim_thickness_mm']);cylinder(rim+'_Inner',rim,along-.1,radius,w['rim_thickness_mm']+.2,'cut');selection['detail_body_ids'].append(rim)
    selection['window']={'center_mm':center+[z+w['center_height_mm']],'diameter_mm':w['diameter_mm'],'axis':[u[0],u[1],0],'pane_body_id':pane}
    return result
