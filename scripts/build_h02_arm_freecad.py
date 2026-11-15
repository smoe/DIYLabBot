"""Native default arm plus independently constructed H02; continuous OCC audit."""
import FreeCAD as App
import Part
import sys
from pathlib import Path
import json
import math
import copy
import h02_arm_pickup as model
import h02_direct_pickup as local
import build_h02_direct_pickup_freecad as h02_native
import build_tube_carrier_freecad as shapes_native
import build_neutral_freecad as arm_native
import build_extraction_kit_station as common
sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion_native


def box(shape,optimal=False):
    # OCC default boxes may include spline control-point hulls. Keep those
    # conservative boxes for motion bounds; compare native geometric extrema.
    b=shape.optimalBoundingBox(False,False) if optimal else shape.BoundBox
    return {'min':[b.XMin,b.YMin,b.ZMin],'max':[b.XMax,b.YMax,b.ZMax]}


def center(shape):
    volume=sum(s.Volume for s in shape.Solids)
    if volume<=0:raise ValueError('Empty native collision body')
    return [sum(s.CenterOfMass[i]*s.Volume for s in shape.Solids)/volume for i in range(3)]


def main(case_path):
    case=json.loads(Path(case_path).read_text());common.verify_pins(case['pins'])
    if case.get('program_kind')=='h02-rack-transfer':
        import h02_rack_transfer as transfer
        program=transfer.Program()
    else:program=model.Program()
    scene=program.local_scene;spec=local.context(scene,case['variant']);p=local.parameters(spec)
    directory=model.ROOT/case['directory'];cad=model.ROOT/case['cad_directory']
    local_case={'variant':case['variant'],'pins':case['pins'],'freecad':common.relative(cad/'holder.FCStd'),
        'step':None,'freecad_report':common.relative(directory/'local-freecad.json')}
    common.write(directory/'holder.case.json',local_case);h02_native.build(directory/'holder.case.json')
    doc=arm_native.build(program.arm,cad/'arm-source.FCStd');motion_native.set_angles(doc,[0]*6)
    for name,value in [('H02SceneSource',common.relative(getattr(program,'source_path',model.SOURCE))),('H02SceneSHA256',model.robot.digest(getattr(program,'source_path',model.SOURCE)))]:
        doc.Controller.addProperty('App::PropertyString',name,'H02 source');setattr(doc.Controller,name,value)
    doc.Robot.Placement.Base=App.Vector(*program.definition['arm_fixture']['position_mm']);doc.recompute()
    records=[];objects={};styles=[];hidden=set()
    looks=model.robot.appearances(program.arm)
    def remember(obj,kind,color,opacity=1):
        name=obj.SourceBody;objects[name]=obj
        styles.append({'id':name,'appearance':{'color':color,'opacity':opacity}})
        if obj.ModelRole=='viewing_cone':hidden.add(name);return
        shape=motion_native.world_shape(obj);bounds=box(shape)
        local_bounds={key:[x-v for x,v in zip(bounds[key],program.definition['arm_fixture']['position_mm'])] for key in ['min','max']} if kind=='arm' else bounds
        records.append({'id':name,'group':obj.RigidLink,'kind':kind,'role':obj.ModelRole,'local_bbox':local_bounds})
    for obj in motion_native.features(doc):
        color,opacity=motion_native.source_color(looks,obj.SourceBody,obj.RigidLink)
        remember(obj,'arm','#'+''.join('%02x'%round(v*255) for v in color),opacity)
    # Do not copy serialized joint structures between documents: fixture bodies
    # are evaluated from source in this same kernel, then placed in explicit groups.
    source,_,witnesses=local.proof(spec,p);meta={b['id']:b for b in source['bodies']};groups={}
    for c in source['components']:
        groups[c['id']]=doc.addObject('App::Part',c['id'])
    for child,parent in [('FingerLeft','Tool'),('FingerRight','Tool')]:groups[parent].addObject(groups[child])
    holder=App.openDocument(str(cad/'holder.FCStd'))
    for item in shapes_native.objects(holder):
        m=meta[item.SourceBody];obj=doc.addObject('Part::Feature',item.SourceBody);groups[m['component']].addObject(obj)
        obj.Shape=motion_native.world_shape(item)
        for key,value in [('SourceBody',item.SourceBody),('RigidLink',m['component']),('ModelRole',m['role'])]:obj.addProperty('App::PropertyString',key,'Source');setattr(obj,key,value)
        kind='sample' if m['component']=='Tube' else 'tool' if m['component'] in ('Tool','FingerLeft','FingerRight') else 'fixture'
        if m['component']=='Proof':
            objects[obj.SourceBody]=obj;styles.append({'id':obj.SourceBody,'appearance':m['appearance']});hidden.add(obj.SourceBody)
        else:remember(obj,kind,m['appearance']['color'],m['appearance']['opacity'])
        if obj.SourceBody.endswith('MouthKeepout'):hidden.add(obj.SourceBody)
    App.closeDocument(holder.Name)
    if hasattr(program,'extra_parts'):
        from h02_transfer_adapters import freecad_extras
        parts,extra=freecad_extras(program,case['variant'],cad/'rack-parts.FCStd',shapes_native);meta_extra={b['id']:b for b in parts}
        for item in shapes_native.objects(extra):
            b=meta_extra[item.SourceBody];group=groups.get(b['group'])
            if group is None:group=doc.addObject('App::Part',b['group']);groups[b['group']]=group
            obj=doc.addObject('Part::Feature',b['id']);group.addObject(obj);obj.Shape=motion_native.world_shape(item);obj.Placement.Base=obj.Placement.Base+App.Vector(*b['translation'])
            for key,value in [('SourceBody',b['id']),('RigidLink',b['group']),('ModelRole',b['role'])]:obj.addProperty('App::PropertyString',key,'Source');setattr(obj,key,value)
            remember(obj,b['kind'],b['appearance']['color'],b['appearance']['opacity'])
            if b['hidden']:hidden.add(b['id'])
        App.closeDocument(extra.Name)
    program.local_certified=True
    for name in getattr(program,'coordinate_names',['ToolZ','TubeZ','JawLeft','JawRight']):doc.Controller.addProperty('App::PropertyAngle' if name.endswith('Yaw') else 'App::PropertyDistance',name,'H02 coordinates')
    groups['Tool'].setExpression('Placement.Base.z','Controller.ToolZ');groups['Tube'].setExpression('Placement.Base.z','Controller.TubeZ')
    groups['FingerLeft'].setExpression('Placement.Base.x','-Controller.JawLeft');groups['FingerRight'].setExpression('Placement.Base.x','Controller.JawRight')
    if 'ToolY' in doc.Controller.PropertiesList:
        groups['Tool'].setExpression('Placement.Base.y','Controller.ToolY');groups['Tube'].setExpression('Placement.Base.y','Controller.TubeY')
        groups['Tool'].setExpression('Placement.Rotation.Angle','Controller.ToolYaw');groups['Tool'].Placement.Rotation.Axis=App.Vector(0,0,1)
        groups['Tube'].setExpression('Placement.Rotation.Angle','Controller.TubeYaw');groups['Tube'].Placement.Rotation.Axis=App.Vector(0,0,1)
    for probe in model.probes(program):
        obj=doc.addObject('Part::Feature',probe['id']);doc.getObject(probe['group']).addObject(obj)
        obj.Shape=Part.makeSphere(.2,App.Vector(*probe['point']))
        for key,value in [('SourceBody',probe['id']),('RigidLink',probe['group']),('ModelRole','fk_probe')]:obj.addProperty('App::PropertyString',key,'Source');setattr(obj,key,value)
        objects[obj.SourceBody]=obj;hidden.add(obj.SourceBody);styles.append({'id':obj.SourceBody,'appearance':{'color':'#ff00ff','opacity':1}})
    b=program.definition['support_plane'];bench=doc.addObject('Part::Feature','SupportPlane')
    bench.Shape=Part.makeBox(*b['size_mm'],App.Vector(*b['origin_mm']))
    for key,value in [('SourceBody','SupportPlane'),('RigidLink','Ground'),('ModelRole','support_plane_witness')]:bench.addProperty('App::PropertyString',key,'Source');setattr(bench,key,value)
    remember(bench,'bench','#90999c')
    control=doc.addObject('Part::Feature','ArmMidpathBlocker');groups['Proof'].addObject(control)
    mid=program.state('extraction',.5);point=mid.get('tool_position_mm',[0,0,mid['tool_z_mm']]);point=[point[0],point[1],point[2]+program.kin.length-3]
    control.Shape=Part.makeBox(1,1,1,App.Vector(point[0]-.5,point[1]-.5,point[2]-.5))
    for key,value in [('SourceBody','ArmMidpathBlocker'),('RigidLink','Proof'),('ModelRole','negative_control')]:control.addProperty('App::PropertyString',key,'Source');setattr(control,key,value)
    objects['ArmMidpathBlocker']=control;hidden.add('ArmMidpathBlocker');styles.append({'id':'ArmMidpathBlocker','appearance':{'color':'#ff00ff','opacity':.2}})
    # Marker inputs describe source positions, never collision geometry.
    def set_state(phase,u):
        state=program.state(phase,u)
        for i,value in enumerate(state['joints_deg'],1):setattr(doc.Controller,'J'+str(i),value)
        for name,value in state['coordinates'].items():setattr(doc.Controller,name,value)
        doc.recompute();return state
    count=0
    def provider(requests):
        nonlocal count
        frames=[]
        for phase,u,width in requests:
            state=set_state(phase,u);shapes={name:motion_native.world_shape(obj) for name,obj in objects.items()}
            centers={name:center(shapes[name]) for name in [v['id'] for v in model.probes(program)]+['ToolMount']}
            active={r['id']:shapes[r['id']] for r in records}
            boxes={name:box(s) for name,s in active.items()};threshold=max(5,max(program.definition['clearance_mm'].values())+1)
            def distance(a,b,values=active,bounds=boxes,coarse=width>1/16):
                lower=model.bbox_distance(bounds[a],bounds[b])
                return lower if coarse or lower>=threshold else values[a].distToShape(values[b])[0]
            frames.append({'boxes':boxes,'coarse_lower_bounds_only':width>1/16,
                'fk_error_mm':model.probe_error(program,state,centers,records),
                'distance':distance})
            count+=1
        print('OCC frames '+str(count),flush=True)
        return frames
    audit=model.certify(program,records,provider);common.write(directory/'continuous-freecad.json',audit)
    if not audit['passed']:
        print(json.dumps(audit['failures'])[:12000],flush=True);raise AssertionError('Continuous arm OCC audit failed')
    actual_records=records;actual_program=program;program=copy.copy(program);program.curves={'extraction':program.curves['extraction']}
    records=[next(r for r in actual_records if r['id']=='ToolMount'),{'id':'ArmMidpathBlocker','group':'Proof','kind':'control','role':'negative_control','local_bbox':box(control.Shape)}]
    rejected=model.certify(program,records,provider);control_shapes=[]
    for u in [0,.5,1]:
        set_state('extraction',u);mount=motion_native.world_shape(objects['ToolMount']);obstacle=motion_native.world_shape(control)
        control_shapes.append({'u':u,'distance_mm':mount.distToShape(obstacle)[0],
                              'overlap_mm3':sum(s.Volume for s in mount.common(obstacle).Solids)})
    negative={'rejected_by_continuous_audit':not rejected['passed'],'states':control_shapes,'audit':rejected}
    if rejected['passed'] or control_shapes[1]['overlap_mm3']<.9 or min(control_shapes[i]['distance_mm'] for i in [0,2])<1:
        raise AssertionError('Midpath robot/tool control was not rejected with clear endpoints')
    records=actual_records;program=actual_program
    contacts=[]
    if hasattr(program,'extra_parts'):
        set_state('release',0);support=motion_native.world_shape(objects['Rack_Base'])
        for name in ['Selected_ReferenceTube','CarriedEnvelope']:
            sample=motion_native.world_shape(objects[name]);distance=sample.distToShape(support)[0];volume=sum(s.Volume for s in sample.common(support).Solids)
            if distance>1e-6 or volume>program.local_scene['volume_tolerance_mm3']:raise AssertionError('Rack support contact is not nonpenetrating')
            contacts.append({'body':name,'distance_mm':distance,'overlap_mm3':volume,'passed':True})
    poses=[]
    for label,phase,u in getattr(program,'native_poses',[('approach','approach',0),('grasp','closure',1),('extracted','extraction',1)]):
        state=set_state(phase,u);geometry=[]
        for name,obj in objects.items():
            shape=motion_native.world_shape(obj);geometry.append({'body':name,'volume_mm3':sum(s.Volume for s in shape.Solids),'center_of_mass':center(shape),'bbox':box(shape,optimal=True),
                                                                'closed':shape.isValid() and len(shape.Solids)>=1})
        path=cad/(label+'.FCStd');doc.saveAs(str(path))
        h02_native.presentation(path,{'bodies':styles},geometry,hidden)
        poses.append({'state':label,'file':common.relative(path),'geometry':geometry})
    App.closeDocument(doc.Name);common.verify_pins(case['pins'])
    report={'passed':True,'pins':case['pins'],'records':records,'poses':poses,'continuous_audit':common.relative(directory/'continuous-freecad.json'),
            'local_audit':local_case['freecad_report'],'analytic_reach_and_motion':program.audit(),
            'negative_control':negative,'support_contacts':contacts,
            'presentation':'Native metadata saved; FreeCAD GUI rendering not inspected'}
    common.write(directory/'freecad-report.json',report)
    print('Full arm OCC passed '+case['variant'],flush=True)


if __name__=='__main__':main(sys.argv[1])
