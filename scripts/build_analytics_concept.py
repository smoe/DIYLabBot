"""Build and render the referenced CF01 plus two-arm analytical concept."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import analytics_concept as model
import assembly_model as assembly
from build_instrument_concepts import freecad_environment, write
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import robot_components
import robot_spec as robot
import solidcraft_vendor as vendor
import synthetic_lab_scene as scene_model
import tip_collector_model as collector
import tool_paths
from tube_carrier_model import numeric_shape


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-report', type=Path, default=model.ROOT/'exports/generated/synthetic-lab-scene-b52c199ef5ef/solidcraft-scene-validation.json')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args = parser.parse_args()
    tool_paths.resolve_tool_arguments(parser, args)
    spec, spatial = model.load()
    states = model.arm_states(spec, spatial)
    if not all(s['passed'] for s in states.values()):
        raise ValueError('Analytical arm pose is outside its source kinematics')
    revision = stem = 'two-arm-analytics-'+robot.digest(model.SOURCE)[:12]
    index = 1
    while (model.ROOT/'cad/generated'/revision).exists():
        index += 1
        revision = stem+'-r'+str(index)
    out, cad, renders = [model.ROOT/top/revision for top in ['exports/generated', 'cad/generated', 'renders']]
    for directory in [out, cad, renders]:
        directory.mkdir(parents=True)
    source_paths = model.source_dependencies()+[Path(__file__), model.ROOT/'scripts/analytics_concept.py',
        model.ROOT/'scripts/build_analytics_concept_freecad.py', model.ROOT/'model/two-arm-analytics.schema.json',
        model.ROOT/'model/analytics-tools.schema.json']
    hashes = {str(p.relative_to(model.ROOT)): robot.digest(p) for p in source_paths}
    core = model.read(args.core_report)
    if not core['passed'] or core['freecad_required']:
        raise ValueError('Checked independent native SolidCraft CF01 context required')
    for file, checksum in {**core['source_files_sha256'], **core['artifact_sha256']}.items():
        if file in core['source_files_sha256'] and robot.digest(model.ROOT/file) != checksum:
            if file not in {'model/synthetic-cf01-workspace.shared.json', 'model/equipment/cf01-workspace.json', 'model/centrifuge-cf01.robot-pickup.shared.json'}:
                raise ValueError('Context source changed: '+file)
        elif file in core['artifact_sha256'] and robot.digest(model.ROOT/file) != checksum:
            raise ValueError('Context artifact changed: '+file)
    scene = pickup.load()
    data = pickup.trajectory(scene)
    equivalence = scene_model.verify_core_geometry(core, scene, data, [('Grasp', 21.5), ('RackReleased', 60)])
    library = robot_components.library(pickup.arm_source(scene))
    sections = {}
    for part in core['vendor_exterior']['parts']:
        output = part['output']
        if robot.digest(output['step']) != output['sha256']:
            raise ValueError('Checked vendor exterior changed')
        sections[str(model.ROOT/library['parts'][part['part']]['sections']['housing']['step'])] = output
    context = {'revision': revision, 'out': str(out), 'cad': str(cad), 'arm_states': states,
               'core_manifest': core['body_manifest'], 'source_hashes': hashes}
    write(out/'context.json', context)
    subprocess.run([args.freecad_python, str(model.ROOT/'scripts/build_analytics_concept_freecad.py'), str(out/'context.json')],
                   check=True, cwd=model.ROOT, env=freecad_environment(args.freecad_python))
    native = model.read(out/'freecad-validation.json')
    manifest = []
    for body in core['body_manifest']:
        identity = ('Arm' if body['asset'] == 'arm' or body['group'] in {'Tool', 'FingerLeft', 'FingerRight'}
                    else 'Rack' if body['group'] == 'Rack' else 'BenchSurface' if body['group'] == 'Scene' else 'CF01')
        manifest.append({'instance': identity, 'source_body': body['id'], 'names': body['names']})
    commands = []

    def append(pair):
        command_items, body_items = pair
        commands.extend(command_items)
        manifest.extend(body_items)

    for identity, state in states.items():
        append(model.arm_commands(spatial['devices'][identity], state, sections))
    shape = numeric_shape(spatial['bench']['operations'][0]['shape'], {})
    append(model.primitive_commands('AnalyticsBench', [{'id': 'Surface', 'shape': shape,
        'appearance': spatial['bench']['bodies'][0]['appearance']}], robot.identity()))
    for entry in scene_model.instrument_instances(spatial):
        append(scene_model.frozen_commands(entry))
    for item in spatial['devices'].values():
        if 'case' in item['source']:
            parts, _ = model.kit_parts(model.kit_load(assembly.validate_reference(item['source'])), item['source']['case'])
            append(model.primitive_commands(item['id'], parts, item['matrix']))
        elif item['asset'] == 'waste':
            source = collector.load(assembly.validate_reference(item['source']))
            p = collector.parameters(source)
            expanded = collector.expanded(source, p)
            names = [b['id'] for b in expanded['bodies']]+[c['id'] for c in expanded['components']]
            extra, mapping = model.namespace(collector.solidcraft_commands(source, p), item['id'], source['parameters'], names)
            commands.extend(extra)
            manifest.extend({'instance': item['id'], 'source_body': b['id'], 'names': [mapping[b['id']]]} for b in expanded['bodies'])
            for component in expanded['components']:
                commands.append({'command': 'occurrence.move', 'params': {'occurrence': mapping[component['id']]+':1',
                    'space': 'world', 'matrix': item['matrix'], 'move_grounded': True}})
    for identity, task in spec['arm_tasks'].items():
        state = states[identity]
        if task['role'] == 'pipetting':
            parts, _ = model.kit_parts(model.kit_load(assembly.validate_reference(task['tool'])), task['tool']['case'])
            append(model.primitive_commands(identity+'Tool', parts, state['flange_matrix']))
        else:
            parts = pickup.gripper_parts(scene, cf.parameters(cf.load()))
            for group in ['Tool', 'FingerLeft', 'FingerRight']:
                selected = [p for p in parts if p['group'] == group]
                for part in selected:
                    part['appearance'] = {'color': '#d5a03a', 'opacity': 1}
                matrix = state['tcp_matrix']
                if group.startswith('Finger'):
                    offset = (-1 if group == 'FingerLeft' else 1)*scene['gripper']['open_gap_mm']/2
                    matrix = robot.multiply(matrix, model.workspace.pose([offset, 0, 0], 0))
                append(model.primitive_commands(identity+'Tool', selected, matrix, group))
    commands.append({'command': 'document.metadata.set', 'params': {'values': {'org.solidcraftbot.analytics-concept': {
        'source': str(model.SOURCE.relative_to(model.ROOT)), 'source_sha256': robot.digest(model.SOURCE),
        'representation': 'Static concept; three referenced six-axis arms, conceptual pipette and dilution fixtures; no liquid handling execution'}}}})
    core_snapshot = next(s for s in core['snapshots'] if s['time_s'] == spec['context']['time_s']) if 'time_s' in core['snapshots'][0] else next(s for s in core['snapshots'] if s['phase'] == 'Grasp')
    target = cad/'TwoArmAnalytics.sc'
    actual = vendor.run(args.solidcraft_cli, commands, out/'scene.commands.json', out/'solidcraft-validation.json',
                        **{'in': core_snapshot['solidcraft'], 'save': target})
    checks = scene_model.compare_instances(actual, native, manifest)
    if not all(c['passed'] for c in checks):
        write(out/'cross-cad-validation.json', checks)
        raise ValueError('Analytical scene cross-CAD mismatch')

    def render(item):
        name, camera = item
        subprocess.run([args.solidcraft_cli, 'snapshot', '--in', str(target), '--out', str(renders/(name+'.png')),
            '--width', '2000', '--height', '1200', '--camera', json.dumps(camera), '--no-grid', '--no-axes', '--quality', 'fine'], check=True, cwd=model.ROOT)
    cameras = [('overview', {'target': [900, -20, 160], 'yaw': -.9, 'pitch': .65, 'distance': 3500}),
               ('analytics', {'target': [1410, -40, 150], 'yaw': -.9, 'pitch': .7, 'distance': 2200})]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(render, cameras))
    hashes.update({f: robot.digest(model.ROOT/f) for f in core['source_files_sha256']})
    for source in ['cad/synthetic-lab-scene/shared-build-report.json', 'exports/generated/build-report.json',
                   'cad/nanodrop-concept/shared-build-report.json', 'cad/qubit-4-concept/shared-build-report.json',
                   'scripts/tip_collector_model.py', 'scripts/build_tip_collector_freecad.py']:
        hashes[source] = robot.digest(model.ROOT/source)
    report = {'format': 'solidcraftbot.two-arm-analytics-build/1', 'passed': True, 'revision': revision,
        'source_sha256': robot.digest(model.SOURCE), 'source_files_sha256': hashes, 'core_source_equivalence': equivalence,
        'arm_states': states, 'geometry_validation': native, 'instance_cross_cad': checks, 'body_manifest': manifest,
        'files': {'solidcraft': str(target.relative_to(model.ROOT)), 'freecad': native['freecad']},
        'artifact_sha256': {'solidcraft': robot.digest(target), 'freecad': robot.digest(model.ROOT/native['freecad'])},
        'renders': {name: str((renders/(name+'.png')).relative_to(model.ROOT)) for name, _ in cameras},
        'render_sha256': {name: robot.digest(renders/(name+'.png')) for name, _ in cameras}, 'limitations': spec['limitations']}
    write(out/'build-report.json', report)
    family = model.ROOT/'cad/two-arm-analytics'
    family.mkdir(exist_ok=True)
    write(family/'shared-build-report.json', report)
    write(family/'render-manifest.json', {'source_sha256': report['source_sha256'], 'model': report['files']['solidcraft'],
        'model_sha256': report['artifact_sha256']['solidcraft'], 'views': [{'id': name, 'path': str(renders/(name+'.png')),
        'sha256': report['render_sha256'][name]} for name, _ in cameras], 'visual_review': {'passed': False}})
    print(json.dumps({'passed': True, 'revision': revision, 'renders': report['renders']}), flush=True)


if __name__ == '__main__':
    main()
