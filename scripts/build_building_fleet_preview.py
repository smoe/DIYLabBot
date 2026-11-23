"""Build an explicitly experimental, lossless prefix of an interrupted BF01 run.

This separate entry point never produces or substitutes a full-program native
or independent-export proof. The strict completed-demo builder stays unchanged.
"""
import argparse
import base64
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import build_building_fleet_demo as browser
import building_fleet_model as model
import export_building_walkthrough_freecad as native
from export_building_fleet_vehicle_freecad import checked_camera_report

ROOT = browser.ROOT
PREVIEW_FORMAT = 'solidcraftbot.building-fleet-experimental-preview/1'
QUALIFICATION = dict.fromkeys(('full_mission_coverage_verified',
    'native_full_program_verified', 'independent_export_verified',
    'hardware_or_real_safety_qualified'), False)


def artifact(path):
    path = native.project_path(path)
    return {'path': str(path.relative_to(ROOT)), 'sha256': native.digest(path)}


def partial_prefix(program):
    """Retain only the common recorded prefix, using existing PVA knots only."""
    if program.get('format') != 'solidcraftbot.building-fleet-program/1' or program.get('complete') is not False:
        raise ValueError('Explicit incomplete BF01 recording required')
    rows = program.get('trajectories', [])
    if len(rows) != 20 or {r['vehicle_id'] for r in rows} != {'BF%02d' % i for i in range(1, 21)}:
        raise ValueError('Exactly BF01..BF20 recorded trajectories required')
    duration = program.get('duration_s')
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Positive recorded duration required')
    end = min(duration, *(r['episodes'][-1]['end_s'] for r in rows))
    common = None
    for row in rows:
        times = {p['time_s'] for e in row['episodes'] for p in e['points'] if p['time_s'] <= end}
        common = times if common is None else common & times
    end = max(common or {0})
    if end <= 0:
        raise ValueError('No positive common recorded PVA endpoint')
    value = {**program, 'trajectories': copy.deepcopy(rows)}
    value['duration_s'] = end
    for row in value['trajectories']:
        episodes = []
        previous = 0
        for episode in row['episodes']:
            if episode['start_s'] >= end:
                break
            if episode['start_s'] != previous:
                raise ValueError('Continuous recorded episode coverage required')
            episode['points'] = [p for p in episode['points'] if p['time_s'] <= end]
            episode['end_s'] = min(episode['end_s'], end)
            if (len(episode['points']) < 2 or episode['points'][0]['time_s'] != episode['start_s']
                    or episode['points'][-1]['time_s'] != episode['end_s']):
                raise ValueError('Prefix clipping requires existing recorded endpoint knots')
            episodes.append(episode)
            previous = episode['end_s']
        if previous != end:
            raise ValueError('Every vehicle must cover the common recorded prefix')
        row['episodes'] = episodes
    return value, {'source_duration_s': duration, 'recorded_end_s': end,
        'clipped_to_common_recorded_prefix': value['trajectories'] != program['trajectories'],
        'retained_pva_knots_unchanged': True,
        'policy': 'Only existing common recorded knots; no interpolation, retiming or new transfer.'}


