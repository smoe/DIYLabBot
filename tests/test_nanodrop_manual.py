"""Synthetic human tasks: identity, custody, consumption, import and crash recovery."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError, digest
from nanodrop_csv import parse_report
from nanodrop_manual import (SOURCE, Workflow, ObservationError, inventory_observations,
                             load_profile, original_location)

FIXTURES = ROOT / 'tests/fixtures/nanodrop'
ACTOR = 'SYN.Operator01'
RUN_ID = 'SYN-ND-FIXTURE'


class ReportAdapterTests(unittest.TestCase):
    def test_synthetic_reports_preserve_order_cells_units_and_multiple_metrics(self):
        for name in ['one-synthetic.csv', 'ultrac-synthetic.csv']:
            report = parse_report((FIXTURES / name).read_bytes())
            by_id = {row['measurement_id']: row for row in report['rows']}
            first = by_id[RUN_ID + '.A01.M001']
            self.assertEqual(first['metrics']['concentration'], {'value': 11, 'unit': 'ng/uL'})
            self.assertEqual(first['metrics']['a260_a280'], {'value': 1.8, 'unit': '1'})
            self.assertEqual(first['metrics']['a260']['unit'], '1')
            self.assertIsNone(first['metrics']['factor']['unit'])
            self.assertEqual(first['instrument_messages']['Warnings'], 'SYNTHETIC DATA')
            self.assertIn('Sample Name', first['raw_cells'])
            self.assertNotEqual(report['rows'][0]['measurement_id'], RUN_ID + '.A01.M001')

    def test_utf16_bom_and_tab_delimited_report(self):
        report = parse_report('Sample Name\tng/µL\tWarnings\r\nM1\t1,5\tSYNTHETIC\r\n'.encode('utf-16'))
        self.assertEqual(report['rows'][0]['metrics']['concentration']['value'], 1.5)
        self.assertIsNone(report['rows'][0]['metrics']['a260_a230']['value'])

    def test_negative_reported_values_are_preserved_for_explicit_review(self):
        report = parse_report(b'Sample Name,ng/uL,A260/A280\nM1,-0.1,-2.0\n')
        self.assertEqual(report['rows'][0]['metrics']['concentration']['value'], -0.1)

    def test_invalid_headers_units_numbers_identity_and_structure_are_rejected(self):
        cases = [b'Sample Name,mg/mL\nM1,2\n',
                 b'Sample Name,ng/uL,ng/uL\nM1,2,3\n',
                 b'Sample Name,ng/uL\n,2\n',
                 b'Sample Name,ng/uL\nM1,2,3\n',
                 b'Sample Name,ng/uL\nM1,NaN\n',
                 b'Sample Name,ng/uL\nM1,Infinity\n',
                 b'Sample Name,ng/uL\nM1,\n',
                 b'Sample Name,ng/uL\n', b'\xff\x00broken',
                 b'Application:,dsDNA\nApplication:,RNA\nSample Name,ng/uL\nM1,2\n']
        for content in cases:
            with self.subTest(content=content), self.assertRaises(TaskError):
                parse_report(content)


class ProfileTests(unittest.TestCase):
    def test_shared_capability_protocol_and_rack_references(self):
        one = load_profile()
        other = copy.deepcopy(one['profile'])
        other['instrument']['type'] = 'nanodrop_ultrac'
        ultra = load_profile(other)
        self.assertEqual(one['protocol'], ultra['protocol'])
        self.assertEqual(one['places'], ultra['places'])
        self.assertEqual(one['places'][0]['id'], 'CF01.OutputRack.Slot01')
        self.assertNotIn('geometry', one['instrument_type'])
        self.assertIn('cuvette_absorbance', ultra['instrument_type']['capabilities'])

    def test_invalid_parameters_and_unsupported_execution_are_rejected(self):
        base = json.loads(SOURCE.read_text())
        cases = []
        for key, value in [('sample_volume_ul', 0), ('sample_volume_ul', True),
                           ('sample_volume_ul', float('nan')), ('task_deadline_s', -1)]:
            data = copy.deepcopy(base)
            data['parameters'][key] = value
            cases.append(data)
        for change in [{'mode': 'hardware'}, {'unexpected': True}, {'samples': []}]:
            cases.append({**copy.deepcopy(base), **change})
        data = copy.deepcopy(base)
        data['parameters']['unimplemented_parameter'] = 1
        cases.append(data)
        data = copy.deepcopy(base)
        data['protocol']['source_sha256'] = '0' * 64
        cases.append(data)
        data = copy.deepcopy(base)
        data['workspace']['frame'] = 'MissingFrame'
        cases.append(data)
        data = copy.deepcopy(base)
        data['samples'][1]['vessel_id'] = data['samples'][0]['vessel_id']
        cases.append(data)
        data = copy.deepcopy(base)
        data['samples'][0]['rack_slot'] = 99
        cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_profile(data)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='nanodrop-cli-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.store = self.folder / 'tasks.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_nanodrop_manual.py'),
                                 '--store', str(self.store), *arguments],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def test_cli_demo_report_and_original_artifact_roundtrip(self):
        result = self.cli('demo', '--run-id', 'SYN-ND-CLI')
        card = json.loads(result.stdout)
        self.assertEqual(card['status'], 'completed')
        self.assertTrue(card['sop']['synthetic'])
        report_file = self.folder / 'report.json'
        self.cli('report', 'SYN-ND-CLI', '--out', str(report_file))
        report = json.loads(report_file.read_text())
        self.assertTrue(report['passed'])
        self.assertTrue(report['order_restored'])
        checksum = next(iter(report['imports']))
        exported = self.folder / 'original.csv'
        self.cli('artifact', checksum, '--out', str(exported))
        self.assertEqual(digest(exported.read_bytes()), checksum)
        self.assertEqual(exported.read_bytes(), (self.folder / 'SYN-ND-CLI/synthetic-report.csv').read_bytes())

    def test_cli_resumed_session_cannot_confirm_without_reconciliation(self):
        result = self.cli('demo', '--run-id', 'SYN-ND-CLI-PAUSED', '--pause-after-intent')
        card = json.loads(result.stdout)
        intent = card['pending_measurement']['intent_id']
        actions = self.folder / 'actions.jsonl'
        request = {'command': 'confirm_measurement', 'actor_id': ACTOR,
                   'data': {'intent_id': intent, 'observed_sample_id': 'Sample01',
                            'volume_ul': 1.5, 'cleaned': True}}
        actions.write_text(json.dumps(request) + '\n')
        failure = self.cli('session', 'SYN-ND-CLI-PAUSED', '--actions', str(actions), expected=1)
        self.assertIn('reconciliation', failure.stderr)
        status = json.loads(self.cli('status', 'SYN-ND-CLI-PAUSED').stdout)
        self.assertEqual(status['recovery_required'], 'session_restarted')
        self.assertEqual(len(status['resources']), 3)
        self.assertEqual(status['pending_measurement']['intent_id'], intent)

    def test_cli_rejects_runtime_output_outside_exports(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_nanodrop_manual.py'),
                                 '--store', str(ROOT / 'model/forbidden-runtime.sqlite3'), 'demo'],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertIn('exports/', result.stderr)
        self.assertFalse((ROOT / 'model/forbidden-runtime.sqlite3').exists())


class ManualTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'tasks.sqlite3'
        self.now = [1000.0]
        self.journal = Journal(self.path, clock=lambda: self.now[0])
        self.flow = Workflow.create(self.journal, run_id=RUN_ID)

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def claim(self, flow=None):
        flow = flow or self.flow
        flow.act('rack_ready', ACTOR, observations=inventory_observations(flow.state))
        flow.act('workspace_clear', ACTOR, confirmed=True)
        flow.act('claim', ACTOR)
        flow.act('blank', ACTOR, reference_id='SYN.Buffer01', cleaned=True)

    def take(self, sample_id='Sample01', flow=None):
        flow = flow or self.flow
        sample = flow.state['samples'][sample_id]
        flow.act('take', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                 place_id=sample['location']['place_id'], rack_id=sample['location']['rack_id'])

    def begin(self, sample_id='Sample01', flow=None):
        flow = flow or self.flow
        flow.act('begin_measurement', ACTOR, sample_id=sample_id,
                 measurement_id=flow.state['planned_measurements'][sample_id])
        return flow.state['pending_measurement']['intent_id']

    def confirm(self, sample_id='Sample01', flow=None, **changes):
        flow = flow or self.flow
        pending = flow.state['pending_measurement']
        data = {'intent_id': pending['intent_id'] if pending else changes.get('intent_id'),
                'observed_sample_id': sample_id, 'volume_ul': 1.5, 'cleaned': True}
        flow.act('confirm_measurement', ACTOR, **{**data, **changes})

    def place(self, sample_id='Sample01', flow=None):
        flow = flow or self.flow
        sample = flow.state['samples'][sample_id]
        flow.act('place', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                 place_id=sample['original_place_id'],
                 rack_id=flow.state['definition']['profile']['rack']['id'])

    def measure_all(self, flow=None):
        flow = flow or self.flow
        for sample_id in flow.state['samples']:
            self.take(sample_id, flow)
            self.begin(sample_id, flow)
            self.confirm(sample_id, flow)
            self.place(sample_id, flow)

    def import_content(self, content=None, flow=None):
        flow = flow or self.flow
        content = content if content is not None else (FIXTURES / 'one-synthetic.csv').read_bytes()
        flow.act('import_results', ACTOR, artifact=content, file_name='synthetic.csv')
        return digest(content)

    def review(self, flow=None):
        (flow or self.flow).act('review_results', ACTOR, decision='accepted', reason='Synthetic test decision')

    def reconcile(self, flow=None, **changes):
        flow = flow or self.flow
        data = {'observations': inventory_observations(flow.state),
                'workspace_clear': False, 'blank_still_valid': True}
        return flow.act('reconcile', ACTOR, **{**data, **changes})

    def test_full_run_maps_reordered_results_and_preserves_lineage_and_unknown_volume(self):
        self.claim()
        self.assertEqual(len(self.journal.owners()), 3)
        self.assertTrue(all(s['location']['kind'] == 'rack' for s in self.flow.state['samples'].values()))
        self.measure_all()
        checksum = self.import_content()
        self.assertFalse(self.flow.report()['passed'])
        with self.assertRaisesRegex(TaskError, 'review'):
            self.flow.act('release', ACTOR, workspace_clear=True)
        self.review()
        self.flow.act('release', ACTOR, workspace_clear=True)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertTrue(report['order_restored'])
        self.assertEqual(self.journal.owners(), {})
        self.assertEqual(self.journal.artifact(checksum), (FIXTURES / 'one-synthetic.csv').read_bytes())
        for index, sample_id in enumerate(['Sample01', 'Sample02', 'Sample03'], 1):
            name = self.flow.state['planned_measurements'][sample_id]
            self.assertEqual(report['results'][name]['metrics']['concentration']['value'], index * 11)
            self.assertEqual(report['results'][name]['sample_id'], sample_id)
            self.assertEqual(report['measurements'][name]['parent_sample_id'], sample_id)
            self.assertEqual(report['measurements'][name]['withdrawn_volume'], {'value': 1.5, 'unit': 'uL'})
            self.assertFalse(report['samples'][sample_id]['mass_confirmation_valid'])
        self.assertEqual(report['samples']['Sample01']['remaining_volume_ul'], 38.5)
        self.assertIsNone(report['samples']['Sample03']['remaining_volume_ul'])
        for flag in ['network_executed', 'hardware_executed', 'robot_motion_executed',
                     'safety_function_qualified', 'real_export_validated', 'cf01_continuation_executed']:
            self.assertFalse(report[flag], flag)
        self.assertTrue(all(event['payload'].get('evidence', 'synthetic_input') == 'synthetic_input'
                            for event in report['trace']))

    def test_ultrac_uses_identical_workflow_and_decimal_comma_adapter(self):
        data = json.loads(SOURCE.read_text())
        data['instrument'].update(type='nanodrop_ultrac', serial_number='SYN-ND-ULTRAC-001')
        # A separate database permits the same externally visible measurement IDs.
        with Journal(Path(self.temp.name) / 'ultra.sqlite3') as journal:
            flow = Workflow.create(journal, data, RUN_ID)
            self.claim(flow)
            self.measure_all(flow)
            self.import_content((FIXTURES / 'ultrac-synthetic.csv').read_bytes(), flow)
            self.review(flow)
            flow.act('release', ACTOR, workspace_clear=True)
            self.assertTrue(flow.report()['passed'])

    def test_claim_requires_initial_clearance_and_measurement_requires_blank(self):
        self.flow.act('rack_ready', ACTOR, observations=inventory_observations(self.flow.state))
        with self.assertRaises(TaskError):
            self.flow.act('claim', ACTOR)
        self.flow.act('workspace_clear', ACTOR, confirmed=True)
        self.flow.act('claim', ACTOR)
        self.take()
        with self.assertRaises(TaskError):
            self.begin()
        self.assertEqual(self.flow.state['measurements'], {})

    def test_wrong_pickup_and_return_observations_require_reconciliation(self):
        self.claim()
        sample = self.flow.state['samples']['Sample01']
        with self.assertRaises(ObservationError):
            self.flow.act('take', ACTOR, sample_id='Sample01', observed_sample_id='Sample02',
                          place_id=sample['original_place_id'], rack_id=sample['location']['rack_id'])
        self.assertEqual(self.flow.state['samples']['Sample01']['location'], original_location(self.flow.state, sample))
        self.assertEqual(self.flow.state['recovery_required'], 'observation_mismatch')
        self.assertEqual(len(self.journal.owners()), 3)
        with self.assertRaisesRegex(TaskError, 'reconciliation'):
            self.take()
        self.reconcile()
        self.take()
        self.begin()
        self.confirm()
        with self.assertRaises(ObservationError):
            self.flow.act('place', ACTOR, sample_id='Sample01', observed_sample_id='Sample01',
                          rack_id=self.flow.state['definition']['profile']['rack']['id'],
                          place_id='CF01.OutputRack.Slot04')
        self.assertEqual(self.flow.state['samples']['Sample01']['location']['kind'], 'operator')
        self.assertFalse(self.flow.report()['passed'])

    def test_missing_vessel_or_duplicate_observation_never_restores_inventory(self):
        self.claim()
        self.flow.close()
        self.flow = Workflow.open(self.journal, RUN_ID)
        observations = inventory_observations(self.flow.state)
        for broken in [observations[:-1], [observations[0]] * 3]:
            with self.assertRaises(ObservationError):
                self.reconcile(observations=broken)
            self.assertIsNotNone(self.flow.state['recovery_required'])
            self.assertEqual(len(self.journal.owners()), 3)

    def test_exact_file_reimport_is_idempotent_and_conflicting_import_is_quarantined(self):
        self.claim()
        self.measure_all()
        first = self.import_content()
        revision = self.journal.state(RUN_ID)[1]
        self.import_content()
        self.assertEqual(self.journal.state(RUN_ID)[1], revision)
        changed = (FIXTURES / 'one-synthetic.csv').read_bytes().replace(b',11.0,', b',99.0,')
        other = self.import_content(changed)
        self.assertEqual(self.flow.state['imports'][other]['status'], 'quarantined')
        self.assertEqual(self.flow.state['results'][RUN_ID + '.A01.M001']['metrics']['concentration']['value'], 11)
        with self.assertRaisesRegex(TaskError, 'quarantined'):
            self.review()
        self.flow.act('discard_import', ACTOR, sha256=other, reason='Synthetic duplicate test')
        self.assertEqual(self.journal.artifact(other), changed)
        self.assertEqual(self.journal.artifact(first), (FIXTURES / 'one-synthetic.csv').read_bytes())
        self.review()

    def test_missing_foreign_duplicate_malformed_and_wrong_instrument_results_are_quarantined(self):
        self.claim()
        self.measure_all()
        original = (FIXTURES / 'one-synthetic.csv').read_bytes()
        lines = original.splitlines(keepends=True)
        cases = [('missing_measurement', b''.join(lines[:-1])),
                 ('foreign_measurement', original.replace(b'.A01.M001', b'.A02.M001')),
                 ('duplicate_measurement', original + lines[-1]),
                 ('instrument_serial_mismatch', original.replace(b'SYN-ND-ONE-001', b'FOREIGN')),
                 ('method_mismatch', original.replace(b'dsDNA', b'RNA')),
                 ('numeric', original.replace(b',11.0,', b',NaN,'))]
        for expected, content in cases:
            with self.subTest(expected=expected):
                checksum = self.import_content(content)
                record = self.flow.state['imports'][checksum]
                self.assertEqual(record['status'], 'quarantined')
                self.assertIn(expected, ' '.join(record['issues']))
                self.assertEqual(self.journal.artifact(checksum), content)
        self.assertEqual(self.flow.state['results'], {})
        with self.assertRaises(TaskError):
            self.review()

    def test_result_rejection_and_missing_handback_block_completion(self):
        self.claim()
        self.measure_all()
        self.import_content()
        self.flow.act('review_results', ACTOR, decision='rejected', reason='Synthetic quality decision')
        with self.assertRaises(TaskError):
            self.flow.act('release', ACTOR, workspace_clear=True)
        self.review()
        with self.assertRaises(ObservationError):
            self.flow.act('release', ACTOR, workspace_clear=False)
        self.assertEqual(len(self.journal.owners()), 3)
        self.assertFalse(self.flow.report()['passed'])

    def test_deadline_is_a_reconciliation_hold_and_does_not_release_or_repeat(self):
        self.claim()
        self.now[0] += 3601
        self.flow.act('check_deadline', ACTOR)
        self.assertEqual(self.flow.state['recovery_required'], 'deadline_exceeded')
        self.assertEqual(self.flow.state['measurements'], {})
        self.assertEqual(len(self.journal.owners()), 3)
        with self.assertRaises(TaskError):
            self.take()
        self.reconcile()
        self.assertIsNone(self.flow.state['recovery_required'])
        self.assertGreater(self.flow.state['deadline_unix_s'], self.now[0])

    def test_cancel_while_vessel_is_out_preserves_holds_until_observed_return(self):
        self.claim()
        self.take()
        self.flow.act('cancel', ACTOR, reason='Synthetic operator interruption')
        self.assertEqual(self.flow.state['status'], 'cancelling')
        self.assertEqual(len(self.journal.owners()), 3)
        self.reconcile()
        with self.assertRaises(TaskError):
            self.flow.act('finish_cancel', ACTOR, workspace_clear=True)
        self.place()
        self.flow.act('finish_cancel', ACTOR, workspace_clear=True)
        self.assertEqual(self.flow.state['status'], 'cancelled')
        self.assertFalse(self.flow.report()['passed'])
        self.assertEqual(self.journal.owners(), {})

    def test_pending_measurement_requires_explicit_outcome_before_retry_or_cancel(self):
        self.claim()
        self.take()
        old_intent = self.begin()
        self.assertIsNone(self.flow.report()['samples']['Sample01']['remaining_volume_ul'])
        self.flow.close()
        self.flow = Workflow.open(self.journal, RUN_ID)
        with self.assertRaisesRegex(TaskError, 'outcome'):
            self.reconcile()
        self.reconcile(pending_resolution={'intent_id': old_intent, 'outcome': 'unknown'})
        self.assertIsNotNone(self.flow.state['recovery_required'])
        self.assertIsNone(self.flow.report()['samples']['Sample01']['remaining_volume_ul'])
        self.reconcile(pending_resolution={'intent_id': old_intent, 'outcome': 'not_performed'})
        self.assertEqual(self.flow.state['samples']['Sample01']['remaining_volume_ul'], 40)
        new_intent = self.begin()
        self.assertNotEqual(old_intent, new_intent)
        with self.assertRaisesRegex(TaskError, 'Stale'):
            self.confirm(intent_id=old_intent)
        self.confirm()
        self.assertEqual(self.flow.state['samples']['Sample01']['remaining_volume_ul'], 38.5)

    def test_reconciliation_records_a_wrong_actual_place_but_requires_original_place_for_completion(self):
        self.claim()
        self.measure_all()
        self.import_content()
        self.review()
        self.flow.close()
        self.flow = Workflow.open(self.journal, RUN_ID)
        observed = inventory_observations(self.flow.state)
        observed[0]['location']['place_id'] = 'CF01.OutputRack.Slot04'
        self.reconcile(observations=observed)
        self.assertEqual(self.flow.state['samples']['Sample01']['location']['place_id'], 'CF01.OutputRack.Slot04')
        with self.assertRaisesRegex(TaskError, 'original rack place'):
            self.flow.act('release', ACTOR, workspace_clear=True)
        self.take()
        self.place()
        self.flow.act('release', ACTOR, workspace_clear=True)
        self.assertTrue(self.flow.report()['passed'])

    def test_bad_inventory_location_does_not_crash_or_release_resources(self):
        self.claim()
        self.flow.close()
        self.flow = Workflow.open(self.journal, RUN_ID)
        observations = inventory_observations(self.flow.state)
        observations[0]['location'] = None
        with self.assertRaises(ObservationError):
            self.reconcile(observations=observations)
        self.assertEqual(len(self.journal.owners()), 3)

    def test_row_metadata_is_checked_and_manual_entry_has_explicit_origin(self):
        self.claim()
        self.measure_all()
        header = 'Sample Name,ng/uL,Application,Serial Number\n'
        rows = ''.join(name + ',10,dsDNA,SYN-ND-ONE-001\n'
                       for name in self.flow.state['planned_measurements'].values())
        foreign = (header + rows).replace('SYN-ND-ONE-001', 'FOREIGN', 1).encode()
        checksum = self.import_content(foreign)
        self.assertIn('instrument_serial_mismatch', self.flow.state['imports'][checksum]['issues'])
        self.flow.act('discard_import', ACTOR, sha256=checksum, reason='Synthetic foreign serial')
        content = (header + rows).encode()
        self.flow.act('import_results', ACTOR, artifact=content, file_name='hand-entered.csv',
                      origin='synthetic_manual_entry')
        for result in self.flow.state['results'].values():
            self.assertEqual(result['origin'], 'synthetic_manual_entry')
            self.assertEqual(result['method_source'], 'report')
            self.assertEqual(result['serial_source'], 'report')
            self.assertIsNone(result['metrics']['a260_a280']['value'])

    def test_corrupt_archived_bytes_cannot_be_reviewed_or_reported_as_success(self):
        self.claim()
        self.measure_all()
        checksum = self.import_content()
        self.journal.connection.execute('UPDATE artifacts SET content=? WHERE sha256=?',
                                        (b'SYNTHETIC CORRUPTION', checksum))
        self.journal.connection.commit()
        with self.assertRaisesRegex(TaskError, 'corrupt artifact'):
            self.review()
        with self.assertRaises(TaskError):
            self.flow.report()
        self.assertEqual(len(self.journal.owners()), 3)

    def test_stale_revision_from_second_connection_cannot_overwrite_new_events(self):
        state, revision = self.journal.state(RUN_ID)
        with Journal(self.path) as other:
            other.append(RUN_ID, revision, 'synthetic_concurrent_audit', {}, state)
        state['resources'] = ['rack:STALE']
        with self.assertRaisesRegex(TaskError, 'changed'):
            self.journal.append(RUN_ID, revision, 'stale_write', {}, state)
        self.assertNotIn('rack:STALE', self.journal.owners())

    def test_restart_after_confirmed_measurement_preserves_exactly_one_consumption(self):
        self.claim()
        self.take()
        intent = self.begin()
        self.confirm()
        self.flow.close()
        with Journal(self.path, clock=lambda: self.now[0]) as other:
            flow = Workflow.open(other, RUN_ID)
            self.assertIsNone(flow.state['pending_measurement'])
            self.assertEqual(flow.state['samples']['Sample01']['remaining_volume_ul'], 38.5)
            self.reconcile(flow)
            with self.assertRaises(TaskError):
                self.confirm(flow=flow, intent_id=intent)
            with self.assertRaises(TaskError):
                self.begin(flow=flow)
            self.assertEqual(len(flow.state['measurements']), 1)
            self.place(flow=flow)

    def test_insufficient_known_volume_blocks_measurement_before_intent(self):
        profile = json.loads(SOURCE.read_text())
        profile['samples'][0]['initial_volume_ul'] = 0
        with Journal(Path(self.temp.name) / 'empty.sqlite3') as journal:
            flow = Workflow.create(journal, profile, 'SYN-ND-EMPTY')
            self.claim(flow)
            self.take(flow=flow)
            with self.assertRaisesRegex(TaskError, 'Insufficient'):
                self.begin(flow=flow)
            self.assertIsNone(flow.state['pending_measurement'])
            self.assertEqual(flow.state['measurements'], {})

    def test_resource_conflict_rolls_back_and_separate_rack_instances_can_run_independently(self):
        self.claim()
        other = Workflow.create(self.journal, run_id='SYN-ND-OTHER')
        revision = self.journal.state(other.run_id)[1]
        with self.assertRaisesRegex(TaskError, 'Resource reserved'):
            other.act('rack_ready', ACTOR, observations=inventory_observations(other.state))
        self.assertEqual(self.journal.state(other.run_id)[1], revision)
        self.assertEqual(other.state['resources'], [])
        profile = json.loads(SOURCE.read_text())
        profile['rack']['id'] = 'SYN.Rack02'
        profile['instrument']['id'] = 'SYN.NanoDrop02'
        profile['workspace']['id'] = 'SYN.WorkArea02'
        independent = Workflow.create(self.journal, profile, 'SYN-ND-INDEPENDENT')
        self.claim(independent)
        self.assertEqual(len(self.journal.owners()), 6)
        self.assertEqual(self.flow.state['samples']['Sample01']['original_place_id'],
                         independent.state['samples']['Sample01']['original_place_id'])
        self.assertNotEqual(original_location(self.flow.state, self.flow.state['samples']['Sample01']),
                            original_location(independent.state, independent.state['samples']['Sample01']))

    def test_other_actor_and_stale_session_cannot_confirm_or_release(self):
        self.claim()
        with self.assertRaisesRegex(TaskError, 'another'):
            self.flow.act('blank', 'SYN.OtherOperator', reference_id='SYN.Buffer', cleaned=True)
        with self.assertRaisesRegex(TaskError, 'explicit resume'):
            Workflow.open(self.journal, RUN_ID)
        recovered = Workflow.open(self.journal, RUN_ID, resume=True)
        with self.assertRaisesRegex(TaskError, 'Stale'):
            self.take()
        self.assertIsNotNone(recovered.state['recovery_required'])

    def test_withdrawal_deviation_requires_reason_and_consumption_is_not_inferred_from_results(self):
        self.claim()
        self.take()
        self.begin()
        with self.assertRaises(TaskError):
            self.confirm(volume_ul=2)
        self.confirm(volume_ul=2, deviation_reason='Synthetic deliberate deviation')
        self.assertEqual(self.flow.state['samples']['Sample01']['remaining_volume_ul'], 38)

    def test_partial_database_write_rolls_back_artifact_event_and_reservation(self):
        state, revision = self.journal.state(RUN_ID)
        content = b'SYNTHETIC TRANSACTION FAILURE'
        state['resources'] = ['rack:SYN.TEST.TRANSACTION']
        with patch.object(self.journal, '_event', side_effect=RuntimeError('Synthetic disk failure')):
            with self.assertRaises(RuntimeError):
                self.journal.append(RUN_ID, revision, 'test_failure', {}, state, artifact=content)
        self.assertEqual(self.journal.state(RUN_ID)[1], revision)
        self.assertEqual(self.journal.owners(), {})
        with self.assertRaises(TaskError):
            self.journal.artifact(digest(content))

    def test_hard_process_exit_and_restart_require_reconciliation_without_double_withdrawal(self):
        crash_db = Path(self.temp.name) / 'crash.sqlite3'
        script = '''
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()/'scripts'))
from manual_tasks import Journal
from nanodrop_manual import Workflow, inventory_observations
journal=Journal(sys.argv[1])
flow=Workflow.create(journal, run_id='SYN-ND-CRASH')
actor='SYN.Operator01'
flow.act('rack_ready',actor,observations=inventory_observations(flow.state))
flow.act('workspace_clear',actor,confirmed=True)
flow.act('claim',actor)
flow.act('blank',actor,reference_id='SYN.Buffer',cleaned=True)
s=flow.state['samples']['Sample01']
flow.act('take',actor,sample_id='Sample01',observed_sample_id='Sample01',place_id=s['original_place_id'],rack_id=s['location']['rack_id'])
flow.act('begin_measurement',actor,sample_id='Sample01',measurement_id=flow.state['planned_measurements']['Sample01'])
os._exit(23)
'''
        child = subprocess.run([sys.executable, '-c', script, str(crash_db)], cwd=ROOT,
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(child.returncode, 23, child.stderr)
        with Journal(crash_db) as journal:
            with self.assertRaises(TaskError):
                Workflow.open(journal, 'SYN-ND-CRASH')
            flow = Workflow.open(journal, 'SYN-ND-CRASH', resume=True)
            self.assertEqual(flow.state['recovery_required'], 'session_restarted')
            self.assertEqual(len(journal.owners()), 3)
            intent = flow.state['pending_measurement']['intent_id']
            with self.assertRaisesRegex(TaskError, 'reconciliation'):
                self.confirm(flow=flow)
            flow.act('reconcile', ACTOR, observations=inventory_observations(flow.state),
                     workspace_clear=False, blank_still_valid=True,
                     pending_resolution={'intent_id': intent, 'outcome': 'performed',
                                         'observed_sample_id': 'Sample01', 'volume_ul': 1.5, 'cleaned': True})
            self.assertEqual(flow.state['samples']['Sample01']['remaining_volume_ul'], 38.5)
            self.assertEqual(len(flow.state['measurements']), 1)
            with self.assertRaises(TaskError):
                self.confirm(flow=flow, intent_id=intent)
            self.assertEqual(flow.state['samples']['Sample01']['remaining_volume_ul'], 38.5)
            self.assertFalse(flow.report()['passed'])


if __name__ == '__main__':
    unittest.main()
