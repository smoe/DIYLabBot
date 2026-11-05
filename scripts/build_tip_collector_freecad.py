"""Native FreeCAD T01 builder: expressions, sketches, extrusions and cuts."""
from pathlib import Path
import ast
import json
import math
import sys
import FreeCAD as App
import Part
import Sketcher
import tip_collector_model as model
from build_neutral_freecad import native_expression


def origin(obj,values):
    for axis,value in zip('xyz',values): obj.setExpression('Placement.Base.'+axis,native_expression(value))


def face_from_curves(curves):
    pending=[]
    for c in curves:
        if c['kind']=='line': edge=Part.makeLine(App.Vector(*c['start'],0),App.Vector(*c['end'],0))
        else:
            curve=Part.BezierCurve()
            curve.setPoles([App.Vector(*c[k],0) for k in ['start','control','end']])
            edge=curve.toShape()
        pending.append((c['start'],c['end'],edge))
    wires=[]
    while pending:
        a,b,e=pending.pop(0); start=a; last=b; edges=[e]
        while math.dist(last,start)>1e-8:
            found=next((i for i,(a,b,e) in enumerate(pending) if min(math.dist(last,a),math.dist(last,b))<1e-8),None)
            if found is None: raise ValueError('Unclosed portable profile')
            a,b,e=pending.pop(found)
            if math.dist(last,a)<1e-8: last=b
            else: e.reverse(); last=a
            edges.append(e)
        wires.append(Part.Wire(edges))
    return Part.makeFace(wires,'Part::FaceMakerBullseye')


