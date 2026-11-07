"""Native parameter-driven L01 boxes, constrained polygon sketches and booleans."""
from pathlib import Path
import json
import math
import sys
import FreeCAD as App
import Part
import Sketcher
import lab_room_model as model
from build_neutral_freecad import native_expression
from build_tube_carrier_freecad import measurements, step_check, objects


def build(spec,p,path):
    if Path(path).exists(): raise FileExistsError(path)
    source=model.expanded(spec,p); doc=App.newDocument(spec['id'])
    dims=doc.addObject('App::FeaturePython','ModelParameters')
    for name in spec['parameters']:
        dims.addProperty('App::PropertyDistance',name,'Provisional dimensions (mm)'); setattr(dims,name,p[name])
    controller=doc.addObject('App::FeaturePython','Controller')
    for key,value in [('SourceFile',str(model.SOURCE.relative_to(model.ROOT))),('SpecSHA256',model.digest(model.SOURCE)),('Status',spec['status'])]:
        controller.addProperty('App::PropertyString',key,'Source'); setattr(controller,key,value)
    groups={c['id']:doc.addObject('App::Part',c['id']) for c in source['components']}
    latest={}; meta={b['id']:b for b in source['bodies']}
    for operation in source['operations']:
        s=operation['shape']; name=operation['id']; target=operation['body']; group=groups[meta[target]['component']]
        if s['kind']=='box':
            obj=doc.addObject('Part::Box',name+'_Primitive'); group.addObject(obj)
            for prop,value in zip(['Length','Width','Height'],s['size']): obj.setExpression(prop,native_expression(value))
            for axis,value in zip('xyz',s['origin']): obj.setExpression('Placement.Base.'+axis,native_expression(value))
        else:
            sketch=doc.addObject('Sketcher::SketchObject',name+'_Profile'); group.addObject(sketch)
            sketch.setExpression('Placement.Base.z',native_expression(s['z']))
            geoms=[]; constraints=[]; expressions=[]
            points=s['points']
            for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
                geoms.append(Part.LineSegment(App.Vector(*(model.evaluate(v,p) for v in a),0),App.Vector(*(model.evaluate(v,p) for v in b),0)))
                for endpoint,point in [(1,a),(2,b)]:
                    for axis,value in zip('XY',point):
                        constraints.append(Sketcher.Constraint('Distance'+axis,i,endpoint,model.evaluate(value,p)))
                        expressions.append(native_expression(value))
            sketch.addGeometry(geoms,False); ids=sketch.addConstraint(constraints)
            for index,expression in zip(ids,expressions): sketch.setExpression('Constraints[%s]'%index,expression)
            obj=doc.addObject('Part::Extrusion',name+'_Extrusion'); group.addObject(obj); obj.Base=sketch; obj.Solid=True
            obj.setExpression('Dir.z',native_expression(s['height']))
        if operation['action']!='create':
            boolean=doc.addObject('Part::Cut' if operation['action']=='cut' else 'Part::Fuse',name+'_Result')
            group.addObject(boolean); boolean.Base=latest[target]; boolean.Tool=obj; boolean.Refine=True; obj=boolean
        latest[target]=obj
    for f in source['frames']:
        obj=doc.addObject('App::FeaturePython',f['id'].replace('.','_')); groups['RoomShell'].addObject(obj)
        obj.addProperty('App::PropertyString','FrameID','Source'); obj.FrameID=f['id']
        obj.addProperty('App::PropertyPlacement','Placement','Frame')
        yaw=math.degrees(math.atan2(f['x_axis'][1],f['x_axis'][0]))
        obj.Placement=App.Placement(App.Vector(),App.Rotation(App.Vector(0,0,1),yaw))
        for axis,value in zip('xyz',f['origin']): obj.setExpression('Placement.Base.'+axis,native_expression(value))
    doc.recompute()
    for name,obj in latest.items():
        obj.Label=name
        for key,value in [('SourceBody',name),('RigidLink',meta[name]['component']),('ModelRole',meta[name]['role'])]:
            obj.addProperty('App::PropertyString',key,'Shared source'); setattr(obj,key,value)
    doc.recompute(); doc.saveAs(str(path)); return doc


