"""CLI/process checks for explicit local fixtures, never device execution."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cutrun_input_sonication_demo import FixtureClock
from manual_tasks import Journal


class SonicationCliTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='sonication-cli-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = self.directory / 'root.sqlite3'
        self.command = [sys.executable, str(ROOT / 'scripts/run_cutrun_input_sonication.py'),
                        '--store', str(self.store)]
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}

    def cli(self, *arguments):
        result = subprocess.run([*self.command, *map(str,arguments)], cwd=ROOT,
            env=self.env, capture_output=True, text=True, timeout=90)
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_prepare_keeps_real_and_fixture_gates_open_and_creates_no_store(self):
        code, report = self.cli('prepare')
        self.assertEqual(code, 0)
        self.assertFalse(report['synthetic_gate_readiness']['S09'])
        self.assertFalse(any(report['real_stage_readiness'].values()))
        self.assertFalse(report['original_pdf_verified'])
        self.assertFalse(self.store.exists())
        code, report = self.cli('prepare','--require-complete')
        self.assertEqual(code, 2)
        self.assertFalse(self.store.exists())

    def test_output_is_new_private_json_and_is_checked_before_effects(self):
        output = self.directory / 'prepare.json'
        code, report = self.cli('prepare','--out',output)
        self.assertEqual(code,0)
        before = output.read_bytes()
        code, error = self.cli('prepare','--out',output)
        self.assertEqual(code,1)
        self.assertEqual(output.read_bytes(),before)
        code,error = self.cli('prepare','--out',ROOT/'docs'/'sonication-cli-invalid.json')
        self.assertEqual(code,1)
        self.assertFalse((ROOT/'docs'/'sonication-cli-invalid.json').exists())
        self.assertFalse(self.store.exists())

    def evidence_parent_fixture(self):
        base = ROOT / 'exports' / 'sonication-evidence'
        base.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='cli-parent-check-', dir=base)
        self.addCleanup(temporary.cleanup)
        blocker = Path(temporary.name) / 'existing-file'
        blocker.write_bytes(b'Preserve this evidence-path blocker\n')
        return blocker

    def test_blocked_evidence_ancestors_are_rejected_before_creating_store_or_fixtures(self):
        blocker = self.evidence_parent_fixture()
        before = blocker.read_bytes()
        for suffix in (Path('new-bundle'), Path('missing/deeper/new-bundle')):
            with self.subTest(suffix=suffix):
                fixtures = self.directory / 'not-created'
                code, error = self.cli('demo', '--directory', fixtures,
                                       '--evidence-directory', blocker / suffix)
                self.assertEqual(code, 1)
                self.assertEqual(error['error'], 'Output parent must be a directory: ' + str(blocker))
                self.assertFalse(self.store.exists())
                self.assertFalse(fixtures.exists())
                self.assertEqual(blocker.read_bytes(), before)

    def test_blocked_evidence_ancestors_preserve_existing_journal_and_owners(self):
        identity = 'Fixture.CLI.Existing'
        code, ready = self.cli('fixture-intent', '--directory', self.directory / 'seed',
                               '--run-id', identity)
        self.assertEqual(code, 0, ready)
        with Journal(self.store) as journal:
            history = journal.history(identity)
            owners = journal.owners()
            state = journal.state(identity)
            dump = tuple(journal.connection.iterdump())
            self.assertTrue(history)
            self.assertTrue(owners)
        database_bytes = self.store.read_bytes()
        blocker = self.evidence_parent_fixture()
        before = blocker.read_bytes()
        for suffix in (Path('new-bundle'), Path('missing/deeper/new-bundle')):
            with self.subTest(suffix=suffix):
                fixtures = self.directory / 'not-created'
                code, error = self.cli('demo', '--directory', fixtures,
                                       '--evidence-directory', blocker / suffix)
                self.assertEqual(code, 1)
                self.assertEqual(error['error'], 'Output parent must be a directory: ' + str(blocker))
                self.assertEqual(self.store.read_bytes(), database_bytes)
                self.assertFalse(fixtures.exists())
                self.assertEqual(blocker.read_bytes(), before)
                with Journal(self.store) as journal:
                    self.assertEqual(journal.history(identity), history)
                    self.assertEqual(journal.owners(), owners)
                    self.assertEqual(journal.state(identity), state)
                    self.assertEqual(tuple(journal.connection.iterdump()), dump)

    def test_blocked_fixture_ancestors_are_rejected_before_creating_store(self):
        blocker = self.directory / 'existing-file'
        blocker.write_bytes(b'Preserve this fixture-path blocker\n')
        before = blocker.read_bytes()
        for command in ('demo', 'fixture-intent'):
            for suffix in (Path('new-fixtures'), Path('missing/deeper/new-fixtures')):
                with self.subTest(command=command, suffix=suffix):
                    arguments = [command, '--directory', blocker / suffix]
                    if command == 'fixture-intent':
                        arguments.extend(['--run-id', 'Fixture.CLI.BlockedParent'])
                    code, error = self.cli(*arguments)
                    self.assertEqual(code, 1)
                    self.assertEqual(error['error'], 'Output parent must be a directory: ' + str(blocker))
                    self.assertFalse(self.store.exists())
                    self.assertEqual(blocker.read_bytes(), before)

    def test_sigkill_after_intent_never_replays_and_cli_resume_fences_old_session(self):
        identity = 'Fixture.CLI.Restart'
        process = subprocess.Popen([*self.command,'fixture-intent','--directory',str(self.directory/'child'),
            '--run-id',identity,'--scenario-id','restart','--wait'],cwd=ROOT,env=self.env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout,selectors.EVENT_READ)
                self.assertTrue(selector.select(30),'Fixture worker did not persist intent in time')
                line=process.stdout.readline()
            self.assertTrue(line, 'Fixture worker exited before intent')
            ready=json.loads(line);self.assertTrue(ready['intent_persisted'])
            process.kill();process.wait(timeout=10)
            self.assertEqual(process.returncode,-signal.SIGKILL)
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=10)
            for stream in (process.stdin,process.stdout,process.stderr):
                if stream is not None:stream.close()
        with Journal(self.store) as journal:
            state=journal.state(identity)[0]
            old_session=state['session'];intent=state['pending_operation']['intent_id']
            count=len(journal.history(identity))
            self.assertEqual(state['bookings'][intent]['outcome'],'intent')
            holds=state['resources'];self.assertTrue(holds)
        code,report=self.cli('report',identity)
        self.assertEqual(code,0)
        self.assertEqual(report['bookings'][intent]['outcome'],'intent')
        self.assertFalse(report['hardware_executed'])
        with Journal(self.store) as journal:self.assertEqual(len(journal.history(identity)),count)
        clock=FixtureClock(clock_id='Fixture.CLI.NewClock',process_id='Fixture.CLI.NewWriter')
        clock_file=self.directory/'clock.json';clock_file.write_text(json.dumps(clock.sample()))
        blocked_parent=self.directory/'existing-file';blocked_parent.write_text('Preserve this file')
        code,error=self.cli('resume',identity,'--clock',clock_file,'--out',blocked_parent/'result.json')
        self.assertEqual(code,1)
        with Journal(self.store) as journal:
            self.assertEqual(len(journal.history(identity)),count)
            self.assertEqual(journal.state(identity)[0]['session'],old_session)
        self.assertEqual(blocked_parent.read_text(),'Preserve this file')
        code,resume=self.cli('resume',identity,'--clock',clock_file)
        self.assertEqual(code,0);self.assertNotEqual(resume['session'],old_session)
        with Journal(self.store) as journal:
            after=journal.state(identity)[0]
            self.assertEqual(after['bookings'][intent]['outcome'],'intent')
            self.assertEqual(after['resources'],holds)
            self.assertTrue(after['recovery_required'])
            self.assertEqual(len(journal.history(identity)),count+1)
        envelope={'observation_id':'Fixture.CLI.Unknown','source_kind':'test_fixture','observed_at':None,
                  'source_ref':'fixture://CLI','artifact_sha256':None}
        observation=self.directory/'observation.json';observation.write_text(json.dumps(envelope))
        arguments=['--clock',clock_file,'--actor','Fixture.Operator','--action','resolve_sonication',
                   '--observation',observation,'--data',json.dumps({'intent_id':intent,'outcome':'unknown','reason':'Explicit CLI fixture uncertainty'})]
        code,error=self.cli('act',identity,'--session',old_session,*arguments)
        self.assertEqual(code,1)
        with Journal(self.store) as journal:self.assertEqual(len(journal.history(identity)),count+1)
        code,state=self.cli('act',identity,'--session',resume['session'],*arguments)
        self.assertEqual(code,0)
        self.assertEqual(state['bookings'][intent]['outcome'],'unknown')
        self.assertEqual(state['resources'],holds)
        with Journal(self.store) as journal:
            count=len(journal.history(identity))
        code,same=self.cli('act',identity,'--session',resume['session'],*arguments)
        self.assertEqual(code,0)
        with Journal(self.store) as journal:self.assertEqual(len(journal.history(identity)),count)

    def test_complete_three_scenarios_and_repeated_demo_do_not_reset_materials(self):
        directory=self.directory/'three-scenarios'
        code,result=self.cli('demo','--directory',directory)
        self.assertEqual(code,0,result)
        self.assertEqual({item['scenario_id']:item['status'] for item in result['scenarios']},
                         {'normal':'working','restart':'working','cancel':'cancelled'})
        self.assertFalse(result['hardware_executed'])
        with Journal(self.store) as journal:
            heads={item['run_id']:journal.history(item['run_id'])[-1]['sha256'] for item in result['scenarios']}
        code,error=self.cli('demo','--directory',directory)
        self.assertEqual(code,1)
        with Journal(self.store) as journal:
            self.assertEqual({run:journal.history(run)[-1]['sha256'] for run in heads},heads)

    def test_fixture_run_id_is_validated_before_any_directory_or_store_write(self):
        for run_id in (str(self.directory/'escaped'), '../escaped', 'bad/id', 'SYN.WrongEngine', 'x'*65):
            with self.subTest(run_id=run_id):
                code,error=self.cli('fixture-intent','--directory',self.directory/'child','--run-id',run_id)
                self.assertEqual(code,1)
                self.assertIn('Run id',error['error'])
                self.assertFalse(self.store.exists())
                self.assertFalse((self.directory/'child').exists())
        self.assertFalse((self.directory/'escaped.fixture-decisions.json').exists())


if __name__=='__main__':unittest.main()
