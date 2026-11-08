"""One-time LF migration of tracked active text and its byte-level source pins.

Historical inputs, media and build evidence are preserved. The generated report
is a snapshot of this migration, not a new CAD or hardware validation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPORT = 'docs/line-ending-migration.json'
GALLERY = 'docs/models/provenance.json'
TOKEN = re.compile(rb'(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])')
BINARY = {'.step', '.stp', '.sc', '.solidcraft', '.stl', '.fcstd', '.pdf', '.png', '.mp4'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def frozen(path):
    return (path.startswith(('docs/media/', 'model/history/', 'tests/fixtures/'))
            or '/vendor-model-' in path or '/vendor-document-' in path
            or Path(path).suffix.lower() in BINARY or path in ('MANIFEST.sha256', REPORT))


def text_inputs(files):
    result = {}
    for path, data in files.items():
        if frozen(path) or b'\0' in data:
            continue
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            continue
        result[path] = data
    return result


def plan(files, baseline):
    """Compute everything in memory before writing; return changed files/report."""
    original = text_inputs(files)
    current = {p: b.replace(b'\r\n', b'\n') for p, b in original.items()}
    targets = [p for p in current if original[p] != current[p]]
    aliases = {digest(original[p]): digest(current[p]) for p in targets}
    gallery_before = json.loads(original[GALLERY]) if GALLERY in original else None

    def resolve(value):
        seen = set()
        while value in aliases and aliases[value] != value:
            if value in seen:
                raise ValueError('Cyclic checksum dependencies; no files written')
            seen.add(value)
            value = aliases[value]
        return value

    def replace(data):
        return TOKEN.sub(lambda match: resolve(match[0].decode()).encode(), data)

    for _ in range(100):
        changes = {}
        for path, data in current.items():
            if path == GALLERY:
                gallery = json.loads(data)
                for record in gallery['images']:
                    # These are current pins. Build/source-equivalence evidence
                    # describes an actual previous run and must not be rewritten.
                    for field in ('source_files_sha256', 'dependency_files_sha256'):
                        record[field] = {p: resolve(h) for p, h in record[field].items()}
                    before = next(r for r in gallery_before['images'] if r['id'] == record['id'])
                    if any(record[f] != before[f] for f in ('source_files_sha256', 'dependency_files_sha256')):
                        record['line_ending_equivalence'] = {
                            'baseline_commit': baseline, 'migration_report': REPORT,
                            'method': 'LF normalization and updated dependency hashes only; original build evidence and image bytes retained'}
                after = (json.dumps(gallery, indent=2) + '\n').encode()
            else:
                after = replace(data)
            if after != data:
                changes[path] = after
        if not changes:
            break
        for path, after in changes.items():
            aliases[digest(current[path])] = digest(after)
            current[path] = after
    else:
        raise ValueError('Checksum chain did not converge; no files written')

    changed = {p: b for p, b in current.items() if b != original[p]}
    report = {
        'format': 'solidcraftbot.lf-migration/1', 'baseline_commit': baseline,
        'scope': 'LF in repository and checkout; current full source pins only',
        'files': [{'path': p, 'old_sha256': digest(original[p]), 'new_sha256': digest(changed[p]),
                   'line_endings_changed': p in targets} for p in sorted(changed)],
        'preserved_files_sha256': {p: digest(b) for p, b in files.items() if frozen(p)},
        'gallery_build_evidence_retained': True,
        'note': 'Historical build hashes, revision prefixes, images and frozen inputs retain their original meaning; no new CAD validation is claimed.'}
    # Check a second pass against the same old aliases: active pins must be final.
    for path, data in current.items():
        if path != GALLERY and replace(data) != data:
            raise ValueError('Unresolved source pin: ' + path)
    return changed, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the exact migration snapshot before subsequent source changes')
    args = parser.parse_args()
    report_path = ROOT / REPORT
    if args.check:
        report = json.loads(report_path.read_text())
        for entry in report['files']:
            if digest((ROOT / entry['path']).read_bytes()) != entry['new_sha256']:
                raise ValueError('Source changed since migration snapshot: ' + entry['path'])
        for path, sha in report['preserved_files_sha256'].items():
            if digest((ROOT / path).read_bytes()) != sha:
                raise ValueError('Frozen input changed: ' + path)
        print('Migration snapshot and frozen inputs verified')
        return
    if report_path.exists():
        raise FileExistsError('One-time migration already recorded; use --check on its commit')
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    files = {p: (ROOT / p).read_bytes() for p in names if p and (ROOT / p).is_file()}
    baseline = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    changed, report = plan(files, baseline)
    normalized = [r for r in report['files'] if r['line_endings_changed']]
    if len(normalized) != 41:
        raise ValueError('Expected reviewed 41-file LF set; got ' + str(len(normalized)))
    manifest = ROOT / 'MANIFEST.sha256'
    if manifest.exists():
        data = manifest.read_bytes()
        archive = ROOT / 'exports/history' / ('MANIFEST-' + digest(data)[:12] + '.sha256')
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists() and archive.read_bytes() != data:
            raise ValueError('Manifest archive conflict')
        shutil.copyfile(manifest, archive)
        report['removed_local_manifest'] = {'was_tracked': 'MANIFEST.sha256' in files,
            'archive': str(archive.relative_to(ROOT)), 'sha256': digest(data)}
        manifest.unlink()
    for path, data in changed.items():
        (ROOT / path).write_bytes(data)
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'normalized_files': len(normalized), 'source_pin_followups': len(changed) - len(normalized), 'report': REPORT}))


if __name__ == '__main__':
    main()
