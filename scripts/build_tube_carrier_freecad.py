"""Native expression-driven FreeCAD H01 adapter; STEP is used only for validation."""
from pathlib import Path
import json
import ast
import math
import sys
import FreeCAD as App
import Part
import Sketcher
import tube_carrier_model as model
from build_neutral_freecad import native_expression

sys.path.insert(0, str(model.ROOT / 'scripts/freecad'))
import solidcraftbot_freecad as motion


def origin(obj, values):
    for axis, value in zip('xyz', values):
        obj.setExpression('Placement.Base.' + axis, native_expression(value))


def build(spec, p, path):
    if Path(path).exists(): raise FileExistsError(path)
    source = model.expanded(spec, p); doc = App.newDocument(spec['id'])
    params = doc.addObject('App::FeaturePython', 'ModelParameters')
    for name in spec['parameters']:
        params.addProperty('App::PropertyAngle' if spec['parameters'][name].get('unit')=='deg' else 'App::PropertyDistance', name, 'Shared dimensions'); setattr(params, name, p[name])
    for name, definition in spec['parameters'].items():
        if any(isinstance(n, ast.Name) for n in ast.walk(ast.parse(str(definition['expression']), mode='eval'))):
            params.setExpression(name, native_expression(definition['expression']))
    controller = doc.addObject('App::FeaturePython', 'Controller')
    for key, value in [('SpecSHA256', model.digest(model.SOURCE)), ('SourceFile', str(model.SOURCE.relative_to(model.ROOT))), ('Status', spec['status'])]:
        controller.addProperty('App::PropertyString', key, 'Source'); setattr(controller, key, value); controller.setEditorMode(key, 1)
    values = model.pose(spec, p)
    groups = {c['id']: doc.addObject('App::Part', c['id']) for c in source['components']}
    for c in source['components']:
        if c.get('parent'): groups[c['parent']].addObject(groups[c['id']])
    for joint in source['joints']:
        name = joint['id']; angular=joint.get('type')=='revolute'
        controller.addProperty('App::PropertyAngle' if angular else 'App::PropertyDistance', name, 'Joint positions (deg/mm)')
        setattr(controller, name, values[name])
        hi = joint.get('limit_parameter', 'transfer_travel' if name.startswith('Slide') else 'latch_travel')
        if angular:
            anchor=doc.addObject('App::Part',name+'_Anchor');groups[joint['parent']].addObject(anchor)
            frame=motion.frame_placement({'origin':[model.evaluate(v,p) for v in joint['origin']],'x':joint['reference_x'],'z':joint['axis']})
            anchor.Placement=frame;origin(anchor,joint['origin'])
            turn=doc.addObject('App::Part',name+'_Motion');anchor.addObject(turn)
            turn.setExpression('Placement.Rotation.Angle',f'max(0 deg; min(ModelParameters.{hi}; Controller.{name}))')
            turn.addObject(groups[joint['child']]);groups[joint['child']].Placement=frame.inverse()
            inverse=frame.Rotation.inverted().toMatrix();coordinates=[]
            for row in range(3):
                terms=[f'({-getattr(inverse,"A%d%d"%(row+1,col+1))})*({joint["origin"][col]})' for col in range(3) if abs(getattr(inverse,'A%d%d'%(row+1,col+1)))>1e-12]
                coordinates.append('+'.join(terms) or 0)
            origin(groups[joint['child']],coordinates)
        else:
            for axis, scale in zip('xyz', joint['axis']):
                groups[joint['child']].setExpression('Placement.Base.' + axis,
                    f'{scale} * max(0 mm; min(ModelParameters.{hi}; Controller.{name}))')
    if hasattr(model,'native_controller_fields'):
        fields=model.native_controller_fields(spec,p)
        for field in fields:
            if field['name'] not in controller.PropertiesList:
                controller.addProperty({'mm':'App::PropertyDistance','deg':'App::PropertyAngle','':'App::PropertyFloat'}[field['unit']],field['name'],'Cam program')
                setattr(controller,field['name'],field['value'])
        for field in fields:
            if field['expression'] is not None:controller.setExpression(field['name'],field['expression']);controller.setEditorMode(field['name'],1)
    latest = {}; meta = {b['id']: b for b in source['bodies']}
    for operation in source['operations']:
        s = operation['shape']; kind = s['kind']; name = operation['id']; target = operation['body']
        group = groups[meta[target]['component']]
        if kind=='polygon_prism':
            profile=doc.addObject('Sketcher::SketchObject',name+'_Sketch');group.addObject(profile)
            if s['plane']=='XZ':
                profile.Placement=App.Placement(App.Vector(),App.Rotation(App.Vector(1,0,0),-90))
                profile.setExpression('Placement.Base.y',native_expression(s['offset']))
                points=[[x,f'-({z})'] for x,z in s['points']];direction=[0,1,0]
            else:
                profile.Placement=App.Placement(App.Vector(),App.Rotation(App.Vector(0,1,0),App.Vector(0,0,1),App.Vector(1,0,0),'ZXY'))
                profile.setExpression('Placement.Base.x',native_expression(s['offset']))
                points=s['points'];direction=[1,0,0]
            geometry=[];constraints=[];expressions=[]
            for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
                geometry.append(Part.LineSegment(App.Vector(*(model.evaluate(v,p) for v in a),0),App.Vector(*(model.evaluate(v,p) for v in b),0)))
                if s.get('fixed'):
                    constraints.append(Sketcher.Constraint('Block',i));continue
                for endpoint,point in [(1,a),(2,b)]:
                    for axis,value in zip('XY',point):
                        constraints.append(Sketcher.Constraint('Distance'+axis,i,endpoint,model.evaluate(value,p)));expressions.append(native_expression(value))
            profile.addGeometry(geometry,False);ids=profile.addConstraint(constraints)
            if not s.get('fixed'):
                for index,expression in zip(ids,expressions):profile.setExpression('Constraints[%s]'%index,expression)
            obj=doc.addObject('Part::Extrusion',name+'_Extrusion');group.addObject(obj);obj.Base=profile;obj.Solid=True
            for axis,scale in zip('xyz',direction):obj.setExpression('Dir.'+axis,native_expression(f'{scale}*({s["depth"]})'))
        elif kind == 'axis_revolved_profile':
            if s['axis']!='X':raise ValueError('Unsupported revolution axis')
            x,y,z=s['axis_origin']
            profile=doc.addObject('Sketcher::SketchObject',name+'_Sketch');group.addObject(profile)
            profile.setExpression('Placement.Base.z',native_expression(z))
            points=[[f'({x})+({a})',f'({y})+({r})'] for a,r in s['points_ar']]
            geometry=[];constraints=[];expressions=[]
            for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
                geometry.append(Part.LineSegment(App.Vector(*(model.evaluate(v,p) for v in a),0),App.Vector(*(model.evaluate(v,p) for v in b),0)))
                for endpoint,point in [(1,a),(2,b)]:
                    for axis,value in zip('XY',point):
                        constraints.append(Sketcher.Constraint('Distance'+axis,i,endpoint,model.evaluate(value,p)));expressions.append(native_expression(value))
            profile.addGeometry(geometry,False);ids=profile.addConstraint(constraints)
            for index,expression in zip(ids,expressions):profile.setExpression('Constraints[%s]'%index,expression)
            obj=doc.addObject('Part::Revolution',name+'_Revolution');group.addObject(obj)
            obj.Source=profile;obj.Axis=App.Vector(1,0,0);obj.Angle=360;obj.Solid=True
            for axis,value in zip('xyz',[x,y,z]):obj.setExpression('Base.'+axis,native_expression(value))
            latest[target]=obj
            continue
        elif kind == 'revolved_profile':
            profile = doc.addObject('Sketcher::SketchObject', name+'_Sketch'); group.addObject(profile)
            profile.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 90))
            points = [[f'({s["center_x"]})+({r})', z] for r, z in s['points_rz']]
            geometries = []; constraints = []; expressions = []
            for i, (a, b) in enumerate(zip(points, points[1:]+points[:1])):
                geometries.append(Part.LineSegment(App.Vector(*(model.evaluate(v, p) for v in a), 0), App.Vector(*(model.evaluate(v, p) for v in b), 0)))
                for endpoint, point in [(1, a), (2, b)]:
                    for axis, value in zip('XY', point):
                        constraints.append(Sketcher.Constraint('Distance'+axis, i, endpoint, model.evaluate(value, p)))
                        expressions.append(native_expression(value))
            profile.addGeometry(geometries, False); ids = profile.addConstraint(constraints)
            for index, expression in zip(ids, expressions): profile.setExpression('Constraints[%s]' % index, expression)
            obj = doc.addObject('Part::Revolution', name+'_Revolution'); group.addObject(obj)
            obj.Source = profile; obj.Axis = App.Vector(0, 0, 1); obj.Angle = 360; obj.Solid = True
            obj.setExpression('Base.x', native_expression(s['center_x']))
            latest[target] = obj
            continue
        else:
            obj = doc.addObject({'box': 'Part::Box', 'cylinder': 'Part::Cylinder', 'cone': 'Part::Cone', 'sphere': 'Part::Sphere'}[kind], name + '_Primitive')
            group.addObject(obj)
            properties = list(zip(['Length', 'Width', 'Height'], s['size'])) if kind == 'box' else [('Radius', s['radius'])] if kind == 'sphere' else \
                [('Radius1', s['radius']), ('Radius2', s['top_radius']), ('Height', s['height'])] if kind == 'cone' else [('Radius', s['radius']), ('Height', s['height'])]
            for key, value in properties: obj.setExpression(key, native_expression(value))
            if 'axis' in s:obj.Placement=App.Placement(App.Vector(),App.Rotation(App.Vector(0,0,1),App.Vector(*s['axis'])))
            origin(obj, s['origin'])
        if operation['action'] != 'create':
            boolean = doc.addObject('Part::Cut' if operation['action'] == 'cut' else 'Part::Fuse', name + '_Result')
            group.addObject(boolean); boolean.Base = latest[target]; boolean.Tool = obj; boolean.Refine = True; obj = boolean
        latest[target] = obj
    doc.recompute()
    for name, obj in latest.items():
        obj.Label = name
        for key, value in [('SourceBody', name), ('RigidLink', meta[name]['component']), ('ModelRole', meta[name]['role'])]:
            obj.addProperty('App::PropertyString', key, 'Shared source'); setattr(obj, key, value); obj.setEditorMode(key, 1)
    doc.recompute(); doc.saveAs(str(path))
    return doc


