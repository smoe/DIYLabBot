"""Compose L01 from native room and pinned, posed equipment snapshots."""
from pathlib import Path
import json
import math
import sys
import FreeCAD as App
import Part
import Import
import lab_layout_model as model
import lab_room_model as room
import build_lab_room_freecad as room_backend
from build_neutral_freecad import native_expression

sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion


def placement(item,p): return App.Placement(App.Matrix(*[v for row in model.matrix(item,p) for v in row]))
def bb(shape):
    b=shape.optimalBoundingBox(False,False)
    return {'min':[b.XMin,b.YMin,b.ZMin],'max':[b.XMax,b.YMax,b.ZMax]}
def intersects(a,b): return all(a['min'][k]<b['max'][k]-1e-6 and b['min'][k]<a['max'][k]-1e-6 for k in range(3))
def volume_center(shapes):
    volume=sum(s.Volume for s in shapes)
    centre=[sum(sum(sol.CenterOfMass[k]*sol.Volume for sol in s.Solids) for s in shapes)/volume for k in range(3)]
    return volume,centre
def hexcolor(color): return color if isinstance(color,str) else '#'+''.join('%02x'%int(v) for v in color)


def asset_meta(s,kind,item):
    provider=model.provider(kind); source=model.instance_source(s,item)
    if kind=='arm': return source,provider.appearances(source)
    p=provider.parameters(source)
    expanded=provider.expanded(source,p,model.instance_variant(source,item)) if kind in ['transporter','tube_rack'] else provider.expanded(source,p)
    return source,{b['id']:b for b in expanded['bodies']}


def source_document(s,item,path):
    """Instantiate existing native adapters, preserving geometry/frame parameter coupling."""
    kind=item['asset'];source=model.instance_source(s,item);provider=model.provider(kind);p=provider.parameters(source)
    if kind=='arm':
        from build_neutral_freecad import build
        return build(source,path)
    if kind in ['transporter','tube_rack']:
        from build_sample_transport_freecad import build
        return build(source,p,model.instance_variant(source,item),path)
    if kind=='centrifuge':
        from build_centrifuge_freecad import build
    elif kind=='tip_collector':
        from build_tip_collector_freecad import build
    else: raise ValueError('Unsupported native layout instance: '+kind)
    return build(source,p,path)


