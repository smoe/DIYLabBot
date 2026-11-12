"""Render a source-referenced room highlight from a checked building model.

The native document is never saved. This changes appearance and visibility only;
it does not place the separate L01 furniture scene in the relative building.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

import building_stack as model
import tool_paths

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.building-stack-highlight/1'
COLOR = '#ef8b23'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local(root, name):
    name = Path(name)
    if name.is_absolute() or '..' in name.parts:
        raise ValueError('Building proof paths must stay inside the project')
    result = (root/name).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError('Building proof path leaves the project')
    return result


def verify(bindings, root=ROOT):
    for name, expected in bindings.items():
        if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected) or digest(local(root, name)) != expected:
            raise ValueError('Source or native artifact changed: '+name)


def checked_build(path, root=ROOT):
    path = Path(path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('The checked building report must be inside the project')
    report = json.loads(path.read_text())
    if (report.get('format') != 'solidcraftbot.building-stack-build/1' or report.get('passed') is not True
            or (report.get('solidcraft_checks') or {}).get('passed') is not True
            or report.get('backends') not in {'solidcraft', 'both'}):
        raise ValueError('A passed native SolidCraft building proof is required; run the building builder first')
    files, artifacts = report['files'], report['artifact_sha256']
    if set(files) != set(artifacts) or 'solidcraft' not in files:
        raise ValueError('Complete native artifact pins are required')
    bindings = dict(report['source_files_sha256'])
    if bindings.get(report['source']) != report['source_sha256']:
        raise ValueError('The leading building source must be pinned')
    for key, name in files.items():
        if name in bindings and bindings[name] != artifacts[key]:
            raise ValueError('Conflicting native artifact pins')
        bindings[name] = artifacts[key]
    bindings[str(path.relative_to(root.resolve()))] = digest(path)
    verify(bindings, root)
    native = local(root, files['solidcraft'])
    if native.suffix != '.sc':
        raise ValueError('A checked native SolidCraft model is required')
    return report, native, bindings


def selection(spec, p, level_id='OG3', area_id='R3_003'):
    contract = model.interfaces(spec, p)
    level = next((item for item in contract['levels'] if item['id'] == level_id), None)
    if level is None:
        raise ValueError('Unknown building level: '+level_id)
    plan = model.level_plan(spec, level_id)
    area = next((item for item in plan['areas'] if item['id'] == area_id), None)
    if area is None or area['kind'] != 'room':
        raise ValueError('A referenced room area is required: '+area_id)
    expanded = model.expanded(spec, p)
    by_source = {(body.get('level_id'), body.get('source_body_id')): body['id'] for body in expanded['bodies'] if body.get('level_id')}
    floor = by_source.get((level_id, 'Area_'+area_id))
    if floor is None or floor not in level['floor_bodies']:
        raise ValueError('The source room has no native floor body')
    wall_ids = [by_source[(level_id, 'Wall_'+ref['wall'])] for ref in area['boundary'] if (level_id, 'Wall_'+ref['wall']) in by_source]
    if not wall_ids or not set(wall_ids) <= set(level['wall_bodies']):
        raise ValueError('The referenced room requires native boundary walls')
    return {'level_id': level_id, 'level_label': level['label'], 'area_id': area_id, 'area_label': area['label'],
            'template_source': level['template_source'], 'template_id': level['template_id'], 'floor_body_id': floor,
            'wall_body_ids': wall_ids, 'roof_body_ids': contract.get('roof', {}).get('body_ids', []),
            'top_level_wall_ids': level['wall_bodies'], 'all_body_ids': [body['id'] for body in expanded['bodies']]}


def view_commands(selected):
    commands = []
    if selected['roof_body_ids']:
        commands.append({'command': 'browser.visibility', 'params': {'items': selected['roof_body_ids'], 'visible': False}})
    commands.extend([
        {'command': 'appearance.assign', 'params': {'bodies': selected['top_level_wall_ids'], 'opacity': .10}},
        {'command': 'appearance.assign', 'params': {'bodies': [selected['floor_body_id']], 'color': COLOR, 'opacity': 1.}},
        {'command': 'appearance.assign', 'params': {'bodies': selected['wall_body_ids'], 'color': COLOR, 'opacity': .32}},
    ])
    return commands


def camera(geometry, width=1800, height=1400, yaw=-.8, pitch=.67):
    if not geometry or not all(math.isfinite(v) for v in (yaw, pitch)) or not .1 <= pitch <= 1.4:
        raise ValueError('Finite camera and nonempty measured building geometry required')
    lo = [min(body['bbox']['min'][i] for body in geometry) for i in range(3)]
    hi = [max(body['bbox']['max'][i] for body in geometry) for i in range(3)]
    dx, dy, dz = [b-a for a, b in zip(lo, hi)]; fov = .6
    across = abs(math.cos(yaw))*dx+abs(math.sin(yaw))*dy
    depth = abs(math.sin(yaw))*dx+abs(math.cos(yaw))*dy
    span = max(across/(width/height), dz*math.cos(pitch)+depth*math.sin(pitch))
    return {'target': [(a+b)/2 for a, b in zip(lo, hi)], 'yaw': yaw, 'pitch': pitch,
            'distance': span*1.15/(2*math.tan(fov/2))+depth/2, 'fov': fov}


def render(args):
    report_path = Path(args.build_report).resolve(); report, native, bindings = checked_build(report_path)
    own = Path(__file__).resolve(); bindings[str(own.relative_to(ROOT))] = digest(own)
    source = local(ROOT, report['source']); spec = model.load(source); p = model.parameters(spec)
    selected = selection(spec, p, args.level, args.area)
    if spec['_source']['sha256'] != report['source_sha256']:
        raise ValueError('The highlighted room source differs from the native building proof')
    if 'freecad_validation' in report['files']:
        measured = json.loads(local(ROOT, report['files']['freecad_validation']).read_text())['geometry']
    else:
        measured = [{'body': body['name'], 'bbox': body['bbox']} for body in json.loads(local(ROOT, report['files']['solidcraft_measurements']).read_text())['bodies']]
    if {body['body'] for body in measured} != set(selected['all_body_ids']):
        raise ValueError('Measured building bodies differ from the referenced composition')
    visible = [body for body in measured if body['body'] not in set(selected['roof_body_ids'])]
    cam = camera(visible, args.width, args.height, args.yaw, args.pitch); commands = view_commands(selected)
    out = Path(args.output_dir).resolve() if args.output_dir else ROOT/'renders'/('building-highlight-'+report['source_sha256'][:12]+'-'+args.level+'-'+args.area)
    if not out.is_relative_to(ROOT) or out.exists():
        raise ValueError('Use a new output directory inside the project; existing views are preserved')
    out.mkdir(parents=True)
    command_file = out/'view.commands.json'; command_file.write_text(json.dumps({'commands': commands}, indent=2)+'\n')
    image = out/'room-highlight.png'; staged = out/'room-highlight.pending.png'
    command = [args.solidcraft_cli, 'snapshot', str(command_file), '--in', str(native), '--out', str(staged),
               '--width', str(args.width), '--height', str(args.height), '--camera', json.dumps(cam), '--no-grid', '--no-axes', '--quality', 'fine']
    verify(bindings)
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    verify(bindings)
    if not staged.is_file() or staged.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Native snapshot did not produce a PNG')
    staged.replace(image)
    result = {'format': FORMAT, 'build_report': str(report_path.relative_to(ROOT)), 'build_report_sha256': digest(report_path),
              'native_revision': report['revision'], 'native_model': str(native.relative_to(ROOT)), 'native_model_sha256': digest(native),
              'source_files_sha256': report['source_files_sha256'], 'producer': str(own.relative_to(ROOT)), 'producer_sha256': digest(own),
              'selection': selected, 'highlight_color': COLOR, 'camera': cam, 'view_commands': commands,
              'view_script': str(command_file.relative_to(ROOT)), 'view_script_sha256': digest(command_file), 'command_line': command,
              'image': str(image.relative_to(ROOT)), 'image_sha256': digest(image), 'pixels': [args.width, args.height],
              'caption': 'Orange: Labor '+selected['area_label']+' im '+selected['level_label']+'. Referenzierte F03-Raumgeometrie; keine Einpassung von L01-Möbeln.',
              'native_model_unchanged': True, 'geometry_added': False, 'l01_furnishings_instantiated': False, 'metric_scale_known': False,
              'visually_reviewed': False, 'limitations': ['Appearance and roof visibility only; building geometry and immutable CAD proof are preserved.',
                  'The room is associated with L01 semantically; no measured registration or furniture placement is demonstrated.']}
    path = out/'highlight-report.json'; path.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'image': result['image'], 'image_sha256': result['image_sha256'], 'report': str(path.relative_to(ROOT))}))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-report', default=str(ROOT/'cad/building-stack/shared-build-report.json'))
    parser.add_argument('--level', default='OG3'); parser.add_argument('--area', default='R3_003')
    parser.add_argument('--output-dir'); parser.add_argument('--width', type=int, default=1800); parser.add_argument('--height', type=int, default=1400)
    parser.add_argument('--yaw', type=float, default=-.8); parser.add_argument('--pitch', type=float, default=.67)
    parser.add_argument('--solidcraft-cli', default=None); args = parser.parse_args(argv)
    if not 400 <= args.width <= 4000 or not 400 <= args.height <= 4000:
        parser.error('Native view dimensions must be 400..4000 pixels')
    tool_paths.resolve_tool_arguments(parser, args, required=('solidcraft_cli',))
    return render(args)


if __name__ == '__main__':
    main()