def build(spec,p,path):
    if Path(path).exists(): raise FileExistsError(path)
    source=model.expanded(spec,p); doc=App.newDocument(spec['id'])
    params=doc.addObject('App::FeaturePython','ModelParameters')
    for name,d in spec['parameters'].items():
        # PropertyLength clamps negative values. Signed positions such as the
        # front edge and left lane require PropertyDistance (also a mm quantity).
        params.addProperty('App::PropertyDistance',name,'Shared dimensions (mm)')
        setattr(params,name,p[name])
    for name,d in spec['parameters'].items():
        if any(isinstance(n,ast.Name) for n in ast.walk(ast.parse(str(d['expression']),mode='eval'))):
            params.setExpression(name,native_expression(d['expression']))
    # Outline/text changes are made in the common source and rebuilt in both CADs.
    params.setEditorMode('umr_height',1)
    controller=doc.addObject('App::FeaturePython','Controller')
    for key,value in [('SpecSHA256',model.digest(model.SOURCE)),('MarkingSHA256',model.digest(model.ROOT/spec['marking_asset'])),
                      ('SourceFile','model/tip-collector-t01.shared.json'),('Status',spec['status'])]:
        controller.addProperty('App::PropertyString',key,'Shared source'); setattr(controller,key,value); controller.setEditorMode(key,1)
    groups={c['id']:doc.addObject('App::Part',c['id']) for c in source['components']}
    latest={}; meta={b['id']:b for b in source['bodies']}

    def box(name,size,center,group):
        obj=doc.addObject('Part::Box',name); group.addObject(obj)
        for prop,value in zip(['Length','Width','Height'],size): obj.setExpression(prop,native_expression(value))
        origin(obj,[f'({c})-({s})/2' for c,s in zip(center,size)])
        return obj

    def cylinder(name,diameter,height,base,group):
        obj=doc.addObject('Part::Cylinder',name); group.addObject(obj)
        obj.setExpression('Radius',native_expression(f'({diameter})/2'))
        obj.setExpression('Height',native_expression(height)); origin(obj,base)
        return obj

    def extrusion(name,profile,depth,group):
        obj=doc.addObject('Part::Extrusion',name); group.addObject(obj)
        obj.Base=profile; obj.Dir=App.Vector(0,0,model.evaluate(depth,p)); obj.Solid=True
        obj.setExpression('Dir.z',native_expression(depth))
        return obj

    def groove(name,lane,group):
        w='groove_'+lane; x='lane_'+lane+'_x'
        sketch=doc.addObject('Sketcher::SketchObject',name+'_TaperSketch'); group.addObject(sketch)
        origin(sketch,[x,0,'fork_z-1'])
        points=[['-mouth_width/2','fork_front_y-1'],['mouth_width/2','fork_front_y-1'],
                ['mouth_width/2','fork_front_y'],[w+'/2','taper_end_y'],['-'+w+'/2','taper_end_y'],
                ['-mouth_width/2','fork_front_y']]
        geoms=[]; constraints=[]; expressions=[]
        for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
            geoms.append(Part.LineSegment(App.Vector(*(model.evaluate(v,p) for v in a),0),App.Vector(*(model.evaluate(v,p) for v in b),0)))
            for endpoint,point in [(1,a),(2,b)]:
                for axis,value in [('X',point[0]),('Y',point[1])]:
                    constraints.append(Sketcher.Constraint('Distance'+axis,i,endpoint,model.evaluate(value,p)))
                    expressions.append(native_expression(value))
        sketch.addGeometry(geoms,False); ids=sketch.addConstraint(constraints)
        for index,expression in zip(ids,expressions): sketch.setExpression('Constraints[%s]'%index,expression)
        taper=extrusion(name+'_Taper',sketch,'fork_t+2',group)
        rect=box(name+'_Straight',[w,'slot_end_y-taper_end_y','fork_t+2'],
                 [x,'(slot_end_y+taper_end_y)/2','fork_z+fork_t/2'],group)
        cap=cylinder(name+'_End',w,'fork_t+2',[x,'slot_end_y','fork_z-1'],group)
        joined=doc.addObject('Part::MultiFuse',name+'_Tool'); group.addObject(joined)
        joined.Shapes=[taper,rect,cap]; joined.Refine=True
        return joined

    for op in source['operations']:
        s=op['shape']; name=op['id']
        group=groups[meta[op['body'] if op['action']=='create' else op['targets'][0]]['component']]
        if s['kind']=='box': obj=box(name+'_Primitive',s['size'],s['center'],group)
        elif s['kind']=='cylinder': obj=cylinder(name+'_Tool',s['diameter'],s['height'],s['base'],group)
        elif s['kind']=='stripper_groove': obj=groove(name,s['lane'],group)
        else:
            profile=doc.addObject('Part::Feature',name+'_Profile'); group.addObject(profile)
            profile.Shape=face_from_curves(s['curves'])
            u,v=App.Vector(*s['u_axis']),App.Vector(*s['v_axis'])
            rot=App.Rotation(u,v,u.cross(v),'ZXY'); profile.Placement=App.Placement(App.Vector(),rot)
            origin(profile,s['origin'])
            obj=doc.addObject('Part::Extrusion',name+'_Extrusion'); group.addObject(obj)
            obj.Base=profile; obj.Dir=u.cross(v)*model.evaluate(s['depth'],p); obj.Solid=True
            for axis,component in zip('xyz',u.cross(v)):
                obj.setExpression('Dir.'+axis,native_expression(f'{component}*({s["depth"]})'))
        if op['action']=='create': latest[op['body']]=obj
        else:
            for i,target in enumerate(op['targets']):
                cut=doc.addObject('Part::Cut',name+'_Cut'+str(i)); groups[meta[target]['component']].addObject(cut)
                cut.Base=latest[target]; cut.Tool=obj; cut.Refine=True; latest[target]=cut
        doc.recompute()
    for name,obj in latest.items():
        obj.Label=name
        for key,value in [('SourceBody',name),('RigidLink',meta[name]['component']),('ModelRole',meta[name]['role'])]:
            obj.addProperty('App::PropertyString',key,'Shared source'); setattr(obj,key,value); obj.setEditorMode(key,1)
    doc.recompute(); doc.saveAs(str(path))
    return doc


