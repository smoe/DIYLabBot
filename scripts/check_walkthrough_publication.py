"""Reject a published snapshot that no longer represents the checked-out sources."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

import building_walkthrough as walkthrough
import building_stack as stack
import export_building_walkthrough_freecad as native_mesh
from build_building_walkthrough import add_monitor_wall

ROOT = Path(__file__).resolve().parents[1]
MONITOR_RENDERER_SOURCES = ('scripts/camera_monitor_wall.js', 'scripts/monitor_frustum.js')


def required_body_ids(program, building_ids):
    """Native building plus each checked, source-bound equipment/support body."""
    result = set(building_ids)
    laboratories = program.get('laboratories', [])
    if not laboratories:
        return result
    source = program['equipment_source']
    report = native_mesh.checked_report(native_mesh.project_path(source['build_report']), 'lab')
    if report['source_sha256'] != source['source_sha256']:
        raise ValueError('Equipment proof differs from the published source contract')
    source_ids = [row['body'] for row in report['layout_validation']['scene_geometry']]
    for laboratory, device in native_mesh.native_equipment_bindings(laboratories):
        originals = [name for name in source_ids if name.startswith(device['id']+'__')]
        expected = report['layout_validation']['instance_metrics'][device['id']]['body_count']
        if not originals or len(originals) != expected:
            raise ValueError('Incomplete checked equipment body coverage: '+device['id'])
        placed = {device['body_prefix']+name[len(device['id']+'__'):] for name in originals}
        if len(placed) != len(originals) or placed & result:
            raise ValueError('Ambiguous published equipment body IDs: '+device['id'])
        result.update(placed)
    return result


def check(html, manifest, program=None, body_ids=None):
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    require(manifest['html']['sha256'] == hashlib.sha256(html).hexdigest()
            and manifest['html']['bytes'] == len(html), 'Published HTML checksum/length mismatch')
    match = re.search(rb'<script id="walkthrough-data" type="application/json">(.*?)</script>', html, re.S)
    require(match is not None, 'Missing inline walkthrough data')
    payload = json.loads(match[1])
    program = add_monitor_wall(walkthrough.compile()) if program is None else program
    require(payload.get('navigation') == program.get('navigation'), 'Stale published navigation policy')
    for key in ('objects', 'interaction', 'stops', 'levels', 'settings', 'rendering', 'hidden_body_ids'):
        require(payload.get(key) == program[key], 'Stale published walkthrough: '+key)
    for key in ('robots', 'laboratories', 'equipment_source', 'elevator', 'places', 'topology'):
        if key in program:
            require(payload.get(key) == program[key], 'Stale published walkthrough: '+key)
    require(payload.get('camera_wall') == program.get('camera_wall'), 'Stale published walkthrough: camera_wall')
    require(payload.get('room_signs') == program.get('room_signs'), 'Stale published walkthrough: room_signs')
    expected = dict(program['source_files_sha256'])
    renderer_sources = ('scripts/build_building_walkthrough.py', 'scripts/export_building_walkthrough_freecad.py',
                        'scripts/building_walkthrough_viewer.html', 'scripts/walkthrough_interaction.js')
    if program.get('camera_wall') is not None:
        renderer_sources += MONITOR_RENDERER_SOURCES
    for name in renderer_sources:
        expected[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    for name, digest in expected.items():
        require(payload.get('source_files_sha256', {}).get(name) == digest,
                'Stale published source: '+name)
        require(manifest.get('source_files_sha256', {}).get(name) == digest,
                'Stale publication manifest: '+name)
    if body_ids is None:
        source = stack.load()
        body_ids = required_body_ids(program,
            {v['id'] for v in stack.expanded(source, stack.parameters(source))['bodies']})
    actual = [v['id'] for v in payload['scenes']['building']['groups']]
    require(len(actual) == len(set(actual)) and set(actual) == set(body_ids),
            'Published building body coverage differs from current source')
    return {'passed': True, 'building_bodies': len(actual),
            'objects': [v['id'] for v in payload['objects']],
            'html_sha256': manifest['html']['sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('site', help='Local directory or HTTPS site URL')
    args = parser.parse_args()
    if args.site.startswith('https://'):
        def read(name):
            with urlopen(args.site.rstrip('/')+'/'+name, timeout=60) as response:
                return response.read()
    else:
        def read(name):
            return (Path(args.site)/name).read_bytes()
    print(json.dumps(check(read('index.html'), json.loads(read('site-manifest.json'))), indent=2))


if __name__ == '__main__':
    main()