def check_frames(doc,spec,p):
    source=model.expanded(spec,p); frame_objs={o.FrameID:o for o in doc.Objects if 'FrameID' in o.PropertiesList}
    checks=[]; bodies={o.SourceBody:o for o in objects(doc)}
    for frame in source['frames']:
        expected=[model.evaluate(v,p) for v in frame['origin']]; actual=list(frame_objs[frame['id']].Placement.Base)
        error=math.dist(actual,expected)
        if '.Worktop' in frame['id']:
            name=frame['id'].split('.')[1]+'_Worktop'; error=max(error,abs(bodies[name].Shape.BoundBox.ZMax-expected[2]))
        elif frame['id']=='L01.IslandShelf.Top': error=max(error,abs(bodies['IslandShelf_Board'].Shape.BoundBox.ZMax-expected[2]))
        elif frame['id'].startswith('L01.IslandCupboard'):
            error=max(error,abs(bodies[frame['id'].split('.')[1]].Shape.BoundBox.ZMin-expected[2]))
        checks.append({'id':frame['id'],'error_mm':error,'passed':error<1e-6})
    return checks


def check_window_assembly(doc):
    bodies={o.SourceBody:o.Shape for o in objects(doc)}; column=bodies['ConcreteSupport']; checks=[]
    for side in ['Left','Right']:
        shape=bodies['WindowBench'+side+'_Worktop']; x=shape.BoundBox.XMax if side=='Left' else shape.BoundBox.XMin
        near=[v.Point.y for v in shape.Vertexes if abs(v.Point.x-x)<1e-6 and abs(v.Point.z-shape.BoundBox.ZMax)<1e-6]
        error=abs(min(near)-column.BoundBox.YMin)
        checks.append({'id':'L01.WindowBench'+side+'.front_alignment','error_mm':error,'passed':error<1e-6})
    related=[name for name in bodies if name.startswith('WindowBench') or name.startswith('HeatingCover') or name=='SupportGapCover']
    for name in related:
        volume=column.common(bodies[name]).Volume
        checks.append({'id':'L01.ConcreteSupport.clearance.'+name,'intersection_mm3':volume,'passed':volume<1e-3})
    for side in ['Left','Right']:
        worktop=bodies['WindowBench'+side+'_Worktop'].BoundBox
        for i in range(1,3):
            leg=bodies['WindowBench'+side+'_Leg'+str(i)].BoundBox
            error=max(abs(leg.ZMin),abs(leg.ZMax-worktop.ZMin))
            checks.append({'id':'L01.WindowBench'+side+'.leg'+str(i),'contact_error_mm':error,'passed':error<1e-6})
    return checks


def check_island_shelf(doc):
    bodies={o.SourceBody:o.Shape for o in objects(doc)}; shelf=bodies['IslandShelf_Board']; bb=shelf.BoundBox
    left=bodies['IslandLeft_Worktop'].BoundBox; right=bodies['IslandRight_Worktop'].BoundBox
    error=abs((bb.XMin+bb.XMax)/2-left.XMax)
    checks=[{'id':'L01.IslandShelf.centred','error_mm':error,'passed':error<1e-6},
        {'id':'L01.IslandShelf.above_worktops','clearance_mm':bb.ZMin-left.ZMax,'passed':bb.ZMin>left.ZMax},
        {'id':'L01.IslandShelf.inside_island','passed':bb.XMin>left.XMin and bb.XMax<right.XMax and bb.YMin>left.YMin and bb.YMax<left.YMax}]
    for i in range(1,4):
        name='IslandShelf_Post'+str(i); pb=bodies[name].BoundBox
        error=max(abs(pb.ZMin-left.ZMax),abs(pb.ZMax-bb.ZMin))
        inside=pb.XMin>=bb.XMin and pb.XMax<=bb.XMax and pb.YMin>=bb.YMin and pb.YMax<=bb.YMax
        overlap=sum(bodies[name].common(bodies[n]).Volume for n in ['IslandLeft_Worktop','IslandRight_Worktop'])
        checks.append({'id':'L01.IslandShelf.post'+str(i),'contact_error_mm':error,'worktop_overlap_mm3':overlap,'passed':inside and error<1e-6 and overlap<1e-3})
    cupboard_bottom=min(bodies['IslandCupboard'+str(i)].BoundBox.ZMin for i in [1,2])
    gap=cupboard_bottom-bb.ZMax
    checks.append({'id':'L01.IslandShelf.reach_through_band','height_mm':gap,'passed':gap>0})
    for i in range(1,4):
        ub=bodies['IslandShelf_UpperPost'+str(i)].BoundBox
        error=max(abs(ub.ZMin-bb.ZMax),abs(ub.ZMax-cupboard_bottom))
        checks.append({'id':'L01.IslandShelf.upper_post'+str(i),'contact_error_mm':error,'passed':error<1e-6})
    # Two cross-island line segments through the clear spans. These establish
    # geometric openness, not hand-size, reach distance or ergonomic suitability.
    z=(bb.ZMax+cupboard_bottom)/2
    for t in [0.25,0.75]:
        y=bb.YMin+t*(bb.YMax-bb.YMin); line=Part.makeLine(App.Vector(left.XMin,y,z),App.Vector(right.XMax,y,z)); blockers=[]
        for name,shape in bodies.items():
            bounds=shape.BoundBox
            if not bounds.YMin<=y<=bounds.YMax or not bounds.ZMin<=z<=bounds.ZMax: continue
            if line.common(shape).Length>1e-6: blockers.append(name)
        checks.append({'id':'L01.IslandShelf.cross_probe.'+str(t),'z_mm':z,'blocking_bodies':blockers,'passed':not blockers})
    return checks


