"""Reject a published snapshot that no longer represents the checked-out sources."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

import building_walkthrough as walkthrough
import building_stack as stack

ROOT = Path(__file__).resolve().parents[1]


def check(html, manifest, program=None, body_ids=None):
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    require(manifest['html']['sha256'] == hashlib.sha256(html).hexdigest()
            and manifest['html']['bytes'] == len(html), 'Published HTML checksum/length mismatch')
    match = re.search(rb'<script id="walkthrough-data" type="application/json">(.*?)</script>', html, re.S)
    require(match is not None, 'Missing inline walkthrough data')
    payload = json.loads(match[1])
    program = walkthrough.compile() if program is None else program
    for key in ('objects', 'interaction', 'stops', 'levels', 'settings', 'rendering', 'hidden_body_ids'):
        require(payload.get(key) == program[key], 'Stale published walkthrough: '+key)
    expected = dict(program['source_files_sha256'])
    for name in ('scripts/build_building_walkthrough.py', 'scripts/export_building_walkthrough_freecad.py',
                 'scripts/building_walkthrough_viewer.html', 'scripts/walkthrough_interaction.js'):
        expected[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    for name, digest in expected.items():
        require(payload.get('source_files_sha256', {}).get(name) == digest,
                'Stale published source: '+name)
        require(manifest.get('source_files_sha256', {}).get(name) == digest,
                'Stale publication manifest: '+name)
    if body_ids is None:
        source = stack.load()
        body_ids = {v['id'] for v in stack.expanded(source, stack.parameters(source))['bodies']}
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
