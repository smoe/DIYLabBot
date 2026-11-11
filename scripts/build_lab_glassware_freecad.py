"""Independent native FreeCAD glassware build and BRep checks of actual openings."""
import argparse
import json
import math
from pathlib import Path
import sys

import FreeCAD as App
import Part

import build_tube_carrier_freecad as native
import lab_glassware as model


def clear_space(spec, p):
    pieces = []
    for lo, hi, r0, r1 in model.cavity_segments(spec, p):
        base = App.Vector(0, 0, lo)
        pieces.append(Part.makeCylinder(r0, hi-lo, base) if abs(r0-r1) < 1e-12 else
                      Part.makeCone(r0, r1, hi-lo, base))
    result = pieces[0]
    for shape in pieces[1:]:
        result = result.fuse(shape)
    return result


def functional_checks(doc, spec, p):
    shapes = {obj.SourceBody: native.motion.world_shape(obj) for obj in native.objects(doc)}
    glass = shapes['Vessel']
    void = clear_space(spec, p)
    expected_volume = model.cavity_volume_ml(spec, p)*1000
    overlap = glass.common(void).Volume
    checks = [{'id': 'real_clear_interior', 'glass_overlap_mm3': overlap,
               'volume_mm3': void.Volume, 'analytic_volume_mm3': expected_volume,
               'passed': overlap < 1e-5 and abs(void.Volume-expected_volume) < 1e-5}]
    mouth = model.interfaces(spec, p)['mouth']
    probe = Part.makeCylinder(mouth['clear_diameter_mm']*.4, 5,
                              App.Vector(0, 0, p['height']-.5))
    glass_obstruction = glass.common(probe).Volume
    obstruction = sum(shape.common(probe).Volume for shape in shapes.values())
    opened = spec['state'] == 'open'
    checks.append({'id': 'mouth_access_matches_configuration', 'glass_obstruction_mm3': glass_obstruction,
                   'all_parts_obstruction_mm3': obstruction, 'accessible': mouth['accessible'],
                   'passed': glass_obstruction < 1e-5 and mouth['accessible'] == opened
                             and (obstruction < 1e-5 if opened else obstruction > 1e-3)})
    family = spec['item']['family']
    if family == 'funnel':
        axis = Part.makeCylinder(p['outlet_radius']*.8, p['height']+2, App.Vector(0, 0, -1))
        blocked = glass.common(axis).Volume
        checks.append({'id': 'continuous_inlet_to_outlet_bore', 'obstruction_mm3': blocked,
                       'passed': blocked < 1e-5})
    else:
        bottom_line = Part.makeLine(App.Vector(0, 0, -1), App.Vector(0, 0, p['bottom']/2))
        bottom_length = glass.common(bottom_line).Length
        checks.append({'id': 'closed_glass_bottom', 'material_length_mm': bottom_length,
                       'passed': bottom_length > p['bottom']*.4})
        nominal = spec['item']['nominal_volume_ml']
        fill_z = model.fill_height_mm(spec, p, nominal)
        fill = void.common(Part.makeCylinder(p['outer_radius']+1, fill_z, App.Vector()))
        checks.append({'id': 'nominal_volume_fits_clear_space', 'fill_height_mm': fill_z,
                       'native_volume_ml': fill.Volume/1000, 'nominal_volume_ml': nominal,
                       'passed': abs(fill.Volume/1000-nominal) < 1e-6})
        if family in {'beaker','measuring_cylinder'}:
            probe = Part.makeCylinder(p['wall']*.1, p['spout_length']+p['wall']+5,
                                      App.Vector(p['inner_radius']-3, 0, p['height']-p['wall']*.25),
                                      App.Vector(1, 0, 0))
            blocked = glass.common(probe).Volume
            checks.append({'id': 'real_open_pour_channel', 'obstruction_mm3': blocked,
                           'passed': blocked < 1e-5})
            if family=='measuring_cylinder':
                foot = glass.common(Part.makeBox(2*p['base_radius']+2,2*p['base_radius']+2,p['base_height']/2,
                                                 App.Vector(-p['base_radius']-1,-p['base_radius']-1,0)))
                expected = 3*math.sqrt(3)*p['base_radius']**2/2*p['base_height']/2
                checks.append({'id':'hexagonal_glass_foot','native_volume_mm3':foot.Volume,
                               'passed':abs(foot.Volume-expected)<1e-5})
        else:
            overlap = glass.common(shapes['Closure']).Volume
            checks.append({'id': 'separate_closure_without_glass_penetration', 'overlap_mm3': overlap,
                           'passed': overlap < 1e-5})
            if opened:
                bb = shapes['Closure'].BoundBox
                checks.append({'id': 'removed_closure_parked_beside_vessel', 'bottom_mm': bb.ZMin,
                               'passed': abs(bb.ZMin) < 1e-7 and bb.XMin > p['outer_radius']})
    ink = [s for name,s in shapes.items() if name.startswith('MarkerInk')]
    if ink:
        inside = sum(shape.common(void).Volume for shape in ink)
        checks.append({'id':'marker_ink_keeps_interior_clear','stroke_count':len(ink),
                       'interior_overlap_mm3':inside,'passed':inside<1e-5})
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path, help='Generated item/configuration descriptor')
    parser.add_argument('output', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--compare-step', type=Path, help='Optional independent cross-CAD comparison only')
    args = parser.parse_args()
    catalog = model.load()
    case = json.loads(args.case.read_text())
    if case['kind'] == 'overview':
        spec, source, placements = model.overview(catalog)
        p = {}
        class Provider:
            ROOT = model.ROOT
            SOURCE = model.SOURCE
            digest = staticmethod(model.digest)
            evaluate = staticmethod(model.evaluate)
            expanded = staticmethod(lambda spec, p: source)
            pose = staticmethod(model.pose)
        native.model = Provider
    else:
        spec = model.materialize(catalog, case['item'], case['state'], overrides=case.get('overrides'),label=case.get('marker_label'))
        p = model.parameters(spec)
        source = model.expanded(spec, p)
        placements = None
        native.model = model
    doc = native.build(spec, p, args.output)
    geometry = native.measurements(doc)
    checks = [] if placements is not None else functional_checks(doc, spec, p)
    interference = native.interference(doc)
    exact = native.step_check(doc, args.compare_step) if args.compare_step else None
    interfaces = model.interfaces(spec, p) if placements is None else None
    for key, value in [('Configuration', spec.get('state', 'derived_overview')),
                       ('InterfacesJSON', json.dumps(interfaces)),
                       ('MarkerLabelJSON',json.dumps(spec.get('label'))),
                       ('UpdatePolicy', 'Regenerate geometry and semantic references from the shared source after edits')]:
        doc.Controller.addProperty('App::PropertyString', key, 'Glassware')
        setattr(doc.Controller, key, value)
        doc.Controller.setEditorMode(key, 1)
    if placements is None:
        for name, frame in interfaces.items():
            obj = doc.addObject('App::Part', 'Interface_'+name)
            obj.Label = name
            x, z = App.Vector(*frame['x_axis']), App.Vector(*frame['z_axis'])
            obj.Placement = App.Placement(App.Vector(*frame['origin_mm']), App.Rotation(x, z.cross(x), z, 'ZXY'))
    doc.recompute()
    doc.save()
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(args.output))
    doc.recompute()
    reopened = native.measurements(doc)
    reopen_ok = (len(reopened) == len(geometry)
                 and all(b['valid'] and b['solid_count'] == 1 for b in reopened)
                 and all(math.dist(a['world_center_of_mass_mm'], b['world_center_of_mass_mm']) < 1e-7
                         for a, b in zip(geometry, reopened)))
    report = {'passed': (all(b['valid'] and b['solid_count'] == 1 for b in geometry)
                         and all(c['passed'] for c in checks) and interference['passed']
                         and (exact is None or all(c['passed'] for c in exact)) and reopen_ok),
              'geometry': geometry, 'functional_checks': checks, 'interfaces': interfaces,
              'interference': interference, 'solidcraft_step_xor': exact,
              'reopened': {'passed': reopen_ok}, 'freecad_version': App.Version(),
              'backend': 'Native expression-driven profiles, revolutions and booleans; no imported source geometry'}
    args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    App.closeDocument(doc.Name)
    print(json.dumps({'case': spec['id'], 'passed': report['passed'],
                      'failed_checks': [c['id'] for c in checks if not c['passed']]}), flush=True)
    if not report['passed']:
        raise AssertionError('Native glassware checks failed: '+str(args.report))


if __name__ == '__main__':
    # FreeCAD initializes __main__; retain this adapter's globals in its module.
    import build_lab_glassware_freecad as adapter
    adapter.main()
