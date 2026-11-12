"""Evidence mutation tests use only disposable fixture bytes, never media."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import material_ledger as ledger
from manual_tasks import TaskError, encoded
import sonication_evidence as evidence
import render_sonication_evidence as renderer


class FixtureJournal:
    """Real SQL documents with a tiny independent read-only artifact store."""
    def __init__(self, definition):
        self.connection = sqlite3.connect(':memory:')
        self.connection.execute('CREATE TABLE events(run_id TEXT,sequence INTEGER,document TEXT,sha256 TEXT)')
        self.original = b'Explicit unit-test original, not laboratory evidence.\n'
        self.original_sha = evidence.sha(self.original)
        self.artifacts = {self.original_sha: self.original}
        self.definition = definition
        definition['initial_artifact_sha256'] = [self.original_sha]
        content = encoded(definition).encode()
        self.definition_sha = evidence.sha(content)
        self.artifacts[self.definition_sha] = content

    def artifact(self, checksum):
        content = self.artifacts.get(checksum)
        if content is None or evidence.sha(content) != checksum:
            raise TaskError('Missing or corrupt fixture original')
        return content

    def append(self, run_id, state, kind):
        previous = self.connection.execute('SELECT sequence,sha256 FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1',
                                           (run_id,)).fetchone()
        sequence = 1 if previous is None else previous[0] + 1
        event = {'run_id': run_id, 'sequence': sequence, 'event_id': 'Fixture.' + str(sequence),
            'time_unix_s': 1 + sequence, 'previous_sha256': None if previous is None else previous[1],
            'kind': kind, 'payload': {}, 'state': copy.deepcopy(state),
            'storage_format': 'solidcraftbot.task-event/2', 'definition_sha256': self.definition_sha}
        document = encoded(event)
        self.connection.execute('INSERT INTO events VALUES(?,?,?,?)',
            (run_id, sequence, document, evidence.sha(document.encode())))

    def history(self, run_id):
        events, previous = [], None
        for sequence, document, checksum in self.connection.execute(
                'SELECT sequence,document,sha256 FROM events WHERE run_id=? ORDER BY sequence', (run_id,)):
            event = json.loads(document)
            if evidence.sha(document.encode()) != checksum or event['previous_sha256'] != previous:
                raise TaskError('Corrupt fixture journal')
            event['state']['definition'] = copy.deepcopy(self.definition)
            events.append({**event, 'sha256': checksum})
            previous = checksum
        return events


class SonicationEvidenceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='sonication-evidence-unit-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.boundary = self.directory / 'evidence'
        boundary = patch.object(evidence, 'EVIDENCE', self.boundary)
        boundary.start();self.addCleanup(boundary.stop)
        self.source_root = self.directory / 'repository'
        (self.source_root / 'model').mkdir(parents=True)
        self.source = self.source_root / 'model/fixture-source.txt'
        self.source.write_bytes(b'Explicit source snapshot.\n')
        pins = {'model/fixture-source.txt': evidence.sha(self.source.read_bytes())}
        self.definition = {'format': 'solidcraftbot.material-workflow-definition/3',
            'profile': {'type': evidence.ENGINE}, 'clock_source_kind': 'test_clock',
            'source_files_sha256': pins, 'runtime_profile': {'enabled': True},
            'sonication_plan': {'fragment_size': {'comparison_target': {'minimum': 100, 'maximum': 600},
                'column_maximum_exclusive_bp': {'value': 10000}}}}
        self.journal = FixtureJournal(self.definition)
        self.addCleanup(self.journal.connection.close)
        self.run_id = 'Fixture.Sonication.Evidence'
        self.material_id, self.output_id, self.vessel_id = 'Fixture.Input', 'Fixture.Sonicated', 'Fixture.Tube'
        inventory = ledger.initial_inventory([
            {'id': self.material_id, 'kind': 'control', 'vessel_id': self.vessel_id,
             'quantity': {'value': 300, 'unit': 'uL'}, 'origin_id': 'Fixture.Culture'}],
            [{'id': self.vessel_id, 'location': {'kind': 'rack', 'rack_id': 'Fixture.Rack', 'place_id': 'P01'}}])
        self.state = {'format': 'solidcraftbot.material-workflow-state/3', 'status': 'working',
            'session': 'Fixture.Session', 'inventory': inventory, 'bookings': {},
            'resources': ['rack:Fixture.Rack', 'vessel:' + self.vessel_id], 'pending_operation': None,
            'recovery_required': None, 'observation_context': None,
            'clock': {'lower_s': 0, 'upper_s': 0},
            'manual': {'engine': evidence.ENGINE, 'actions': {}, 'qc_artifacts': {},
                'reactions': {'Fixture.Reaction.Input': {'role': 'input', 'current_material_id': self.material_id}}},
            'sop': {'engine': evidence.ENGINE, 'stages': {}, 'artifacts': {}, 'evidence': {}}}
        self.journal.append(self.run_id, self.state, 'created')
        pulse = {'cycles': 3, 'pulse_on_s': 7, 'between_pulses_s': 2, 'total_on_s': 21,
            'total_between_pulses_s': 4, 'nominal_elapsed_s': 25, 'energy_delivered_j': None, 'executed': False}
        self.meta = {'reaction_id': 'Fixture.Reaction.Input', 'stage_run_id': 'Fixture.Stage.S09',
            'material_before_id': self.material_id, 'material_after_id': self.output_id, 'vessel_id': self.vessel_id,
            'quantity_before': {'value': 300, 'unit': 'uL'},
            'original_rack_location': {'kind': 'rack', 'rack_id': 'Fixture.Rack', 'place_id': 'P01'},
            'intent_session': self.state['session'], 'pulse_plan': pulse, 'size_records': {},
            'physical_receipt': None, 'source_pins_sha256': evidence.sha(encoded(pins).encode())}
        self.state['sop']['stages']['Fixture.Stage.S09'] = {'id': 'Fixture.Stage.S09', 'stage_id': 'S09',
            'reaction_id': 'Fixture.Reaction.Input', 'material_id': self.material_id, 'vessel_id': self.vessel_id,
            'status': 'open', 'phases': {'S09.input_preparation': {'times': [], 'temperatures': []}}}
        self.state['manual']['actions']['Fixture.Intent'] = {'operation': 'material', 'sonication': self.meta}
        self.state['bookings']['Fixture.Intent'] = {'outcome': 'intent',
            'request': {'kind': 'transformation', 'inputs': [{'material_id': self.material_id,
                'quantity': {'value': 300, 'unit': 'uL'}}], 'outputs': []},
            'actual_inputs': [], 'actual_outputs': []}
        self.state['clock'] = {'lower_s': 1, 'upper_s': 1}
        self.journal.append(self.run_id, self.state, 'begin_sonication')
        self.state['bookings']['Fixture.Intent'].update(outcome='performed',
            actual_inputs=[{'material_id': self.material_id, 'quantity': {'value': 300, 'unit': 'uL'}}],
            actual_outputs=[{'material_id': self.output_id, 'quantity': {'value': 300, 'unit': 'uL'}}])
        self.state['inventory']['materials'][self.output_id] = {
            **copy.deepcopy(self.state['inventory']['materials'][self.material_id]), 'id': self.output_id,
            'kind': 'intermediate', 'parents': [self.material_id]}
        self.state['manual']['reactions']['Fixture.Reaction.Input']['current_material_id'] = self.output_id
        self.state['clock'] = {'lower_s': 26, 'upper_s': 26}
        self.state['bookings']['Fixture.QC'] = {'outcome': 'performed',
            'request': {'kind': 'withdrawal', 'inputs': [{'material_id': self.output_id,
                'quantity': {'value': 5, 'unit': 'uL'}}], 'outputs': []},
            'actual_inputs': [{'material_id': self.output_id, 'quantity': {'value': 5, 'unit': 'uL'}}], 'actual_outputs': []}
        self.meta['size_records']['Fixture.Size'] = {'observation': {
            'size_id': 'Fixture.Size', 'withdrawal_intent_id': 'Fixture.QC', 'material_id': self.output_id,
            'vessel_id': self.vessel_id, 'minimum_bp': 150, 'maximum_bp': 450, 'unit': 'bp',
            'artifact_sha256': self.journal.original_sha, 'reason': 'Explicit size fixture'},
            'fixture_range_conformant': True, 'biological_acceptance': False, 'receipt': {'evidence': 'test_fixture'}}
        self.state['sop']['stages']['Fixture.Stage.S09']['status'] = 'completed'
        self.journal.append(self.run_id, self.state, 'complete_sonication')
        trace = self.journal.history(self.run_id)
        self.report = {key: copy.deepcopy(self.state[key]) for key in
            ('status', 'inventory', 'bookings', 'resources', 'clock', 'pending_operation', 'recovery_required')}
        self.report.update(run_id=self.run_id, trace=trace, source_files_sha256=pins,
            remaining={identity: ledger.remaining(self.state, identity) for identity in self.state['inventory']['materials']},
            execution_ready=False, hardware_executed=False, network_executed=False,
            sonication={'enabled': True, 'mode': 'test_fixture_only', 'source_pins': pins,
                'pending_intents': [], 'flags': {'hardware_executed': False, 'ros_executed': False},
                'intents': {'Fixture.Intent': {**copy.deepcopy(self.meta), 'booking_outcome': 'performed',
                                              'continuation_uncertain': False}}})
        self.measurement = {'basis': 'perf_counter_ns_after_event', 'elapsed_wall_s': 0.4,
            'events': [{'sequence': n, 'elapsed_wall_s': n / 10} for n in range(1, 4)]}

    def export(self, *, scenario='normal', report=None, measurement=None, directory='bundle', process=None):
        item = {'scenario_id': scenario, 'run_id': self.run_id,
            'report': self.report if report is None else report,
            'measurement': self.measurement if measurement is None else measurement}
        if process is not None:item['process_evidence'] = process
        return evidence.export_bundle(self.journal, [item],
            self.boundary / directory, source_root=self.source_root)

    def change_input_file(self, input_path, relative, value):
        data = evidence.read_json(input_path)
        target = input_path.parent / relative
        target.write_bytes(evidence.json_bytes(value))
        for record in data['files']:
            if record['path'] == relative:
                record.update(sha256=evidence.sha(target.read_bytes()), bytes=target.stat().st_size)
        input_path.write_bytes(evidence.json_bytes(data))

    def fake_manifest(self, input_path):
        derived = evidence.derive(input_path);base = input_path.parent
        frames = base / 'frames';frames.mkdir()
        rows = {item['path']: item for item in derived['files']}
        cards = renderer.scene_cards(derived)
        png = b'\x89PNG\r\n\x1a\n' + (13).to_bytes(4, 'big') + b'IHDR' + (1600).to_bytes(4, 'big') + (1000).to_bytes(4, 'big')
        for index, card in enumerate(cards, 1):
            for suffix, content, role in [('.txt', card['body'].encode(), 'scene_text'), ('.png', png, 'scene_png')]:
                path = frames / ('%06d' % index + suffix);path.write_bytes(content)
                rows[str(path.relative_to(base))] = evidence.file_record(path, role, base)
        tools = {'fixture': 'Explicit fake tool bytes for checker unit tests only'}
        for name, content, role in [('scenes.json', evidence.json_bytes(derived['scenes']), 'scenes'),
                ('render-cards.json', evidence.json_bytes(cards), 'renderer_input'),
                ('renderer.swift', b'unit-test fixture source', 'native_renderer_source'),
                ('renderer-appkit', b'unit-test fixture binary', 'compiled_renderer'),
                ('sonication-evidence.mp4', b'unit-test fixture video', 'schematic_video'),
                ('tool-versions.json', evidence.json_bytes(tools), 'tool_versions')]:
            path = base / name;path.write_bytes(content);rows[name] = evidence.file_record(path, role, base)
        manifest = {'format': evidence.MANIFEST_FORMAT, **derived, 'files': list(rows.values()), 'tools': tools,
            'render': {'width': 1600, 'height': 1000, 'frame_count': len(cards),
                'video': 'sonication-evidence.mp4', 'scenes': 'scenes.json', 'cards': 'render-cards.json',
                'renderer_source': 'renderer.swift', 'renderer_binary': 'renderer-appkit', 'tool_versions': 'tool-versions.json',
                'video_duration_s': len(cards) * 0.5, 'video_codec': 'h264',
                'visual_review': {'reviewed': False, 'frames': evidence.inspection_frames(len(cards)),
                                  'record': None, 'source_manifest': None}}}
        path = base / 'manifest.json';path.write_bytes(evidence.json_bytes(manifest))
        return path

    def probe(self):
        return patch.object(renderer, 'probe_video', return_value={'codec_name': 'h264', 'width': 1600,
            'height': 1000, 'nb_frames': '3', 'duration': '1.5'})

    def test_export_preserves_exact_sql_documents_chain_and_originals(self):
        rows = self.journal.connection.execute('SELECT * FROM events').fetchall()
        path = self.export()
        data = evidence.read_json(path);journal_path = path.parent / data['scenarios'][0]['journal']
        archive, events, artifacts = evidence.verify_journal(journal_path)
        self.assertEqual([row['document'] for row in archive['events']], [row[2] for row in rows])
        self.assertEqual(events[-1]['sha256'], archive['chain_head_sha256'])
        self.assertEqual(artifacts[self.journal.original_sha].read_bytes(), self.journal.original)
        self.assertEqual(rows, self.journal.connection.execute('SELECT * FROM events').fetchall())

    def test_scene_ids_clock_axes_fixture_flags_and_canonical_qc_balance(self):
        value = evidence.derive(self.export());scene = value['scenes'][-1]
        self.assertEqual(scene['intent']['pulse_plan']['nominal_elapsed_s'], 25)
        self.assertEqual(scene['remaining'], {'value': 295.0, 'unit': 'uL', 'knowledge': 'known'})
        self.assertEqual((scene['run_id'], scene['reaction_id'], scene['vessel_id']),
            (self.run_id, 'Fixture.Reaction.Input', self.vessel_id))
        self.assertEqual((scene['process_time_s']['minimum'], scene['measured_fixture_elapsed_s'], scene['video_time_s']), (26, 0.3, 1.0))
        self.assertFalse(any(value['claims'][name] for name in
            ('network_executed','sila_executed','ros_executed','hardware_executed','robot_motion_executed')))

    def test_source_snapshots_remain_valid_after_live_fixture_source_changes(self):
        path = self.export();self.source.write_bytes(b'A later independent source revision.\n')
        self.assertEqual(len(evidence.derive(path)['scenes']), 3)

    def test_archived_source_byte_change_is_rejected(self):
        path = self.export();data = evidence.read_json(path)
        source = path.parent / next(iter(data['scenarios'][0]['source_snapshots'].values()))
        source.write_bytes(source.read_bytes() + b'!')
        with self.assertRaisesRegex(TaskError, 'checksum'):evidence.derive(path)

    def test_artifact_byte_change_is_rejected(self):
        path = self.export();artifact = next((path.parent / 'inputs/artifacts').glob('*.bin'))
        artifact.write_bytes(artifact.read_bytes() + b'!')
        with self.assertRaisesRegex(TaskError, 'checksum'):evidence.derive(path)

    def test_raw_journal_chain_head_mutation_reaches_chain_verification(self):
        path = self.export();data = evidence.read_json(path);name = data['scenarios'][0]['journal']
        changed = evidence.read_json(path.parent / name);changed['chain_head_sha256'] = '0' * 64
        self.change_input_file(path, name, changed)
        with self.assertRaisesRegex(TaskError, 'chain head'):evidence.derive(path)

    def test_raw_document_mutation_is_not_hidden_by_file_rehash(self):
        path = self.export();data = evidence.read_json(path);name = data['scenarios'][0]['journal']
        changed = evidence.read_json(path.parent / name)
        changed['events'][1]['document'] += ' '
        self.change_input_file(path, name, changed)
        with self.assertRaisesRegex(TaskError, 'document checksum'):evidence.derive(path)

    def test_report_balance_cannot_be_rewritten_with_coherent_file_hash(self):
        path = self.export();data = evidence.read_json(path);name = data['scenarios'][0]['report']
        changed = evidence.read_json(path.parent / name);changed['remaining'][self.output_id]['value'] = 300
        self.change_input_file(path, name, changed)
        with self.assertRaisesRegex(TaskError, 'material balance'):evidence.derive(path)

    def test_report_intent_binding_cannot_be_rewritten_with_coherent_file_hash(self):
        path = self.export();data = evidence.read_json(path);name = data['scenarios'][0]['report']
        changed = evidence.read_json(path.parent / name);changed['sonication']['intents']['Fixture.Intent']['vessel_id'] = 'Wrong.Tube'
        self.change_input_file(path, name, changed)
        with self.assertRaisesRegex(TaskError, 'canonical action'):evidence.derive(path)

    def test_measurement_requires_exact_event_coverage_and_real_time_basis(self):
        for mutation in ('basis', 'coverage', 'order', 'nan'):
            with self.subTest(mutation=mutation):
                measurement = copy.deepcopy(self.measurement)
                if mutation == 'basis':measurement['basis'] = 'synthetic-clock'
                if mutation == 'coverage':measurement['events'].pop()
                if mutation == 'order':measurement['events'][1]['elapsed_wall_s'] = 0
                if mutation == 'nan':measurement['elapsed_wall_s'] = float('nan')
                with self.assertRaises((TaskError, ValueError)):
                    self.export(measurement=measurement, directory='bad-' + mutation)

    def test_output_escape_collision_and_existing_bundle_are_rejected(self):
        with self.assertRaises(TaskError):evidence.output_path(ROOT / 'docs/media/new.mp4')
        with self.assertRaises(TaskError):evidence.output_path(self.boundary)
        self.export()
        with self.assertRaises(FileExistsError):self.export()
        with self.assertRaises(TaskError):self.export(scenario='../escape', directory='escape')

    def test_source_and_implementation_closures_are_archived(self):
        path = self.export();data = evidence.read_json(path)
        self.assertIn('scripts/manual_tasks.py', data['implementation_sources'])
        self.assertIn('scripts/render_dna_evidence.py', data['implementation_sources'])
        for name, item in data['implementation_sources'].items():
            self.assertEqual(evidence.sha((path.parent / item['path']).read_bytes()), item['sha256'])
        self.assertEqual(data['provenance']['assignment'],
            'Base commit plus these archived working bytes; not an uncreated future commit')

    def test_source_file_omitted_from_byte_inventory_is_rejected(self):
        path = self.export();data = evidence.read_json(path)
        source = next(iter(data['scenarios'][0]['source_snapshots'].values()))
        data['files'] = [item for item in data['files'] if item['path'] != source]
        path.write_bytes(evidence.json_bytes(data))
        with self.assertRaisesRegex(TaskError, 'not byte-pinned'):evidence.derive(path)

    def test_scene_text_keeps_values_and_claims_separate(self):
        value = evidence.derive(self.export());text = renderer.scene_text(value['scenes'][-1], value['claims'])
        for text_piece in ['25', '21', '150', '450', '295', 'PROZESSZEIT', 'GEMESSENE', 'VIDEOZEIT', 'keine Hardware']:
            self.assertIn(text_piece, text)
        self.assertNotIn('SiLA-Loopback ausgeführt', text)

    def test_process_receipt_cannot_invent_a_restart_for_normal_trace(self):
        process = {'worker_exit_code': -9, 'signal': 'SIGKILL',
                   'intent_persisted_before_kill': True, 'effect_replayed': False}
        with self.assertRaisesRegex(TaskError, 'persisted intent and later explicit uncertain resume'):
            self.export(process=process)

    def test_process_receipt_is_bound_to_uncertain_resume_and_one_confirmation(self):
        self.journal.connection.execute('DELETE FROM events WHERE sequence=3')
        pending = json.loads(self.journal.connection.execute('SELECT document FROM events WHERE sequence=2').fetchone()[0])['state']
        pending['session'] = 'Fixture.Reopened';pending['recovery_required'] = 'manual_session_restarted'
        self.journal.append(self.run_id, pending, 'manual_session_opened')
        self.state['session'] = 'Fixture.Reopened'
        self.journal.append(self.run_id, self.state, 'complete_sonication')
        self.report['trace'] = self.journal.history(self.run_id)
        measurement = {'basis':'perf_counter_ns_after_event','elapsed_wall_s':0.5,
            'events':[{'sequence':n,'elapsed_wall_s':n/10} for n in range(1,5)]}
        process = {'worker_exit_code': -9, 'signal': 'SIGKILL',
                   'intent_persisted_before_kill': True, 'effect_replayed': False}
        value = evidence.derive(self.export(process=process, measurement=measurement))
        self.assertEqual(value['scenarios'][0]['process_evidence'], process)
        self.assertIn('nachträglich', renderer.scene_text(value['scenes'][-1], value['claims']).lower())

    def test_manifest_roundtrip_does_not_claim_visual_review(self):
        path = self.fake_manifest(self.export())
        with self.probe():value = evidence.check_manifest(path)
        self.assertFalse(value['render']['visual_review']['reviewed'])

    def test_rendered_png_or_video_byte_change_is_rejected(self):
        for name in ['frames/000002.png', 'sonication-evidence.mp4']:
            with self.subTest(name=name):
                path = self.fake_manifest(self.export(directory='bytes-' + name.replace('/', '-')))
                target = path.parent / name;target.write_bytes(target.read_bytes() + b'!')
                with self.probe(), self.assertRaisesRegex(TaskError, 'checksum'):evidence.check_manifest(path)

    def test_manifest_hardware_claim_tool_version_or_extra_field_cannot_be_invented(self):
        for mutation in ('claim', 'tools', 'extra'):
            with self.subTest(mutation=mutation):
                path = self.fake_manifest(self.export(directory=mutation));value = evidence.read_json(path)
                if mutation == 'claim':value['claims']['hardware_executed'] = True
                if mutation == 'tools':value['tools']['fixture'] = 'invented'
                if mutation == 'extra':value['invented_hardware_executed'] = True
                path.write_bytes(evidence.json_bytes(value))
                with self.probe(), self.assertRaises(TaskError):evidence.check_manifest(path)

    def test_ffprobe_result_must_match_frame_count_and_duration(self):
        path = self.fake_manifest(self.export())
        with patch.object(renderer, 'probe_video', return_value={'codec_name':'h264', 'width':1600,
                'height':1000, 'nb_frames':'2', 'duration':'1.5'}), self.assertRaisesRegex(TaskError, 'Encoded video'):
            evidence.check_manifest(path)

    def test_visual_review_requires_explicit_frames_and_preserves_original_manifest(self):
        path = self.fake_manifest(self.export());before = path.read_bytes()
        with self.probe(), self.assertRaises(TaskError):
            evidence.record_visual_review(path, inspected_frames=[], note='Unit-test invalid review')
        self.assertEqual(path.read_bytes(), before)

    def test_manifest_missing_scene_text_record_is_rejected(self):
        path = self.fake_manifest(self.export());value = evidence.read_json(path)
        value['files'] = [item for item in value['files'] if item['path'] != 'frames/000002.txt']
        path.write_bytes(evidence.json_bytes(value))
        with self.probe(), self.assertRaisesRegex(TaskError, 'Rendered text'):evidence.check_manifest(path)


if __name__ == '__main__':
    unittest.main()
