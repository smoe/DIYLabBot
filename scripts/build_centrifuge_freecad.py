"""Native CF01 FreeCAD adapter and sampled geometry checks; no imported CAD source."""
import json
import math
import sys
from pathlib import Path
import FreeCAD as App
import Part
import centrifuge_model as model

sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion
from persist_station_view import persist


def build(spec,p,path):
    if Path(path).exists(): raise FileExistsError(path)
    source=model.expanded(spec,p); doc=App.newDocument(spec['id'])
    control=doc.addObject('App::FeaturePython','Controller')
    for key,value in [('SourceFile',str(model.SOURCE.relative_to(model.ROOT))),('SpecSHA256',model.digest(model.SOURCE)),('Status',spec['status'])]:
        control.addProperty('App::PropertyString',key,'Source'); setattr(control,key,value)
    groups={}; values=model.pose(spec,p)
    for c in source['components']:
        j=next((j for j in source['joints'] if j['child']==c['id']),None)
        if j:
            control.addProperty('App::PropertyAngle' if j['unit']=='deg' else 'App::PropertyDistance',j['id'],'Motion coordinates in mm or deg')
            setattr(control,j['id'],values[j['id']])
            anchor=doc.addObject('App::Part',c['id']+'_Anchor'); groups[j['parent']].addObject(anchor)
            frame=motion.frame_placement({'origin':j['origin'],'x':j['reference_x'],'z':j['axis']}); anchor.Placement=frame
            move=doc.addObject('App::Part',c['id']+'_Motion'); anchor.addObject(move)
            field='Placement.Rotation.Angle' if j['type']=='revolute' else 'Placement.Base.z'
            unit=j['unit']; move.setExpression(field,f"max({j['limits'][0]} {unit}; min({j['limits'][1]} {unit}; Controller.{j['id']}))")
            group=doc.addObject('App::Part',c['id']); move.addObject(group); group.Placement=frame.inverse()
        else: group=doc.addObject('App::Part',c['id'])
        groups[c['id']]=group
    latest={}; metadata={b['id']:b for b in source['bodies']}
    for op in source['operations']:
        s=op['shape']; group=groups[metadata[op['body']]['component']]; name=op['id']; kind=s['kind']
        if kind=='round_cable':
            o,u,v=App.Vector(*s['plane_origin']),App.Vector(*s['u_axis']),App.Vector(*s['v_axis'])
            def point(p): return o+u*p[0]+v*p[1]
            edges=[]
            for curve in s['curves']:
                a,b=point(curve['start']),point(curve['end'])
                edges.append(Part.makeLine(a,b) if curve['kind']=='line' else Part.Arc(a,point(curve['through']),b).toShape())
            spine=doc.addObject('Part::Feature',name+'_Path'); group.addObject(spine); spine.Shape=Part.Wire(edges)
            section=doc.addObject('Part::Feature',name+'_Section'); group.addObject(section)
            section.Shape=Part.Wire([Part.makeCircle(s['radius'],App.Vector(*s['origin']),App.Vector(*s['start_tangent']))])
            obj=doc.addObject('Part::Sweep',name+'_Sweep'); group.addObject(obj)
            obj.Sections=[section]; obj.Spine=(spine,['Edge'+str(i+1) for i in range(len(edges))]); obj.Solid=True; obj.Frenet=True
        elif kind=='profile':
            u,v=App.Vector(*s['u_axis']),App.Vector(*s['v_axis']); faces=[]
            for loop in s['loops']:
                pts=[u*x+v*y for x,y in loop]; faces.append(Part.Face(Part.makePolygon(pts+[pts[0]])))
            face=faces[0]
            for hole in faces[1:]: face=face.cut(hole)
            profile=doc.addObject('Part::Feature',name+'_Profile'); group.addObject(profile); profile.Shape=face
            profile.Placement.Base=App.Vector(*s['origin'])
            obj=doc.addObject('Part::Extrusion',name+'_Extrusion'); group.addObject(obj); obj.Base=profile
            obj.Dir=u.cross(v)*s['depth']; obj.Solid=True
        else:
            obj=doc.addObject({'box':'Part::Box','cylinder':'Part::Cylinder','cone':'Part::Cone'}[kind],name+'_Primitive'); group.addObject(obj)
            if kind=='box': props=list(zip(['Length','Width','Height'],s['size']))
            elif kind=='cone': props=[('Radius1',s['radius']),('Radius2',s['top_radius']),('Height',s['height'])]
            else: props=[('Radius',s['radius']),('Height',s['height'])]
            for key,value in props: setattr(obj,key,value)
            if 'axis' in s: obj.Placement.Rotation=App.Rotation(App.Vector(0,0,1),App.Vector(*s['axis']))
            obj.Placement.Base=App.Vector(*s['origin'])
        if op['action']!='create':
            boolean=doc.addObject('Part::Cut' if op['action']=='cut' else 'Part::Fuse',name+'_Result'); group.addObject(boolean)
            boolean.Base=latest[op['body']]; boolean.Tool=obj; boolean.Refine=True; obj=boolean
        latest[op['body']]=obj
    for name,obj in latest.items():
        obj.Label=name
        for key,value in [('SourceBody',name),('RigidLink',metadata[name]['component']),('ModelRole',metadata[name]['role'])]:
            obj.addProperty('App::PropertyString',key,'Source'); setattr(obj,key,value)
        if metadata[name]['material_family']=='steel':
            obj.addProperty('App::PropertyString','MaterialFamily','Source'); obj.MaterialFamily='steel'
            obj.addProperty('App::PropertyString','SteelGrade','Source'); obj.SteelGrade='unselected'
            obj.addProperty('App::PropertyFloat','DensityAssumptionKgM3','Source'); obj.DensityAssumptionKgM3=spec['structure']['density_assumption_kg_m3']
    doc.recompute(); doc.saveAs(str(path)); return doc,source


