"""Native FreeCAD station adapter and independent geometry/placement checks."""
from pathlib import Path
import json
import math
import sys
import FreeCAD as App
import Part
import station_model as model
from build_neutral_freecad import native_expression

sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion


def origin(obj,values):
    for axis,value in zip('xyz',values): obj.setExpression('Placement.Base.'+axis,native_expression(value))


def build(spec,p,path):
    if Path(path).exists(): raise FileExistsError(path)
    doc=App.newDocument(spec['id'])
    params=doc.addObject('App::FeaturePython','ModelParameters')
    for name,definition in spec['parameters'].items():
        params.addProperty('App::PropertyLength',name,'Shared source', 'Geometry exploration range: %s to %s mm'%tuple(definition['range']))
        setattr(params,name,p[name])
    # Independent parameters use the selected case values; derived values remain linked.
    import ast
    for name,definition in spec['parameters'].items():
        if any(isinstance(n,ast.Name) for n in ast.walk(ast.parse(str(definition['expression']),mode='eval'))): params.setExpression(name,native_expression(definition['expression']))
    controller=doc.addObject('App::FeaturePython','Controller')
    controller.addProperty('App::PropertyString','SpecSHA256','Source'); controller.SpecSHA256=model.digest(model.SOURCE)
    controller.setEditorMode('SpecSHA256',1)
    for j in spec['joints']:
        for suffix,value in [('',spec['poses_deg']['pipetting'][j['id']]),('Min',j['limits_deg'][0]),('Max',j['limits_deg'][1])]:
            name=j['id']+suffix
            controller.addProperty('App::PropertyAngle',name,'Joint angles in degrees' if not suffix else 'Concept limits')
            setattr(controller,name,value)
            if suffix: controller.setEditorMode(name,1)
    groups={}
    for component in spec['components']:
        name=component['id']
        joint=next((j for j in spec['joints'] if j['child']==name),None)
        if joint:
            anchor=doc.addObject('App::Part',name+'_Anchor')
            groups[joint['parent']].addObject(anchor)
            frame=motion.frame_placement({'origin':[model.evaluate(x,p) for x in joint['origin']],'x':joint['reference_x'],'z':joint['axis']})
            anchor.Placement=frame; origin(anchor,joint['origin'])
            turn=doc.addObject('App::Part',name+'_Motion'); anchor.addObject(turn)
            turn.setExpression('Placement.Rotation.Angle','max(%s deg; min(%s deg; Controller.%s))'%(*joint['limits_deg'],name))
            group=doc.addObject('App::Part',name); turn.addObject(group); group.Placement=frame.inverse()
            inverse=frame.Rotation.inverted().toMatrix()
            coords=[]
            for row in range(3):
                terms=['(%s) * (%s)'%(-getattr(inverse,'A%d%d'%(row+1,col+1)),joint['origin'][col]) for col in range(3) if abs(getattr(inverse,'A%d%d'%(row+1,col+1)))>1e-12]
                coords.append(' + '.join(terms) or 0)
            origin(group,coords)
        else: group=doc.addObject('App::Part',name)
        groups[name]=group

    def primitive(name,shape,group):
        if shape['type']=='polygon_prism':
            u,v=App.Vector(*shape['u_axis']),App.Vector(*shape['v_axis'])
            faces=[]
            for loop in shape['loops']:
                points=[u*x+v*y for x,y in loop]
                faces.append(Part.Face(Part.makePolygon(points+[points[0]])))
            face=faces[0]
            for hole in faces[1:]: face=face.cut(hole)
            profile=doc.addObject('Part::Feature',name+'_Profile'); group.addObject(profile)
            profile.Shape=face; origin(profile,shape['origin'])
            obj=doc.addObject('Part::Extrusion',name); group.addObject(obj)
            obj.Base=profile; obj.Dir=u.cross(v)*model.evaluate(shape['depth'],p); obj.Solid=True
            return obj
        obj=doc.addObject('Part::Box' if shape['type']=='box' else 'Part::Cylinder',name)
        group.addObject(obj)
        if shape['type']=='box':
            for name,value in zip(['Length','Width','Height'],shape['size']): obj.setExpression(name,native_expression(value))
        else:
            obj.setExpression('Radius',native_expression(shape['radius'])); obj.setExpression('Height',native_expression(shape['height']))
            obj.Placement=App.Placement(App.Vector(),App.Rotation(App.Vector(0,0,1),App.Vector(*shape['axis'])))
        origin(obj,shape['origin'])
        return obj

    for body in spec['bodies']:
        group=groups[body['component']]
        obj=primitive(body['id']+'_Primitive',body['geometry'],group)
        for cut in (c for c in spec['cuts'] if c['target']==body['id']):
            tool=primitive(cut['id']+'_Tool',cut['geometry'],group)
            result=doc.addObject('Part::Cut',cut['id']); group.addObject(result)
            result.Base=obj; result.Tool=tool; result.Refine=True; obj=result
        obj.Label=body['id']
        for name,value in [('SourceBody',body['id']),('RigidLink',body['component']),('ModelRole',body['role'])]:
            obj.addProperty('App::PropertyString',name,'Shared source'); setattr(obj,name,value); obj.setEditorMode(name,1)
    doc.recompute(); doc.saveAs(str(path))
    return doc


def bodies(doc): return [o for o in doc.Objects if 'SourceBody' in o.PropertiesList]


