"""Native building presentation checks, with optional STEP comparison only."""
import argparse
import json
from pathlib import Path
import sys
import FreeCAD as App
import Part
import build_tube_carrier_freecad as native
import build_building_stack as evidence
import building_stack as model
import building_room_signs


def union_inspection(witness, targets, shapes):
    hits=[]; bounded=0; named=[('Witness',witness)]+[(name,shapes[name])for name in targets]
    for index,(a,ashape)in enumerate(named):
        for b,bshape in named[index+1:]:
            if not ashape.BoundBox.intersect(bshape.BoundBox):
                bounded+=1;continue
            volume=ashape.common(bshape).Volume
            if volume>0:hits.append({'a':a,'b':b,'volume_mm3':volume})
    return {'checked':len(named),'count':len(hits),'interferences':hits,'unchecked':[],'truncated':False,'budget_exceeded':False,
            'pairs_not_checked':0,'skipped_pairs':0,'bbox_separated_pairs':bounded}


def measured_geometry(doc):
    geometry=native.measurements(doc);objects={obj.SourceBody:obj for obj in native.objects(doc)}
    for body in geometry:
        group=objects[body['body']].getParentGeoFeatureGroup()
        if group is None or group.TypeId!='App::Part' or group.getParentGeoFeatureGroup() is not None:
            raise ValueError('Static building bodies require separate native root App::Part groups')
        body['component']=group.Name
        body['component_evidence']='Actual native App::Part parent; no copied RigidLink annotation'
        shape = native.motion.world_shape(objects[body['body']])
        body['closed_solids'] = bool(shape.Solids) and all(solid.isClosed() for solid in shape.Solids) and len(shape.Faces) == sum(len(solid.Faces) for solid in shape.Solids)
    return geometry


def prism(probe):
    points=[App.Vector(x,y,probe['offset_mm'])for x,y in probe['points_mm']]
    shape=Part.Face(Part.makePolygon(points+[points[0]])).extrude(App.Vector(0,0,probe['depth_mm']))
    if not shape.isValid()or shape.Volume<=0:raise ValueError('Invalid native presentation prism')
    return shape


