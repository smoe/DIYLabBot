"""Native MB01 FreeCAD assembly, using the existing native arm adapter."""
from pathlib import Path
import copy
import json
import math
import sys
import FreeCAD as App
import Part
import mobile_base_model as model
import robot_spec as robot
import robot_cameras
import build_neutral_freecad as native

sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion


def build(spec,arm,p,path):
    composed=copy.deepcopy(arm)
    composed['parameters'].update({k:{'unit':'mm','expression':d['expression']} for k,d in spec['parameters'].items()})
    # Keep overrides as driving dimensions; derived expressions remain native.
    for k,d in spec['parameters'].items():
        if not any(c.isalpha() for c in str(d['expression'])): composed['parameters'][k]['expression']=p[k]
    doc=native.build(composed,path)
    doc.Label=spec['id']+' — manual bench base (concept)'
    controller=doc.Controller
    for name in ['BaseX','BaseY','ChassisLift','SupportA','SupportB','SupportC']:
        controller.addProperty('App::PropertyDistance','MB01_'+name,'Mobile base (mm)')
    controller.addProperty('App::PropertyAngle','MB01_BaseYaw','Mobile base (deg)')
    controller.addProperty('App::PropertyString','MB01_SourceSHA256','Source'); controller.MB01_SourceSHA256=model.digest(model.SOURCE)
    controller.addProperty('App::PropertyString','MB01_Pose','Mobile base')
    controller.addProperty('App::PropertyString','MB01_ResumeRequirement','Mobile base')
    controller.MB01_ResumeRequirement='Fresh tip/tube localization, stable supports and deliberate operator resume; no hardware interlock implemented'
    location=doc.addObject('App::Part','MB01_ManualPose')
    location.setExpression('Placement.Base.x','Controller.MB01_BaseX')
    location.setExpression('Placement.Base.y','Controller.MB01_BaseY')
    location.setExpression('Placement.Rotation.Angle','Controller.MB01_BaseYaw')
    chassis=doc.addObject('App::Part','MB01_Chassis'); location.addObject(chassis)
    chassis.setExpression('Placement.Base.z','Controller.MB01_ChassisLift')
    chassis.addObject(doc.Robot)
    doc.Robot.setExpression('Placement.Base.z',native.native_expression('mb_mount_z'))
    source=model.expanded(spec,p); groups={'MB01_Chassis':chassis}
    for support in source['supports']:
        group=doc.addObject('App::Part',support['component']); chassis.addObject(group)
        group.setExpression('Placement.Base.z','-Controller.MB01_Support'+support['id']); groups[support['component']]=group
    for name,point in source['frames'].items():
        marker=doc.addObject('App::Part',name.replace('.','_')+'_Frame')
        tag=name.rsplit('.',1)[-1]; parent=groups['MB01_Foot_'+tag] if name.startswith('MB01.Support.') else chassis
        parent.addObject(marker); native.set_origin(marker,point)
        marker.Label=name+' (shared design frame)'
    latest={}
    for body in source['bodies']:
        shape=body['geometry']; group=groups[body['component']]; kind=shape['type']
        obj=doc.addObject('Part::Box' if kind=='box' else 'Part::Cylinder',body['id']); group.addObject(obj)
        values=list(zip(['Length','Width','Height'],shape['size'])) if kind=='box' else [('Radius',shape['radius']),('Height',shape['height'])]
        for name,value in values: obj.setExpression(name,native.native_expression(value))
        if kind=='cylinder': obj.Placement.Rotation=App.Rotation(App.Vector(0,0,1),App.Vector(*shape['axis']))
        native.set_origin(obj,shape['origin'])
        for cut in [c for c in source['cuts'] if c['target']==body['id']]:
            s=cut['geometry']; tool=doc.addObject('Part::Cylinder',cut['id']); group.addObject(tool)
            tool.setExpression('Radius',native.native_expression(s['radius'])); tool.setExpression('Height',native.native_expression(s['height']))
            tool.Placement.Rotation=App.Rotation(App.Vector(0,0,1),App.Vector(*s['axis'])); native.set_origin(tool,s['origin'])
            result=doc.addObject('Part::Cut',cut['id']+'_Cut'); group.addObject(result)
            result.Base=obj; result.Tool=tool; result.Refine=True; obj=result
        for key,value in [('SourceBody',body['id']),('RigidLink',body['component']),('ModelRole',body['role'])]:
            obj.addProperty('App::PropertyString',key,'Shared source'); setattr(obj,key,value)
        obj.Label=body['id']; latest[body['id']]=obj
    set_state(doc,model.state(spec,arm,p,'working'),'working')
    doc.recompute(); doc.save()
    return doc


