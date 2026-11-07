"""Native live L01 arm/centrifuge scene and sampled BRep motion audit."""
from pathlib import Path
import json
import math
import shutil
import sys
import FreeCAD as App
import Part
import Import
import lab_transfer_model as model
import lab_layout_model as layout
import robot_spec as robot
import centrifuge_model as cf
import build_lab_layout_freecad as static
sys.path.insert(0,str(layout.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion


def app(m):return App.Placement(App.Matrix(*[v for row in m for v in row]))
def shape_at(shape,m):
    result=shape.copy();result.Placement=app(m).multiply(shape.Placement);return result
def bounds(shape):return shape.BoundBox
def lower_distance(a,b):return math.sqrt(sum(max(0,x0-y1,y0-x1)**2 for x0,x1,y0,y1 in [(a.XMin,a.XMax,b.XMin,b.XMax),(a.YMin,a.YMax,b.YMin,b.YMax),(a.ZMin,a.ZMax,b.ZMin,b.ZMax)]))
def sample_matrix(bottom,axis):
    tilt=math.acos(max(-1,min(1,axis[2])));yaw=math.atan2(axis[1],axis[0]) if abs(axis[0])+abs(axis[1])>1e-10 else 0
    c,s=math.cos(yaw),math.sin(yaw);a,b=math.cos(tilt),math.sin(tilt)
    return [[c*a,-s,c*b,bottom[0]],[s*a,c,s*b,bottom[1]],[-b,0,a,bottom[2]],[0,0,0,1]]


def prepare(path):
    ctx=json.loads(Path(path).read_text());s=model.load();ls=layout.load();d=model.data(s,ls)
    if ctx.get('reuse_scene'):
        reuse(ctx,s,ls,d);return
    cad=Path(ctx['cad']);out=Path(ctx['out']);assets=cad/'assets';assets.mkdir(exist_ok=True)
    parent=json.loads(Path(ctx['layout_context']).read_text());doc=App.openDocument(parent['scene_file'])
    scene=cad/'LabTransfer_L01.FCStd';doc.saveAs(str(scene));ctx.update(scene_file=str(scene),snapshots=[],dynamic=[],styles=dict(parent['styles']))
    doc.Label='L01 sample transfer - native prescribed kinematics'
    for key,value in [('TransferSourceFile',str(model.SOURCE.relative_to(layout.ROOT))),('TransferSHA256',ctx['protocol_sha256']),('TransferLayoutSHA256',ctx['layout_sha256'])]:
        doc.LayoutController.addProperty('App::PropertyString',key,'Transfer source');setattr(doc.LayoutController,key,value)
    controllers={};native_groups={};cache=[];joint_specs={};baseline_docs=[]
    for tag in ['ArmC','CF01']:
        for o in list(motion.features(doc)):
            if o.LayoutInstance==tag:doc.removeObject(o.Name)
        ctx['styles']={k:v for k,v in ctx['styles'].items() if not k.startswith(tag+'__')}
    selected='TR01__'+s['sample']['transporter_body']
    for o in list(motion.features(doc)):
        if o.SourceBody==selected:doc.removeObject(o.Name)
    ctx['styles'].pop(selected,None)
    for snapshot in parent['snapshots']:
        if snapshot['id'] in ['ArmC','CF01']:continue
        snap=dict(snapshot);snap['bodies']=[b for b in snapshot['bodies'] if b['name']!=selected]
        target=assets/(snapshot['id']+'.step');shutil.copy2(snapshot['step'],target);snap['step']=str(target)
        if snapshot['id']=='TR01':
            export=App.newDocument('TRSnapshot');objects=[];inv=doc.TR01.Placement.inverse()
            for o in motion.features(doc):
                if o.LayoutInstance!='TR01':continue
                shape=motion.world_shape(o);shape.Placement=inv.multiply(shape.Placement)
                b=export.addObject('Part::Feature',o.SourceBody);b.Shape=shape.Solids[0];b.Label=o.SourceBody;objects.append(b)
            Import.export(objects,str(target));App.closeDocument(export.Name)
        ctx['snapshots'].append(snap)

    def emit(tag,groups,joints,records):
        parent_group=doc.getObject(tag) if doc.getObject(tag) else doc.addObject('App::Part',tag)
        if tag in d['items']:parent_group.Placement=app(layout.matrix(d['items'][tag],d['p']))
        control=doc.addObject('App::FeaturePython',tag+'Control');controllers[tag]=control;groupmap={}
        for group in groups:
            joint=next((j for j in joints if j['child']==group),None)
            if joint:
                anchor=doc.addObject('App::Part',tag+'_'+group+'_Anchor');groupmap[joint['parent']].addObject(anchor)
                frame=motion.frame_placement({'origin':joint['origin'],'x':joint['reference_x'],'z':joint['axis']});anchor.Placement=frame
                turn=doc.addObject('App::Part',tag+'_'+group+'_Motion');anchor.addObject(turn)
                control.addProperty('App::PropertyAngle' if joint['unit']=='deg' else 'App::PropertyDistance',joint['id'],'Coordinates')
                field='Placement.Rotation.Angle' if joint['type']=='revolute' else 'Placement.Base.z'
                turn.setExpression(field,control.Name+'.'+joint['id'])
                part=doc.addObject('App::Part',tag+'_'+group);turn.addObject(part);part.Placement=frame.inverse()
            else:part=doc.addObject('App::Part',tag+'_'+group);parent_group.addObject(part)
            groupmap[group]=part
        native_groups[tag]=groupmap;joint_specs[tag]=joints
        for group in groups:
            export=App.newDocument(tag+'_'+group+'_Export');objects=[];bodies=[]
            for name,rigid,shape,style,role in records:
                if rigid!=group:continue
                name=tag+'__'+name;shape=shape.Solids[0] if len(shape.Solids)==1 else shape
                target=doc.addObject('Part::Feature',name);groupmap[group].addObject(target);target.Shape=shape.copy();target.Label=name
                for key,value in [('SourceBody',name),('RigidLink',group),('LayoutInstance',tag),('ModelRole',role)]:target.addProperty('App::PropertyString',key,'Source');setattr(target,key,value)
                e=export.addObject('Part::Feature',name);e.Shape=shape.copy();e.Label=name;objects.append(e)
                ctx['styles'][name]=style;bodies.append({'name':name,'appearance':style})
                cache.append({'name':name,'tag':tag,'group':group,'role':role,'shape':shape.copy()})
            step=assets/(tag+'_'+group+'.step')
            if objects:Import.export(objects,str(step))
            App.closeDocument(export.Name)
            ctx['dynamic'].append({'id':tag+'_'+group,'tag':tag,'group':group,'step':str(step) if objects else None,
                                   'matrix':layout.matrix(d['items'][tag],d['p']),'bodies':bodies,'grounded':not any(j['child']==group for j in joints)})

    arm_doc=static.source_document(ls,d['items'][s['arm']],assets/'TransferArm_source.FCStd');baseline_docs.append(arm_doc)
    for i in range(1,7):setattr(arm_doc.Controller,'J'+str(i),0)
    arm_doc.recompute();look=robot.appearances(d['arm']);records=[]
    for o in motion.features(arm_doc):
        if o.ModelRole=='viewing_cone':continue
        color,opacity=motion.source_color(look,o.SourceBody,o.RigidLink)
        records.append((o.SourceBody,o.RigidLink,motion.world_shape(o),{'color':static.hexcolor([round(x*255) for x in color]),'opacity':opacity},o.ModelRole))
    flange_z=robot.evaluate(d['arm']['flange_reference']['point'][2],d['ap']);tool=s['tool'];tip=flange_z+tool['flange_standoff_mm']
    shaft=Part.makeCylinder(tool['shaft_radius_mm'],tool['flange_standoff_mm']-tool['shaft_start_mm']-tool['shaft_end_gap_mm'],App.Vector(0,0,flange_z+tool['shaft_start_mm']))
    collar=Part.makeCylinder(9,8,App.Vector(0,0,tip+4)).cut(Part.makeCylinder(7.5,10,App.Vector(0,0,tip+3)))
    for name,shape in [('ToolProxyShaft',shaft),('ToolProxyCollar',collar)]:records.append((name,d['arm']['flange_reference']['link'],shape,{'color':'#e8ac47','opacity':0.6},'assumed_handling_envelope'))
    arm_joints=[{'id':'J'+str(i),'parent':j['parent'],'child':j['child'],'type':'revolute','origin':layout.xyz(j['frame']['origin'],d['ap']),'axis':j['frame']['axis'],'reference_x':j['frame']['x'],'limits':j['limits_deg'],'unit':'deg'} for i,j in enumerate(d['arm']['joints'],1)]
    emit('ArmC',[l['id'] for l in d['arm']['links']],arm_joints,records)
    cf_doc=static.source_document(ls,d['items']['CF01'],assets/'TransferCF_source.FCStd');baseline_docs.append(cf_doc)
    for j in d['ce']['joints']:setattr(cf_doc.Controller,j['id'],0)
    cf_doc.recompute();meta={b['id']:b for b in d['ce']['bodies']};records=[];sample_records=[]
    bottom,axis=cf.pocket(d['cs'],d['cp'],1);canonical_inv=robot.inverse(sample_matrix(bottom,axis))
    for o in motion.features(cf_doc):
        shape=motion.world_shape(o);style=meta[o.SourceBody]['appearance'];role=meta[o.SourceBody]['role']
        if o.SourceBody in ['Tube01','ClosedCap01']:
            sample_records.append((o.SourceBody,shape_at(shape,canonical_inv),style));continue
        records.append((o.SourceBody,o.RigidLink,shape,style,role))
    emit('CF01',[c['id'] for c in d['ce']['components']],d['ce']['joints'],records)
    sample_group=doc.addObject('App::Part','Sample');sample_export=App.newDocument('SampleExport');sample_objs=[];sample_bodies=[]
    for name,shape,style in sample_records:
        label='Sample__'+name;o=doc.addObject('Part::Feature',label);sample_group.addObject(o);o.Shape=shape;o.Label=label
        for key,value in [('SourceBody',label),('RigidLink','Sample'),('LayoutInstance','Sample'),('ModelRole','transferred_sample')]:o.addProperty('App::PropertyString',key,'Source');setattr(o,key,value)
        export=sample_export.addObject('Part::Feature',label);export.Shape=shape.Solids[0];export.Label=label;sample_objs.append(export)
        ctx['styles'][label]=style;sample_bodies.append({'name':label,'appearance':style});cache.append({'name':label,'tag':'Sample','group':'Sample','role':'transferred_sample','shape':shape.copy()})
    step=assets/'Sample.step';Import.export(sample_objs,str(step));App.closeDocument(sample_export.Name);ctx['sample_step']=str(step);ctx['sample_bodies']=sample_bodies
    ctx['joint_specs']=joint_specs
    complete(ctx,doc,cache,s,ls,d)
    for source_doc in baseline_docs:App.closeDocument(source_doc.Name)
    App.closeDocument(doc.Name)


def reuse(ctx,s,ls,d):
    doc=App.openDocument(ctx['reuse_scene']);doc.saveAs(str(Path(ctx['cad'])/'LabTransfer_L01.FCStd'));ctx['scene_file']=doc.FileName
    doc.LayoutController.TransferSHA256=ctx['protocol_sha256'];cache=[]
    for o in motion.features(doc):
        if o.LayoutInstance in ['ArmC','CF01','Sample']:
            cache.append({'name':o.SourceBody,'tag':o.LayoutInstance,'group':o.RigidLink,'role':o.ModelRole,'shape':o.Shape.copy()})
    # Reuse is only for a changed trajectory, never a changed tool or sample.
    shaft=next(c for c in cache if c['name']=='ArmC__ToolProxyShaft')['shape'];tool=s['tool']
    expected=math.pi*tool['shaft_radius_mm']**2*(tool['flange_standoff_mm']-tool['shaft_start_mm']-tool['shaft_end_gap_mm'])
    if abs(shaft.Volume-expected)>1e-5:raise ValueError('Changed tool requires a fresh geometry build')
    if any(o.SourceBody=='TR01__'+s['sample']['transporter_body'] for o in motion.features(doc)):raise ValueError('Changed source cell requires fresh geometry')
    if s['sample']['centrifuge_slot']!=1:raise ValueError('Changed slot requires fresh geometry')
    complete(ctx,doc,cache,s,ls,d);App.closeDocument(doc.Name)


def complete(ctx,doc,cache,s,ls,d):
    out=Path(ctx['out']);controllers={tag:doc.getObject(tag+'Control') for tag in ['ArmC','CF01']}
    native_groups={'ArmC':{l['id']:doc.getObject('ArmC_'+l['id']) for l in d['arm']['links']}}
    timeline=model.compile(s,ls);frames=model.samples(timeline,s,ls)
    (out/'timeline.json').write_text(json.dumps(timeline,indent=2)+'\n');(out/'samples.json').write_text(json.dumps(frames,separators=(',',':')))

    def apply(frame):
        for i,v in enumerate(frame['q'],1):setattr(controllers['ArmC'],'J'+str(i),v)
        for name,v in frame['cf'].items():setattr(controllers['CF01'],name,v)
        doc.Sample.Placement=app(sample_matrix(frame['sample_bottom'],frame['sample_axis']));doc.recompute()

    apply(frames[0]);doc.save();ctx['initial_frame']=frames[0]
    ctx['presentation_bounds']=[]
    for obj in motion.features(doc):
        b=motion.world_shape(obj).BoundBox
        ctx['presentation_bounds'].append({'body':obj.SourceBody,'bbox':{'min':[b.XMin,b.YMin,b.ZMin],'max':[b.XMax,b.YMax,b.ZMax]}})
    # Compare native expression hierarchy with independent common-source FK.
    native_errors=[]
    for frame in [model.at_time(timeline,k['time_s'],s,ls,d) for k in timeline['keyframes'] if k['id'] in ['ready','vehicle_grasp','cf_insert','return_grasp','vehicle_replace','complete']]:
        apply(frame);poses=robot.forward(d['arm'],frame['q'])
        for group,obj in native_groups['ArmC'].items():
            expected=robot.multiply(d['base'],poses[group]);actual=motion.global_placement(obj).Matrix
            error=max(abs(actual.A[i*4+j]-expected[i][j]) for i in range(4) for j in range(4));native_errors.append(error)
    apply(frames[0]);doc.save()
    (out/'context.json').write_text(json.dumps(ctx,indent=2)+'\n')
    endpoints={k['id']:k for k in timeline['keyframes']}
    probe=audit(doc,cache,[model.at_time(timeline,k['time_s'],s,ls,d) for k in endpoints.values()],s,ls,d)
    report=audit(doc,cache,frames,s,ls,d) if probe['passed'] else probe
    report['endpoint_precheck_passed']=probe['passed']
    report['native_arm_frame_max_error']=max(native_errors);report['passed']=report['passed'] and max(native_errors)<1e-7
    (out/'motion-validation.json').write_text(json.dumps(report,indent=2)+'\n');ctx['passed']=report['passed']
    (out/'context.json').write_text(json.dumps(ctx,indent=2)+'\n');print(json.dumps({'passed':report['passed'],'samples':report['samples_checked'],'collisions':report['collisions'][:8],'native_frame_error':max(native_errors)}),flush=True)


def cf_matrix(d,group,values):
    origin=cf.transform(d['ce'],group,[0,0,0],values)
    columns=[model.add(cf.transform(d['ce'],group,v,values),origin,-1) for v in [[1,0,0],[0,1,0],[0,0,1]]]
    m=robot.identity()
    for i in range(3):m[i]=[columns[j][i] for j in range(3)]+[origin[i]]
    return robot.multiply(d['station'],m)


def audit(doc,cache,frames,s,ls,d):
    environment=[];furniture=[]
    def fixed(name,shape,role):
        b=shape.BoundBox
        return {'name':name,'shape':shape,'role':role,'box':model.obb(robot.identity(),[b.XMin,b.YMin,b.ZMin],[b.XMax,b.YMax,b.ZMax])}
    for o in motion.features(doc):
        if o.LayoutInstance in ['ArmC','CF01','Sample','Guides']:continue
        item=fixed(o.SourceBody,motion.world_shape(o),o.ModelRole);environment.append(item)
        if o.LayoutInstance=='Room' and any(k in o.ModelRole for k in ['storage','work_surface','shelf','cupboard']):furniture.append(item)
    for record in cache:
        b=record['shape'].BoundBox;record['minimum']=[b.XMin,b.YMin,b.ZMin];record['maximum']=[b.XMax,b.YMax,b.ZMax]
    collisions=[];best=1e9;nearest=None;seen={};checked=0;self_pairs=set();threshold=s['checks']['volume_threshold_mm3'];groups=[l['id'] for l in d['arm']['links']]
    exact_tests=0;pair_cache={}
    def actual(entry):
        if entry['shape'] is None:entry['shape']=shape_at(entry['record']['shape'],entry['matrix'])
        return entry['shape']
    for index,frame in enumerate(frames):
        key=tuple(round(q,6) for q in frame['q'])+tuple(round(frame['cf'][j['id']],6) for j in d['ce']['joints'])+(frame['sample_owner'],)
        if key in seen:checked+=1;continue
        seen[key]=True;fk=robot.forward(d['arm'],frame['q']);moving=[];station=[];cf_poses={}
        for record in cache:
            if record['tag']=='ArmC':matrix=robot.multiply(d['base'],fk[record['group']])
            elif record['tag']=='CF01':
                if record['group'] not in cf_poses:cf_poses[record['group']]=cf_matrix(d,record['group'],frame['cf'])
                matrix=cf_poses[record['group']]
            else:matrix=sample_matrix(frame['sample_bottom'],frame['sample_axis'])
            entry={'name':record['name'],'shape':None,'record':record,'matrix':matrix,'box':model.obb(matrix,record['minimum'],record['maximum'])}
            (station if record['tag']=='CF01' else moving).append(entry)
        def test(a,b,category):
            nonlocal exact_tests
            if not model.boxes_overlap(a['box'],b['box']):return
            relative=robot.multiply(robot.inverse(a.get('matrix',robot.identity())),b.get('matrix',robot.identity()))
            pair_key=(a['name'],b['name'],tuple(round(v,8) for row in relative for v in row))
            if pair_key in pair_cache:volume=pair_cache[pair_key]
            else:
                exact_tests+=1;volume=actual(a).common(actual(b)).Volume;pair_cache[pair_key]=volume
            if volume>threshold:collisions.append({'sample':index,'time_s':frame['time_s'],'phase':frame['phase'],'a':a['name'],'b':b['name'],'category':category,'volume_mm3':volume})
        for a in moving:
            for b in environment:test(a,b,'static_environment')
            for b in station:test(a,b,'centrifuge')
            if a['record']['tag']=='ArmC' or frame['sample_owner']=='arm':
                for b in furniture:
                    lower=math.sqrt(sum(max(0,a['box']['min'][i]-b['box']['max'][i],b['box']['min'][i]-a['box']['max'][i])**2 for i in range(3)))
                    if lower>=best-1e-7:continue
                    distance=actual(a).distToShape(actual(b))[0]
                    if distance<best:best=distance;nearest={'a':a['name'],'b':b['name'],'phase':frame['phase'],'time_s':frame['time_s']}
        # Adjacent rigid links meet at their real joint interfaces. Audit all
        # non-adjacent link pairs, plus carried sample vs arm except the tool.
        for i,a in enumerate(moving):
            for b in moving[i+1:]:
                if a['record']['tag']==b['record']['tag']=='ArmC':
                    ga,gb=groups.index(a['record']['group']),groups.index(b['record']['group'])
                    if abs(ga-gb)<=1:continue
                    test(a,b,'nonadjacent_arm_self')
                elif a['record']['tag']!=b['record']['tag']:
                    if 'ToolProxy' in a['name'] or 'ToolProxy' in b['name']:continue
                    test(a,b,'sample_arm')
        checked+=1
        if index%20==0:print(json.dumps({'audit_sample':index,'of':len(frames),'phase':frame['phase'],'hits':len(collisions),'exact_tests':exact_tests}),flush=True)
        if len(collisions)>=20:break
    return {'passed':checked==len(frames) and not collisions,'samples_checked':checked,'requested_samples':len(frames),'unique_states_checked':len(seen),
            'collisions':collisions,'minimum_furniture_distance_mm':best,'nearest_furniture_pair':nearest,
            'broad_phase':'Conservative oriented body bounds with 15-axis separation; BRep overlap refinement','exact_overlap_tests':exact_tests,
            'cache':'Exact overlap results reused only for identical body-pair relative transforms, rounded to 1e-8',
            'checks':s['checks'],'excluded_pairs':['within each rigid link','adjacent arm link interfaces','assumed tool/sample grasp contact'],
            'scope':'sampled BRep overlap and furniture distance; no continuous swept-volume guarantee'}


if __name__=='__main__':
    import build_lab_transfer_freecad as backend
    backend.prepare(sys.argv[1])