def validate(output,case_path,report_path,step_path):
    spec=model.load(); case=json.loads(Path(case_path).read_text(encoding='utf-8')); p=model.parameters(spec,case['overrides'])
    doc=build(spec,p,output); geometry=measurements(doc); exact=step_check(doc,step_path); frames=check_frames(doc,spec,p); window_checks=check_window_assembly(doc)
    shelf_checks=check_island_shelf(doc)
    # A native width+facade edit must move curved geometry and named work frames.
    edits=[]
    if case['id']=='default':
        for overrides in [{'room_width':7100,'facade_bulge':650},{'support_offset_x':250,'support_width':400,'support_depth':550},
                {'island_length':3600,'island_shelf_top_z':1550,'island_shelf_depth':400,'island_shelf_end_inset':200,
                 'island_cupboard_bottom_z':1850,'island_cupboard_height':500,'island_cupboard_depth':450}]:
            pp=model.parameters(spec,overrides)
            for key,value in overrides.items(): setattr(doc.ModelParameters,key,value)
            doc.recompute(); edit_geometry=measurements(doc); frame_checks=check_frames(doc,spec,pp); window_edits=check_window_assembly(doc); shelf_edits=check_island_shelf(doc)
            edits.append({'overrides':overrides,'geometry':edit_geometry,'frames':frame_checks,'window_checks':window_edits,'shelf_checks':shelf_edits,
                'passed':all(b['valid'] and b['solid_count']==1 for b in edit_geometry) and all(c['passed'] for c in frame_checks+window_edits+shelf_edits)})
            for key in overrides: setattr(doc.ModelParameters,key,p[key])
            doc.recompute()
    doc.save(); App.closeDocument(doc.Name); doc=App.openDocument(str(output)); doc.recompute(); reopened=measurements(doc)
    reopen_ok=len(reopened)==len(geometry) and all(b['valid'] and b['solid_count']==1 for b in reopened)
    passed=all(b['valid'] and b['solid_count']==1 for b in geometry) and all(c['passed'] for c in exact+frames+edits+window_checks+shelf_checks) and reopen_ok
    report={'passed':passed,'case':case,'source_sha256':model.digest(model.SOURCE),'geometry':geometry,'solidcraft_step_xor':exact,
        'frame_geometry_checks':frames,'window_assembly_checks':window_checks,'island_shelf_checks':shelf_checks,'native_parameter_edits':edits,'reopened_passed':reopen_ok,'freecad_version':App.Version(),
        'circulation':model.circulation(p),'backend':'Native expression-driven boxes, constrained polygon sketches, extrusions and cuts; STEP only for comparison'}
    Path(report_path).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8'); App.closeDocument(doc.Name)
    print(json.dumps({'passed':passed,'case':case['id'],'bodies':len(geometry),'max_xor_mm3':max(c['xor_mm3'] for c in exact)}),flush=True)
    if not passed: raise AssertionError('L01 FreeCAD check failed: '+str(report_path))


if __name__=='__main__':
    import build_lab_room_freecad as backend
    backend.validate(*sys.argv[1:])
