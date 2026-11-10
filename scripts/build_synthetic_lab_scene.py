"""Build the five-device reference-bank scene in both CADs and render it."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from build_instrument_concepts import freecad_environment, write
import centrifuge_robot_pickup as pickup
import robot_spec as robot
import solidcraft_vendor as vendor
import synthetic_lab_scene as model
import synthetic_workspace as workspace
import tool_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-report', type=Path, help='Reuse a checked, source-current independent CF01 review build')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args = parser.parse_args()
    tool_paths.resolve_tool_arguments(parser, args)
    spatial = workspace.load()
    entries = model.instrument_instances(spatial)
    scene = pickup.load()
    data = pickup.trajectory(scene)
    stem = 'synthetic-lab-scene-'+robot.digest(workspace.SOURCE)[:12]
    revision, index = stem, 1
    while (model.ROOT/'cad/generated'/revision).exists():
        index += 1
        revision = stem+'-r'+str(index)
    out, cad, render = (model.ROOT/top/revision for top in ('exports/generated', 'cad/generated', 'renders'))
    for path in (out, cad, render):
        path.mkdir(parents=True)
    source_files = [*workspace.source_dependencies(spatial), pickup.SOURCE,
                    model.ROOT/'scripts/synthetic_lab_scene.py', Path(__file__),
                    model.ROOT/'scripts/cf01_collision_scope.py',
                    model.ROOT/'scripts/build_synthetic_lab_scene_freecad.py',
                    model.ROOT/'scripts/instrument_concept.py', model.ROOT/'scripts/build_instrument_concepts.py',
                    model.ROOT/'scripts/build_tube_carrier.py', model.ROOT/'scripts/tube_carrier_model.py',
                    model.ROOT/'scripts/assembly_model.py', model.ROOT/'scripts/freecad/persist_station_view.py',
                    model.ROOT/'scripts/freecad/persist_view.py', model.ROOT/'scripts/freecad/solidcraftbot_freecad.py']
    hashes = {str(p.relative_to(model.ROOT)): robot.digest(p) for p in source_files}
    context = {'revision': revision, 'out': str(out), 'cad': str(cad),
               'solidcraft_cli': args.solidcraft_cli, 'source_hashes': hashes,
               'poses': [['Grasp', 21.5], ['RackReleased', 60]],
               'instrument_reachability': model.instrument_reachability(scene, entries)}
    if not context['instrument_reachability']['passed']:
        raise AssertionError('Instrument reference-TCP reach failed')
    write(out/'context.json', context)
    write(out/'trajectory.json', data)
    # The existing independent SolidCraft exporter supplies the core scene and
    # vendor-part mapping. The extra instruments do not alter its motion source.
    if args.core_report:
        native_core = json.loads(args.core_report.read_text())
        if not native_core['passed'] or native_core['freecad_required']:
            raise ValueError('Source-current independent native CF01 build required')
        for file, checksum in native_core['artifact_sha256'].items():
            if robot.digest(model.ROOT/file) != checksum:
                raise ValueError('Core scene artifact changed: '+file)
        changed = {f: {'old_sha256': h, 'current_sha256': robot.digest(model.ROOT/f)}
                   for f, h in native_core['source_files_sha256'].items() if robot.digest(model.ROOT/f) != h}
        allowed = {str(workspace.SOURCE.relative_to(model.ROOT)), str(pickup.SOURCE.relative_to(model.ROOT)),
                   'model/equipment/cf01-workspace.json'}
        if set(changed)-allowed:
            raise ValueError('Core geometry source changed: '+str(sorted(set(changed)-allowed)))
        if changed:
            native_core['source_equivalence'] = {**model.verify_core_geometry(native_core, scene, data, context['poses']),
                                                  'composition_source_changes': changed}
        write(out/'solidcraft-scene-validation.json', native_core)
        hashes[str(args.core_report.resolve().relative_to(model.ROOT))] = robot.digest(args.core_report)
    else:
        subprocess.run([sys.executable, str(model.ROOT/'scripts/export_centrifuge_robot_pickup_solidcraft.py'),
                        '--context', str(out/'context.json'), '--solidcraft-cli', args.solidcraft_cli],
                       check=True, cwd=model.ROOT)
    subprocess.run([args.freecad_python, str(model.ROOT/'scripts/build_synthetic_lab_scene_freecad.py'),
                    str(out/'context.json')], check=True, cwd=model.ROOT,
                   env=freecad_environment(args.freecad_python))
    native_core = json.loads((out/'solidcraft-scene-validation.json').read_text())
    native_freecad = json.loads((out/'freecad-scene-validation.json').read_text())
    instrument_motion = json.loads((out/'instrument-motion-validation.json').read_text())
    approach_checks = [s for s in native_freecad if s['id'] not in {p[0] for p in context['poses']}]
    manifest = []
    for body in native_core['body_manifest']:
        identity = ('Arm' if body['asset'] == 'arm' or body['group'] in {'Tool', 'FingerLeft', 'FingerRight'}
                    else 'Rack' if body['group'] == 'Rack'
                    else 'BenchSurface' if body['group'] == 'Scene' else 'CF01')
        manifest.append({'instance': identity, 'source_body': body['id'], 'names': body['names']})
    extra_commands = []
    for entry in entries:
        commands, bodies = model.frozen_commands(entry)
        extra_commands.extend(commands)
        manifest.extend(bodies)
    snapshots = []
    for label, time_s in context['poses']:
        core = next(s for s in native_core['snapshots'] if s['phase'] == label)
        target = cad/('SyntheticLab_'+label+'.sc')
        commands = extra_commands + [{'command': 'document.metadata.set', 'params': {'values': {
            'org.solidcraftbot.synthetic-lab': {'workspace_source': str(workspace.SOURCE.relative_to(model.ROOT)),
                                             'workspace_sha256': robot.digest(workspace.SOURCE),
                                             'phase': label, 'time_s': time_s,
                                             'instrument_poses': 'Frozen source defaults; no robot or workflow coupling'}}}}]
        actual = vendor.run(args.solidcraft_cli, commands, out/(label+'.scene.commands.json'),
                            out/(label+'.scene.solidcraft.json'), **{'in': core['solidcraft'], 'save': target})
        freecad = next(s for s in native_freecad if s['id'] == label)
        checks = model.compare_instances(actual, freecad, manifest)
        snapshots.append({'id': label, 'time_s': time_s,
                          'passed': freecad['passed'] and all(c['passed'] for c in checks),
                          'instance_cross_cad': checks, 'geometry_validation': freecad,
                          'files': {'solidcraft': str(target.relative_to(model.ROOT)), 'freecad': freecad['freecad']},
                          'artifact_sha256': {'solidcraft': robot.digest(target),
                                              'freecad': robot.digest(model.ROOT/freecad['freecad'])}})
        if not snapshots[-1]['passed']:
            raise AssertionError('Composed scene cross-CAD mismatch: '+label)
    for view, snapshot, options in [
            ('overview', 'Grasp', ['--camera', json.dumps({'target': [-20, -20, 120], 'yaw': -0.8, 'pitch': 0.65, 'distance': 1750})]),
            ('top', 'RackReleased', ['--view', 'top'])]:
        path = cad/('SyntheticLab_'+snapshot+'.sc')
        subprocess.run([args.solidcraft_cli, 'snapshot', '--in', str(path), '--out', str(render/(view+'.png')),
                        '--width', '1800', '--height', '1200', '--no-grid', '--no-axes', '--quality', 'fine', *options],
                       check=True, cwd=model.ROOT)
    hashes.update({f: robot.digest(model.ROOT/f) for f in native_core['source_files_sha256']})
    for file in ['exports/generated/build-report.json', 'scripts/build_centrifuge_freecad.py',
                 *['cad/'+e['spec']['family']+'/shared-build-report.json' for e in entries]]:
        hashes[file] = robot.digest(model.ROOT/file)
    from cf01_collision_scope import trajectory_signature
    report = {'format': 'solidcraftbot.synthetic-lab-scene/1',
              'cf01_trajectory': {'path': str((out/'trajectory.json').relative_to(model.ROOT)),
                                  'sha256': robot.digest(out/'trajectory.json'),
                                  'semantic_sha256': trajectory_signature(data)},
              'passed': all(s['passed'] for s in snapshots+approach_checks) and context['instrument_reachability']['passed'] and instrument_motion['passed'],
              'workspace_source': str(workspace.SOURCE.relative_to(model.ROOT)),
              'workspace_sha256': robot.digest(workspace.SOURCE), 'source_files_sha256': hashes,
              'core_source_equivalence': native_core.get('source_equivalence'),
              'source_bindings': {e['instance']['id']: e['instance']['source'] for e in entries},
              'instance_poses': {i: d['matrix'] for i, d in spatial['devices'].items()},
              'instrument_reachability': context['instrument_reachability'],
              'instrument_motion_validation': instrument_motion,
              'approach_geometry_checks': [{**check, 'artifact_sha256': robot.digest(model.ROOT/check['freecad'])}
                                           for check in approach_checks],
              'snapshots': snapshots, 'body_manifest': manifest,
              'renders': {v: str((render/(v+'.png')).relative_to(model.ROOT)) for v in ('overview', 'top')},
              'render_sha256': {v: robot.digest(render/(v+'.png')) for v in ('overview', 'top')},
              'limitations': ['Independent illustrative instrument dimensions; no manufacturer-fit or measurement qualification',
                              'Two static CF01/arm review poses; new instruments checked against all other device bodies in those poses',
                              f"NanoDrop/Qubit source-defined sample points reached by a vertical reference TCP; FreeCAD checks the two approaches {context['instrument_reachability']['approach_height_mm']} mm above them against equipment, bench and nonadjacent arm links",
                              'Existing CF01 path sampled against both instruments; NanoDrop lever clearance additionally checked at 5 degree hinge steps through its source-defined range',
                              'No measurement tool, continuous connecting robot path, hardware, network or workflow-actuation coupling',
                              'FreeCAD and SolidCraft resolve their own native geometry from the shared sources; no cross-CAD build dependency',
                              'Native FreeCAD regenerates CF01 and resolves checked arm/instrument builds; build the arm and instruments first on a fresh checkout',
                              'Vendor split case pieces are summed in SolidCraft and Boolean-unioned in FreeCAD; comparison tolerances retain original seam differences']}
    write(out/'build-report.json', report)
    write(model.ROOT/'cad/synthetic-lab-scene/shared-build-report.json', report)
    print(json.dumps({'passed': report['passed'], 'revision': revision, 'images': report['renders']}), flush=True)


if __name__ == '__main__':
    main()
