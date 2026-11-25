"""Build the local walkthrough overlay from a certified Lab 3.003 TR01 lap."""
import argparse
from array import array
import base64
import json
import math
from pathlib import Path
import sys

import build_building_walkthrough as browser
import building_stack
import building_walkthrough
import export_building_walkthrough_freecad as mesh
import lab_layout_model as layout
import robot_spec as robot

ROOT = browser.ROOT


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def checked_file(ref):
    path = mesh.project_path(ref['file'])
    if mesh.digest(path) != ref['sha256']:
        raise ValueError('Changed lap artifact: '+str(path))
    return path


def certified_route(path, baseline):
    proof = read(path)
    if (proof.get('passed') is not True or proof.get('cover_on') is not True
            or proof['required_clearance_mm'] != 15 or proof['minimum_certified_clearance_mm'] < 15
            or not proof['floor_support']['passed'] or not proof['native_collision_clearance']['passed']
            or [p['direction'] for p in proof['direction_checks']] != ['forward', 'reverse']
            or any(not p['longitudinal']['passed'] or not p['no_stop_within_section']['passed']
                   for p in proof['direction_checks'])):
        raise ValueError('A complete 15 mm certificate including reverse docking is required')
    if proof['geometry_changes'] != {'body_ids': [], 'left_window_worktop': 'original_full_depth',
                                     'stools': 'original_rolling_stools'}:
        raise ValueError('The local lap requires the original window worktop and stool positions')
    mesh.verify_pins(proof['source_files_sha256'])
    route_path = checked_file(proof['motion_program'])
    native_path = checked_file(proof['native_model'])
    if proof['native_stock_sha256'] != baseline['native_builds']['building']['native_sha256']:
        raise ValueError('The checked route and building scene do not share the same native stock')
    program = read(route_path)
    route, = program['routes']
    if (route['duration_s'] != proof['model_duration_s'] or route['dock'] != proof['dock']
            or route['reversal'] != proof['reversal'] or route['direction_sections'] != proof['direction_sections']):
        raise ValueError('The playback points differ from the proven reverse-docking lap')
    return proof, route, native_path


def unpack(value, kind):
    result = array(kind)
    result.frombytes(base64.b64decode(value, validate=True))
    if sys.byteorder != 'little':
        result.byteswap()
    return result


def replacement_mesh(path, old_scene, lab, visual_changes):
    import FreeCAD as App
    import MeshPart
    sys.path.insert(0, str(ROOT/'scripts/freecad'))
    from solidcraftbot_freecad import world_shape

    old_groups = {group['id']: group for group in old_scene['groups']}
    tr = next(d for d in lab['device_instances'] if d['id'] == 'TR01')
    trans = lab['transform']
    room_source = read(mesh.project_path(lab['layout_source']['source']))
    instance = next(d for d in room_source['instances'] if d['id'] == 'TR01')
    provider = layout.provider('transporter')
    equipment = layout.instance_source(room_source, instance)
    cover = next(b for b in provider.expanded(equipment, provider.parameters(equipment),
                 layout.instance_variant(equipment, instance))['bodies'] if b['id'] == 'TransportCover')
    color = cover['appearance']['color']
    cover_style = {'color': [int(color[i:i+2], 16)/255 for i in (1, 3, 5)],
                   'opacity': cover['appearance']['opacity']}
    doc = App.openDocument(str(path))
    output = mesh.MeshBuilder()
    try:
        physical = {obj.Label: obj for obj in doc.Objects if obj.TypeId == 'Part::Feature'}
        replacements = {name: physical[name] for name in visual_changes}
        vehicles = {tr['body_prefix']+name.removeprefix('TR01_'): obj
                    for name, obj in physical.items() if name.startswith('TR01_')}
        cover_id = tr['body_prefix']+'TransportCover'
        if cover_id not in vehicles or len(vehicles) != 57:
            raise ValueError('The checked native vehicle must include all 57 bodies and the cover')
        expected = set(vehicles)-{cover_id}
        if expected != {k for k in old_groups if k.startswith(tr['body_prefix'])}:
            raise ValueError('Incomplete stock TR01 scene mapping')
        for name, obj in {**replacements, **vehicles}.items():
            shape = world_shape(obj)
            if shape.isNull() or not shape.isValid() or not shape.Solids:
                raise ValueError('Invalid checked native shape: '+name)
            points, triangles, normals = mesh.native_face_mesh(shape, 1., .35, MeshPart)
            group = old_groups.get(name) or {**cover_style, 'role': cover['role'], 'instance_id': 'TR01'}
            output.add(name, [mesh.rigid_point(trans, p) for p in points], triangles, group,
                       level_id=lab['level_id'], role=group['role'], instance_id=group['instance_id'],
                       normals=[mesh.rigid_point(trans, n, vector=True) for n in normals])
            output.groups[-1].update(laboratory_id=lab['id'])
        return output.result(), sorted(vehicles), cover_id
    finally:
        App.closeDocument(doc.Name)


