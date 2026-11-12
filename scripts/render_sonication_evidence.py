"""Render static journal-derived S09 fixture cards; never operate equipment."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from render_dna_evidence import probe_video, run, versions
from sonication_evidence import (MANIFEST_FORMAT, check_manifest, derive, file_record,
    inspection_frames, output_path, require, write_json, write_new)
from manual_tasks import TaskError

WIDTH, HEIGHT = 1600, 1000
SWIFT = r'''import AppKit
import Foundation
let cards = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [[String: Any]]
let output = URL(fileURLWithPath: CommandLine.arguments[2])
for card in cards {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1600, pixelsHigh: 1000,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    bitmap.size = NSSize(width: 1600, height: 1000)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSColor(calibratedRed: 0.04, green: 0.08, blue: 0.12, alpha: 1).setFill()
    NSRect(x: 0, y: 0, width: 1600, height: 1000).fill()
    let headings = [(50.0, "INPUT / ROOT-INVENTAR"), (590.0, "S09 / SONIKATIONSPLAN"), (1130.0, "GRÖSSENBEFUND")]
    for (x, title) in headings {
        NSColor(calibratedRed: 0.10, green: 0.27, blue: 0.32, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: x, y: 825, width: 420, height: 70), xRadius: 12, yRadius: 12).fill()
        (title as NSString).draw(at: NSPoint(x: x + 16, y: 851), withAttributes: [
            .font: NSFont.monospacedSystemFont(ofSize: 20, weight: .semibold), .foregroundColor: NSColor.white])
    }
    for x in [510.0, 1050.0] {
        ("→" as NSString).draw(at: NSPoint(x: x, y: 840), withAttributes: [
            .font: NSFont.systemFont(ofSize: 40), .foregroundColor: NSColor.cyan])
    }
    (card["title"] as! NSString).draw(at: NSPoint(x: 45, y: 940), withAttributes: [
        .font: NSFont.systemFont(ofSize: 28, weight: .bold), .foregroundColor: NSColor.white])
    let paragraph = NSMutableParagraphStyle(); paragraph.lineSpacing = 3
    (card["body"] as! NSString).draw(in: NSRect(x: 45, y: 25, width: 1510, height: 775), withAttributes: [
        .font: NSFont.monospacedSystemFont(ofSize: 17, weight: .regular),
        .foregroundColor: NSColor(calibratedWhite: 0.92, alpha: 1), .paragraphStyle: paragraph])
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent(card["png"] as! String))
}
'''


def _compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def scene_text(scene, claims):
    intent = scene['intent']
    pulse = None if intent is None else intent['pulse_plan']
    phase = scene['phase_evidence']
    times, temperatures = [], []
    for phases in phase.values():
        for record in phases.values():
            times.extend(record['times']);temperatures.extend(record['temperatures'])
    sizes = [] if intent is None else intent['size_records']
    if isinstance(sizes, dict):sizes = list(sizes.values())
    time = times[-1] if times else None
    temperature = temperatures[-1] if temperatures else None
    process = scene['process_time_s']
    lines = [' | '.join(claims['labels'][:2]), ' | '.join(claims['labels'][2:]), '',
        'Szenario: ' + scene['scenario_id'] + ' | Rootzustand: ' + scene['root_status'],
        'Run: ' + scene['run_id'],
        'Ereignis ' + str(scene['event_sequence']) + ': ' + scene['event_kind'] + ' | SHA256 ' + scene['event_sha256'],
        'Reaktion: ' + scene['reaction_id'],
        'Material: ' + scene['material_id'] + ' | Gefäß: ' + str(scene['vessel_id']),
        'Ort: ' + _compact(scene['location']) + ' | Restmenge: ' + _compact(scene['remaining']),
        'Root-Ressourcen gehalten: ' + str(bool(scene['resources'])) + ' | offene Operation: ' + str(scene['pending_operation'] is not None),
        '', 'S09-Absicht: ' + str(scene['intent_id'])]
    if intent is None:
        lines += ['Noch keine Sonikationsabsicht; keine Durchführung angenommen.']
    else:
        material_label = ('Material vorher/nachher: ' if intent['booking_outcome'] == 'performed'
                          else 'Material vorher / GEPLANTES Zielmaterial: ')
        lines += ['StageRun: ' + intent['stage_run_id'] + ' | Buchung: ' + intent['booking_outcome'],
            material_label + intent['material_before_id'] + ' → ' + intent['material_after_id'],
            'PULSPLAN (fiktive Planung): n=' + str(pulse['cycles']) + ', EIN=' + str(pulse['pulse_on_s'])
            + ' s, Pause zwischen Pulsen=' + str(pulse['between_pulses_s']) + ' s',
            'Plan EIN gesamt=' + str(pulse['total_on_s']) + ' s; nominale Planzeit=' + str(pulse['nominal_elapsed_s'])
            + ' s; keine Pause nach letztem Puls.']
    if time:
        lines += ['ZEITBELEG (Fixture): Start=' + str(time['start_earliest_s']) + '..' + str(time['start_latest_s'])
                  + ' s; Ende=' + str(time['end_earliest_s']) + '..' + str(time['end_latest_s']) + ' s']
    else:
        lines += ['ZEITBELEG: noch keiner; ein Pulsplan ist keine Zeitbeobachtung.']
    if temperature:
        lines += ['TEMPERATUR (Fixture): ' + str(temperature['minimum_deg_c']) + '..' + str(temperature['maximum_deg_c'])
            + ' °C; Unsicherheit=' + str(temperature['uncertainty_deg_c']) + ' °C',
            'Temperaturbeleg: ' + temperature['artifact_sha256'][:20] + '…; keine echte Gerätequalifikation.']
    else:
        lines += ['TEMPERATUR: noch kein beobachtetes Intervall.']
    if sizes:
        # Keep archived single-record cards byte-compatible. Multiple findings
        # must remain visible regardless of canonical JSON key ordering.
        if len(sizes) > 1:
            lines += [('GRÖSSENPRÜFUNG: alle erfassten Fixture-Bereiche passend; weitere S09-Gates separat.'
                       if all(value['fixture_range_conformant'] is True for value in sizes)
                       else 'GRÖSSENPRÜFUNG: WIDERSPRUCH; S09-Abschluss gesperrt.')]
        for value in sorted(sizes, key=lambda item: item['observation']['size_id']):
            observation = value['observation']
            dimensions = {name: item for name, item in observation.items()
                          if 'bp' in name and type(item) in (int, float)}
            label = ('GRÖSSENBEFUND (Fixture, bp): ' if len(sizes) == 1 else
                     'GRÖSSENBEFUND ' + observation['size_id'] + ' (Fixture, bp): ')
            lines += [label + _compact(dimensions),
                      'Originalbeleg: ' + str(observation['artifact_sha256'])[:24]
                      + '…; Fixture-Bereich passend=' + str(value['fixture_range_conformant']) + '.']
    else:
        lines += ['GRÖSSENBEFUND: noch keiner; Konzentration ersetzt keine Fragmentgröße.']
    lines += ['', 'PROZESSZEIT (synthetischer Root): ' + str(process['minimum']) + '..' + str(process['maximum']) + ' s',
        'GEMESSENE lokale Fixture-Laufzeit: ' + str(round(scene['measured_fixture_elapsed_s'], 6)) + ' s',
        'VIDEOZEIT: ' + str(scene['video_time_s']) + ' s; ' + str(claims['time_axes']['video_event_interval_s'])
        + ' s/Ereignis, ereignisweise gerafft.',
        'Pfeile zeigen den Zusammenhang. Keine Bahn, kein Scan, keine Geräteausführung.']
    if scene.get('process_evidence'):
        lines += ['Szenario-Prozessnachweis: Child SIGKILL / Exit -9; Absicht persistiert; kein Effekt-Replay.',
                  'Nachträglich für das Szenario aufgezeichnet; kein Zeitnachweis des einzelnen Ereignisses.']
    return '\n'.join(lines)


def scene_cards(derived):
    return [{'title': 'CUT&RUN-Input: Sonikation | Schematische Darstellung',
             'body': scene_text(scene, derived['claims']), 'png': '%06d.png' % index}
            for index, scene in enumerate(derived['scenes'], 1)]


def render(input_path, *, seconds_per_event=0.5):
    input_path = output_path(input_path);base = input_path.parent
    require(not (base / 'manifest.json').exists(), 'Evidence already rendered; use --check or a new bundle')
    derived = derive(input_path, seconds_per_event);tools = versions()
    frames = base / 'frames';frames.mkdir(exist_ok=False)
    records = {item['path']: item for item in derived['files']}
    cards = scene_cards(derived)
    for index, card in enumerate(cards, 1):
        text_path = write_new(frames / ('%06d.txt' % index), card['body'].encode())
        records[str(text_path.relative_to(base))] = file_record(text_path, 'scene_text', base)
    scenes_path = write_json(base / 'scenes.json', derived['scenes'])
    cards_path = write_json(base / 'render-cards.json', cards)
    swift_path = write_new(base / 'renderer.swift', SWIFT.encode())
    tools_path = write_json(base / 'tool-versions.json', tools)
    binary = base / 'renderer-appkit';cache = base / 'tool-cache';cache.mkdir(exist_ok=False)
    env = {**os.environ, 'CLANG_MODULE_CACHE_PATH': str(cache), 'SWIFT_MODULECACHE_PATH': str(cache)}
    run([tools['tools']['swiftc'], '-module-cache-path', str(cache), str(swift_path), '-o', str(binary)], env=env)
    run([str(binary), str(cards_path), str(frames)], env=env)
    for index in range(1, len(cards) + 1):
        image = frames / ('%06d.png' % index);records[str(image.relative_to(base))] = file_record(image, 'scene_png', base)
    video = base / 'sonication-evidence.mp4'
    run([tools['tools']['ffmpeg'], '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
         '-framerate', str(1 / derived['seconds_per_event']), '-i', str(frames / '%06d.png'),
         '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
         '-movflags', '+faststart', str(video)])
    stream = probe_video(video)
    for path, role in [(scenes_path, 'scenes'), (cards_path, 'renderer_input'), (swift_path, 'native_renderer_source'),
                       (binary, 'compiled_renderer'), (video, 'schematic_video'), (tools_path, 'tool_versions')]:
        records[str(path.relative_to(base))] = file_record(path, role, base)
    manifest = {'format': MANIFEST_FORMAT, **derived, 'files': sorted(records.values(), key=lambda item: item['path']),
        'tools': tools, 'render': {'width': WIDTH, 'height': HEIGHT, 'frame_count': len(cards),
            'video': video.name, 'scenes': scenes_path.name, 'cards': cards_path.name,
            'renderer_source': swift_path.name, 'renderer_binary': binary.name,
            'tool_versions': tools_path.name,
            'video_duration_s': float(stream['duration']), 'video_codec': stream['codec_name'],
            'visual_review': {'reviewed': False, 'frames': inspection_frames(len(cards)),
                              'record': None, 'source_manifest': None}}}
    path = write_json(base / 'manifest.json', manifest);check_manifest(path)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--seconds-per-event', type=float, default=0.5)
    args = parser.parse_args(argv)
    try:
        if args.check:
            value = check_manifest(args.path)
            print(json.dumps({'checked': True, 'frames': value['render']['frame_count']}))
        else:
            path = render(args.path, seconds_per_event=args.seconds_per_event)
            value = check_manifest(path)
            print(json.dumps({'manifest': str(path), 'visual_review_frames': value['render']['visual_review']['frames']}))
        return 0
    except (TaskError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
