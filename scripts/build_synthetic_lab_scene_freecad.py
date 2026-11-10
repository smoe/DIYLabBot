"""Compose a native FreeCAD scene from checked native sources and common poses."""
import json
import math
from pathlib import Path
import sys

import FreeCAD as App
import Part

import assembly_model as assembly
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import instrument_concept as instruments
import robot_spec as robot
import synthetic_lab_scene as model
import synthetic_workspace as workspace

sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion
from persist_station_view import persist


def placement(matrix):
    return App.Placement(App.Matrix(*[v for row in matrix for v in row]))


def primitive(shape):
    if shape['kind'] == 'box':
        return Part.makeBox(*shape['size'], App.Vector(*shape['origin']))
    if shape['kind'] == 'cone':
        return Part.makeCone(shape['radius'], shape['top_radius'], shape['height'], App.Vector(*shape['origin']))
    return Part.makeCylinder(shape['radius'], shape['height'], App.Vector(*shape['origin']))


def instrument_motion_validation(records, scene, data, reachability):
    """Sample the existing CF01 path and NanoDrop hinge against native bodies."""
    entries = model.instrument_instances()
    nd = next(e for e in entries if e['instance']['asset'] == 'nanodrop')
    nd_id = nd['instance']['id']
    moving = {nd_id+'.'+b['id'] for b in instruments.expanded(nd['spec'], nd['parameters'])['bodies']
              if b['component'] == 'MovingArm'}
    angles = sorted({*range(0, math.floor(nd['parameters']['max_open'])+1, 5),
                     nd['parameters']['max_open'], instruments.pose(nd['spec'], nd['parameters'])['Hinge']})

    def bounds(shape):
        b = shape.BoundBox
        return (b.XMin, b.YMin, b.ZMin), (b.XMax, b.YMax, b.ZMax)

    def lower_distance(a, b):
        return math.sqrt(sum(max(0, a[0][i]-b[1][i], b[0][i]-a[1][i])**2 for i in range(3)))

    fixed = [(r, r['shape'], bounds(r['shape'])) for r in records if r['group'] == 'FixedInstrument']
    levers = []
    for record, shape, _ in fixed:
        if record['name'] not in moving:
            continue
        local = shape.copy()
        local.Placement = placement(robot.inverse(model.component_matrix(nd, 'MovingArm'))).multiply(local.Placement)
        for angle in angles:
            variant = local.copy()
            variant.Placement = placement(model.component_matrix(nd, 'MovingArm', angle)).multiply(variant.Placement)
            levers.append((record['name'], angle, variant, bounds(variant)))
    if not levers:
        raise ValueError('Native NanoDrop lever bodies required for motion validation')
    evaluate = pickup.SceneEvaluator(scene, data)
    states = [(dict(sample), 'CF01') for sample in data['samples']]
    for check in reachability['checks']:
        if check['kind'] == 'approach':
            sample = pickup.interpolate(data['samples'], data['duration_s'])
            sample['joints_deg'] = check['joints_deg']
            states.append((sample, check['id']))
    seen, hits, exact, distances = set(), [], 0, 0
    minimum, nearest = float('inf'), None
    required = scene['checks']['minimum_robot_equipment_clearance_mm']
    for index, (sample, label) in enumerate(states):
        matrices = evaluate(sample)
        for record in records:
            if record['instance'] != 'Arm':
                continue
            matrix = matrices[record['group']]
            signature = (record['name'], tuple(round(v, 8) for row in matrix for v in row))
            if signature in seen:
                continue
            seen.add(signature)
            actual = record['shape'].copy()
            actual.Placement = placement(matrix).multiply(actual.Placement)
            box = bounds(actual)
            for other, shape, other_box in fixed:
                if lower_distance(box, other_box) > 0:
                    continue
                exact += 1
                volume = actual.common(shape).Volume
                if volume > 1e-3:
                    hits.append({'a': record['name'], 'b': other['name'], 'pose': label,
                                 'cf01_time_s': sample['time_s'], 'volume_mm3': volume})
            for name, angle, lever, lever_box in levers:
                distance = lower_distance(box, lever_box)
                method = 'aabb_lower_bound'
                if distance < required:
                    distance = actual.distToShape(lever)[0]
                    distances += 1
                    method = 'native_brep_distance'
                if distance < minimum:
                    minimum = distance
                    nearest = {'arm_body': record['name'], 'lever_body': name, 'hinge_deg': angle,
                               'pose': label, 'cf01_time_s': sample['time_s'], 'method': method}
        if index % 25 == 0:
            print(json.dumps({'instrument_motion_frame': index, 'of': len(states),
                              'exact_overlap_tests': exact, 'exact_distance_tests': distances}), flush=True)
    return {'passed': not hits and minimum >= required, 'cf01_path_samples': len(data['samples']),
            'approach_configurations': len(states)-len(data['samples']), 'nanodrop_hinge_angles_deg': angles,
            'minimum_nanodrop_lever_arm_distance_lower_bound_mm': minimum, 'nearest_pair': nearest,
            'required_lever_arm_distance_mm': required, 'collisions': hits,
            'exact_overlap_tests': exact, 'exact_distance_tests': distances,
            'scope': 'Discrete CF01 path and two approach configurations versus both instruments in their default poses; NanoDrop lever clearance also sampled from closed to maximum opening in 5 degree steps. Conservative world AABB separation proves distant pairs; native BRep distances resolve pairs below the required clearance. The reported minimum is a clearance lower bound, not the exact global minimum. No continuous swept-volume or connecting-path qualification.'}