def prepare(context):
    s=model.load(); p=model.parameters(s); out=Path(context['out']); cad=Path(context['cad']); assets=cad/'assets'; assets.mkdir(exist_ok=True)
    room_source=room.load(model.assembly.validate_reference(s['assets']['room']))
    doc=room_backend.build(room_source,room.parameters(room_source),cad/'LabLayout_L01.FCStd')
    for key,value in s['parameters'].items():
        doc.ModelParameters.addProperty('App::PropertyDistance',key,'Layout study (mm)'); setattr(doc.ModelParameters,key,value)
    controller=doc.addObject('App::FeaturePython','LayoutController')
    for key,value in [('SourceFile',str(model.SOURCE.relative_to(model.ROOT))),('SpecSHA256',model.digest(model.SOURCE)),('Status',s['status'])]:
        controller.addProperty('App::PropertyString',key,'Layout source'); setattr(controller,key,value)
    cached={}; snapshots=[]; scene_styles={}; scene_meta={}; all_groups={}
    room_expanded=room.expanded(room_source,room.parameters(room_source))
    for b in room_expanded['bodies']: scene_styles[b['id']]=b['appearance']; scene_meta[b['id']]={'instance':'Room','role':b['role']}
    for obj in room_backend.objects(doc): obj.addProperty('App::PropertyString','LayoutInstance','Layout'); obj.LayoutInstance='Room'

    def add_snapshot(item,records):
        tag=item['id']; group=doc.addObject('App::Part',tag); all_groups[tag]=group
        group.Placement=placement(item,p)
        # Native translations are adjustable; rotations use the group's placement.
        for axis,value in zip('xyz',item['xyz']): group.setExpression('Placement.Base.'+axis,native_expression(value))
        group.addProperty('App::PropertyString','LayoutAsset','Layout'); group.LayoutAsset=item['asset']
        export_doc=App.newDocument(tag+'_Snapshot'); export_objects=[]; expected=[]
        # A compound product may lose its STEP product name on import. Export
        # each solid with a stable suffix in both target snapshots instead.
        solids=[]
        for old,shape,style,role in records:
            if len(shape.Solids)>1:
                solids.extend((old+'__Solid'+str(i),solid,style,role)
                              for i,solid in enumerate(shape.Solids,1))
            else: solids.append((old,shape.Solids[0] if shape.Solids else shape,style,role))
        for old,shape,style,role in solids:
            name=tag+'__'+old; target=doc.addObject('Part::Feature',name); group.addObject(target); target.Shape=shape.copy(); target.Label=name
            for key,value in [('SourceBody',name),('RigidLink',tag),('ModelRole',role),('LayoutInstance',tag),('OriginalBody',old)]:
                target.addProperty('App::PropertyString',key,'Layout source'); setattr(target,key,value)
            obj=export_doc.addObject('Part::Feature',name); obj.Shape=shape.copy(); obj.Label=name; export_objects.append(obj)
            scene_styles[name]=style; scene_meta[name]={'instance':tag,'role':role}
            expected.append({'name':name,'role':role,'appearance':style})
        step=assets/(tag+'.step'); Import.export(export_objects,str(step)); App.closeDocument(export_doc.Name)
        snapshots.append({'id':tag,'step':str(step),'matrix':model.matrix(item,p),'bodies':expected,'source_asset':item['asset'],'instance':item})

    for item in s['instances']:
        kind=item['asset']; lookup='transporter' if kind=='tube_rack' else kind
        source,styles=asset_meta(s,kind,item)
        cache_key=json.dumps({'asset':lookup,'parameters':model.provider(kind).parameters(source),'variant':item.get('variant','Floor_Mixed')},sort_keys=True)
        if cache_key not in cached:
            # Build each distinct source/parameter variant once; scene bodies are derived snapshots.
            cached[cache_key]=source_document(s,item,assets/(item['id']+'_source.FCStd'))
        upstream=cached[cache_key]
        if kind=='arm':
            for i,value in enumerate(item['joints_deg'],1): setattr(upstream.Controller,'J'+str(i),value)
        if kind=='centrifuge':
            import centrifuge_model as cf
            for key,value in cf.pose(source,cf.parameters(source),item.get('pose','closed')).items(): setattr(upstream.Controller,key,value)
        upstream.recompute(); records=[]
        for obj in motion.features(upstream):
            old=obj.SourceBody; role=getattr(obj,'ModelRole','equipment_geometry')
            if role=='viewing_cone' or old in item.get('exclude_bodies',[]): continue
            shape=motion.world_shape(obj)
            if kind=='arm':
                color,opacity=motion.source_color(styles,old,obj.RigidLink); style={'color':hexcolor([round(v*255) for v in color]),'opacity':opacity}
            else: style=styles.get(old,{}).get('appearance',{'color':'#b4bec8','opacity':1})
            if kind=='tube_rack':
                if not (old in ['B2_Cassette','B2_Rack24'] or old.startswith('B2_Tube')): continue
                shape.translate(App.Vector(*[-v for v in model.cassette_datum(source,item)])); old=old.removeprefix('B2_'); role='reused_tube_cassette'
            records.append((old,shape,style,role))
        add_snapshot(item,records)
        if kind=='centrifuge':
            import centrifuge_model as cf
            for key,value in cf.pose(source,cf.parameters(source),'open').items(): setattr(upstream.Controller,key,value)
            upstream.recompute(); open_shapes=[motion.world_shape(o) for o in motion.features(upstream)]
            context['cf_open_step']=str(assets/'CF01_open.step'); Part.makeCompound(open_shapes).exportStep(context['cf_open_step'])
            for key,value in cf.pose(source,cf.parameters(source),'closed').items(): setattr(upstream.Controller,key,value)
    for prop in model.primitives(s):
        latest=None
        for index,operation in enumerate(prop['ops']):
            shape=Part.makeBox(*operation['size'],App.Vector(*operation['origin']))
            latest=shape if operation['action']=='create' else latest.cut(shape)
        add_snapshot({**prop,'asset':'mount_riser'},[('Frame',latest,{'color':prop['color'],'opacity':1},'concept_open_riser')])
    for corridor in s['corridors']:
        x0,x1,y0,y1=model.xyz(corridor['bounds'][:3],p)+[model.robot.evaluate(corridor['bounds'][3],p)]
        obj=doc.addObject('Part::Box',corridor['id']); obj.Length=x1-x0;obj.Width=y1-y0;obj.Height=1.5;obj.Placement.Base=App.Vector(x0,y0,0.1)
        for key,value in [('SourceBody',corridor['id']),('RigidLink','Guides'),('ModelRole','planning_overlay'),('LayoutInstance','Guides')]: obj.addProperty('App::PropertyString',key,'Layout');setattr(obj,key,value)
        scene_styles[corridor['id']]={'color':corridor['color'],'opacity':0.32};scene_meta[corridor['id']]={'instance':'Guides','role':'planning_overlay'}
    doc.recompute();doc.save()
    context.update({'snapshots':snapshots,'styles':scene_styles,'body_metadata':scene_meta,'scene_file':str(cad/'LabLayout_L01.FCStd')})
    (out/'context.json').write_text(json.dumps(context,indent=2)+'\n',encoding='utf-8')
    validate(doc,s,context)
    for source_doc in list(cached.values()):
        if source_doc.Name in App.listDocuments(): App.closeDocument(source_doc.Name)
    App.closeDocument(doc.Name)


