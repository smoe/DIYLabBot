"""CUT&RUN CLI preserves read-only views and explicit resume/session semantics."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cutrun_workflow import CutRunWorkflow
from manual_tasks import Journal, TaskError
from run_cutrun_workflow import ACTOR


class CutrunWorkflowCliTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'exports', prefix='cutrun-e3-cli-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = self.directory / 'tasks.sqlite3'
        self.run_id = 'SYN.CUTRUN.CLI'
        with Journal(self.store) as journal:
            flow = CutRunWorkflow.create(journal, run_id=self.run_id)
            flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
            flow.act('workspace_clear', ACTOR, confirmed=True)
            flow.act('claim', ACTOR)
            self.session = flow.session

    def cli(self, *arguments, success=True):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_cutrun_workflow.py'),
                                 '--store', str(self.store), *arguments],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_status_and_report_do_not_take_over_the_session_or_change_history(self):
        with Journal(self.store) as journal:
            before = journal.history(self.run_id)
        status = self.cli('status', self.run_id)
        self.assertEqual(status['status'], 'working')
        target = self.directory / 'report.json'
        report = self.cli('report', self.run_id, '--out', str(target))
        self.assertEqual(json.loads(target.read_text()), report)
        self.assertFalse(report['hardware_executed'])
        with Journal(self.store) as journal:
            self.assertEqual(before, journal.history(self.run_id))
        self.assertIn('error', self.cli('report', self.run_id, '--out', str(target), success=False))

    def test_resume_marks_time_gap_and_rejects_old_session_then_accepts_explicit_elapsed_interval(self):
        result = self.cli('resume', self.run_id)
        session = result['session']
        self.assertNotEqual(session, self.session)
        self.assertTrue(result['state']['clock']['gap_required'])
        self.assertIsNone(result['state']['clock']['uncertainty_s'])
        self.cli('act', self.run_id, '--session', self.session, '--actor', ACTOR,
                 '--action', 'advance_time', '--data', '{"seconds":1}', success=False)
        state = self.cli('act', self.run_id, '--session', session, '--actor', ACTOR,
                         '--action', 'resolve_time_gap', '--data',
                         json.dumps({'min_s': 5, 'max_s': 10, 'reason': 'Explicit synthetic elapsed interval'}))
        self.assertEqual(state['logical_time_s'], 5)
        self.assertEqual(state['clock']['uncertainty_s'], 5)
        self.assertTrue(state['recovery_required'])

    def test_generic_effect_action_and_output_outside_exports_are_rejected(self):
        with Journal(self.store) as journal:
            before = journal.history(self.run_id)
        self.cli('act', self.run_id, '--session', self.session, '--actor', ACTOR,
                 '--action', 'begin_effect', success=False)
        self.cli('report', self.run_id, '--out', str(ROOT / 'model/forbidden-e3-output.json'), success=False)
        with Journal(self.store) as journal:
            self.assertEqual(before, journal.history(self.run_id))

    def test_writer_cannot_reuse_saved_session_after_runtime_pin_changes_but_history_stays_readable(self):
        with Journal(self.store) as journal:
            before = journal.history(self.run_id)
            with patch('cutrun_workflow.digest', return_value='changed-runtime-bytes'):
                with self.assertRaisesRegex(TaskError, 'Runtime source changed'):
                    CutRunWorkflow(journal, self.run_id, self.session)
                report = CutRunWorkflow(journal, self.run_id, None).report()
                self.assertEqual(report['status'], 'working')
            self.assertEqual(before, journal.history(self.run_id))



if __name__ == '__main__':
    unittest.main()
