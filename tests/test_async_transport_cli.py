"""Subprocess evidence for the synthetic A/B teleportation entry point."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AsyncTransportCLITests(unittest.TestCase):
    def setUp(self):
        (ROOT/'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='async-cli-', dir=ROOT/'exports')
        self.directory = Path(self.temp.name)
        self.store = self.directory/'workflows.sqlite3'
        self.run_id = 'SYN.CLI.Transport'

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *arguments, success=True):
        result = subprocess.run([sys.executable, str(ROOT/'scripts/run_async_transport.py'),
            '--store', str(self.store), *arguments], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 2, result.stdout+result.stderr)
        return json.loads(result.stdout if success else result.stderr)

    def demo(self):
        return self.cli('demo', '--run-id', self.run_id)

    def test_demo_two_inflight_jobs_roundtrip_and_unchanged_materials(self):
        report = self.demo()
        self.assertTrue(report['passed'])
        self.assertEqual(set(report['completed_jobs']), {'OutHuman', 'OutRobot', 'BackRobot'})
        self.assertEqual(report['rack_placements']['SYN.Async.Rack01'],
                         {'kind': 'endpoint', 'endpoint_id': 'LabA.S1'})
        self.assertEqual(report['rack_placements']['SYN.Async.Rack02'],
                         {'kind': 'endpoint', 'endpoint_id': 'LabB.S2'})
        self.assertEqual(report['bookings'], {})
        amounts = sorted((m['initial_quantity']['value'] for m in report['inventory']['materials'].values()),
                         key=lambda value: -1 if value is None else value)
        self.assertEqual(amounts, [None, None, 40, 40])
        self.assertEqual(report['transport_time_s'], 0)
        self.assertEqual(report['execution_mode'], 'teleportation_mock')
        for key in ['network_executed', 'robot_motion_executed', 'hardware_executed',
                    'existing_workflow_integrated', 'cross_owner_stock', 'quantity_changes']:
            self.assertFalse(report[key])
        self.assertNotIn('agent:AgentHuman', report['resources'])
        self.assertNotIn('agent:AgentRobot', report['resources'])

    def test_status_read_only_and_demo_replay_cannot_reset_existing_root(self):
        before = self.demo()
        after = self.cli('status', self.run_id)
        self.assertEqual(after, before)
        error = self.cli('demo', '--run-id', self.run_id, success=False)
        self.assertIn('exists', error['error'])
        self.assertEqual(self.cli('status', self.run_id), before)

    def test_create_is_unadmitted_and_writing_session_requires_explicit_resume(self):
        initial = self.cli('create', '--run-id', self.run_id)
        self.assertFalse(initial['admitted'])
        self.assertEqual(initial['inventory'], {})
        self.assertEqual(initial['resources'], [])
        error = self.cli('session', self.run_id, success=False)
        self.assertIn('--resume', error['error'])
        self.assertEqual(self.cli('status', self.run_id), initial)

    def test_jsonl_resume_and_admission_preserve_exact_message_shape(self):
        self.cli('create', '--run-id', self.run_id)
        actions = self.directory/'actions.jsonl'
        actions.write_text(json.dumps({'operation': 'admit', 'principal': 'SYN.Async.Owner',
                                      'request_id': 'CLI.Admit', 'args': {}})+'\n')
        report = self.cli('session', self.run_id, '--resume', '--request-id', 'CLI.Resume',
                          '--actions', str(actions))
        self.assertTrue(report['admitted'])
        self.assertFalse(report['passed'])
        self.assertTrue(report['resources'])
        bad = self.directory/'bad.jsonl'
        bad.write_text('{"operation":"admit","principal":"SYN.Async.Owner",'
                       '"principal":"Other","request_id":"X","args":{}}\n')
        error = self.cli('session', self.run_id, '--resume', '--request-id', 'CLI.Resume2',
                         '--actions', str(bad), success=False)
        self.assertIn('Duplicate', error['error'])

    def test_report_preserves_existing_output_and_rejects_outside_exports(self):
        self.demo()
        target = self.directory/'report.json'
        result = self.cli('report', self.run_id, '--out', str(target))
        self.assertEqual(Path(result['report']), target)
        original = target.read_bytes()
        self.cli('report', self.run_id, '--out', str(target), success=False)
        self.assertEqual(target.read_bytes(), original)
        with tempfile.TemporaryDirectory() as folder:
            outside = Path(folder)/'forbidden.json'
            self.cli('report', self.run_id, '--out', str(outside), success=False)
            self.assertFalse(outside.exists())


if __name__ == '__main__':
    unittest.main()
