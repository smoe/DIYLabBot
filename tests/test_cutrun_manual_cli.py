"""Real CLI processes preserve open E4 bindings and opaque test-only originals."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, digest


class CutrunManualCliTests(unittest.TestCase):
    ACTOR = 'TEST.ManualCLI.Operator'
    RUN = 'TEST.ManualCLI.Capture'

    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='manual-cli-test-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = self.folder / 'manual.sqlite3'
        materials, vessels, reactions = [], [], {}
        for role in ('h3k4me3', 'igg', 'input'):
            identity, tube = 'TEST.Material.' + role, 'TEST.Tube.' + role
            materials.append({'id': identity, 'kind': 'sample' if role == 'h3k4me3' else 'control',
                'vessel_id': tube, 'quantity': {'value': None, 'unit': 'cells'}, 'origin_id': 'TEST.UnmeasuredCulture'})
            reagents = {}
            for name in (() if role == 'input' else ('activation', 'stop')):
                reagent = 'TEST.Issued.' + role + '.' + name
                materials.append({'id': reagent, 'kind': 'reagent', 'vessel_id': reagent + '.Tube',
                    'quantity': {'value': None, 'unit': 'uL'}, 'origin_id': 'TEST.ExplicitUnmeasuredAliquot'})
                reagents[name] = reagent
            reactions['TEST.Reaction.' + role] = {'role': role, 'material_id': identity, 'vessel_id': tube,
                'activation_material_id': reagents.get('activation'), 'stop_material_id': reagents.get('stop')}
        for index, identity in enumerate([item['vessel_id'] for item in materials] + ['TEST.PCR.NTC.Tube'], 1):
            vessels.append({'id': identity, 'location': {'kind': 'rack', 'rack_id': 'TEST.ManualCLI.Rack',
                                                       'place_id': 'P%02d' % index}})
        self.inventory = self.folder / 'inventory.json'
        self.inventory.write_text(json.dumps({'materials': materials, 'vessels': vessels,
                                             'reactions': reactions, 'actors': [self.ACTOR]}))

    def run_cli(self, *arguments):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/run_cutrun_manual.py'),
                                 '--store', str(self.store), *map(str, arguments)],
                                cwd=ROOT, capture_output=True, text=True)
        try:
            content = json.loads(result.stdout)
        except ValueError:
            self.fail('CLI did not return JSON: ' + result.stderr + result.stdout[:500])
        return result, content

    def create(self):
        result, record = self.run_cli('create', '--inventory', self.inventory, '--run-id', self.RUN)
        self.assertEqual(result.returncode, 0, record.get('error', result.stderr))
        return record

    def observation(self, identity='TEST.ManualCLI.Observation'):
        path = self.folder / 'observation.json'
        path.write_text(json.dumps({'observation_id': identity, 'source_kind': 'test_fixture',
            'observed_at': None, 'source_ref': 'TEST.CLI fixture; no laboratory observation', 'artifact_sha256': None}))
        return path

    def snapshot(self):
        with Journal(self.store) as journal:
            state, revision = journal.get_current(self.RUN)
        return state, revision, self.store.read_bytes()

    def test_prepare_leaves_parameters_unknown_stages_blocked_and_creates_no_database(self):
        target = self.folder / 'prepare.json'
        result, prepared = self.run_cli('prepare', '--out', target)
        self.assertEqual(result.returncode, 0, prepared.get('error', result.stderr))
        self.assertFalse(self.store.exists())
        self.assertTrue(all(item['value'] is None for item in prepared['manual_profile']['parameters'].values()))
        self.assertTrue(all(item['basis'] == 'unknown' for item in prepared['manual_profile']['parameters'].values()))
        self.assertTrue(prepared['open_requirements'])
        self.assertFalse(any(prepared['stage_readiness'].values()))
        self.assertFalse(prepared['preparation_complete'])
        self.assertFalse(prepared['can_claim_reference_success'])
        self.assertFalse(prepared['original_pdf_verified'])
        self.assertNotIn('evidence_artifacts', prepared)
        self.assertEqual(json.loads(target.read_text()), prepared)

    def test_create_status_and_report_preserve_database_bytes_and_only_estimate_current_clock(self):
        created = self.create()
        self.assertEqual(created['state']['format'], 'solidcraftbot.material-workflow-state/3')
        self.assertIsNone(created['state']['observation_context'])
        self.assertFalse(any(created['state']['definition']['stage_readiness'].values()))
        before, revision, original_bytes = self.snapshot()
        for command in ('status', 'report'):
            with self.subTest(command=command):
                result, report = self.run_cli(command, self.RUN)
                self.assertEqual(result.returncode, 0, report.get('error', result.stderr))
                self.assertEqual(report['mode'], 'manual_observation')
                self.assertFalse(report['reference_success']);self.assertFalse(report['capture_completed'])
                self.assertTrue(report['current_clock_estimate_is_uncommitted'])
                self.assertIn('current_clock_estimate', report)
                self.assertEqual(report['clock'], before['clock'])
                state, count, raw = self.snapshot()
                self.assertEqual((state, count), (before, revision))
                self.assertEqual(raw, original_bytes)

    def test_resume_records_new_clock_domain_and_fences_the_previous_session(self):
        created = self.create();old_session = created['session']
        old_clock = created['state']['clock']['last_sample']['clock_id']
        result, resumed = self.run_cli('resume', self.RUN)
        self.assertEqual(result.returncode, 0, resumed.get('error', result.stderr))
        self.assertNotEqual(resumed['session'], old_session)
        self.assertNotEqual(resumed['state']['clock']['last_sample']['clock_id'], old_clock)
        self.assertTrue(resumed['state']['clock']['gap_required'])
        self.assertIsNone(resumed['state']['clock']['upper_s'])
        before, count, raw = self.snapshot()
        result, error = self.run_cli('act', self.RUN, '--session', old_session, '--actor', self.ACTOR,
                                    '--action', 'check_clock', '--observation', self.observation())
        self.assertEqual(result.returncode, 1);self.assertIn('Stale', error['error'])
        self.assertEqual(self.snapshot(), (before, count, raw))

    def test_opaque_qc_original_can_be_archived_unclaimed_and_held_without_consumption(self):
        created = self.create();before = created['state']
        artifact = self.folder / 'opaque-qc.bin'
        original = b'\x00\xffTEST opaque instrument-like original\r\nnot decoded; not a real laboratory export\r\n'
        artifact.write_bytes(original)
        result, state = self.run_cli('act', self.RUN, '--session', created['session'], '--actor', self.ACTOR,
            '--action', 'attach_qc', '--observation', self.observation('TEST.AttachOriginal'),
            '--artifact', artifact, '--data', json.dumps({'file_name': 'opaque-qc.bin', 'origin': 'test_fixture'}))
        self.assertEqual(result.returncode, 0, state.get('error', result.stderr))
        self.assertIsNone(state['actor_id'])
        self.assertTrue(state['recovery_required'])
        self.assertEqual(state['inventory'], before['inventory'])
        self.assertEqual(state['bookings'], {})
        self.assertIsNone(state['pending_operation'])
        reference = digest(original)
        metadata = state['manual']['qc_artifacts'][reference]
        self.assertEqual(metadata['status'], 'unmapped');self.assertIsNone(metadata['decoder'])
        self.assertEqual(metadata['evidence'], 'test_fixture')
        with Journal(self.store) as journal:
            self.assertEqual(journal.artifact(reference), original)
            self.assertEqual(journal.history(self.RUN)[-1]['payload']['artifact_sha256'], reference)
        result, report = self.run_cli('report', self.RUN)
        self.assertEqual(result.returncode, 0, report.get('error', result.stderr))
        self.assertFalse(report['vendor_qc_decoder_executed'])
        self.assertFalse(report['biochemical_protocol_executed'])
        self.assertFalse(report['reference_success'])

    def test_synthetic_advance_time_is_rejected_without_event_or_observation_registration(self):
        created = self.create();before, count, raw = self.snapshot()
        result, error = self.run_cli('act', self.RUN, '--session', created['session'], '--actor', self.ACTOR,
            '--action', 'advance_time', '--observation', self.observation('TEST.NoSyntheticClock'),
            '--data', json.dumps({'seconds': 1000}))
        self.assertEqual(result.returncode, 1);self.assertIn('cannot bypass', error['error'])
        self.assertEqual(self.snapshot(), (before, count, raw))


if __name__ == '__main__':
    unittest.main()
