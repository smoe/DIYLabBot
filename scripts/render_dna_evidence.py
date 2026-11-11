"""Render journal-derived schematic DNA evidence, separate from README media.

No workflow is executed. AppKit draws still event cards; FFmpeg encodes them.
The video clock is a presentation clock, never a robot or process trajectory.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from dna_evidence_manifest import (MANIFEST_FORMAT, ROOT, check_manifest, derive,
                                   file_record, output_path, require, sha, write_json)
from manual_tasks import TaskError

WIDTH, HEIGHT = 1600, 1000

# Native, installed AppKit avoids a new Python/image dependency. The source is
# copied and pinned in each evidence bundle, along with actual compiler versions.
SWIFT = r'''import AppKit
import Foundation
let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
let cards = try JSONSerialization.jsonObject(with: Data(contentsOf: input)) as! [[String: Any]]
for card in cards {
    // An explicit bitmap fixes pixel dimensions independently of the display's
    // Retina backing scale. NSImage.lockFocus() can silently double them.
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1600, pixelsHigh: 1000,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    bitmap.size = NSSize(width: 1600, height: 1000)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSColor(calibratedRed: 0.05, green: 0.08, blue: 0.13, alpha: 1).setFill()
    NSRect(x: 0, y: 0, width: 1600, height: 1000).fill()
    let boxes: [(CGFloat, String)] = [(50, "RACK / VERDÜNNUNGSANSATZ"), (590, "NANODROP"), (1130, "QUBIT dsDNA HS")]
    for (x, name) in boxes {
        NSColor(calibratedRed: 0.13, green: 0.25, blue: 0.35, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: x, y: 825, width: 420, height: 70), xRadius: 12, yRadius: 12).fill()
        (name as NSString).draw(at: NSPoint(x: x + 20, y: 850), withAttributes: [
            .font: NSFont.monospacedSystemFont(ofSize: 22, weight: .semibold), .foregroundColor: NSColor.white])
    }
    // Static arrows describe assay order. They are not transport motion.
    ("→" as NSString).draw(at: NSPoint(x: 510, y: 840), withAttributes: [.font: NSFont.systemFont(ofSize: 40), .foregroundColor: NSColor.cyan])
    ("→" as NSString).draw(at: NSPoint(x: 1050, y: 840), withAttributes: [.font: NSFont.systemFont(ofSize: 40), .foregroundColor: NSColor.cyan])
    let title = card["title"] as! String
    (title as NSString).draw(at: NSPoint(x: 45, y: 940), withAttributes: [
        .font: NSFont.systemFont(ofSize: 28, weight: .bold), .foregroundColor: NSColor.white])
    let body = card["body"] as! String
    let style = NSMutableParagraphStyle()
    style.lineSpacing = 3
    (body as NSString).draw(in: NSRect(x: 45, y: 25, width: 1510, height: 775), withAttributes: [
        .font: NSFont.monospacedSystemFont(ofSize: 16, weight: .regular),
        .foregroundColor: NSColor(calibratedWhite: 0.91, alpha: 1), .paragraphStyle: style])
    NSGraphicsContext.restoreGraphicsState()
    let png = bitmap.representation(using: .png, properties: [:])!
    try png.write(to: output.appendingPathComponent(card["png"] as! String))
}
'''


def run(command, **options):
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, **options)
    require(result.returncode == 0, 'Evidence tool failed: ' + command[0] + '\n' + result.stderr[-4000:])
    return result.stdout


def versions():
    tools = {name: shutil.which(name) for name in ['swiftc', 'ffmpeg', 'ffprobe']}
    require(all(tools.values()), 'Installed swiftc, ffmpeg and ffprobe required; no automatic installs')
    return {'python': sys.version.splitlines()[0], 'platform': platform.platform(),
            'swiftc': run([tools['swiftc'], '--version']).splitlines()[0],
            'ffmpeg': run([tools['ffmpeg'], '-version']).splitlines()[0],
            'ffprobe': run([tools['ffprobe'], '-version']).splitlines()[0],
            'drawing': 'macOS AppKit; static schematic cards',
            'font': 'NSFont.monospacedSystemFont / systemFont', 'tools': tools}


def _metric(value):
    if not value:
        return 'noch kein Ergebnis'
    original = value.get('root_original_concentration') or {}
    original_value = original.get('value')
    return (str(value['measured_value']) + ' ' + str(value['measured_unit']) + ' ' + value['status']
            + '; Original=' + str(original_value) + ' ng/uL; F=' + str(value['external_factor']))


def scene_text(scene, claims):
    elapsed = ('unbekannt / noch keine Serverbeobachtung' if scene['server_elapsed_s'] is None
               else str(round(scene['server_elapsed_s'], 6)) + ' s')
    reference = scene.get('last_completed_reference') or {}
    def identity(key):
        if scene[key] is not None:
            return str(scene[key])
        if reference.get(key):
            return 'kein aktiver Bezug; zuletzt abgeschlossen: ' + reference[key]
        return 'noch kein aktiver oder abgeschlossener Bezug'
    def place(location):
        if location.get('kind') == 'rack':
            return location['rack_id'] + '/' + location['place_id']
        return json.dumps(location, ensure_ascii=False, sort_keys=True)
    if scene['source_vessel_id'] is None:
        location_line = 'Original-Inventar: ' + '; '.join(
            item['vessel_id'] + ' → ' + place(item['location']) for item in scene['original_vessels'])
        home_line = 'Original-Heimat: ' + '; '.join(
            item['vessel_id'] + ' → ' + place(item['home']) for item in scene['original_vessels'])
    else:
        location_line = 'Ort: ' + json.dumps(scene['location'], ensure_ascii=False, sort_keys=True)
        home_line = 'Ursprungsplatz: ' + json.dumps(scene['home'], ensure_ascii=False, sort_keys=True)
    lines = [' | '.join(claims['labels']),
             'LOGISCH: ' + str(scene['logical_time_s']) + ' s   SERVER (beobachtet): ' + elapsed,
             'VIDEO: ' + str(scene['video_time_s']) + ' s  (eigene Präsentationszeit; keine Zeitachsen-Gleichsetzung)',
             'Ereignisweise gerafft: ' + str(claims['time_axes']['video_event_interval_s'])
             + ' s/Ereignis; keine gleichmäßige physische Zeitachse.',
             '', 'Run: ' + scene['run_id'],
             'Ereignis ' + str(scene['event_sequence']) + ': ' + scene['event_kind'] + ' | Zustand: ' + scene['status'],
             'Befehlsausgang: ' + str(scene['command_status']) + ' | Request: ' + str(scene['request_id']),
             'SHA256: ' + scene['event_sha256'],
             'Versuch: ' + identity('attempt_id'), 'Kontext: ' + identity('context_id'),
             'Task: ' + str(scene['task_goal_id']) + ' | Worker: ' + str(scene['executing_agent_id']),
             'Worker-Boot: ' + str(scene['worker_boot_id']) + ' | Claim: ' + str(scene['claim_id']),
             'Quellgefäß: ' + identity('source_vessel_id'), location_line, home_line,
             '', 'NanoDrop: ng/uL; 2 ist LOD, keine qualifizierte LLOQ; Referenz bis 27500 ng/uL.',
             'Qubit dsDNA HS: 0.1–120 ng DNA im Assay; Ansatzvolumina müssen bestätigt sein.',
             'Externer Faktor einmal aus bestätigter Verdünnung; NanoDrop-Rohfeld Factor bleibt ungenutzt.', '']
    for attempt in scene['attempts']:
        lines += [attempt['attempt_id'] + ' | Quelle ' + attempt['input_vessel_id'] + ' | F=' + str(attempt['external_factor']),
                  '  ND: ' + _metric(attempt['evaluations'].get('nanodrop')),
                  '  QB: ' + _metric(attempt['evaluations'].get('qubit'))]
    lines += ['', 'Alle Gefäß-/Platzkennungen und Rohereignisse: scenes.json und inputs/journal.json.',
              'Pfeile zeigen die Reihenfolge. Kein Roboterpfad, kein Scan und keine Hardwareausführung.']
    return '\n'.join(lines)


def probe_video(path):
    return json.loads(run([shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                           '-show_entries', 'stream=codec_name,width,height,nb_frames,duration',
                           '-of', 'json', str(path)]))['streams'][0]


def render(input_path, *, seconds_per_event=0.5):
    input_path = output_path(input_path)
    base = input_path.parent
    manifest_path = base / 'manifest.json'
    require(not manifest_path.exists(), 'Evidence bundle already rendered; use --check or a new run directory')
    derived = derive(input_path, seconds_per_event)
    tool_versions = versions()
    frames = base / 'frames'
    frames.mkdir(exist_ok=False)
    cards, records = [], derived['files'][:]
    for index, scene in enumerate(derived['scenes'], 1):
        name = '%06d' % index
        text_path = frames / (name + '.txt')
        text = scene_text(scene, derived['claims'])
        text_path.write_text(text, encoding='utf-8')
        cards.append({'title': 'DNA-Probe: NanoDrop → Qubit | Schematische Darstellung',
                      'body': text, 'png': name + '.png'})
        records.append(file_record(text_path, 'scene_text', base))
    scene_path = write_json(base / 'scenes.json', derived['scenes'])
    cards_path = write_json(base / 'render-cards.json', cards)
    swift_path = base / 'renderer.swift'
    swift_path.write_text(SWIFT, encoding='utf-8')
    renderer = base / 'renderer-appkit'
    cache = base / 'tool-cache'
    cache.mkdir(exist_ok=False)
    environment = {**os.environ, 'CLANG_MODULE_CACHE_PATH': str(cache), 'SWIFT_MODULECACHE_PATH': str(cache)}
    run([tool_versions['tools']['swiftc'], '-module-cache-path', str(cache), str(swift_path), '-o', str(renderer)],
        env=environment)
    run([str(renderer), str(cards_path), str(frames)], env=environment)
    for index in range(1, len(cards) + 1):
        records.append(file_record(frames / ('%06d.png' % index), 'scene_png', base))
    video = base / 'dna-evidence.mp4'
    run([tool_versions['tools']['ffmpeg'], '-hide_banner', '-loglevel', 'error', '-nostdin',
         '-framerate', str(1 / seconds_per_event), '-i', str(frames / '%06d.png'),
         '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
         '-movflags', '+faststart', str(video)])
    stream = probe_video(video)
    require(int(stream['nb_frames']) == len(cards)
            and (stream['width'], stream['height']) == (WIDTH, HEIGHT), 'Video output does not match scenes')
    records += [file_record(scene_path, 'scenes', base), file_record(cards_path, 'renderer_input', base),
                file_record(swift_path, 'native_renderer_source', base), file_record(video, 'schematic_video', base)]
    manifest = {'format': MANIFEST_FORMAT, **derived, 'files': records, 'tools': tool_versions,
                'implementation_files_sha256': {str(path.relative_to(ROOT)): sha(path.read_bytes())
                    for path in [Path(__file__), ROOT / 'scripts' / 'dna_evidence_manifest.py',
                                 ROOT / 'scripts' / 'dna_quantification_ledger.py']},
                'render': {'width': WIDTH, 'height': HEIGHT, 'frame_count': len(cards),
                           'video': video.name, 'scenes': scene_path.name,
                           'video_duration_s': float(stream['duration']),
                           'video_codec': stream['codec_name'], 'scene_clock': 'independent presentation clock'}}
    write_json(manifest_path, manifest)
    check_manifest(manifest_path)
    return manifest_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path, help='evidence-input.json; with --check: manifest.json')
    parser.add_argument('--check', action='store_true', help='Recalculate bytes, journal and semantic claims')
    parser.add_argument('--seconds-per-event', type=float, default=0.5)
    args = parser.parse_args(argv)
    try:
        if args.check:
            manifest = check_manifest(args.path)
            print(json.dumps({'checked': True, 'run_id': manifest['journal']['run_id'],
                              'event_count': manifest['journal']['event_count']}))
        else:
            print(json.dumps({'manifest': str(render(args.path, seconds_per_event=args.seconds_per_event))}))
    except (TaskError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
