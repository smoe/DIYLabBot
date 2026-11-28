"""Bind reviewed furniture screenshots to a checked native walkthrough."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

import building_stack as stack
import building_walkthrough as walkthrough
import export_building_walkthrough_freecad as native

ROOT = native.ROOT
PUBLIC = ROOT / 'docs/media'
CAPTURE_SCRIPT = ROOT / 'scripts/capture_building_furnishings_gallery.cjs'
CURRENT_PROOF = PUBLIC / 'building-furnishings-current.provenance.json'
HISTORY = ('docs/media/building-furnishings.provenance.json',
           'docs/building-furnishings-media-compatibility.json',
           'docs/building-furnishings-media-status.json')
IMAGE_NAMES = {
    'Kitchen1008': 'kitchen-1-008.png',
    'PhD1002': 'office-1-002.png',
    'PhD3002': 'office-3-002.png',
    'Kitchen1008_EasterEgg': 'kitchen-fridge-easter-egg.png',
}
PNG_HEADER = b'\x89PNG\r\n\x1a\n'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def serialized(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(serialized(value))


def reference(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size,
            'sha256': native.digest(path)}


def png_pixels(path):
    with path.open('rb') as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != PNG_HEADER or header[12:16] != b'IHDR':
        raise ValueError('Expected a PNG image: ' + str(path))
    return list(struct.unpack('>II', header[16:24]))


def framing(program):
    """Reuse the PhD viewpoint's approach against the actual OG1 plan."""
    phd = next(stop for stop in program['stops'] if stop['id'] == 'phd')
    level = next(level for level in program['levels'] if level['id'] == 'OG1')
    building = stack.load()
    eye, target = walkthrough.building_camera(
        phd['anchor'], stack.level_plan(building, level['id']),
        stack.parameters(building)['display_scale'], level['z_mm'], program['settings']['eye_height_mm'])
    return {'phd1002': {**phd, 'id': 'phd1002', 'level_id': level['id'],
                        'label': 'Doktorandenraum 1.002', 'eye_mm': eye, 'target_mm': target}}


def checked_walkthrough(folder):
    report_path = folder / 'build-report.json'
    report = read(report_path)
    if report.get('format') != 'solidcraftbot.building-walkthrough-build/1' or report.get('passed') is not True:
        raise ValueError('A successful native walkthrough build is required')
    native.verify_pins(report['source_files_sha256'])
    paths = {role: native.project_path(name) for role, name in report['files'].items()}
    for role, path in paths.items():
        if path.parent != folder or native.digest(path) != report['artifact_sha256'][role]:
            raise ValueError('Unexpected or changed walkthrough artifact: ' + role)
    return report, report_path, paths, read(paths['manifest'])


def record(walkthrough_dir, captures):
    report, report_path, paths, program = checked_walkthrough(walkthrough_dir)
    capture_path = captures / 'browser-gallery-report.json'
    captured = read(capture_path)
    fixture = framing(program)
    if (captured.get('format') != 'solidcraftbot.building-furnishings-browser-gallery/1'
            or captured.get('passed') is not True
            or captured['html_sha256'] != report['artifact_sha256']['html']
            or captured['build_report_sha256'] != native.digest(report_path)
            or captured['native_builds'] != report['native_builds']
            or captured['qualification'] != program['qualification']
            or captured['browser_errors']
            or captured['fixture_sha256'] != hashlib.sha256(serialized(fixture)).hexdigest()):
        raise ValueError('Browser checks must cover the checked walkthrough and gallery viewpoints')
    rows = {row['id']: row for row in captured['images']}
    if len(captured['images']) != len(IMAGE_NAMES) or rows.keys() != IMAGE_NAMES.keys():
        raise ValueError('Exactly the four furniture gallery images are required')
    derived_files = set()
    native_reports = {}
    for scene, build in report['native_builds'].items():
        path = native.project_path(build['report'])
        checked = native.checked_report(path, scene)
        if native.digest(path) != build['report_sha256'] or checked['source_sha256'] != build['source_sha256']:
            raise ValueError('Walkthrough and native build differ: ' + scene)
        derived_files.update([build['report'], *checked['files'].values()])
        native_reports[scene] = checked
    producer_pins = {name: digest for name, digest in report['source_files_sha256'].items()
                     if name not in derived_files}
    for path in (Path(__file__), CAPTURE_SCRIPT):
        producer_pins[path.relative_to(ROOT).as_posix()] = native.digest(path)

    revision = report['native_builds']['building']['revision']
    destination = PUBLIC / 'furnishings-gallery' / revision
    images = []
    copies = []
    for identity, filename in IMAGE_NAMES.items():
        row = rows[identity]
        path = captures / (identity + '.png')
        actual = reference(path)
        pixels = png_pixels(path)
        if row['sha256'] != actual['sha256'] or row['bytes'] != actual['bytes'] or row['pixels'] != pixels:
            raise ValueError('Screenshot differs from browser evidence: ' + identity)
        target = destination / filename
        copies.append((path, target))
        images.append({**{key: value for key, value in row.items() if key != 'file'},
                       **actual, 'path': target.relative_to(ROOT).as_posix(),
                       'pixels': pixels, 'visual_reviewed': True})
    proof = {
        'format': 'solidcraftbot.building-furnishings-gallery/1',
        'images': images,
        'source_files_sha256': producer_pins,
        'walkthrough': {**{role: reference(paths[role]) for role in ('html', 'manifest', 'native_mesh')},
                        'build_report': reference(report_path)},
        'native_builds': report['native_builds'],
        'browser_capture': {'report': reference(capture_path),
                            'browser': captured['browser'], 'fridge': captured['fridge'], 'passed': True},
        'framing': fixture,
        'historical_records': [reference(ROOT / name) for name in HISTORY],
        'original_photographs_included': False,
        'qualification': program['qualification'],
        'freecad_checks_passed': native_reports['building']['freecad_checks_passed'],
        'cross_cad_checked': native_reports['building']['cross_cad_checked'],
        'limitations': [
            'Reviewed browser images of native FreeCAD tessellations in assumed presentation dimensions.',
            'The refrigerator detail shows its browser open state. No real door sweep is qualified.',
            'The static gallery provides no measured registration, real fit, ergonomics, motion or safety evidence.',
            'Historical room images and their independent CAD checks remain bound to their own revisions.',
        ],
    }
    destination.mkdir(parents=True, exist_ok=True)
    for path, target in copies:
        shutil.copyfile(path, target)
    write(CURRENT_PROOF, proof)
    return CURRENT_PROOF


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fixtures', 'record'))
    parser.add_argument('walkthrough', type=native.project_path)
    parser.add_argument('destination', type=native.project_path)
    parser.add_argument('--reviewed', action='store_true', help='Confirm visual review of all four screenshots')
    args = parser.parse_args()
    if args.action == 'fixtures':
        _, _, _, program = checked_walkthrough(args.walkthrough)
        write(args.destination, framing(program))
    else:
        if not args.reviewed:
            parser.error('Inspect all four screenshots before recording the gallery with --reviewed')
        print(record(args.walkthrough, args.destination))


if __name__ == '__main__':
    main()