def replace_mesh(scene, replacement):
    changed = {group['id'] for group in replacement['groups']}
    old_indices = unpack(scene['indices_base64'], 'I')
    indices = array('I')
    groups = []
    for group in scene['groups']:
        if group['id'] in changed:
            continue
        offset = group['index_start']
        groups.append({**group, 'index_start': len(indices)})
        indices.extend(old_indices[offset:offset+group['index_count']])
    next_vertex = scene['vertex_count']
    next_index = len(indices)
    indices.extend(index+next_vertex for index in unpack(replacement['indices_base64'], 'I'))
    groups.extend({**g, 'index_start': g['index_start']+next_index} for g in replacement['groups'])
    result = {**scene, 'groups': groups, 'index_count': len(indices), 'indices_base64': mesh.packed(indices),
              'native_body_count': len(groups), 'vertex_count': next_vertex+replacement['vertex_count']}
    for key in ('positions_base64', 'normals_base64'):
        values = unpack(scene[key], 'f')
        values.extend(unpack(replacement[key], 'f'))
        result[key] = mesh.packed(values)
    result.pop('native_face_count', None)
    result['scope'] = 'Local checked native overlay for Lab 3.003 and the covered TR01'
    return result


def configuration(program, lab, proof, route, body_ids, cover_id):
    stop_id = 'tr01-runde'
    boundary = set(program['isolation']['body_ids'])
    objects = []
    states = {}
    for original in program['objects']:
        obj = dict(original)
        if obj['id'].startswith(lab['id']+'.') or boundary.intersection(obj['moving_body_ids']):
            fixed = 'closed' if obj['id'].startswith(lab['id']+'.Freezer01.') else obj['reference_state']
            # Robot joints use their source reference value and are also
            # monitored through the arm session's home-state predicate.
            obj['initial_state'] = fixed
            states[obj['id']] = fixed
        objects.append(obj)
    program['objects'] = objects
    lab_stop = next(stop for stop in program['stops'] if stop['id'] == 'lab')
    entry = {**lab_stop['anchor'], 'opening': 'D3_003B'}
    building = building_stack.load(ROOT/program['scene_sources']['building']['source'])
    plan = building_stack.level_plan(building, lab['level_id'])
    eye, _ = building_walkthrough.building_camera(
        entry, plan, building_stack.parameters(building)['display_scale'],
        lab['transform'][2][3], program['settings']['eye_height_mm'])
    x, y, _ = route['points'][0]['pose_mm_rad']
    target = robot.transform(lab['transform'], [x, y, 620])
    program['stops'] = [*program['stops'], {**lab_stop, 'id': stop_id,
        'label': 'Labor 3.003 · TR01', 'eye_mm': eye, 'target_mm': target, 'anchor': entry}]
    program['default_stop'] = stop_id
    program['tr01_lap'] = {
        'stop_id': stop_id, 'scene': 'building', 'level_id': lab['level_id'],
        'laboratory_id': lab['id'], 'autoplay': True,
        'room_to_world': lab['transform'], 'body_ids': body_ids, 'cover_body_id': cover_id,
        'fixture_states': states,
        'parked_robots': [r['id'] for r in program['robots'] if r['id'].startswith(lab['id']+'.')],
        'points': route['points'], 'duration_s': route['duration_s'],
        'direction_sections': route['direction_sections'], 'reversal': route['reversal'],
        'length_mm': proof['length_mm'], 'minimum_clearance_mm': proof['required_clearance_mm'],
        'playback_rates': [1, 4, 8, 16], 'default_playback_rate': 8,
    }


def equivalent(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equivalent(value, b[key]) for key, value in a.items())
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and type(b) in (int, float):
        return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)
    return a == b