def validate(doc,s,context):
    p=model.parameters(s); entries=[]; groups={}
    for o in motion.features(doc):
        shape=motion.world_shape(o); bounds=bb(shape); tag=o.LayoutInstance
        entries.append((o,shape,bounds));groups.setdefault(tag,[]).append(shape)
    overlaps=[]
    for i,(a,ash,ab) in enumerate(entries):
        if a.LayoutInstance=='Guides':continue
        for b,bsh,bbx in entries[i+1:]:
            if a.LayoutInstance==b.LayoutInstance or b.LayoutInstance=='Guides' or not intersects(ab,bbx): continue
            volume=ash.common(bsh).Volume
            if volume>1e-3: overlaps.append({'a':a.SourceBody,'b':b.SourceBody,'volume_mm3':volume})
    corridor_checks=[]
    for c in s['corridors']:
        x0,x1,y0,y1=[model.robot.evaluate(v,p) for v in c['bounds']]
        envelope=Part.makeBox(x1-x0,y1-y0,p['human_check_h'],App.Vector(x0,y0,0)); bounds=bb(envelope); blockers=[]
        for o,shape,b in entries:
            if o.LayoutInstance=='Guides' or not intersects(bounds,b): continue
            volume=envelope.common(shape).Volume
            if volume>1e-3: blockers.append({'body':o.SourceBody,'volume_mm3':volume})
        corridor_checks.append({'id':c['id'],'width_mm':min(x1-x0,y1-y0),'blockers':blockers,'passed':not blockers})
    tr_group=doc.getObject('TR01'); inv=tr_group.Placement.inverse(); vehicle=Part.makeCompound([shape for o,shape,b in entries if o.LayoutInstance=='TR01']);vehicle.Placement=inv.multiply(vehicle.Placement)
    route=s['vehicle_route']; starts=model.xyz(route['waypoints'][0]+[0],p); ends=model.xyz(route['waypoints'][1]+[0],p); length=math.dist(starts,ends); count=math.ceil(length/route['sample_step_mm']); route_hits=[]
    obstacles=[(o,shape,b) for o,shape,b in entries if o.LayoutInstance not in ['Guides','TR01']]
    for i in range(count+1):
        t=i/count; item={'xyz':[a+t*(b-a) for a,b in zip(starts,ends)],'yaw_deg':route['yaw_deg']}; moved=vehicle.copy(); moved.Placement=placement(item,p).multiply(vehicle.Placement); bounds=bb(moved)
        for o,shape,b in obstacles:
            if intersects(bounds,b):
                volume=moved.common(shape).Volume
                if volume>1e-3:route_hits.append({'sample':i,'body':o.SourceBody,'volume_mm3':volume})
    cf_item=next(i for i in s['instances'] if i['id']=='CF01'); cf_shape=Part.read(context['cf_open_step']); cf_shape.Placement=placement(cf_item,p).multiply(cf_shape.Placement); open_hits=[]
    for o,shape,b in entries:
        if o.LayoutInstance in ['CF01','Guides'] or not intersects(bb(cf_shape),b):continue
        volume=cf_shape.common(shape).Volume
        if volume>1e-3:open_hits.append({'body':o.SourceBody,'volume_mm3':volume})
    metrics={}
    for tag,shapes in groups.items():
        v,c=volume_center(shapes); bounds=[bb(x) for x in shapes]
        metrics[tag]={'body_count':len(shapes),'volume_mm3':v,'center_of_mass_mm':c,'bbox':{'min':[min(b['min'][i] for b in bounds) for i in range(3)],'max':[max(b['max'][i] for b in bounds) for i in range(3)]}}
    report={'geometry_valid':all(shape.isValid() and shape.Volume>0 for o,shape,b in entries),'body_count':len(entries),'instance_metrics':metrics,
        'static_interferences':overlaps,'human_corridors':corridor_checks,'vehicle_route':{'samples':count+1,'collisions':route_hits,'passed':not route_hits},
        'centrifuge_open':{'collisions':open_hits,'passed':not open_hits},'position_only_reach':model.reach_report(s)}
    report['passed']=report['geometry_valid'] and not overlaps and all(c['passed'] for c in corridor_checks) and not route_hits and not open_hits and all(r['passed'] for r in report['position_only_reach'])
    (Path(context['out'])/'layout-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'bodies':len(entries),'overlaps':overlaps[:12],'corridor_failures':[c for c in corridor_checks if not c['passed']],'route_collisions':route_hits[:8],'open_lid_collisions':open_hits[:8]}),flush=True)


def main(path): prepare(json.loads(Path(path).read_text(encoding='utf-8')))


if __name__=='__main__':
    import build_lab_layout_freecad as backend
    backend.main(sys.argv[1])