def center(shape):
    if shape.Volume<=0: raise ValueError('Expected positive solid volume')
    result=App.Vector()
    for solid in shape.Solids: result=result.add(solid.CenterOfMass.multiply(solid.Volume/shape.Volume))
    return result


def set_pose(doc,spec,pose):
    model.validate_pose(spec,pose)
    for name,value in pose.items(): setattr(doc.Controller,name,value)
    doc.recompute()


def measurements(doc):
    result=[]
    for obj in bodies(doc):
        shape=motion.world_shape(obj); com=center(shape); bb=shape.BoundBox
        result.append({'body':obj.SourceBody,'component':obj.RigidLink,'valid':shape.isValid(),'solid_count':len(shape.Solids),'volume_mm3':shape.Volume,'world_center_of_mass_mm':list(com),'bbox':{'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]}})
    return result


def compare_step(doc,path):
    step=Part.read(str(path))
    unmatched=list(step.Solids); results=[]
    if len(unmatched)!=len(bodies(doc)): raise AssertionError('STEP solid count mismatch')
    for obj in bodies(doc):
        actual=motion.world_shape(obj)
        nearest=min(range(len(unmatched)),key=lambda i:(unmatched[i].CenterOfMass-center(actual)).Length+abs(unmatched[i].Volume-actual.Volume)/max(1,actual.Volume))
        reference=unmatched.pop(nearest)
        xor=actual.cut(reference).Volume+reference.cut(actual).Volume
        results.append({'body':obj.SourceBody,'xor_mm3':xor,'passed':xor<=1e-3})
    return results


def validate(doc,spec,p,step_path):
    expected={b['body']:b for b in model.references(spec,p)}
    geometry=[]
    for b in measurements(doc):
        ref=expected[b['body']]
        expected_com=model.transform(spec,b['component'],ref['center_of_mass_mm'],p,spec['poses_deg']['pipetting'])
        error=math.dist(b['world_center_of_mass_mm'],expected_com)
        volume_error=abs(b['volume_mm3']-ref['volume_mm3'])
        geometry.append({**b,'analytic_com_error_mm':error,'analytic_volume_error_mm3':volume_error,'passed':b['valid'] and b['solid_count']==1 and error<1e-7 and volume_error<1e-5})
    poses=[]
    for sample in model.pose_samples(spec):
        set_pose(doc,spec,sample['angles_deg']); max_error=0
        for c in spec['components']:
            actual=motion.global_placement(doc.getObject(c['id']))
            for point in [[0,0,0],[17,0,0],[0,23,0],[0,0,31]]:
                max_error=max(max_error,math.dist(list(actual.multVec(App.Vector(*point))),model.transform(spec,c['id'],point,p,sample['angles_deg'])))
        poses.append({**sample,'max_probe_error_mm':max_error,'passed':max_error<1e-7})
    set_pose(doc,spec,spec['poses_deg']['pipetting'])
    exact=compare_step(doc,step_path)
    return {'geometry':geometry,'poses':poses,'solidcraft_step_xor':exact,'passed':all(x['passed'] for x in geometry+poses+exact)}


def main(output,case_file,report_file,step_path):
    spec=model.load(); case=json.loads(Path(case_file).read_text(encoding='utf-8')); p=model.parameters(spec,case['overrides'])
    doc=build(spec,p,output)
    result=validate(doc,spec,p,step_path)
    # Exercise native expressions without rebuilding the native feature tree.
    if not case['overrides']:
        doc.ModelParameters.tube_mouth_z=110; doc.recompute()
        raised_p=model.parameters(spec,{'tube_mouth_z':110})
        raised_refs={b['body']:b for b in model.references(spec,raised_p)}
        errors=[]
        for b in measurements(doc):
            ref=raised_refs[b['body']]
            errors.append(math.dist(b['world_center_of_mass_mm'],model.transform(spec,b['component'],ref['center_of_mass_mm'],raised_p,spec['poses_deg']['pipetting'])))
        result['native_parameter_edit']={'tube_mouth_z_mm':110,'pivot_z_mm':doc.ModelParameters.pivot_z.Value,'max_body_com_error_mm':max(errors),'passed':max(errors)<1e-7 and abs(doc.ModelParameters.pivot_z.Value-111)<1e-9}
        result['passed'] &= result['native_parameter_edit']['passed']
        doc.ModelParameters.tube_mouth_z=100; doc.recompute()
    doc.save(); App.closeDocument(doc.Name)
    reopened=App.openDocument(str(output)); reopened.recompute()
    result['reopened']={'body_count':len(bodies(reopened)),'all_valid':all(o.Shape.isValid() for o in bodies(reopened))}
    result['passed'] &= result['reopened']['body_count']==len(spec['bodies']) and result['reopened']['all_valid']
    result['freecad_version']=App.Version(); result['backend']='Native Part boxes, cylinders, cuts, polygon extrusions and expression-driven App::Part placements; no STEP import as model source'
    result['spec_sha256']=model.digest(model.SOURCE)
    Path(report_file).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    App.closeDocument(reopened.Name)
    if not result['passed']: raise AssertionError('FreeCAD or cross-kernel checks failed: '+str(report_file))
    print('FreeCAD native geometry, pose and STEP XOR checks passed',flush=True)


if __name__=='__main__':
    import build_tube_station_freecad as backend
    backend.main(*sys.argv[1:])
