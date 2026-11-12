"""B0 worker reports preserve action bindings and never become observations."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_dna_ros_interfaces import build
from dna_quantification_tasks import (SOURCE, MockTaskWorker, decode_claim,
    decode_feedback, decode_goal, fields, goal_fingerprint, load_contract)
from manual_tasks import Journal, TaskError, digest


class DnaQuantificationTaskTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-task-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.contract = load_contract()
        self.goal = dict(request_id='Request01', goal_id='Goal01', run_id='Run01',
            attempt_id='Attempt01', context_id='Context01', operation='transfer_vessel',
            mode='synthetic_only', sample_id='DNA01', vessel_id='Tube01', executing_agent_id='Agent01',
            source_manifest_sha256='1' * 64, task_contract_sha256=self.contract['source_sha256'],
            content_revision=0, source_kind='rack', source_rack_id='OriginalRack',
            source_place_id='Slot01', source_agent_id='', target_kind='agent',
            target_rack_id='', target_place_id='', target_agent_id='Agent01')

    def tearDown(self):
        self.temp.cleanup()

    def test_generated_action_and_decoder_have_the_same_goal_result_feedback_fields(self):
        output = self.folder / 'generated'
        report = build(output, self.contract)
        action = output / 'action/TransferVessel.action'
        sections = action.read_text(encoding='utf-8').split('\n---\n')
        self.assertEqual(len(sections), 3)
        for section, declaration in zip(sections, ['goal', 'result', 'feedback']):
            actual = [tuple(line.split()) for line in section.splitlines() if line and not line.startswith('#')]
            expected = [(field['ros_type'], field['name']) for field in fields(self.contract, declaration)]
            self.assertEqual(actual, expected)
        self.assertEqual(report['source_sha256'], digest(SOURCE.read_bytes()))
        self.assertTrue(all(value is False for value in report['runtime'].values()))
        for name, checksum in report['artifacts'].items():
            self.assertEqual(digest((output / name).read_bytes()), checksum)
        before = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()}
        self.assertEqual(build(output, self.contract), report)
        self.assertEqual({str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()}, before)

    def test_worker_decodes_wire_json_and_returns_a_detached_claim_not_a_booking(self):
        with Journal(self.folder / 'root.sqlite3') as journal:
            journal.create('ROOT', {'resources': [], 'bookings': {}, 'inventory': {}})
            before = journal.state('ROOT'); history = journal.history('ROOT')
            worker = MockTaskWorker('Agent01', boot_id='Boot01')
            claim = worker.dispatch(json.dumps(self.goal).encode())
            self.assertEqual(journal.state('ROOT'), before)
            self.assertEqual(journal.history('ROOT'), history)
            self.assertEqual(journal.owners(), {})
        self.assertEqual(decode_claim(claim, self.goal), claim)
        self.assertEqual(claim['evidence'], 'worker_claim')
        self.assertEqual(claim['outcome'], 'claimed_performed')
        self.assertFalse(claim['motion_executed'])
        self.assertEqual(claim['worker_boot_id'], 'Boot01')
        self.assertEqual(self.goal['target_agent_id'], 'Agent01')
        claim['target_agent_id'] = 'Forged'
        self.assertEqual(worker.dispatch(self.goal)['target_agent_id'], 'Agent01')

    def test_same_goal_is_idempotent_within_one_boot_and_conflicting_reuse_is_rejected(self):
        worker = MockTaskWorker('Agent01', boot_id='Boot01')
        claim = worker.dispatch(self.goal)
        self.assertEqual(worker.dispatch(copy.deepcopy(self.goal)), claim)
        for field, value in [('request_id', 'OtherRequest'), ('sample_id', 'OtherSample'),
                             ('content_revision', 1), ('source_manifest_sha256', '2' * 64)]:
            with self.subTest(field=field), self.assertRaisesRegex(TaskError, 'different task arguments'):
                worker.dispatch({**self.goal, field: value})

    def test_worker_restart_exposes_a_new_boot_without_claiming_persistent_deduplication(self):
        first = MockTaskWorker('Agent01', boot_id='Boot01').dispatch(self.goal)
        second = MockTaskWorker('Agent01', boot_id='Boot02').dispatch(self.goal)
        self.assertNotEqual(first['worker_boot_id'], second['worker_boot_id'])
        self.assertNotEqual(first['claim_id'], second['claim_id'])
        self.assertEqual({key: first[key] for key in self.goal}, self.goal)

    def test_endpoint_kind_does_not_encode_a_custodian_as_a_rack(self):
        returned = {**self.goal, 'source_kind': 'agent', 'source_rack_id': '', 'source_place_id': '',
                    'source_agent_id': 'Agent01', 'target_kind': 'rack', 'target_rack_id': 'OriginalRack',
                    'target_place_id': 'Slot01', 'target_agent_id': ''}
        self.assertEqual(decode_goal(returned), returned)
        variants = [dict(self.goal, target_rack_id='Agent01'), dict(self.goal, target_place_id='Hand'),
                    dict(self.goal, source_agent_id='Agent01'), dict(self.goal, source_place_id=''),
                    dict(self.goal, target_agent_id='OtherAgent'),
                    dict(returned, source_kind='rack', source_rack_id='Rack2', source_place_id='Slot02', source_agent_id='')]
        for index, goal in enumerate(variants):
            with self.subTest(variant=index), self.assertRaises(TaskError):
                decode_goal(goal)

    def test_wrong_executor_and_contract_pin_are_rejected_before_a_claim(self):
        with self.assertRaisesRegex(TaskError, 'another executing agent'):
            MockTaskWorker('OtherAgent').dispatch(self.goal)
        with self.assertRaisesRegex(TaskError, 'digest mismatch'):
            MockTaskWorker('Agent01').dispatch({**self.goal, 'task_contract_sha256': '0' * 64})

    def test_each_result_binding_must_echo_the_goal(self):
        claim = MockTaskWorker('Agent01').dispatch(self.goal)
        for field, value in [('request_id', 'OtherRequest'), ('goal_id', 'OtherGoal'),
                             ('run_id', 'OtherRun'), ('attempt_id', 'OtherAttempt'),
                             ('context_id', 'OtherContext'), ('vessel_id', 'OtherVessel'),
                             ('sample_id', 'OtherSample'), ('content_revision', 1),
                             ('source_manifest_sha256', '2' * 64), ('source_place_id', 'Slot02')]:
            with self.subTest(field=field), self.assertRaises(TaskError):
                decode_claim({**claim, field: value}, self.goal)

    def test_exact_generated_shapes_reject_omitted_extra_and_duplicate_fields(self):
        claim = MockTaskWorker('Agent01').dispatch(self.goal)
        for decoder, value in [(decode_goal, self.goal), (decode_claim, claim)]:
            for field in value:
                incomplete = {key: item for key, item in value.items() if key != field}
                with self.subTest(decoder=decoder.__name__, omitted=field), self.assertRaises(TaskError):
                    decoder(incomplete)
            with self.assertRaises(TaskError):
                decoder({**value, 'volume_ul': 2})
            wire = json.dumps(value)[:-1] + ',"goal_id":"Duplicate"}'
            with self.assertRaisesRegex(TaskError, 'Duplicate task field'):
                decoder(wire)

    def test_counter_and_identity_types_cannot_be_coerced(self):
        for value in [-1, 2**64, 1.0, True, '1', float('nan')]:
            with self.subTest(content_revision=value), self.assertRaises(TaskError):
                decode_goal({**self.goal, 'content_revision': value})
        for value in ['', ' Goal01', 'Goal01\n', 1, True, None]:
            with self.subTest(goal_id=value), self.assertRaises(TaskError):
                decode_goal({**self.goal, 'goal_id': value})
        self.assertEqual(decode_goal({**self.goal, 'content_revision': 2**64 - 1})['content_revision'], 2**64 - 1)
        with self.assertRaises(TaskError):
            decode_goal(json.dumps({**self.goal, 'content_revision': float('inf')}))
        with self.assertRaises(TaskError):
            MockTaskWorker('Agent01', boot_id='')

    def test_claim_evidence_and_motion_flags_cannot_be_promoted(self):
        claim = MockTaskWorker('Agent01').dispatch(self.goal)
        for field, value in [('evidence', 'person_confirmation'), ('evidence', 'sensor'),
                             ('motion_executed', True), ('motion_executed', 0),
                             ('motion_executed', 'false'), ('outcome', 'verified_performed')]:
            with self.subTest(field=field, value=value), self.assertRaises(TaskError):
                decode_claim({**claim, field: value}, self.goal)
        with self.assertRaises(TaskError):
            decode_goal({**self.goal, 'mode': 'hardware'})

    def test_feedback_carries_only_a_goal_binding_and_an_explicit_phase(self):
        feedback = {'goal_id': 'Goal01', 'phase': 'claim_ready'}
        self.assertEqual(decode_feedback(json.dumps(feedback), self.goal), feedback)
        for changed in [dict(feedback, progress=1), dict(feedback, phase='motion_completed'),
                        dict(feedback, goal_id='OtherGoal')]:
            with self.assertRaises(TaskError):
                decode_feedback(changed, self.goal)

    def test_fingerprint_is_order_independent_and_binds_every_goal_field(self):
        self.assertEqual(goal_fingerprint(self.goal), goal_fingerprint(dict(reversed(list(self.goal.items())))))
        self.assertNotEqual(goal_fingerprint(self.goal), goal_fingerprint({**self.goal, 'content_revision': 1}))

    def test_malformed_or_promoted_leading_contract_is_rejected(self):
        baseline = json.loads(SOURCE.read_text(encoding='utf-8'))
        variants = [dict(baseline, mode='hardware'), dict(baseline, goal_fields=None),
                    dict(baseline, feedback_fields=[])]
        duplicated = copy.deepcopy(baseline); duplicated['goal_fields'].append(duplicated['goal_fields'][0]); variants.append(duplicated)
        promoted = copy.deepcopy(baseline)
        next(field for field in promoted['goal_fields'] if field['name'] == 'mode')['values'].append('hardware')
        variants.append(promoted)
        for index, protocol in enumerate(variants):
            path = self.folder / ('bad-%s.json' % index)
            path.write_text(json.dumps(protocol), encoding='utf-8')
            with self.subTest(variant=index), self.assertRaises(TaskError):
                load_contract(path)


if __name__ == '__main__':
    unittest.main()