def measurements(doc):
    result=[]
    for obj in doc.Objects:
        if 'SourceBody' not in obj.PropertiesList: continue
        shape=obj.Shape; bb=shape.BoundBox
        com=center(shape)
        result.append({'body':obj.SourceBody,'valid':shape.isValid(),'solid_count':len(shape.Solids),
            'volume_mm3':shape.Volume,'world_center_of_mass_mm':list(com),
            'bbox':{'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]}})
    return result


def center(shape):
    if shape.Volume<=0: raise ValueError('Expected a positive solid volume')
    com=App.Vector()
    for solid in shape.Solids: com=com.add(solid.CenterOfMass.multiply(solid.Volume/shape.Volume))
    return com


def analytic_check(doc,spec,p):
    refs={r['body']:r for r in model.references(spec,p)}; checks=[]
    for b in measurements(doc):
        expected=refs[b['body']]; v=abs(b['volume_mm3']-expected['volume_mm3']); com=math.dist(b['world_center_of_mass_mm'],expected['center_of_mass_mm'])
        bbox=max(abs(a-c) for key in ['min','max'] for a,c in zip(b['bbox'][key],expected['bbox'][key]))
        checks.append({**b,'analytic_volume_error_mm3':v,'analytic_com_error_mm':com,'bbox_error_mm':bbox,
            'passed':b['valid'] and b['solid_count']==1 and v<1e-5 and com<1e-7 and bbox<1e-7})
    return checks


def step_check(doc,path):
    unmatched=list(Part.read(str(path)).Solids); checks=[]
    bodies=[o for o in doc.Objects if 'SourceBody' in o.PropertiesList]
    if len(unmatched)!=len(bodies): raise AssertionError('STEP body count')
    for obj in bodies:
        shape=obj.Shape
        i=min(range(len(unmatched)),key=lambda i:(unmatched[i].CenterOfMass-center(shape)).Length)
        other=unmatched.pop(i); xor=shape.cut(other).Volume+other.cut(shape).Volume
        checks.append({'body':obj.SourceBody,'xor_mm3':xor,'passed':xor<=1e-3})
    return checks


def interference(doc):
    objs=[o for o in doc.Objects if 'SourceBody' in o.PropertiesList]; found=[]; checked=0
    for i,a in enumerate(objs):
        for b in objs[i+1:]:
            if not a.Shape.BoundBox.intersect(b.Shape.BoundBox): continue
            checked+=1; volume=a.Shape.common(b.Shape).Volume
            if volume>1e-5: found.append({'a':a.SourceBody,'b':b.SourceBody,'volume_mm3':volume})
    return {'candidate_pairs_checked':checked,'interferences':found,'passed':not found,'scope':'Static assembled pose only; no robot/tool or waste pile'}


def main(output,case_path,report_path,step_path):
    spec=model.load(); case=json.loads(Path(case_path).read_text(encoding='utf-8')); p=model.parameters(spec,case['overrides'])
    doc=build(spec,p,output); geometry=analytic_check(doc,spec,p); exact=step_check(doc,step_path); static=interference(doc)
    edits=[]
    if not case['overrides']:
        for name,value in [('groove_M',7),('bin_h',160)]:
            setattr(doc.ModelParameters,name,value); doc.recompute()
            checks=analytic_check(doc,spec,model.parameters(spec,{name:value}))
            edits.append({'parameter':name,'value_mm':value,'max_volume_error_mm3':max(c['analytic_volume_error_mm3'] for c in checks),
                'max_com_error_mm':max(c['analytic_com_error_mm'] for c in checks),'passed':all(c['passed'] for c in checks)})
            setattr(doc.ModelParameters,name,p[name]); doc.recompute()
    doc.save(); App.closeDocument(doc.Name)
    doc=App.openDocument(str(output)); doc.recompute(); reopened=analytic_check(doc,spec,p)
    report={'passed':all(c['passed'] for c in geometry+exact+edits+reopened) and static['passed'],
        'source_sha256':model.digest(model.SOURCE),'case':case,'geometry':geometry,'solidcraft_step_xor':exact,
        'static_interference':static,'native_parameter_edits':edits,'reopened':{'passed':all(c['passed'] for c in reopened),'bodies':len(reopened)},
        'freecad_version':App.Version(),'backend':'Native Part primitives, expression-constrained taper sketches, extrusions and cuts; portable marking profiles; no STEP-derived model'}
    Path(report_path).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8'); App.closeDocument(doc.Name)
    print(json.dumps({'passed':report['passed'],'bodies':len(geometry),'parameter_edits':edits,'maximum_xor_mm3':max(c['xor_mm3'] for c in exact)}),flush=True)
    if not report['passed']: raise AssertionError('FreeCAD collector validation failed: '+str(report_path))


if __name__=='__main__':
    # FreeCAD initializes its embedded main namespace; keep the adapter in its
    # importable module namespace, as the existing station adapter does.
    import build_tip_collector_freecad as backend
    backend.main(*sys.argv[1:])