def objects(doc): return [o for o in doc.Objects if 'SourceBody' in o.PropertiesList]


def measurements(doc):
    result = []
    for obj in objects(doc):
        shape = motion.world_shape(obj); bb = shape.BoundBox; volume = shape.Volume
        if volume <= 0: raise AssertionError('Empty body: ' + obj.SourceBody)
        com = [sum(s.CenterOfMass[i] * s.Volume for s in shape.Solids) / volume for i in range(3)]
        result.append({'body': obj.SourceBody, 'component': obj.RigidLink, 'valid': shape.isValid(),
            'solid_count': len(shape.Solids), 'volume_mm3': volume, 'world_center_of_mass_mm': com,
            'bbox': {'min': [bb.XMin, bb.YMin, bb.ZMin], 'max': [bb.XMax, bb.YMax, bb.ZMax]}})
    return result


def set_pose(doc, source, values):
    model.validate_pose(source, values)
    inputs=model.control_inputs_from_pose(source['model_spec'],source['parameter_values'],values) if hasattr(model,'control_inputs_from_pose') else values
    for name, value in inputs.items(): setattr(doc.Controller, name, value)
    doc.recompute()


def interference(doc, rigid_cache=None):
    # Geometry is rigid during this pose sweep. Reuse intersections only at
    # exactly identical world placements, or within the same rigid component.
    rigid_cache={} if rigid_cache is None else rigid_cache
    bodies=[]
    for obj in objects(doc):
        shape=motion.world_shape(obj);pl=shape.Placement
        bodies.append((obj,shape,(pl.Base.x,pl.Base.y,pl.Base.z,*pl.Rotation.Q)))
    cross = []; internal = []
    for i, (a, ashape, apose) in enumerate(bodies):
        for b, bshape, bpose in bodies[i + 1:]:
            if hasattr(model,'skip_interference_pair') and model.skip_interference_pair(a.SourceBody,b.SourceBody):continue
            same=a.RigidLink==b.RigidLink;key=(a.SourceBody,b.SourceBody) if same else (a.SourceBody,b.SourceBody,apose,bpose)
            if key in rigid_cache:volume=rigid_cache[key]
            else:
                if not ashape.BoundBox.intersect(bshape.BoundBox):
                    rigid_cache[key]=0
                    continue
                volume = ashape.common(bshape).Volume
                rigid_cache[key]=volume
            if volume > 1e-5:
                (internal if a.RigidLink == b.RigidLink else cross).append({'a': a.SourceBody, 'b': b.SourceBody, 'volume_mm3': volume})
    return {'passed': not cross, 'between_components': cross, 'within_rigid_components': internal}