def set_state(doc,pose,name='sample'):
    c=doc.Controller; c.MB01_BaseX,c.MB01_BaseY,c.MB01_BaseYaw=pose['manual_xy_yaw']
    c.MB01_ChassisLift=pose['chassis_lift_mm']
    for tag in 'ABC': setattr(c,'MB01_Support'+tag,pose['support_extension_mm'])
    c.MB01_Pose=name; motion.set_angles(doc,pose['arm_deg']); doc.recompute()


def measurements(doc):
    result=[]
    for obj in motion.features(doc):
        s=motion.world_shape(obj); bb=s.optimalBoundingBox(False,False)
        com=[sum(solid.CenterOfMass[i]*solid.Volume for solid in s.Solids)/s.Volume for i in range(3)]
        result.append({'body':obj.SourceBody,'component':obj.RigidLink,'role':obj.ModelRole,'valid':s.isValid(),
                       'solid_count':len(s.Solids),'volume_mm3':s.Volume,'world_center_of_mass_mm':com,
                       'bbox':{'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]}})
    return result


def probe_error(doc,spec,arm,p,pose):
    root=model.frame_matrix(pose); armroot=robot.identity(); armroot[2][3]=p['mb_mount_z']; root=robot.multiply(root,armroot)
    expected={k:robot.multiply(root,t) for k,t in robot.forward(arm,pose['arm_deg']).items()}
    for link,camera in robot_cameras.cameras(arm):
        expected[camera['id']+'_optical']=robot.multiply(expected[link],robot.frame({'frame':camera['frame']},robot.parameters(arm)))
    error=0
    for name,t in expected.items():
        actual=motion.global_placement(doc.getObject(name))
        for point in [[0,0,0],[17,0,0],[0,23,0],[0,0,31]]:
            error=max(error,(actual.multVec(App.Vector(*point))-App.Vector(*robot.transform(t,point))).Length)
    return error


def envelope(geometry,arm_only=False):
    bodies=[b for b in geometry if b['role']!='viewing_cone' and (not arm_only or not b['body'].startswith('MB01_'))]
    low=[min(b['bbox']['min'][i] for b in bodies) for i in range(3)]
    high=[max(b['bbox']['max'][i] for b in bodies) for i in range(3)]
    return {'min':low,'max':high,'size_mm':[b-a for a,b in zip(low,high)],'xy_area_mm2':(high[0]-low[0])*(high[1]-low[1])}


def contact_geometry(spec,p,pose,geometry):
    by_name={b['body']:b for b in geometry}
    pads=[by_name['MB01_'+tag+'_Pad']['bbox']['min'][2] for tag in 'ABC']
    wheels=[by_name[w['body']]['bbox']['min'][2] for w in model.expanded(spec,p)['wheels']]
    all_low=min(b['bbox']['min'][2] for b in geometry if b['role']!='viewing_cone')
    supported=pose['support_extension_mm']>=p['mb_support_stroke']-1e-8
    released=pose['support_extension_mm']<1e-8
    passed=all_low>=-1e-6
    if supported: passed=passed and max(abs(v) for v in pads)<1e-6 and min(wheels)>p['mb_wheel_lift']-1e-6
    if released: passed=passed and max(abs(v) for v in wheels)<1e-6 and min(pads)>p['mb_foot_clearance']-1e-6
    return {'passed':passed,'pad_bottoms_mm':pads,'wheel_bottoms_mm':wheels,'minimum_physical_z_mm':all_low,
            'load_or_stability_proof':False}


def validate(doc,spec,arm,p):
    geometry=measurements(doc); cache={}; checked=[]
    for sample in model.samples(spec,arm,p):
        print('Checking '+sample['id'],flush=True)
        pose=sample['state']; set_state(doc,pose,sample['id'])
        collisions=motion.check_collisions(doc,cache)
        values=measurements(doc)
        checked.append({'id':sample['id'],'angles_deg':pose['arm_deg'],'max_probe_error_mm':probe_error(doc,spec,arm,p,pose),
                        'overlaps':collisions['overlaps'],'contact_geometry':contact_geometry(spec,p,pose,values)})
        if collisions['overlaps']: print('Overlaps: '+json.dumps(collisions['overlaps']),flush=True)
    envelopes={}
    for name in spec['poses']:
        pose=model.state(spec,arm,p,name); set_state(doc,pose,name); values=measurements(doc)
        envelopes[name]={'assembly':envelope(values),'arm':envelope(values,True),'contact_geometry':contact_geometry(spec,p,pose,values)}
    parameter_checks=[]
    for parameter,delta in [('mb_length',20),('mb_wheel_radius',2)]:
        setattr(doc.ModelParameters,parameter,p[parameter]+delta); doc.recompute()
        changed=model.parameters(spec,{parameter:p[parameter]+delta})
        pose=model.state(spec,arm,changed,'working'); set_state(doc,pose,'parameter_check')
        current=measurements(doc); by_name={b['body']:b for b in current}
        base=model.expanded(spec,changed)
        contact=contact_geometry(spec,changed,pose,current)
        pad_errors=[]
        for support in base['supports']:
            point=[robot.evaluate(v,changed) for v in support['contact']]
            actual=by_name['MB01_'+support['id']+'_Pad']['world_center_of_mass_mm']
            expected=[point[0],point[1],point[2]+3-pose['support_extension_mm']+pose['chassis_lift_mm']]
            pad_errors.append(math.dist(actual,expected))
        parameter_checks.append({'parameter':parameter,'value_mm':changed[parameter],
            'max_probe_error_mm':probe_error(doc,spec,arm,changed,pose),'max_pad_anchor_error_mm':max(pad_errors),'contact_geometry':contact,
            'geometry':current})
        setattr(doc.ModelParameters,parameter,p[parameter]); doc.recompute()
    set_state(doc,model.state(spec,arm,p,'working'),'working')
    return {'passed':all(b['valid'] and b['solid_count']==1 for b in geometry)
            and all(s['max_probe_error_mm']<1e-6 and not s['overlaps'] and s['contact_geometry']['passed'] for s in checked)
            and all(s['max_probe_error_mm']<1e-6 and s['max_pad_anchor_error_mm']<1e-6 and s['contact_geometry']['passed'] for s in parameter_checks),
            'geometry':geometry,'samples':checked,'envelopes':envelopes,'native_parameter_changes':parameter_checks,
            'continuous_collision_checked':False,'physical_stability_tested':False,'freecad_version':App.Version()}


def main(output,report_path,overrides_path=None):
    spec=model.load(); arm=robot.load(model.ROOT/spec['arm_source'])
    overrides=json.loads(Path(overrides_path).read_text()) if overrides_path else {}
    p=model.parameters(spec,overrides); doc=build(spec,arm,p,output)
    report=validate(doc,spec,arm,p)
    report['state_geometry']={}
    for name in ['working','manual_reposition','parked_aside']:
        set_state(doc,model.state(spec,arm,p,name),name)
        target=Path(output) if name=='working' else Path(output).with_name(Path(output).stem+'_'+name+'.FCStd')
        if target!=Path(output) and target.exists(): raise FileExistsError(target)
        doc.saveAs(str(target))
        report['state_geometry'][name]=measurements(doc)
        if name=='working': report['working_geometry']=measurements(doc)
    App.closeDocument(doc.Name)
    reopened=App.openDocument(str(output)); report['reopened_body_count']=len(motion.features(reopened))
    report['reopened']=report['reopened_body_count']==len(report['geometry'])
    report['passed']=report['passed'] and report['reopened']
    App.closeDocument(reopened.Name)
    Path(report_path).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'bodies':len(report['geometry']),'samples':len(report['samples']),
        'overlapping_samples':sum(bool(s['overlaps']) for s in report['samples'])}),flush=True)


if __name__=='__main__':
    import build_mobile_base_freecad
    build_mobile_base_freecad.main(*sys.argv[1:])
