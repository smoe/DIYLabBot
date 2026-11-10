"""Native FreeCAD static review of CF01 and the two-arm analytical station."""
import json
from pathlib import Path
import sys

import FreeCAD as App

import analytics_concept as model
import assembly_model as assembly
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import instrument_concept as instruments
import robot_spec as robot
import synthetic_workspace as workspace
import tip_collector_model as collector
from tube_carrier_model import numeric_shape
from build_synthetic_lab_scene_freecad import placement, primitive

sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion
from persist_station_view import persist


def main(context_path):
    context = model.read(context_path)
    out, cad = Path(context['out']), Path(context['cad'])
    spec, spatial = model.load()
    states = context['arm_states']
    original = model.read(model.ROOT/'cad/synthetic-lab-scene/shared-build-report.json')
    if not original['passed'] or original['workspace_sha256'] != spec['context']['workspace']['source_sha256']:
        raise ValueError('Current checked native FreeCAD CF01 context required')
    for source, checksum in original['source_files_sha256'].items():
        if robot.digest(model.ROOT/source) != checksum:
            raise ValueError('Context geometry source changed: '+source)
    core = next(s for s in original['snapshots'] if s['time_s'] == spec['context']['time_s'])
    if robot.digest(model.ROOT/core['files']['freecad']) != core['artifact_sha256']['freecad']:
        raise ValueError('Context native artifact changed')
    records = []

    def add(identity, name, shape, look, **meta):
        records.append({'instance': identity, 'name': name, 'shape': shape, 'appearance': look, **meta})

    cf_scene = pickup.load()
    station = cf.load()
    cf_meta = {b['id']: b for b in cf.expanded(station, cf.parameters(station))['bodies']}
    arm_styles = robot.appearances(pickup.arm_source(cf_scene))
    upstream = App.openDocument(str(model.ROOT/core['files']['freecad']))
    for obj in motion.features(upstream):
        identity = obj.LayoutInstance
        if identity not in {'Arm', 'CF01', 'Rack', 'BenchSurface'}:
            continue
        name = obj.SourceBody
        if name.startswith('Arm.'):
            group = next(b['group'] for b in context['core_manifest'] if b['id'] == name).removeprefix('Arm.')
            color, opacity = motion.source_color(arm_styles, name.removeprefix('Arm.'), group)
            look = {'color': '#'+''.join('%02x'%round(v*255) for v in color), 'opacity': opacity}
        elif identity == 'CF01':
            look = cf_meta[name]['appearance']
        else:
            look = {'color': '#61b99a' if identity == 'Rack' else '#d5a03a', 'opacity': 1}
            if identity == 'BenchSurface':
                look = workspace.load()['bench']['bodies'][0]['appearance']
        add(identity, name, motion.world_shape(obj), look)
    App.closeDocument(upstream.Name)
    arm_item = next(v for v in spatial['devices'].values() if v['asset'] == 'arm')
    source = assembly.load_instance(robot, arm_item['source'], arm_item.get('overrides'))
    path = assembly.resolve_artifact({**arm_item['source'], 'report': 'exports/generated/build-report.json'})
    upstream = App.openDocument(str(path))
    for name, value in arm_item['overrides'].items():
        setattr(upstream.ModelParameters, name, value)
    upstream.recompute()
    home = robot.forward(source)
    arm_records = []
    for obj in motion.features(upstream):
        if getattr(obj, 'ModelRole', '') == 'viewing_cone':
            continue
        shape = motion.world_shape(obj)
        shape.Placement = placement(robot.inverse(home[obj.RigidLink])).multiply(shape.Placement)
        color, opacity = motion.source_color(robot.appearances(source), obj.SourceBody, obj.RigidLink)
        arm_records.append((obj.SourceBody, obj.RigidLink, shape,
                            {'color': '#'+''.join('%02x'%round(v*255) for v in color), 'opacity': opacity}))
    App.closeDocument(upstream.Name)
    for identity, state in states.items():
        for name, link, baseline, look in arm_records:
            shape = baseline.copy()
            shape.Placement = placement(state['world_links'][link]).multiply(shape.Placement)
            add(identity, identity+'.'+name, shape, look, arm=identity, link=link)
    bench = spatial['bench']
    add('AnalyticsBench', 'AnalyticsBench', primitive(numeric_shape(bench['operations'][0]['shape'], {})), bench['bodies'][0]['appearance'])

    def add_parts(identity, parts, matrix, **meta):
        for part in parts:
            shape = primitive(part['shape'])
            for addition in part.get('additions', []):
                shape = shape.fuse(primitive(addition))
            for cut in part.get('cuts', []):
                shape = shape.cut(primitive(cut))
            shape.Placement = placement(matrix).multiply(shape.Placement)
            add(identity, identity+'.'+part['id'], shape, part['appearance'], **meta)

    for item in spatial['devices'].values():
        if item['asset'] == 'arm':
            continue
        if 'case' in item['source']:
            parts, _ = model.kit_parts(model.kit_load(assembly.validate_reference(item['source'])), item['source']['case'])
            add_parts(item['id'], parts, item['matrix'])
        elif item['asset'] in {'nanodrop', 'qubit'}:
            source = instruments.load(assembly.validate_reference(item['source']))
            path = assembly.resolve_artifact({**item['source'], 'report': 'cad/'+source['family']+'/shared-build-report.json'})
            upstream = App.openDocument(str(path))
            styles = {b['id']: b['appearance'] for b in instruments.expanded(source, instruments.parameters(source))['bodies']}
            for obj in motion.features(upstream):
                shape = motion.world_shape(obj)
                shape.Placement = placement(item['matrix']).multiply(shape.Placement)
                add(item['id'], item['id']+'.'+obj.SourceBody, shape, styles[obj.SourceBody])
            App.closeDocument(upstream.Name)
        elif item['asset'] == 'waste':
            from build_tip_collector_freecad import build
            source = collector.load(assembly.validate_reference(item['source']))
            p = collector.parameters(source)
            upstream = build(source, p, cad/'T01_Source.FCStd')
            styles = {b['id']: b['appearance'] for b in collector.expanded(source, p)['bodies']}
            for obj in motion.features(upstream):
                shape = motion.world_shape(obj)
                shape.Placement = placement(item['matrix']).multiply(shape.Placement)
                add(item['id'], item['id']+'.'+obj.SourceBody, shape, styles[obj.SourceBody])
            App.closeDocument(upstream.Name)
    for identity, task in spec['arm_tasks'].items():
        state = states[identity]
        if task['role'] == 'pipetting':
            parts, _ = model.kit_parts(model.kit_load(assembly.validate_reference(task['tool'])), task['tool']['case'])
            add_parts(identity+'Tool', parts, state['flange_matrix'], tool_for=identity)
        else:
            parts = pickup.gripper_parts(cf_scene, cf.parameters(station))
            for part in parts:
                part['appearance'] = {'color': '#d5a03a', 'opacity': 1}
                matrix = state['tcp_matrix']
                if part['group'].startswith('Finger'):
                    sign = -1 if part['group'] == 'FingerLeft' else 1
                    matrix = robot.multiply(matrix, workspace.pose([sign*cf_scene['gripper']['open_gap_mm']/2, 0, 0], 0))
                add_parts(identity+'Tool', [part], matrix, tool_for=identity)
    doc = App.newDocument('TwoArmAnalytics')
    metrics, geometry = {}, []
    for r in records:
        obj = doc.addObject('Part::Feature', r['name'].replace('.', '_'))
        obj.Label = r['name']
        obj.Shape = r['shape']
        for key, value in [('SourceBody', r['name']), ('LayoutInstance', r['instance'])]:
            obj.addProperty('App::PropertyString', key, 'Source')
            setattr(obj, key, value)
        shape, bounds = r['shape'], r['shape'].BoundBox
        r['bbox'] = {'min': [bounds.XMin, bounds.YMin, bounds.ZMin], 'max': [bounds.XMax, bounds.YMax, bounds.ZMax]}
        geometry.append({'body': r['name'], 'bbox': r['bbox']})
        metrics.setdefault(r['instance'], []).append({'volume_mm3': shape.Volume, 'closed': shape.isValid(),
            'center_of_mass': [sum(s.CenterOfMass[i]*s.Volume for s in shape.Solids)/shape.Volume for i in range(3)], 'bbox': r['bbox']})
    metrics = {i: model.scene_model.instance_metrics(b) for i, b in metrics.items()}
    indices = {link['id']: i for i, link in enumerate(robot.load()['links'])}
    collisions, exact = [], 0
    for i, a in enumerate(records):
        for b in records[i+1:]:
            if a['instance'] == b['instance']:
                if a.get('arm') and a.get('link') and b.get('link') and abs(indices[a['link']]-indices[b['link']]) > 1:
                    pass
                else:
                    continue
            if not (a['instance'].startswith('QC.') or b['instance'].startswith('QC.') or 'AnalyticsBench' in {a['instance'], b['instance']}):
                continue
            if any(x.get('tool_for') == y.get('arm') and y.get('link') == 'L6_BareFlange' for x, y in [(a, b), (b, a)]):
                continue
            if not all(a['bbox']['min'][j] < b['bbox']['max'][j]-1e-7 and b['bbox']['min'][j] < a['bbox']['max'][j]-1e-7 for j in range(3)):
                continue
            exact += 1
            volume = a['shape'].common(b['shape']).Volume
            if volume > 1e-3:
                collisions.append({'a': a['name'], 'b': b['name'], 'volume_mm3': volume})
    supports = []
    bank = metrics['AnalyticsBench']['bbox']
    for item in spatial['devices'].values():
        if item['asset'] == 'arm':
            continue
        bounds = metrics[item['id']]['bbox']
        margin = min(*[bounds['min'][i]-bank['min'][i] for i in (0, 1)], *[bank['max'][i]-bounds['max'][i] for i in (0, 1)])
        supports.append({'instance': item['id'], 'edge_margin_mm': margin, 'passed': margin >= 0 and abs(bounds['min'][2]) < 1e-6})
    path = cad/'TwoArmAnalytics.FCStd'
    doc.recompute()
    doc.saveAs(str(path))
    styles = {'bodies': [{'id': r['name'], 'appearance': r['appearance']} for r in records]}
    presentation = persist(path, styles, geometry)
    report = {'passed': not collisions and all(s['passed'] for s in supports), 'instance_metrics': metrics,
              'collisions': collisions, 'support_checks': supports, 'exact_overlap_tests': exact,
              'freecad': str(path.relative_to(model.ROOT)), 'presentation': presentation,
              'scope': 'One static concept pose; includes tool/fixture and nonadjacent analytical-arm intersections. Internal rigid assemblies and adjacent joints excluded. No cooperative motion, dosing or mechanical qualification.'}
    (out/'freecad-validation.json').write_text(json.dumps(report, indent=2)+'\n')
    App.closeDocument(doc.Name)
    print(json.dumps({'passed': report['passed'], 'collisions': collisions, 'support_checks': supports}), flush=True)
    if not report['passed']:
        raise AssertionError('Analytical concept static geometry failed')


if __name__ == '__main__':
    import build_analytics_concept_freecad as adapter
    adapter.main(*sys.argv[1:])