def objects(doc): return [o for o in doc.Objects if 'SourceBody' in o.PropertiesList]


def measurements(doc):
    result=[]
    for obj in objects(doc):
        shape=motion.world_shape(obj); bb=shape.optimalBoundingBox(False,False); volume=shape.Volume
        if volume<=0: raise ValueError('Empty body: '+obj.SourceBody)
        com=[sum(s.CenterOfMass[i]*s.Volume for s in shape.Solids)/volume for i in range(3)]
        result.append({'body':obj.SourceBody,'component':obj.RigidLink,'valid':shape.isValid(),'solid_count':len(shape.Solids),
                       'volume_mm3':volume,'world_center_of_mass_mm':com,'bbox':{'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]}})
    return result


def set_pose(doc,source,values):
    model.validate_pose(source,values)
    for name,value in values.items(): setattr(doc.Controller,name,value)
    doc.recompute()


def interference(doc,rigid_cache=None):
    if rigid_cache is None: rigid_cache={}
    shapes=[(o,motion.world_shape(o)) for o in objects(doc)]; cross=[]; internal=[]
    for i,(a,aa) in enumerate(shapes):
        for b,bb in shapes[i+1:]:
            if not aa.BoundBox.intersect(bb.BoundBox): continue
            key=(a.SourceBody,b.SourceBody)
            if a.RigidLink==b.RigidLink and key in rigid_cache: volume=rigid_cache[key]
            else:
                volume=aa.common(bb).Volume
                if a.RigidLink==b.RigidLink: rigid_cache[key]=volume
            if volume>1e-4:
                (internal if a.RigidLink==b.RigidLink else cross).append({'a':a.SourceBody,'b':b.SourceBody,'volume_mm3':volume})
    return {'between_components':cross,'within_rigid_components':internal,'passed':not cross}


def service_checks(geometry,spec,p):
    bodies={b['body']:b for b in geometry}; r=p['chamber_inner_radius']+p['chamber_wall']; cable=model.power_cord(spec,p)
    expected={'ContainmentEnvelope':math.pi*(r*r-p['chamber_inner_radius']**2)*(p['chamber_top']-p['chamber_floor_z']-p['chamber_floor']),
              'ChamberFloor':math.pi*(r*r-10**2)*p['chamber_floor'],'CommandLid':math.pi*(r+4)**2*p['lid_thickness'],
              'PowerCord':math.pi*p['power_cable_radius']**2*cable['centerline_length_mm'],
              'MotorStator':math.pi*(p['motor_outer_radius']**2-24**2)*74,
              'ParkingBrakeDisc':math.pi*(p['brake_disc_radius']**2-8**2)*p['brake_disc_thickness']}
    checks=[{'body':name,'expected_volume_mm3':volume,'relative_error':abs(bodies[name]['volume_mm3']-volume)/volume,
             'passed':abs(bodies[name]['volume_mm3']-volume)/volume<1e-5} for name,volume in expected.items()]
    gap=bodies['RotationSensor']['bbox']['min'][0]-bodies['EncoderTargetRing']['bbox']['max'][0]
    checks.append({'id':'CF01.ENCODER.gap','gap_mm':gap,'expected_gap_mm':p['encoder_gap'],'passed':abs(gap-p['encoder_gap'])<1e-7})
    return checks


def step_measurements(doc,path):
    remaining=list(Part.read(str(path)).Solids); result=[]
    if len(remaining)!=len(objects(doc)): raise AssertionError('STEP body count differs')
    for obj in objects(doc):
        shape=motion.world_shape(obj)
        center=sum((s.CenterOfMass*s.Volume for s in shape.Solids),App.Vector())/shape.Volume
        index=min(range(len(remaining)),key=lambda i:(remaining[i].CenterOfMass-center).Length+abs(remaining[i].Volume-shape.Volume)/shape.Volume)
        solid=remaining.pop(index); bb=solid.optimalBoundingBox(False,False)
        result.append({'body':obj.SourceBody,'valid':solid.isValid(),'closed':solid.isClosed(),'volume_mm3':solid.Volume,
                       'center_of_mass':list(solid.CenterOfMass),'bbox':{'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]}})
    return result


def main(output,report,overrides='{}',step_path=None):
    spec=model.load(); p=model.parameters(spec,json.loads(overrides)); doc,source=build(spec,p,output)
    baseline=measurements(doc); step_geometry=step_measurements(doc,step_path) if step_path else []; samples=[]; rigid_cache={}
    services=service_checks(baseline,spec,p)
    for sample in model.samples(spec,p):
        set_pose(doc,source,sample['values']); error=0
        for c in source['components']:
            actual=motion.global_placement(doc.getObject(c['id']))
            for point in [[0,0,0],[17,0,0],[0,23,0],[0,0,31]]:
                error=max(error,math.dist(list(actual.multVec(App.Vector(*point))),model.transform(source,c['id'],point,sample['values'])))
        collisions=interference(doc,rigid_cache)
        samples.append({**sample,**collisions,'frame_error_mm':error,'passed':error<1e-7 and collisions['passed']})
    set_pose(doc,source,model.pose(spec,p)); doc.save(); App.closeDocument(doc.Name)
    reopened=App.openDocument(str(output)); reopened.recompute(); again=measurements(reopened); App.closeDocument(reopened.Name)
    presentation=persist(output,source,baseline)
    result={'source_sha256':model.digest(model.SOURCE),'geometry':baseline,'solidcraft_step_geometry':step_geometry,'motion_samples':samples,'presentation':presentation,'service_geometry_checks':services,
            'passed':all(b['valid'] and b['solid_count']==1 for b in baseline+again) and all(s['passed'] for s in samples+services),
            'backend':'Native Part primitives, booleans and polygon extrusions; expression-driven placements; geometry changes require source regeneration',
            'freecad_version':App.Version(),'reopened_bodies':len(again)}
    model.write(report,result)
    print(json.dumps({'passed':result['passed'],'bodies':len(baseline),'samples':len(samples),'failed_pose_count':sum(not s['passed'] for s in samples),
        'first_failures':[{'id':s['id'],'between_components':s['between_components'],'frame_error_mm':s['frame_error_mm']} for s in samples if not s['passed']][:4]}),flush=True)
    if not result['passed']: raise AssertionError('CF01 geometry/frame checks failed: '+str(report))


if __name__=='__main__':
    import build_centrifuge_freecad as backend
    backend.main(*sys.argv[1:])