def main(context_path):
    context = json.loads(Path(context_path).read_text())
    out, cad = Path(context['out']), Path(context['cad'])
    spatial = workspace.load()
    scene = pickup.load()
    data = json.loads((out/'trajectory.json').read_text())
    station = cf.load()
    p = cf.parameters(station)
    arm = pickup.arm_source(scene)
    # Geometry is resolved through checked build reports, never a revision path
    # in the equipment source. Both native upstream builds have shared-source CLIs.
    native_arm = assembly.resolve_artifact({'source': scene['sources']['robot'], 'report': 'exports/generated/build-report.json'})
    # Generate CF01 directly: its historical standalone report may predate the
    # LF migration. Do not rewrite that report or accept its old source hash.
    from build_centrifuge_freecad import build as build_station
    native_station = cad/'CF01_Source.FCStd'
    station_doc, _ = build_station(station, p, native_station)
    App.closeDocument(station_doc.Name)
    source_docs = []
    records = []
    styles = {}
    station_meta = {b['id']: b for b in cf.expanded(station, p)['bodies']}
    arm_styles = robot.appearances(arm)

    def add(identity, name, group, shape, look):
        records.append({'instance': identity, 'name': name, 'group': group, 'shape': shape})
        styles[name] = look

    for identity, path in [('Arm', native_arm), ('CF01', native_station)]:
        doc = App.openDocument(str(path))
        source_docs.append(doc)
        if identity == 'Arm':
            for name, value in scene.get('robot_parameter_overrides_mm', {}).items():
                setattr(doc.ModelParameters, name, value)
            doc.recompute()
            home = robot.forward(arm)
        else:
            home = {c['id']: pickup.rigid_from_cf(cf.expanded(station, p), c['id'], cf.pose(station, p))
                    for c in cf.expanded(station, p)['components']}
        for obj in motion.features(doc):
            if getattr(obj, 'ModelRole', '') == 'viewing_cone':
                continue
            name, group = obj.SourceBody, obj.RigidLink
            shape = motion.world_shape(obj)
            shape.Placement = placement(robot.inverse(home[group])).multiply(shape.Placement)
            if identity == 'Arm':
                color, opacity = motion.source_color(arm_styles, name, group)
                look = {'color': '#'+''.join('%02x'%round(v*255) for v in color), 'opacity': opacity}
                name, group = 'Arm.'+name, 'Arm.'+group
            else:
                look = station_meta[name]['appearance']
            add(identity, name, group, shape, look)
    for b in pickup.gripper_parts(scene, p)+pickup.rack_geometry(scene, p)['parts']:
        shape = primitive(b['shape'])
        for cut in b.get('cuts', []):
            shape = shape.cut(primitive(cut))
        add('Rack' if b['group'] == 'Rack' else 'Arm', b['id'], b['group'], shape,
            {'color': '#61b99a' if b['group'] == 'Rack' else '#d5a03a', 'opacity': 1})
    bench = scene['bench_surface']
    add('BenchSurface', 'BenchSurface', 'Scene', Part.makeBox(*bench['size_mm'], App.Vector(*bench['origin_mm'])), spatial['bench']['bodies'][0]['appearance'])
    for entry in model.instrument_instances(spatial):
        item, spec = entry['instance'], entry['spec']
        path = assembly.resolve_artifact({**item['source'], 'report': 'cad/'+spec['family']+'/shared-build-report.json'})
        upstream = App.openDocument(str(path))
        source_docs.append(upstream)
        # This composition currently uses each source's checked default case.
        if item.get('overrides'):
            raise ValueError('Rebuild an explicitly selected instrument case before composing overrides')
        meta = {b['id']: b for b in instruments.expanded(spec, entry['parameters'])['bodies']}
        for obj in motion.features(upstream):
            shape = motion.world_shape(obj)
            shape.Placement = placement(item['matrix']).multiply(shape.Placement)
            add(item['id'], item['id']+'.'+obj.SourceBody, 'FixedInstrument', shape, meta[obj.SourceBody]['appearance'])
    for upstream in source_docs:
        App.closeDocument(upstream.Name)
    results = []
    evaluations = [{'id': label, 'time_s': time_s} for label, time_s in context['poses']]
    evaluations.extend({'id': check['id'], 'time_s': data['duration_s'], 'joints_deg': check['joints_deg']}
                       for check in context.get('instrument_reachability', {}).get('checks', [])
                       if check['kind'] == 'approach')
    indices = {'Arm.'+link['id']: i for i, link in enumerate(arm['links'])}
    for evaluation in evaluations:
        label, time_s = evaluation['id'], evaluation['time_s']
        sample = pickup.interpolate(data['samples'], time_s)
        approach = 'joints_deg' in evaluation
        if approach:
            sample['joints_deg'] = evaluation['joints_deg']
        matrices = pickup.matrices(scene, data, sample)
        doc = App.newDocument('SyntheticLab_'+label.replace('.', '_'))
        shapes = []
        for record in records:
            shape = record['shape'].copy()
            if record['group'] != 'FixedInstrument':
                shape.Placement = placement(matrices[record['group']]).multiply(shape.Placement)
            obj = doc.addObject('Part::Feature', record['name'].replace('.', '_'))
            obj.Label = record['name']
            obj.Shape = shape
            for key, value in [('SourceBody', record['name']), ('LayoutInstance', record['instance'])]:
                obj.addProperty('App::PropertyString', key, 'Source')
                setattr(obj, key, value)
            shapes.append((record, shape))
        doc.recompute()
        metrics = {}
        for identity in {r['instance'] for r in records}:
            bodies = []
            for record, shape in shapes:
                if record['instance'] != identity:
                    continue
                bounds = shape.BoundBox
                bodies.append({'volume_mm3': shape.Volume,
                               'center_of_mass': [sum(s.CenterOfMass[i]*s.Volume for s in shape.Solids)/shape.Volume
                                                  for i in range(3)],
                               'bbox': {'min': [bounds.XMin, bounds.YMin, bounds.ZMin],
                                        'max': [bounds.XMax, bounds.YMax, bounds.ZMax]}, 'closed': shape.isValid()})
            metrics[identity] = model.instance_metrics(bodies)
        overlaps, robot_overlaps = [], []
        for i, (a, ashape) in enumerate(shapes):
            for b, bshape in shapes[i+1:]:
                added_device_pair = (a['instance'] != b['instance']
                                     and 'BenchSurface' not in {a['instance'], b['instance']}
                                     and any(r['group'] == 'FixedInstrument' for r in (a, b)))
                arm_pair = False
                if approach:
                    aa, ba = a['instance'] == 'Arm', b['instance'] == 'Arm'
                    arm_pair = aa != ba
                    if aa and ba:
                        ag, bg = a['group'] in indices, b['group'] in indices
                        arm_pair = ag and bg and abs(indices[a['group']]-indices[b['group']]) > 1
                        if ag != bg:
                            arm_pair = (a if ag else b)['group'] != 'Arm.L6_BareFlange'
                if not (added_device_pair or arm_pair):
                    continue
                if ashape.BoundBox.intersect(bshape.BoundBox):
                    volume = ashape.common(bshape).Volume
                    if volume > 1e-3:
                        hit = {'a': a['name'], 'b': b['name'], 'volume_mm3': volume}
                        if added_device_pair:
                            overlaps.append(hit)
                        if arm_pair:
                            robot_overlaps.append(hit)
        supports = []
        bank = metrics['BenchSurface']['bbox']
        for entry in model.instrument_instances(spatial):
            identity = entry['instance']['id']
            box = metrics[identity]['bbox']
            margin = min(box['min'][i]-bank['min'][i] for i in (0, 1))
            margin = min(margin, *(bank['max'][i]-box['max'][i] for i in (0, 1)))
            supports.append({'instance': identity, 'edge_margin_mm': margin,
                             'base_z_mm': box['min'][2],
                             'passed': margin >= 0 and abs(box['min'][2]-bank['max'][2]) < 1e-7})
        path = cad/('SyntheticLab_'+label+'.FCStd')
        doc.saveAs(str(path))
        geometry = [{'body': r['name'], 'bbox': {'min': [s.BoundBox.XMin, s.BoundBox.YMin, s.BoundBox.ZMin],
                                               'max': [s.BoundBox.XMax, s.BoundBox.YMax, s.BoundBox.ZMax]}}
                    for r, s in shapes]
        presentation = persist(path, {'bodies': [{'id': name, 'appearance': look} for name, look in styles.items()]}, geometry)
        valid = all(s.isValid() and s.Volume > 0 for r, s in shapes)
        results.append({'id': label, 'time_s': time_s, 'freecad': str(path.relative_to(model.ROOT)),
                        'instance_metrics': metrics, 'new_instrument_interferences': overlaps,
                        'approach_robot_interferences': robot_overlaps,
                        'support_checks': supports, 'presentation': presentation,
                        'passed': valid and not overlaps and not robot_overlaps and all(s['passed'] for s in supports)})
        App.closeDocument(doc.Name)
    (out/'freecad-scene-validation.json').write_text(json.dumps(results, indent=2)+'\n')
    motion_checks = instrument_motion_validation(records, scene, data, context['instrument_reachability'])
    (out/'instrument-motion-validation.json').write_text(json.dumps(motion_checks, indent=2)+'\n')
    print(json.dumps({'instrument_motion_validation': motion_checks}), flush=True)
    print(json.dumps([{'id': r['id'], 'passed': r['passed'], 'collisions': r['new_instrument_interferences']} for r in results]), flush=True)
    if not all(r['passed'] for r in results) or not motion_checks['passed']:
        raise AssertionError('Synthetic laboratory scene geometry failed validation')


if __name__ == '__main__':
    import build_synthetic_lab_scene_freecad as adapter
    adapter.main(*sys.argv[1:])