def build(program_path, failure_path, runtime_start_path, world_path, camera_path,
          vehicle_mesh_path, output):
    started = time.monotonic()
    paths = [native.project_path(p) for p in (program_path, failure_path, runtime_start_path,
        world_path, camera_path, vehicle_mesh_path)]
    program_path, failure_path, runtime_start_path, world_path, camera_path, mesh_path = paths
    refs = {key: artifact(path) for key, path in zip(('partial_program', 'runtime_failure',
        'runtime_source_start', 'world_report', 'camera_report', 'vehicle_mesh'), paths)}
    program = model.read_json(program_path)
    failure = model.read_json(failure_path)
    runtime_pins = model.read_json(runtime_start_path)
    if (failure.get('format') != 'solidcraftbot.building-fleet-runtime-failure/1'
            or failure.get('passed') is not False or failure.get('complete_fleet_run') is not False
            or failure.get('interrupted') is not True or failure.get('exception') != 'KeyboardInterrupt'):
        raise ValueError('Original explicit interrupted runtime record required')
    if runtime_pins != failure.get('source_files_sha256'):
        raise ValueError('Runtime start and interruption source pins differ')
    native.verify_pins(runtime_pins)
    if any(runtime_pins.get(name) != digest for name, digest in program['source_files_sha256'].items()):
        raise ValueError('Partial recording source pins conflict with runtime start')
    for key in ('world_report', 'camera_report'):
        if runtime_pins.get(refs[key]['path']) != refs[key]['sha256']:
            raise ValueError('Presentation report was not bound at runtime start: ' + key)
    if program['seed'] != failure['seed'] or program['duration_s'] != failure['model_time_s']:
        raise ValueError('Interrupted recording time/seed differ from original failure')
    prefix, clipping = partial_prefix(program)
    from check_building_fleet_freecad import checked_walkthrough
    _, _, manifest, _ = checked_walkthrough(world_path)
    checked_camera_report(camera_path)
    vehicle = model.read_json(mesh_path)
    native.verify_pins(vehicle['source_files_sha256'])
    if (vehicle.get('format') != 'solidcraftbot.building-fleet-vehicle-mesh/1'
            or vehicle['camera_report']['sha256'] != refs['camera_report']['sha256']):
        raise ValueError('Current source-bound native vehicle presentation mesh required')
    import tr01_camera_model as kit
    expected = {b['id'] for b in kit.expanded(kit.load())['bodies'] if b['role'] != 'viewing_cone'}
    if {g['id'] for g in vehicle['scene']['groups']} != expected:
        raise ValueError('Incomplete physical vehicle presentation mesh')
    # Missing runtime artifact references are supplied in this derived view only.
    # Original partial/failure/start bytes remain untouched and separately pinned.
    prefix['artifacts'] = {'walkthrough_report': refs['world_report'], 'camera_report': refs['camera_report']}
    normalized = browser.view_program(prefix, manifest)
    encoded = json.dumps(normalized, separators=(',', ':'), allow_nan=False).encode()
    preview = {'format': PREVIEW_FORMAT, 'recorded_end_s': prefix['duration_s'],
        'program_sha256': refs['partial_program']['sha256'],
        'original_program_sha256': refs['partial_program']['sha256'],
        'playback_end_s': prefix['duration_s'],
        'playback_sha256': hashlib.sha256(encoded).hexdigest(),
        'interruption': refs['runtime_failure'], 'qualification': copy.deepcopy(QUALIFICATION)}
    compressed = gzip.compress(encoded, mtime=0)
    source = model.load()
    payload = {'program_gzip_base64': base64.b64encode(compressed).decode(),
        'vehicle_mesh': vehicle, 'camera_presentation': source['camera_presentation'],
        'program_source_sha256': refs['partial_program']['sha256'], 'experimental_preview': preview}
    normal, presentation_pins = browser.world_presentation(world_path)
    html = browser.opt_in_html(normal, payload)
    extra = len(html.encode()) - len(normal.encode())
    pins = {**runtime_pins, **presentation_pins, **vehicle['source_files_sha256'],
        **{ref['path']: ref['sha256'] for ref in refs.values()},
        str(browser.VIEW.relative_to(ROOT)): native.digest(browser.VIEW),
        str(Path(browser.__file__).resolve().relative_to(ROOT)): native.digest(browser.__file__),
        str(Path(__file__).resolve().relative_to(ROOT)): native.digest(__file__)}
    for name, digest in runtime_pins.items():
        if pins[name] != digest:
            raise ValueError('Presentation conflicts with recorded physical/runtime source: ' + name)
    native.verify_pins(pins)
    output = native.project_path(output)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    (output / 'index.html').write_text(html)
    report = {'format': 'solidcraftbot.building-fleet-experimental-preview-build/1',
        'passed': True, 'complete': False, 'browser_checked': False, **QUALIFICATION,
        **refs, 'source_files_sha256': pins, 'experimental_preview': preview,
        'html_sha256': native.digest(output / 'index.html'),
        'normal_html_sha256': hashlib.sha256(normal.encode()).hexdigest(),
        'additional_html_bytes': extra, 'html_budget': browser.html_budget(extra),
        'gzip_program_bytes': len(compressed), 'clipping': clipping,
        'playback_projection': {'included_fields': list(browser.PLAYBACK_FIELDS),
            'received_messages_unchanged': normalized['received_messages'] == program['received_messages'],
            'own_captures_unchanged': normalized['camera_captures'] == program['camera_captures'],
            'trajectory_pva_unchanged': normalized['trajectories'] == program['trajectories'],
            'retained_pva_knots_unchanged': True},
        'elapsed_s': time.monotonic() - started,
        'scope': 'Experimental interrupted recording prefix only; build pass means structural/provenance checks, not completed fleet, full native or independent export qualification.',
        'limitations': ['Recording ends without a fleet-completion claim. Full mission coverage, full native motion and independent export checks remain unverified.']}
    (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('program')
    for name in ('runtime-failure', 'runtime-source-start', 'world-report', 'camera-report', 'vehicle-mesh', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    result = build(args.program, args.runtime_failure, args.runtime_source_start,
        args.world_report, args.camera_report, args.vehicle_mesh, args.output_dir)
    print(json.dumps({'format': result['format'], 'recorded_end_s': result['experimental_preview']['recorded_end_s'],
        'html_sha256': result['html_sha256']}), flush=True)


if __name__ == '__main__':
    main()
