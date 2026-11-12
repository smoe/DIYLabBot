"""Teleportation fixtures keep claims, role evidence and owner effects separate."""
import copy
import itertools
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import async_transport_domain as domain
from async_transport_adapters import HumanTeleportMock, RobotTeleportMock
from manual_tasks import Journal, TaskError


def prepared(kind='human'):
    definition = domain.load_definition()
    owner = definition['owner_principal']
    state = domain.initial_state(definition, 'AdapterTest', 'Session01')
    state = domain.apply(state, 'admit', {}, owner)
    agent = next(item['id'] for item in definition['agents'] if item['kind'] == kind)
    state = domain.apply(state, 'request', {'job_id': 'Job01',
        'rack_id': definition['racks'][0]['id'], 'target_endpoint': 'LabB.S1',
        'agent_id': agent}, owner)
    for operation in ['reserve', 'prepare', 'mark_dispatched']:
        state = domain.apply(state, operation, {'job_id': 'Job01'}, owner)
    return state, domain.envelope(state, 'Job01')


def apply_message(state, message):
    return domain.apply(state, message['operation'], message['args'], message['principal'])


class AsyncTransportAdapterTests(unittest.TestCase):
    def test_both_agent_kinds_return_exact_contract_messages_and_distinct_evidence(self):
        for kind, adapter_type in [('human', HumanTeleportMock), ('robot', RobotTeleportMock)]:
            with self.subTest(kind=kind):
                state, envelope = prepared(kind)
                before = copy.deepcopy(state)
                batch = adapter_type(envelope['agent_id'], boot_id='Boot01').submit(envelope)
                self.assertEqual(state, before)
                self.assertEqual(len(batch), 5)
                self.assertEqual(batch[0]['operation'], 'worker_claim')
                claim = batch[0]['args']['claim']
                self.assertEqual(claim, domain.claim_for(envelope, claim['claim_id']))
                self.assertEqual(batch[0]['principal'], envelope['agent_principal'])
                self.assertEqual(claim['execution_mode'], 'teleportation_mock')
                self.assertEqual(claim['transport_time_s'], 0)
                self.assertIs(claim['motion_executed'], False)
                self.assertIs(claim['hardware_executed'], False)
                self.assertEqual(claim['evidence'], 'worker_claim')
                for message, role in zip(batch[1:], domain.ROLES):
                    self.assertEqual(set(message), {'principal', 'request_id', 'operation', 'args'})
                    self.assertEqual(message['operation'], 'observe')
                    self.assertEqual(set(message['args']), {'job_id', 'observation'})
                    observation = message['args']['observation']
                    self.assertEqual(observation, domain.observation_for(
                        envelope, role, observation['observation_id']))
                    self.assertEqual(message['principal'], domain.principal_for(envelope, role))
                    expected = ('synthetic_endpoint_attestation' if role in
                        {'pickup_release', 'delivery_accept'} else
                        'synthetic_courier_attestation' if kind == 'human' else
                        'synthetic_robot_attestation')
                    self.assertEqual(observation['evidence'], expected)
                self.assertEqual(len({message['request_id'] for message in batch}), 5)

    def test_all_receipt_permutations_reach_same_owner_result_without_changing_contents(self):
        initial, envelope = prepared()
        for order in itertools.permutations(domain.ROLES):
            with self.subTest(order=order):
                batch = HumanTeleportMock(envelope['agent_id'], order=order,
                                          boot_id='Boot01').submit(envelope)
                self.assertEqual([item['args']['observation']['role'] for item in batch[1:]], list(order))
                state = initial
                for message in batch:
                    state = apply_message(state, message)
                self.assertEqual(state['jobs']['Job01']['phase'], 'completed')
                self.assertEqual(state['rack_placements'][envelope['rack_id']],
                                 {'kind': 'endpoint', 'endpoint_id': envelope['target_endpoint']})
                self.assertEqual(state['inventory'], initial['inventory'])
                self.assertEqual(state['bookings'], {})
                self.assertEqual(len(state['inbox']), 4)
                self.assertTrue(all(item['status'] == 'applied' for item in state['inbox'].values()))

    def test_delivery_before_late_pickup_is_pending_and_claim_alone_never_moves_rack(self):
        state, envelope = prepared()
        batch = HumanTeleportMock(envelope['agent_id'], order=(
            'delivery_accept', 'delivery_release', 'pickup_accept', 'pickup_release')).submit(envelope)
        initial_place = copy.deepcopy(state['rack_placements'])
        state = apply_message(state, batch[0])
        self.assertEqual(state['rack_placements'], initial_place)
        self.assertEqual(state['inbox'], {})
        for message in batch[1:3]:
            state = apply_message(state, message)
        self.assertEqual(state['rack_placements'], initial_place)
        self.assertEqual(state['jobs']['Job01']['phase'], 'pickup_pending')
        self.assertTrue(all(item['status'] == 'pending' for item in state['inbox'].values()))
        state = apply_message(state, batch[3])
        self.assertEqual(state['rack_placements'], initial_place)
        state = apply_message(state, batch[4])
        self.assertEqual(state['jobs']['Job01']['phase'], 'completed')

    def test_input_and_every_return_are_detached_from_cache_and_each_other(self):
        _, envelope = prepared()
        source = copy.deepcopy(envelope)
        worker = HumanTeleportMock(envelope['agent_id'], boot_id='Boot01')
        first = worker.submit(source)
        original = copy.deepcopy(first)
        self.assertEqual(source, envelope)
        source['manifest'][0]['materials'][0]['material_id'] = 'ChangedInput'
        source['manifest_sha256'] = domain.hashed(source['manifest'])
        first[0]['args']['claim']['motion_executed'] = True
        first[1]['args']['observation']['evidence'] = 'ForgedEvidence'
        first[1]['principal'] = 'ForgedPrincipal'
        second = worker.submit(envelope)
        self.assertEqual(second, original)
        second[2]['args']['observation']['rack_id'] = 'ChangedReturn'
        self.assertEqual(worker.submit(envelope), original)

    def test_order_argument_is_copied_before_caller_mutates_it(self):
        _, envelope = prepared()
        order = list(reversed(domain.ROLES))
        worker = HumanTeleportMock(envelope['agent_id'], order=order)
        order[:] = []
        batch = worker.submit(envelope)
        self.assertEqual([item['args']['observation']['role'] for item in batch[1:]],
                         list(reversed(domain.ROLES)))

    def test_same_assignment_is_within_boot_idempotent_but_conflicting_reuse_is_rejected(self):
        _, envelope = prepared()
        worker = HumanTeleportMock(envelope['agent_id'])
        first = worker.submit(envelope)
        self.assertEqual(worker.submit(copy.deepcopy(envelope)), first)
        for key in ['rack_id', 'target_endpoint', 'source_principal', 'target_principal',
                    'agent_principal', 'pickup_handover_id', 'delivery_handover_id']:
            with self.subTest(field=key), self.assertRaisesRegex(TaskError, 'different arguments'):
                worker.submit({**envelope, key: 'ChangedValue'})
        changed = copy.deepcopy(envelope)
        changed['manifest'][0]['content_revision'] += 1
        changed['manifest_sha256'] = domain.hashed(changed['manifest'])
        with self.assertRaisesRegex(TaskError, 'different arguments'):
            worker.submit(changed)

    def test_restart_does_not_recover_or_submit_and_only_claim_identity_changes_with_boot(self):
        _, envelope = prepared()
        first = HumanTeleportMock(envelope['agent_id'], boot_id='Boot01').submit(envelope)
        with mock.patch.object(HumanTeleportMock, 'submit', side_effect=AssertionError('automatic dispatch')):
            restarted = HumanTeleportMock(envelope['agent_id'], boot_id='Boot02')
        second = restarted.submit(envelope)  # Explicit caller action, never recovery.
        self.assertNotEqual(first[0]['args']['claim']['claim_id'], second[0]['args']['claim']['claim_id'])
        self.assertNotEqual(first[0]['request_id'], second[0]['request_id'])
        self.assertEqual(first[1:], second[1:])
        self.assertEqual(first[0]['args']['claim']['envelope_sha256'],
                         second[0]['args']['claim']['envelope_sha256'])
        self.assertNotIn('worker_boot_id', second[0]['args']['claim'])

    def test_distinct_jobs_and_epochs_have_distinct_receipt_identifiers(self):
        _, envelope = prepared()
        worker = HumanTeleportMock(envelope['agent_id'], boot_id='Boot01')
        batches = [worker.submit(envelope)]
        for change in [{'job_id': 'Job02'}, {'assignment_epoch': envelope['assignment_epoch'] + 1}]:
            batches.append(worker.submit({**envelope, **change}))
        identifiers = [message['args']['observation']['observation_id']
                       for batch in batches for message in batch[1:]]
        self.assertEqual(len(set(identifiers)), 12)

    def test_exact_envelope_shape_rejects_every_omission_and_added_authority_handle(self):
        _, envelope = prepared()
        worker = HumanTeleportMock(envelope['agent_id'])
        for field in envelope:
            with self.subTest(omitted=field), self.assertRaises(TaskError):
                worker.submit({key: value for key, value in envelope.items() if key != field})
        for field, value in [('inventory', {}), ('principal', 'ForgedOwner'), ('journal', None),
                             ('transport_time_s', 100), ('motion_executed', True)]:
            with self.subTest(extra=field), self.assertRaises(TaskError):
                worker.submit({**envelope, field: value})

    def test_manifest_contract_epoch_and_execution_mode_fail_closed(self):
        _, envelope = prepared()
        worker = HumanTeleportMock(envelope['agent_id'])
        variants = [dict(envelope, manifest_sha256='0' * 64),
                    dict(envelope, contract_sha256='0' * 64),
                    dict(envelope, assignment_epoch=True), dict(envelope, assignment_epoch=0),
                    dict(envelope, execution_mode='hardware'),
                    dict(envelope, execution_mode='robot_motion')]
        changed = copy.deepcopy(envelope)
        changed['manifest'].append(copy.deepcopy(changed['manifest'][0]))
        changed['manifest_sha256'] = domain.hashed(changed['manifest'])
        variants.append(changed)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(TaskError):
                worker.submit(value)

    def test_agent_identity_and_kind_are_not_inferred_or_silently_overridden(self):
        _, envelope = prepared()
        with self.assertRaisesRegex(TaskError, 'another agent'):
            HumanTeleportMock('AnotherAgent').submit(envelope)
        with self.assertRaisesRegex(TaskError, 'different mock agent kind'):
            RobotTeleportMock(envelope['agent_id']).submit(envelope)

    def test_order_and_constructor_identifiers_fail_closed(self):
        for value in [[], list(domain.ROLES)[:-1], ['pickup_release'] * 4,
                      list(domain.ROLES[:-1]) + ['unknown'], 'pickup_release',
                      list(domain.ROLES[:-1]) + [[]], set(domain.ROLES)]:
            with self.subTest(order=value), self.assertRaises(TaskError):
                HumanTeleportMock('AgentHuman', order=value)
        for value in ['', None, True, ' spaced ']:
            with self.subTest(agent=value), self.assertRaises(TaskError):
                HumanTeleportMock(value)
        with self.assertRaises(TaskError):
            HumanTeleportMock('AgentHuman', boot_id='')

    def test_submit_does_not_access_journal_database_network_or_wait(self):
        _, envelope = prepared()
        with tempfile.TemporaryDirectory() as directory:
            with Journal(Path(directory) / 'owner.sqlite3') as journal:
                journal.create('Owner', {'inventory': {'sentinel': 1}, 'resources': []})
                before = journal.state('Owner')
                history = journal.history('Owner')
                with mock.patch.object(sqlite3, 'connect', side_effect=AssertionError('database access')), \
                        mock.patch.object(socket, 'socket', side_effect=AssertionError('network access')), \
                        mock.patch('time.sleep', side_effect=AssertionError('travel delay')):
                    HumanTeleportMock(envelope['agent_id']).submit(envelope)
                self.assertEqual(journal.state('Owner'), before)
                self.assertEqual(journal.history('Owner'), history)
                self.assertEqual(journal.owners(), {})


if __name__ == '__main__':
    unittest.main()
