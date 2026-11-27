"""Export only the Lab 3.003 ArmC variant as checked FreeCAD and browser geometry."""

import argparse
import json
from pathlib import Path
import sys

import FreeCAD as App
import MeshPart

import build_neutral_freecad as native
import export_building_walkthrough_freecad as mesh
import lab3003_armc_variant as variant
import robot_spec as robot


def _stock_preview(path):
    report = json.loads((path / 'tr01-preview-report.json').read_text(encoding='utf-8'))
    html = path / 'index.html'
    if report.get('passed') is not True or mesh.digest(html) != report['html_sha256']:
        raise ValueError('A checked standalone TR01 walkthrough preview is required')
    data = html.read_bytes().split(b'<script id="walkthrough-data" type="application/json">', 1)
    if len(data) != 2:
        raise ValueError('The source preview needs its complete inline walkthrough data')
    return json.loads(data[1].split(b'</script>', 1)[0]), report['html_sha256']


def _check_fk(doc, arm, park):
    expected = robot.forward(arm, park)
    points = ([0, 0, 0], [17, 0, 0], [0, 23, 0], [0, 0, 31])
    error = 0.0
    for name, transform in expected.items():
        actual = native.motion.global_placement(doc.getObject(name))
        error = max(error, *((actual.multVec(App.Vector(*point))
                              - App.Vector(*robot.transform(transform, point))).Length for point in points))
    if error > 1e-6:
        raise ValueError('Native ArmC joints disagree with the shared parked forward kinematics')
    return error


def build(stock_preview, output):
    payload, stock_sha256 = _stock_preview(stock_preview)
    lab, = (lab for lab in payload['laboratories'] if lab['id'] == 'Lab3003')
    binding = variant.bind(lab)
    arm = binding['arm']
    source_pins = variant.native_pins(binding)
    output.mkdir(parents=True)
    model_path = output / 'ArmC-long.FCStd'
    mesh_path = output / 'armc-native-mesh.json'
    print('Building the bound Lab 3.003 ArmC variant', flush=True)
    doc = native.build(arm, model_path)
    try:
        park = binding['park_joints_deg']
        native.motion.set_angles(doc, park)
        doc.Label = 'Lab 3.003 · ArmC'
        for name, value in binding['dimensions_mm'].items():
            if getattr(doc.ModelParameters, name).Value != value:
                raise ValueError('Incorrect native ArmC dimension: ' + name)
        fk_error = _check_fk(doc, arm, park)
        doc.save()
        styles = robot.appearances(arm)
        matrix = binding['world_pose']
        excluded = set(binding['exclude_bodies'])
        recipe = {op['body']: link['id'] for link in robot.expanded(arm)['links']
                  for op in link['recipe'] if op['action'] == 'create'
                  and op['role'] != 'viewing_cone' and op['body'] not in excluded}
        old = {group['id']: group for group in payload['scenes']['building']['groups']
               if group['id'].startswith(binding['body_prefix'])}
        bodies = {}
        builder = mesh.MeshBuilder()
        for obj in native.motion.features(doc):
            body, role, link = obj.SourceBody, obj.ModelRole, obj.RigidLink
            if role == 'viewing_cone' or body in excluded:
                continue
            shape = native.motion.world_shape(obj)
            if (body in bodies or recipe.get(body) != link or shape.isNull() or not shape.Solids
                    or not shape.isValid() or shape.Volume <= 0):
                raise ValueError('Unexpected or invalid native ArmC body: ' + body)
            bodies[body] = {'rigid_link': link, 'role': role, 'solid_count': len(shape.Solids)}
            color, opacity = native.motion.source_color(styles, body, link)
            suffixes = ([('__Solid' + str(i), solid) for i, solid in enumerate(shape.Solids, 1)]
                        if len(shape.Solids) > 1 else [('', shape)])
            for suffix, solid in suffixes:
                source_body = body + suffix
                group_id = binding['body_prefix'] + source_body
                if group_id not in old:
                    raise ValueError('Missing checked stock ArmC body identity: ' + group_id)
                points, triangles, normals = mesh.native_face_mesh(solid, 1., .35, MeshPart)
                builder.add(group_id, [mesh.rigid_point(matrix, p) for p in points], triangles,
                            {'color': color, 'opacity': opacity}, role=role,
                            level_id=binding['level_id'], instance_id=binding['device_id'],
                            normals=[mesh.rigid_point(matrix, n, vector=True) for n in normals])
                builder.groups[-1].update(laboratory_id=binding['laboratory_id'], rigid_link=link,
                                          original_body_id=binding['device_id'] + '__' + source_body)
        if set(bodies) != set(recipe) or {group['id'] for group in builder.groups} != set(old):
            raise ValueError('The ArmC overlay must replace the complete native body set')
        mesh_path.write_text(json.dumps(builder.result(), separators=(',', ':')) + '\n', encoding='utf-8')
    finally:
        App.closeDocument(doc.Name)
    mesh.verify_pins(source_pins)
    report = {key: binding[key] for key in ('laboratory_id', 'device_id', 'body_prefix', 'dimensions_mm',
                                          'bound_pose', 'world_pose', 'park_joints_deg')}
    report.update(format=variant.NATIVE_FORMAT, passed=True, source_files_sha256=source_pins,
                  stock_html_sha256=stock_sha256, freecad_version=App.Version(), body_metadata=bodies,
                  maximum_park_fk_error_mm=fk_error,
                  artifacts={kind: {'file': path.name, 'sha256': mesh.digest(path)}
                             for kind, path in (('freecad', model_path), ('mesh', mesh_path))},
                  scope='Valid native parked arm construction and matching browser meshes. '
                        'Room support, collisions and movement are checked separately.')
    report_path = output / 'armc-native-report.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    variant.read_native(report_path, binding)
    print(report_path, flush=True)
    return report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-preview', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=mesh.project_path)
    args = parser.parse_args()
    build(args.stock_preview, args.output_dir)


if __name__ == '__main__':
    main()