def build(baseline_dir, cert, output, *, program=None):
    baseline = read(baseline_dir/'build-report.json')
    if not baseline['passed']:
        raise ValueError('A verified native walkthrough baseline is required')
    for name, filename in (('native_mesh','native-mesh.json'), ('manifest','manifest.json')):
        if mesh.digest(baseline_dir/filename) != baseline['artifact_sha256'][name]:
            raise ValueError('Changed stock walkthrough artifact: '+filename)
    stock_ref = baseline['native_builds']['building']
    stock_report = mesh.project_path(stock_ref['report'])
    if mesh.digest(stock_report) != stock_ref['report_sha256']:
        raise ValueError('Changed native stock build report')
    stock = read(stock_report)
    # These dependencies carry the explicit Lab 3.003 delta; other native
    # building dependencies still have to match the stock scene.
    lab_delta = {
        'model/building-stack.shared.json', 'model/building-laboratories.schema.json',
        'model/building-doors.shared.json', 'model/furnishings/building-laboratories.json',
        'scripts/building_laboratories.py',
    }
    mesh.verify_pins({name: sha for name, sha in stock['source_files_sha256'].items() if name not in lab_delta})
    previous = read(baseline_dir/'manifest.json')
    proof, route, native_path = certified_route(cert, baseline)
    print('Compiling local walkthrough and fixture states', flush=True)
    if program is None:
        program = browser.add_monitor_wall(building_walkthrough.compile())
    mesh.verify_pins(program['source_files_sha256'])
    lab = next(v for v in program['laboratories'] if v['id'] == 'Lab3003')
    previous_lab = next(v for v in previous['laboratories'] if v['id'] == 'Lab3003')
    if not equivalent(lab['transform'], previous_lab['transform']):
        raise ValueError('The checked native overlay requires the same room transform')
    if not equivalent([d for d in lab['device_instances'] if d['id'] != 'TR01'],
                      [d for d in previous_lab['device_instances'] if d['id'] != 'TR01']):
        raise ValueError('Unverified changes in the stock device placement')
    tr = next(v for v in lab['device_instances'] if v['id'] == 'TR01')['bound_pose']
    dock = [tr[0][3], tr[1][3], math.degrees(math.atan2(tr[1][0], tr[0][0]))%360]
    if not all(abs(v-w) < 1e-8 for v,w in zip(dock, proof['dock']['arrival_mm_deg'])):
        raise ValueError('Dock pose differs from the certificate')
    source = read(baseline_dir/'native-mesh.json')['scenes']['building']
    print('Tessellating certified covered TR01 against the original room geometry', flush=True)
    replacements, ids, cover_id = replacement_mesh(native_path, source, lab, proof['geometry_changes']['body_ids'])
    scene = replace_mesh(source, replacements)
    isolated = {group['id'] for group in scene['groups'] if group.get('laboratory_id') == lab['id']}
    program['isolation']['body_ids'] = sorted(set(program['isolation']['body_ids']) | isolated)
    configuration(program, lab, proof, route, ids, cover_id)
    payload = {**program, 'scenes': {'building': scene}}
    output.mkdir(parents=True)
    index = output/'index.html'
    index.write_text(browser.embed_html(browser.TEMPLATE.read_text(), payload), encoding='utf-8')
    report = {'passed': True, 'html_sha256': mesh.digest(index), 'baseline_mesh_sha256': baseline['artifact_sha256']['native_mesh'],
              'certificate_sha256': mesh.digest(cert), 'native_model': proof['native_model'],
              'motion_program': proof['motion_program'], 'vehicle_bodies': ids, 'cover_body': cover_id,
              'local_view': program['default_stop'], 'time_s': route['duration_s'],
              'default_playback_rate': program['tr01_lap']['default_playback_rate'],
              'autoplay': program['tr01_lap']['autoplay'],
              'viewer_source_sha256': {str(path.relative_to(ROOT)): mesh.digest(path) for path in
                   (Path(__file__), browser.TEMPLATE, browser.SEMINAR_SCRIPT, ROOT/'scripts/walkthrough_tr01_lap.js')},
              'reversal': route['reversal'],
              'scope': 'Local covered-TR01 preview with the original worktop and the checked forward and reverse PVA knots.'}
    (output/'tr01-preview-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(index, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'certificate', 'output-dir'):
        parser.add_argument('--'+name, type=mesh.project_path, required=True)
    args = parser.parse_args()
    build(args.baseline, args.certificate, args.output_dir)


if __name__ == '__main__':
    main()
