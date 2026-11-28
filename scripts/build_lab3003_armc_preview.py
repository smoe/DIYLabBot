"""Show the checked ArmC variant parked beside TR01 and CF01 in Lab 3.003."""

import argparse
import json
from pathlib import Path

import build_building_walkthrough as browser
from build_lab3003_tr01_walkthrough import read, replace_mesh
import export_building_walkthrough_freecad as mesh
import lab3003_armc_variant as variant
import lab_layout_model as layout
import monitor_camera_registry as camera_registry
import robot_spec as robot


def checked_stock(directory):
    report = read(directory / 'tr01-preview-report.json')
    html = (directory / 'index.html').read_bytes()
    if report.get('passed') is not True or mesh.digest(directory / 'index.html') != report['html_sha256']:
        raise ValueError('A checked stock TR01 walkthrough is required')
    _, marker, data = html.partition(b'<script id="walkthrough-data" type="application/json">')
    data, close, _ = data.partition(b'</script>')
    if not marker or not close:
        raise ValueError('Missing stock walkthrough data')
    payload = json.loads(data)
    mesh.verify_pins(payload['source_files_sha256'])
    return payload, report


def parked_payload(stock_preview, armc_report_path):
    payload, stock = checked_stock(stock_preview)
    lab, = (room for room in payload['laboratories'] if room['id'] == 'Lab3003')
    arm = variant.bind(lab)
    report, artifacts = variant.read_native(armc_report_path, arm)
    if report['stock_html_sha256'] != stock['html_sha256']:
        raise ValueError('The native arm report names a different stock scene')

    stock_scene = payload['scenes']['building']
    replacement = read(artifacts['mesh'])
    stock_groups = {g['id'] for g in stock_scene['groups'] if g['id'].startswith(arm['body_prefix'])}
    new_groups = {g['id'] for g in replacement['groups']}
    if (not stock_groups or len(new_groups) != len(replacement['groups']) or stock_groups != new_groups
            or any(g.get('instance_id') != arm['device_id'] or g.get('laboratory_id') != lab['id']
                   or g.get('level_id') != lab['level_id'] for g in replacement['groups'])):
        raise ValueError('The verified mesh must replace exactly the parked ArmC native body groups')
    articulated = {group for obj in payload['objects'] for group in obj['moving_body_ids']}
    if new_groups & articulated:
        raise ValueError('The longer arm cannot inherit a stock motion binding')
    stock_lap = payload.pop('tr01_lap')
    parked_groups = {g['id'] for g in stock_scene['groups']}
    if stock_lap['cover_body_id'] not in parked_groups or set(stock_lap['body_ids']) - parked_groups:
        raise ValueError('The docked preview requires the complete covered TR01')
    previous_cycle = payload.pop('lab3003_cf01_cycle', None)
    if previous_cycle is not None:
        payload['stops'] = [stop for stop in payload['stops'] if stop['id'] != previous_cycle['stop_id']]
    scene = replace_mesh(stock_scene, replacement)
    scene['scope'] = 'Parked native ArmC variant and covered TR01 at the Lab 3.003 dock'
    payload['scenes']['building'] = scene

    devices = {item['id']: item for item in lab['device_instances']}
    layout_source = layout.load(validate_builds=False)
    item = next(item for item in layout_source['instances'] if item['id'] == arm['device_id'])
    wall = payload['camera_wall']
    updated_cameras = camera_registry.arm_cameras(lab, devices[arm['device_id']], {
        **item, 'overrides': arm['dimensions_mm'], 'joints_deg': arm['park_joints_deg'],
    }, layout_source, wall['settings'])
    camera_by_id = {camera['id']: camera for camera in updated_cameras}
    if (set(camera_by_id) != {camera['id'] for camera in wall['cameras']
                              if camera['device_id'] == lab['id'] + '.' + arm['device_id']}
            or any(camera['mount_body_id'] not in new_groups for camera in updated_cameras)):
        raise ValueError('The stationary ArmC camera poses must match the native variant')
    wall['cameras'] = [camera_by_id.get(camera['id'], camera) for camera in wall['cameras']]

    stops = payload['stops']
    viewpoint = next(stop for stop in stops if stop['id'] == stock_lap['stop_id'])
    x, y, z = [row[3] for row in arm['bound_pose'][:3]]
    viewpoint.update(label='Labor 3.003 · ArmC am TR01-Dock',
                     eye_mm=robot.transform(lab['transform'], [x+1760, y-680, 1650]),
                     target_mm=robot.transform(lab['transform'], [x+100, y-140, z+140]))
    payload['default_stop'] = viewpoint['id']
    payload['lab3003_armc_parked'] = {
        'stop_id': viewpoint['id'], 'label': 'ArmC · Parkstellung · TR01 am Dock',
        'dimensions_mm': arm['dimensions_mm'], 'arm_motion_included': False,
    }
    payload['source_files_sha256'] = browser.merge_pins(payload['source_files_sha256'], report['source_files_sha256'])
    mesh.verify_pins(payload['source_files_sha256'])
    return payload, {'stock': stock, 'stock_lap': stock_lap, 'arm': arm, 'native_report': report,
                     'native_paths': artifacts, 'body_ids': sorted(new_groups)}


def build(stock_preview, armc_report_path, output):
    payload, native = parked_payload(stock_preview, armc_report_path)
    stock, report, arm = (native[key] for key in ('stock', 'native_report', 'arm'))
    output.mkdir(parents=True)
    html = output / 'index.html'
    html.write_text(browser.embed_html(browser.TEMPLATE.read_text(), payload), encoding='utf-8')
    result = {
        'format': 'solidcraftbot.lab3003-armc-parked-preview/1', 'passed': True,
        'scope': 'Native parked geometry and current camera bindings. No moving-arm, vehicle or station cycle.',
        'artifacts': {'html_sha256': mesh.digest(html), 'stock_html_sha256': stock['html_sha256'],
                      'armc_report_sha256': mesh.digest(armc_report_path),
                      'armc_mesh_sha256': report['artifacts']['mesh']['sha256']},
        'replacement_body_ids': native['body_ids'], 'park_joints_deg': arm['park_joints_deg'],
        'dimensions_mm': arm['dimensions_mm'], 'browser_checked': False,
        'viewer_source_sha256': {str(path.relative_to(variant.ROOT)): mesh.digest(path)
                                for path in (Path(__file__), browser.TEMPLATE)},
    }
    (output / 'preview-report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(html, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-preview', type=Path, required=True)
    parser.add_argument('--armc-report', type=mesh.project_path, required=True)
    parser.add_argument('--output-dir', type=mesh.project_path, required=True)
    args = parser.parse_args()
    build(args.stock_preview, args.armc_report, args.output_dir)


if __name__ == '__main__':
    main()
