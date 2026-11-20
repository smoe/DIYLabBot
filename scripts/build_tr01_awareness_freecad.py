"""Independent native FreeCAD build of the referenced empty TR01 camera kit."""
import json
import math
import sys
from pathlib import Path
import FreeCAD as App
import Part
import tr01_camera_model as model
from build_tube_carrier_freecad import measurements, objects


def build(output, report):
    spec=model.load();source=model.expanded(spec);doc=App.newDocument('TR01_AwarenessKit')
    group=doc.addObject('App::Part','Car'); latest={};meta={b['id']:b for b in source['bodies']}
    controller=doc.addObject('App::FeaturePython','Controller')
    controller.addProperty('App::PropertyString','SourceSHA256','Source');controller.SourceSHA256=model.digest(model.SOURCE)
    for o in source['operations']:
        s=o['shape'];kind=s['kind'];obj=doc.addObject({'box':'Part::Box','cylinder':'Part::Cylinder','cone':'Part::Cone'}[kind],o['id']+'_Primitive');group.addObject(obj)
        if kind=='box':obj.Length,obj.Width,obj.Height=s['size']
        elif kind=='cylinder':obj.Radius,obj.Height=s['radius'],s['height']
        else:obj.Radius1,obj.Radius2,obj.Height=s['radius'],s['top_radius'],s['height']
        if kind!='box':obj.Placement.Rotation=App.Rotation(App.Vector(0,0,1),App.Vector(*s['axis']))
        obj.Placement.Base=App.Vector(*s['origin'])
        if o['action']!='create':
            result=doc.addObject('Part::Cut' if o['action']=='cut' else 'Part::Fuse',o['id']+'_Result');group.addObject(result);result.Base=latest[o['body']];result.Tool=obj;result.Refine=True;obj=result
        latest[o['body']]=obj
    for name,obj in latest.items():
        obj.Label=name
        for key,value in [('SourceBody',name),('RigidLink','Car'),('ModelRole',meta[name]['role'])]:
            obj.addProperty('App::PropertyString',key,'Source');setattr(obj,key,value)
        appearance=meta[name]['appearance'];color=appearance['color']
        if isinstance(color,str):color=[int(color[i:i+2],16)for i in (1,3,5)]
        if hasattr(obj,'ViewObject') and obj.ViewObject:
            obj.ViewObject.ShapeColor=tuple(v/255 for v in color);obj.ViewObject.Transparency=round(100*(1-appearance['opacity']))
    frame=source['camera_frame'];optical=doc.addObject('App::Part','TR01_Awareness_Optical');optical.Placement.Base=App.Vector(*frame['origin_mm'])
    # Optical +Z forward (+X vehicle), +X right (-Y vehicle), +Y down.
    optical.Placement.Rotation=App.Rotation(App.Vector(0,-1,0),App.Vector(0,0,-1),App.Vector(1,0,0),'ZXY')
    doc.recompute();geometry=measurements(doc);c=spec['camera']['id'];physical=[o for o in objects(doc) if o.SourceBody.startswith(c) and o.ModelRole!='viewing_cone'];base=[o for o in objects(doc) if not o.SourceBody.startswith(c)]
    clearance=[]
    for kit in physical:
        for body in base:
            common=kit.Shape.common(body.Shape).Volume
            clearance.append({'kit_body':kit.SourceBody,'base_body':body.SourceBody,'intersection_mm3':common,'distance_mm':kit.Shape.distToShape(body.Shape)[0],'passed':common<1e-7})
    lens=latest[c+'_Lens'];tip=lens.Shape.CenterOfMass+App.Vector(spec['camera']['lens']['length_mm'] if isinstance(spec['camera']['lens']['length_mm'],(int,float)) else source['parameters']['camera_lens_length'],0,0)/2
    frame_error=math.dist(list(tip),frame['origin_mm']);axes={'x':[0,-1,0],'y':[0,0,-1],'z':[1,0,0]};axis_error=max((optical.Placement.Rotation.multVec(App.Vector(*unit))-App.Vector(*axes[name])).Length for name,unit in [('x',[1,0,0]),('y',[0,1,0]),('z',[0,0,1])])
    passed=all(x['valid'] and x['solid_count']==1 for x in geometry) and all(x['passed'] for x in clearance) and frame_error<1e-7 and axis_error<1e-7
    if Path(output).exists():raise FileExistsError(output)
    doc.saveAs(str(output));App.closeDocument(doc.Name);doc=App.openDocument(str(output));reopened=measurements(doc);passed &= len(reopened)==len(geometry) and all(x['valid'] for x in reopened);App.closeDocument(doc.Name)
    result={'passed':passed,'geometry':geometry,'kit_clearance_checks':clearance,'camera_frame':frame,'frame_geometry_error_mm':frame_error,'frame_axis_error':axis_error,'reopened':True,'freecad_version':App.Version(),'scope':'Exact BRep intersection and minimum distance of kit against all retained base bodies; mounting contact allowed, no positive overlap. Optical frame checked against lens end and native axes. Static geometry only.'}
    Path(report).write_text(json.dumps(result,indent=2)+'\n')
    if not passed:raise AssertionError('Camera-kit geometry check failed; see '+str(report))
    print(json.dumps({'passed':passed,'bodies':len(geometry),'frame_error_mm':frame_error}),flush=True)


if __name__=='__main__':build(*sys.argv[1:])
