"""The source-bound native world shared by the browser and BF01."""

import hashlib
import json
from pathlib import Path

import export_building_walkthrough_freecad as mesh_export

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.building-walkthrough-world/1'
REPORT = 'world-build-report.json'
FILES = {'manifest': 'world-manifest.json', 'native_mesh': 'native-mesh.json'}
OVERLAY_SOURCES = frozenset({
    'model/building-fleet-demo.shared.json',
    'model/foyer-camera-wall.shared.json',
    'model/foyer-camera-wall.schema.json',
    'scripts/monitor_camera_registry.py',
    'scripts/camera_monitor_wall.js',
    'scripts/monitor_frustum.js',
})


def check_world(manifest, pins, root):
    overlay_paths = {root / source for source in OVERLAY_SOURCES}
    if (manifest.get('format') != 'solidcraftbot.building-walkthrough/1'
            or manifest.get('source_files_sha256') != pins
            or 'camera_wall' in manifest
            or any(stop.get('id') == 'camera-wall' for stop in manifest.get('stops', []))
            or any((root / name).resolve() in overlay_paths for name in pins)):
        raise ValueError('Walkthrough world must bind exactly its own inputs, excluding the camera overlay')


def write(export, manifest, native_builds, root=ROOT):
    pins = manifest['source_files_sha256']
    check_world(manifest, pins, root)
    mesh_export.verify_pins(pins, root)
    (export / FILES['manifest']).write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    report = {'format': FORMAT, 'passed': True, 'source_files_sha256': pins,
              'files': {key: (export / name).relative_to(root).as_posix() for key, name in FILES.items()},
              'artifact_sha256': {key: mesh_export.digest(export / name) for key, name in FILES.items()},
              'native_builds': native_builds}
    report_path = export / REPORT
    report_path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report_path


def read(export, root=ROOT):
    """Verify every world pin and both exact artifacts before handing out data."""
    root, export = Path(root).resolve(), Path(export).resolve()
    if not export.is_relative_to(root):
        raise ValueError('Project-local fleet export required')
    report_path = export / REPORT
    if not report_path.is_file() or report_path.is_symlink():
        raise ValueError('Separate walkthrough world report required. Export the current walkthrough again.')
    report = json.loads(report_path.read_bytes())
    pins, hashes = report.get('source_files_sha256'), report.get('artifact_sha256', {})
    paths = {key: export / name for key, name in FILES.items()}
    if (report.get('format') != FORMAT or report.get('passed') is not True
            or not isinstance(pins, dict) or not pins
            or report.get('files') != {key: path.relative_to(root).as_posix() for key, path in paths.items()}
            or set(hashes) != set(paths)):
        raise ValueError('A successful current walkthrough world report is required')
    for name, digest in pins.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('External source pin: '+name)
        if not path.is_file() or mesh_export.digest(path) != digest:
            raise ValueError('Stale walkthrough source: '+name)
    artifacts = {}
    for key, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError('Changed walkthrough artifact: '+path.name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != hashes[key]:
            raise ValueError('Changed walkthrough artifact: '+path.name)
        artifacts[key] = json.loads(raw)
    manifest, bundle = artifacts['manifest'], artifacts['native_mesh']
    check_world(manifest, pins, root)
    if (bundle.get('format') != mesh_export.FORMAT or set(bundle.get('scenes', {})) != {'building'}
            or not isinstance(bundle.get('source_files_sha256'), dict)
            or any(pins.get(name) != digest for name, digest in bundle['source_files_sha256'].items())):
        raise ValueError('Unsupported or unbound walkthrough world mesh')
    return report, manifest, bundle
