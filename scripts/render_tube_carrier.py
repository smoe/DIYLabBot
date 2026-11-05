"""Render H01's checked native SolidCraft model and record exact model provenance."""
from pathlib import Path
import argparse
import json
import math
import shutil
import subprocess
import inspect
import tube_carrier_model as model


def main(plan_provider=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--solidcraft-cli', default=shutil.which('solidcraft-cli') or 'solidcraft-cli')
    args = parser.parse_args(); spec = model.load(); directory = model.ROOT/'cad'/spec.get('family', 'tube-carrier-h01')
    report_path = directory/'shared-build-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if not report['passed'] or report['source_sha256'] != model.digest(model.SOURCE):
        raise ValueError('Rebuild and validate the current source before rendering')
    path = (model.ROOT/report['cases'][0]['files']['solidcraft']).resolve()
    if not path.is_relative_to(model.ROOT): raise ValueError('Model must stay in project')
    p = model.parameters(spec)
    health_commands = directory/'health.commands.json'; health_raw = directory/'health-raw.json'
    health_commands.write_text(json.dumps({'commands': [
        {'command': 'document.inspect', 'params': {'measure': False, 'sketches': False}},
        {'command': 'joint.inspect', 'params': {}}]}, indent=2)+'\n', encoding='utf-8')
    subprocess.run([args.solidcraft_cli, 'run', str(health_commands), '--in', str(path), '--results',
                    '--json-out', str(health_raw), '--quiet'], check=True, cwd=model.ROOT)
    document, assembly = json.loads(health_raw.read_text(encoding='utf-8'))
    problems = [f for f in document['timeline'] if f.get('error') or f.get('warning')]
    floating = [s for s in document['sketches'] if s.get('dof') != 0]
    joints = assembly['joints']
    bad_joints = [j for j in joints if j.get('errors') or j.get('conflicts') or not j['a'].get('resolves') or not j['b'].get('resolves')]
    health = {'passed': not problems and not floating and not bad_joints and len(joints) == len(model.expanded(spec, p)['joints']),
        'model': str(path.relative_to(model.ROOT)).replace('\\', '/'), 'model_sha256': model.digest(path),
        'source_sha256': model.digest(model.SOURCE), 'timeline_problems': problems,
        'sketch_degrees_of_freedom': [{'name': s['name'], 'dof': s['dof']} for s in document['sketches']],
        'joints': joints, 'body_count': len(document['bodies'])}
    health_path = directory/'model-health.json'; health_path.write_text(json.dumps(health, indent=2)+'\n', encoding='utf-8')
    if not health['passed']: raise AssertionError('SolidCraft timeline/sketch/joint health failed')
    views = [
        {'id': 'overview', 'path': 'carrier-overview.png', 'pose': spec['display_pose'], 'width': 1300, 'height': 850,
         'camera': {'target': [13.5, -22.5, 23], 'yaw': -math.pi/4, 'pitch': 0.6154797086703874, 'distance': 220, 'fov': 0}},
        {'id': 'cutaway', 'path': 'carrier-cutaway.png', 'pose': 'both_docked_locked', 'width': 1300, 'height': 740,
         'camera': {'target': [0, 0, 24], 'yaw': 0, 'pitch': 0.08, 'distance': 105, 'fov': 0},
         'section': {'plane': 'XZ', 'at_mm': 0, 'flip': True}, 'gripper_hidden': True}
    ]
    if plan_provider: views = plan_provider(spec, p)
    elif hasattr(model, 'render_plan'): views = model.render_plan(spec, p)
    source = model.expanded(spec, p)
    for view in views:
        values=model.pose(spec,p,view['pose'])
        commands = model.drive_commands(spec,p,values) if hasattr(model,'drive_commands') else [{'command': 'joint.drive', 'params': {'joint': name, 'value': value, 'quiet': True}}
                    for name, value in values.items()]
        commands += [{'command': 'joint.solve', 'params': {}}, {'command': 'inspect.section', 'params': {'clear': True}}]
        hidden = [b['id'] for b in source['bodies'] if b['role'] in view.get('hide_roles', []) or
                  (view.get('variant') and not b['id'].startswith(view['variant']+'_'))]
        if view.get('gripper_hidden'): hidden.append('V20_GripperEnvelope')
        if hidden: commands.append({'command': 'browser.visibility', 'params': {'items': hidden, 'visible': False}})
        if 'section' in view:
            s = view['section']; commands.append({'command': 'inspect.section', 'params': {'plane': s['plane'], 'at': s['at_mm'], 'flip': s['flip'], 'hatch': True}})
        script = directory/(view['id']+'.commands.json')
        script.write_text(json.dumps({'commands': commands}, indent=2)+'\n', encoding='utf-8')
        command = [args.solidcraft_cli, 'snapshot', str(script), '--in', str(path)]
        output = directory/view['path']
        command += ['--out', str(output), '--width', str(view['width']), '--height', str(view['height']),
                    '--camera', json.dumps(view['camera']), '--no-grid', '--no-axes']
        run = subprocess.run(command, check=True, cwd=model.ROOT, capture_output=True, text=True)
        view.update(sha256=model.digest(output), renderer_result=json.loads(run.stdout), command_file=script.name, command_sha256=model.digest(script))
        print('Rendered '+str(output.relative_to(model.ROOT)), flush=True)
    manifest = {'format': 'solidcraftbot.model-renders/1', 'source_sha256': model.digest(model.SOURCE),
        'source': str(model.SOURCE.relative_to(model.ROOT)).replace('\\', '/'),
        'model': str(path.relative_to(model.ROOT)).replace('\\', '/'), 'model_sha256': model.digest(path),
        'validation_report_sha256': model.digest(report_path), 'render_generator_sha256': model.digest(__file__),
        'render_plan_source': str(Path(inspect.getsourcefile(plan_provider or model.render_plan)).relative_to(model.ROOT)).replace('\\', '/') if plan_provider or hasattr(model, 'render_plan') else None,
        'render_plan_sha256': model.digest(inspect.getsourcefile(plan_provider or model.render_plan)) if plan_provider or hasattr(model, 'render_plan') else None,
        'model_health_sha256': model.digest(health_path),
        'views': views,
        'visual_review': 'Pending visual inspection; generation alone is not visual QA',
        'note': 'Native SolidCraft model renders through CLI; MCP server did not permit this project path. FreeCAD GUI rendering not verified.'}
    (directory/'render-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__': main()