def step_check(doc, path):
    unmatched = list(Part.read(str(path)).Solids); result = []
    if len(unmatched) != len(objects(doc)): raise AssertionError('STEP solid count mismatch')
    for obj in objects(doc):
        shape = motion.world_shape(obj)
        center = sum((s.CenterOfMass * s.Volume for s in shape.Solids), App.Vector()) / shape.Volume
        index = min(range(len(unmatched)), key=lambda i: (unmatched[i].CenterOfMass - center).Length + abs(unmatched[i].Volume - shape.Volume) / shape.Volume)
        other = unmatched.pop(index); xor = shape.cut(other).Volume + other.cut(shape).Volume
        result.append({'body': obj.SourceBody, 'xor_mm3': xor, 'passed': xor < 1e-3})
    return result


def check_interfaces(doc, spec, p):
    if hasattr(model, 'check_interface_geometry'): return model.check_interface_geometry(spec, p, measurements(doc))
    result = []; source = model.expanded(spec, p); current = measurements(doc)
    by_name = {b['body']: b for b in current}
    for variant in spec['variants']:
        tag = variant['id']; shell = by_name[tag + '_CarrierShell']; insert = by_name[tag + '_Insert']
        # External gripping width and insertion depth are shared despite different cavity/bottom profiles.
        width = shell['bbox']['max'][0] - shell['bbox']['min'][0]
        depth = shell['bbox']['max'][1] - shell['bbox']['min'][1]
        result.append({'variant': tag, 'grip_outer_width_mm': width, 'foot_depth_mm': depth,
            'collar_seat_z_mm': insert['bbox']['max'][2], 'metal_docking_z_mm': insert['bbox']['min'][2],
            'passed': abs(width - 34) < 1e-7 and abs(depth - 24) < 1e-7 and
                      abs(insert['bbox']['max'][2] - p['collar_z']) < 1e-7 and abs(insert['bbox']['min'][2] - p['carrier_bottom_z']) < 1e-7})
    return result