def step_check(doc, path, source):
    """Keep ordinary one-solid matching; compare complete annotation compounds."""
    metadata = {body['id']: body for body in source['bodies']}
    ink_ids = {name for name, body in metadata.items() if body.get('role') == 'room_sign_ink'
               and body.get('geometry_semantics') == 'disconnected_surface_annotation'}
    objects = native.objects(doc)
    if {obj.SourceBody for obj in objects} != set(metadata):
        raise AssertionError('Complete source body identities required for building STEP comparison')
    unmatched = list(Part.read(str(path)).Solids)
    if any(not solid.isValid() or not solid.isClosed() or solid.Volume <= 0 for solid in unmatched):
        raise AssertionError('STEP comparison requires valid closed positive solids')
    result = []; annotations = {}
    for obj in objects:
        shape = native.motion.world_shape(obj)
        if obj.SourceBody in ink_ids:
            annotations[obj.SourceBody] = shape
            continue
        if len(shape.Solids) != 1 or not unmatched:
            raise AssertionError('Physical building parts require one matched STEP solid')
        center = sum((s.CenterOfMass * s.Volume for s in shape.Solids), App.Vector()) / shape.Volume
        index = min(range(len(unmatched)), key=lambda i: (unmatched[i].CenterOfMass-center).Length
                    + abs(unmatched[i].Volume-shape.Volume)/shape.Volume)
        other = unmatched.pop(index); xor = shape.cut(other).Volume + other.cut(shape).Volume
        result.append({'body': obj.SourceBody, 'xor_mm3': xor, 'passed': xor < 1e-3})
    grouped = {name: [] for name in annotations}
    # This margin only finds candidates; the unchanged XOR test accepts geometry.
    bbox_margin = 1e-4
    def contains(outer, inner):
        return all(getattr(inner, axis+'Min') >= getattr(outer, axis+'Min')-bbox_margin
                   and getattr(inner, axis+'Max') <= getattr(outer, axis+'Max')+bbox_margin
                   for axis in 'XYZ')
    for solid in unmatched:
        candidates = [name for name, shape in annotations.items()
                      if contains(shape.BoundBox, solid.BoundBox)]
        if len(candidates) != 1:
            raise AssertionError('Extra or ambiguously assigned STEP annotation solid')
        grouped[candidates[0]].append(solid)
    for name, shape in annotations.items():
        if not grouped[name]:
            raise AssertionError('Missing STEP annotation: '+name)
        other = Part.makeCompound(grouped[name])
        xor = shape.cut(other).Volume + other.cut(shape).Volume
        # Redundant overlapping STEP solids must not disappear inside a set cut.
        volume_delta = abs(shape.Volume-sum(solid.Volume for solid in grouped[name]))
        result.append({'body': name, 'xor_mm3': xor, 'passed': xor < 1e-3 and volume_delta < 1e-3,
                       'step_solid_count': len(grouped[name]), 'native_solid_count': len(shape.Solids),
                       'volume_delta_mm3': volume_delta,
                       'scope': 'Whole annotation geometry; kernel solid decompositions may differ'})
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('case','output','report'):parser.add_argument(name)
    parser.add_argument('--compare-step');args=parser.parse_args(argv);case=json.loads(Path(args.case).read_text())
    evidence.common.verify_pins(case['source_files_sha256']);path=model.ROOT/case['source'];model.SOURCE=path
    if model.digest(path)!=case['source_sha256']:raise ValueError('Building source changed')
    spec=model.load(path);p=model.parameters(spec);source=model.expanded(spec,p)
    if source['joints']:raise ValueError('Building concept must remain static')
    class PhysicalProvider:
        def __getattr__(self, name):
            return getattr(model, name)
        def expanded(self, _spec, _p):
            return building_room_signs.physical_source(source)
    native.model=PhysicalProvider();doc=native.build(model.native_spec(spec,p),p,Path(args.output))
    metadata = {body['id']: body for body in source['bodies']}
    glyph_cache = {}
    for op in source['operations']:
        if op['shape']['kind'] != 'cylinder_bundle':
            continue
        building_room_signs.validate_bundle(op['shape'])
        glyphs = []
        for span in op['shape']['glyph_spans']:
            strokes = op['shape']['cylinders'][span['start']:span['start']+span['count']]
            key = json.dumps(strokes, sort_keys=True, separators=(',', ':'))
            if key not in glyph_cache:
                cylinders = [Part.makeCylinder(c['radius'], c['height'], App.Vector(*c['origin']), App.Vector(*c['axis'])) for c in strokes]
                glyph_cache[key] = cylinders[0].multiFuse(cylinders[1:]) if len(cylinders) > 1 else cylinders[0]
            glyph = glyph_cache[key].copy()
            glyph.translate(App.Vector(*span['offset_mm']));glyphs.append(glyph)
        shape = Part.makeCompound(glyphs);matrix = App.Matrix();frame = op['shape']['frame']
        for col, axis in enumerate((frame['x'], frame['y'], frame['z'])):
            for row, value in enumerate(axis):setattr(matrix, 'A'+str(row+1)+str(col+1), value)
        for row, value in enumerate(frame['origin']):setattr(matrix, 'A'+str(row+1)+'4', value)
        shape.transformShape(matrix)
        obj = doc.addObject('Part::Feature', op['body']);doc.getObject(metadata[op['body']]['component']).addObject(obj)
        obj.Shape = shape
        for key, value in [('SourceBody', op['body']), ('RigidLink', metadata[op['body']]['component']),
                           ('ModelRole', metadata[op['body']]['role'])]:
            obj.addProperty('App::PropertyString', key, 'Shared source');setattr(obj, key, value);obj.setEditorMode(key, 1)
        obj.addProperty('App::PropertyInteger', 'SourceStrokeCount', 'Shared source');obj.SourceStrokeCount = len(op['shape']['cylinders'])
    doc.recompute();doc.save()
    doc.Controller.addProperty('App::PropertyString','CoordinateMeaning','Presentation');doc.Controller.CoordinateMeaning=evidence.NOTICE;doc.Controller.setEditorMode('CoordinateMeaning',1)
    geometry=measured_geometry(doc);evidence.checked_measurements({'geometry':geometry},source,backend='freecad')
    contract,z=evidence.coverage(spec,p,geometry);shapes={o.SourceBody:native.motion.world_shape(o)for o in native.objects(doc)};checks=[]
    for category,probes in [('opening',contract['opening_probes']),('atrium_floor_hole',contract['atrium_prisms'])]:
        for probe in probes:
            witness=prism(probe);targets=probe.get('target_bodies',[probe.get('target_body')]);volumes={name:witness.common(shapes[name]).Volume for name in targets}
            checks.append({'id':probe['id'],'category':category,'targets':targets,'passed':all(v<=1e-5 for v in volumes.values()),'intersections_presentation_mm3':volumes})
    ground=contract['ground_fill_probe'];witness=prism(ground);expected=evidence.prism_volume(ground)
    if ground.get('expectation')=='union_filled':
        targets=ground['target_bodies'];inspection=union_inspection(witness,targets,shapes);result=evidence.union_coverage(inspection,targets,'Witness',expected)
        checks.append({'id':ground['id'],'category':'ground_fill','targets':targets,'passed':result['passed'],'evidence':result,'native_pair_inspection':inspection})
    else:
        target=shapes[ground['target_body']];volume=witness.common(target).Volume;tol=max(1e-5,expected*1e-7)
        checks.append({'id':ground['id'],'category':'ground_fill','targets':[ground['target_body']],'passed':abs(volume-expected)<=tol and abs(target.Volume-expected)<=tol,
                      'expected_presentation_mm3':expected,'intersection_presentation_mm3':volume,'body_volume_presentation_mm3':target.Volume,'tolerance_presentation_mm3':tol})
    for item in evidence.circulation_probe_specs(contract)+evidence.roof_probe_specs(contract)+evidence.opening_closure_probe_specs(contract)+evidence.atrium_access_probe_specs(contract):
        probe=item['probe'];witness=prism(probe);results={}
        if probe.get('expectation')=='union_filled':
            targets=probe['target_bodies'];inspection=union_inspection(witness,targets,shapes);result=evidence.union_coverage(inspection,targets,'Witness',evidence.prism_volume(probe))
            checks.append({'id':probe['id'],'category':item['category'],'targets':targets,'passed':result['passed'],'evidence':result,'native_pair_inspection':inspection});continue
        for name,expected in item['expected'].items():
            volume=witness.common(shapes[name]).Volume
            tolerance=1e-5 if expected==0 else max(1e-5,expected*1e-7)
            results[name]={'passed':volume<=tolerance if expected==0 else abs(volume-expected)<=tolerance,
                           'intersection_presentation_mm3':volume,'expected_presentation_mm3':expected,'tolerance_presentation_mm3':tolerance}
        checks.append({'id':probe['id'],'category':item['category'],'targets':list(results),
                       'passed':all(result['passed']for result in results.values()),'target_evidence':results,
                       **({'area_id':probe['area_id'],'method':item['method']}if item['category']=='roof_glass_area_coverage'else{})})
    circ_geometry=evidence.circulation_geometry(contract,geometry)
    roof_checks=evidence.roof_geometry(contract,geometry)
    corridors=evidence.corridor_roof_checks(contract,checks,roof_checks)
    exact=step_check(doc,args.compare_step,source)if args.compare_step else[]
    doc.save();App.closeDocument(doc.Name);doc=App.openDocument(str(Path(args.output)));doc.recompute();reopened=measured_geometry(doc)
    evidence.checked_measurements({'geometry':reopened},source,backend='freecad');reopen=evidence.floor.comparison(geometry,reopened);App.closeDocument(doc.Name)
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'));from persist_station_view import persist
    presentation=persist(args.output,source,geometry);evidence.common.verify_pins(case['source_files_sha256'])
    report={'passed':presentation['passed']and all(c['passed']for c in checks+z+circ_geometry+roof_checks+corridors+exact+reopen),'source_sha256':case['source_sha256'],'source_files_sha256':case['source_files_sha256'],
            'geometry':geometry,'z_checks':z,'probe_checks':checks,'solidcraft_step_xor':exact,'step_comparison_performed':bool(args.compare_step),'presentation':presentation,
            'circulation_geometry_checks':circ_geometry,'roof_geometry_checks':roof_checks,
            'corridor_roof_checks':corridors,'native_corridor_roof_checks_passed':bool(corridors)and all(c['passed']for c in corridors),
            'reopened':reopen,'coordinate_meaning':evidence.NOTICE,'metric_scale_known':False,'global_interference_checked':False,'freecad_version':App.Version()}
    evidence.write(args.report,report);print(json.dumps({'passed':report['passed'],'closed_bodies':len(geometry),'scoped_probes':len(checks),'z_checks':len(z)}),flush=True)
    if not report['passed']:raise AssertionError('Native building scoped checks failed')


if __name__=='__main__':
    import build_building_stack_freecad as adapter
    adapter.main()