def main(output, case_path, report_path, step_path):
    spec = model.load(); case = json.loads(Path(case_path).read_text(encoding='utf-8')); p = model.parameters(spec, case['overrides'])
    source = model.expanded(spec, p); doc = build(spec, p, output)
    geometry = measurements(doc); exact = step_check(doc, step_path); interfaces = check_interfaces(doc, spec, p)
    samples = []; default_values = model.pose(spec, p);rigid_cache={}
    baseline = {b['body']: b for b in geometry}
    for sample in model.samples(spec, p):
        current=sample.get('joint_values',sample.get('values_mm'));set_pose(doc, source, current); error = 0
        for b in measurements(doc):
            if hasattr(model,'pose_change_point'):
                expected=model.pose_change_point(source,b['component'],baseline[b['body']]['world_center_of_mass_mm'],p,default_values,current)
            else:
                old = model.displacement(source, b['component'], default_values)
                new = model.displacement(source, b['component'], current)
                expected = [c + n - o for c, n, o in zip(baseline[b['body']]['world_center_of_mass_mm'], new, old)]
            error = max(error, math.dist(b['world_center_of_mass_mm'], expected))
        collisions = interference(doc,rigid_cache)
        samples.append({**sample, 'max_translation_error_mm': error, **collisions, 'passed': error < 1e-7 and collisions['passed']})
    set_pose(doc, source, default_values)
    edits = []
    if not case['overrides']:
        for name, definition in spec['parameters'].items():
            lo, hi = definition['range']
            if lo == hi or name not in spec.get('native_edit_parameters', list(spec['parameters'])): continue
            for value in [lo, hi]:
                setattr(doc.ModelParameters, name, value); doc.recompute()
                pp = model.parameters(spec, {name: value})
                # Pose values remain the saved numeric commands, as in SolidCraft; they are bounded by new travel limits.
                effective = {j['id']: min(default_values[j['id']], j['limits_mm'][1]) for j in model.expanded(spec, pp)['joints']}
                measured = measurements(doc)
                checks = check_interfaces(doc, spec, pp)
                edits.append({'parameter': name, 'value_mm': value, 'geometry': measured, 'effective_pose_mm': effective,
                    'passed': all(b['valid'] and b['solid_count'] == 1 for b in measured) and all(c['passed'] for c in checks)})
                setattr(doc.ModelParameters, name, p[name]); doc.recompute()
    doc.save(); App.closeDocument(doc.Name)
    doc = App.openDocument(str(output)); doc.recompute(); reopened = measurements(doc)
    reopened_ok = len(reopened) == len(geometry) and all(b['valid'] and b['solid_count'] == 1 for b in reopened)
    optical = []
    if hasattr(model, 'optical_rays'):
        set_pose(doc, source, model.pose(spec, p, 'ready'))
        blockers = [o for o in objects(doc) if o.ModelRole not in ['tube_shape_reference', 'illustrative_fluid', 'clearance_envelope']]
        for ray in model.optical_rays(spec, p):
            line = Part.makeLine(App.Vector(*ray['start']), App.Vector(*ray['end']))
            blocked = [o.SourceBody for o in blockers if motion.world_shape(o).common(line).Length > 1e-5]
            optical.append({**ray, 'opaque_blockers': blocked, 'passed': not blocked})
        set_pose(doc, source, default_values)
    analytic=model.geometry_checks(spec,p) if hasattr(model,'geometry_checks') else []
    report = {'passed': all(b['valid'] and b['solid_count'] == 1 for b in geometry) and all(c['passed'] for c in exact + interfaces + samples + edits + optical + analytic) and reopened_ok,
        'source_sha256': model.digest(model.SOURCE), 'case': case, 'geometry': geometry, 'solidcraft_step_xor': exact,
        'interfaces': interfaces, 'motion_samples': samples, 'native_parameter_edits': edits, 'optical_segments': optical,'mechanism_geometry_checks':analytic,
        'reopened': {'passed': reopened_ok, 'bodies': len(reopened)}, 'freecad_version': App.Version(),
        'backend': 'Native Part boxes/cylinders/fuses/cuts and expression-constrained sketches/revolutions; expression-driven slider placements; no imported STEP source'}
    Path(report_path).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8'); App.closeDocument(doc.Name)
    print(json.dumps({'passed': report['passed'], 'bodies': len(geometry), 'poses': len(samples),
        'failed_poses': [s['id'] for s in samples if not s['passed']],
        'interference_pairs':sorted(set((c['a'],c['b']) for s in samples for c in s['between_components'])),
        'maximum_xor_mm3': max(c['xor_mm3'] for c in exact)}), flush=True)
    if not report['passed']: raise AssertionError(spec['id']+' FreeCAD validation failed: ' + str(report_path))


if __name__ == '__main__':
    import build_tube_carrier_freecad as backend
    backend.main(*sys.argv[1:])
