"""T2's queue reuses existing owner identities without creating an inventory."""
import copy
import itertools
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import async_transport_domain as domain


class EmbeddedTransportTests(unittest.TestCase):
    def setUp(self):
        # This is the existing, explicitly independent two-rack test world.
        # No biological twelve-sample manifest is copied or repartitioned.
        definition = domain.load_definition()
        self.topology = {key: copy.deepcopy(definition[key]) for key in (
            'owner_principal', 'racks', 'endpoints', 'agents', 'protocol')}
        owner = domain.initial_state(definition, 'SYN.Existing.Owner', 'OwnerSession')
        self.owner = domain.apply(owner, 'admit', {}, definition['owner_principal'])
        self.original_inventory = copy.deepcopy(self.owner['inventory'])
        self.manifests = {rack['id']: domain.manifest(self.owner, rack['id'])
                          for rack in self.topology['racks']}
        self.principal = self.topology['owner_principal']
        self.queue = domain.embedded_initial(self.topology, self.manifests,
                                            self.owner['run_id'], self.owner['session'])

    def act(self, operation, principal=None, **args):
        self.queue = domain.embedded_apply(self.queue, operation, args,
            self.principal if principal is None else principal, self.topology, self.manifests)
        return self.queue

    def prepare(self, job='Job01', rack='SYN.Async.Rack01', target='LabB.S1', agent='AgentHuman'):
        self.act('request', job_id=job, rack_id=rack, target_endpoint=target, agent_id=agent)
        self.act('reserve', job_id=job)
        self.act('prepare', job_id=job)
        return domain.embedded_envelope(self.queue, job, self.topology)

    def receipt(self, envelope, role, identity=None, **changes):
        observation = domain.observation_for(envelope, role,
            identity or envelope['job_id'] + '.' + role)
        observation.update(changes)
        return self.act('observe', principal=domain.principal_for(envelope, role),
                        job_id=envelope['job_id'], observation=observation)

    def finish(self, envelope):
        self.act('mark_dispatched', job_id=envelope['job_id'])
        for role in domain.ROLES:
            self.receipt(envelope, role)

    def test_queue_contains_only_transport_state_and_never_initializes_inventory(self):
        before = copy.deepcopy(self.manifests)
        with patch.object(domain.ledger, 'initial_inventory', side_effect=AssertionError('No inventory creation')):
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Pure queue operation')):
                queue = domain.embedded_initial(self.topology, self.manifests,
                                                self.owner['run_id'], 'OtherSession')
                self.assertTrue(domain.embedded_audit(queue, self.topology, self.manifests))
                domain.embedded_apply(queue, 'request', {'job_id': 'Job01',
                    'rack_id': 'SYN.Async.Rack01', 'target_endpoint': 'LabB.S1',
                    'agent_id': 'AgentHuman'}, self.principal, self.topology, self.manifests)
        self.assertEqual(set(queue), set(domain.EMBEDDED_FIELDS))
        self.assertFalse({'inventory', 'definition', 'manifests', 'bookings'} & set(queue))
        self.assertFalse(any(resource.startswith('fixture:') for resource in queue['resources']))
        self.assertEqual(self.manifests, before)
        self.assertEqual(self.owner['inventory'], self.original_inventory)
        with self.assertRaises(domain.DomainError):
            self.act('admit')

    def test_all_receipt_orders_preserve_causal_custody_and_owner_inventory(self):
        envelope = self.prepare()
        self.act('mark_dispatched', job_id='Job01')
        prepared = copy.deepcopy(self.queue)
        for order in itertools.permutations(domain.ROLES):
            self.queue = copy.deepcopy(prepared)
            for index, role in enumerate(order):
                self.receipt(envelope, role)
                if not set(domain.ROLES[:2]) <= set(order[:index + 1]):
                    self.assertEqual(self.queue['rack_placements'][envelope['rack_id']],
                                     {'kind': 'endpoint', 'endpoint_id': 'LabA.S1'})
            self.assertEqual(self.queue['jobs']['Job01']['phase'], 'completed')
            self.assertEqual(self.queue['rack_placements'][envelope['rack_id']],
                             {'kind': 'endpoint', 'endpoint_id': 'LabB.S1'})
            self.assertTrue(all(item['status'] == 'applied' for item in self.queue['inbox'].values()))
        self.assertEqual(self.owner['inventory'], self.original_inventory)

    def test_completed_jobs_keep_frozen_revisions_after_later_owner_withdrawals(self):
        first = self.prepare()
        self.finish(first)
        snapshot = copy.deepcopy(self.queue['outbox']['Job01']['envelope'])
        self.manifests[first['rack_id']][0]['content_revision'] += 1
        self.assertTrue(domain.embedded_audit(self.queue, self.topology, self.manifests))
        self.assertEqual(domain.embedded_envelope(self.queue, 'Job01', self.topology), snapshot)
        following = self.prepare('Job02', target='LabA.S1', agent='AgentRobot')
        self.assertEqual(following['manifest'][0]['content_revision'], 1)
        self.assertEqual(snapshot['manifest'][0]['content_revision'], 0)
        self.finish(following)
        self.assertTrue(domain.embedded_audit(self.queue, self.topology, self.manifests))
        self.assertEqual(self.queue['outbox']['Job01']['envelope'], snapshot)

    def test_open_claim_rejects_content_drift_without_changing_the_queue(self):
        envelope = self.prepare()
        before = copy.deepcopy(self.queue)
        self.manifests[envelope['rack_id']][0]['content_revision'] += 1
        with self.assertRaises(domain.DomainError):
            domain.embedded_audit(self.queue, self.topology, self.manifests)
        with self.assertRaises(domain.DomainError):
            self.act('mark_dispatched', job_id='Job01')
        self.assertEqual(self.queue, before)

    def test_missing_or_rebound_payload_identity_is_rejected_before_first_request(self):
        for mutation in ('missing', 'rebound'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.manifests)
                if mutation == 'missing':
                    changed['SYN.Async.Rack01'].pop()
                else:
                    changed['SYN.Async.Rack01'][0]['vessel_id'] = 'Unknown.Vessel'
                with self.assertRaises(domain.DomainError):
                    domain.embedded_apply(self.queue, 'request', {'job_id': 'Job01',
                        'rack_id': 'SYN.Async.Rack01', 'target_endpoint': 'LabB.S1',
                        'agent_id': 'AgentHuman'}, self.principal, self.topology, changed)

    def test_two_disjoint_jobs_are_open_without_sharing_claims(self):
        self.prepare()
        self.prepare('Job02', rack='SYN.Async.Rack02', target='LabB.S2', agent='AgentRobot')
        first, second = (self.queue['jobs'][identity] for identity in ['Job01', 'Job02'])
        self.assertEqual(first['phase'], 'pickup_pending')
        self.assertEqual(second['phase'], 'pickup_pending')
        self.assertFalse(set(first['claims']) & set(second['claims']))
        self.act('request', job_id='Conflict', rack_id='SYN.Async.Rack01',
                 target_endpoint='LabB.S2', agent_id='AgentRobot')
        with self.assertRaises(domain.DomainError):
            self.act('reserve', job_id='Conflict')

    def test_claim_alone_and_duplicate_receipts_do_not_change_custody_twice(self):
        envelope = self.prepare()
        self.act('mark_dispatched', job_id='Job01')
        placement = copy.deepcopy(self.queue['rack_placements'])
        self.act('worker_claim', principal=envelope['agent_principal'], job_id='Job01',
                 claim=domain.claim_for(envelope, 'Claim01'))
        self.assertEqual(self.queue['rack_placements'], placement)
        for role in domain.ROLES:
            self.receipt(envelope, role)
        completed = copy.deepcopy(self.queue)
        self.receipt(envelope, 'delivery_accept')
        self.assertEqual(self.queue, completed)
        self.receipt(envelope, 'delivery_accept', identity='NewMessageSameRole')
        self.assertEqual(self.queue['inbox']['NewMessageSameRole']['status'], 'duplicate')
        self.assertEqual(self.queue['rack_placements'], completed['rack_placements'])

    def test_resume_retains_claims_and_marks_old_receipts_stale(self):
        envelope = self.prepare()
        self.act('mark_dispatched', job_id='Job01')
        claims = copy.deepcopy(self.queue['jobs']['Job01']['claims'])
        self.act('resume', session='AfterRestart')
        self.assertEqual(self.queue['jobs']['Job01']['control'], 'held')
        self.assertEqual(self.queue['outbox']['Job01']['status'], 'uncertain')
        self.assertEqual(self.queue['jobs']['Job01']['claims'], claims)
        self.receipt(envelope, 'pickup_release')
        self.assertEqual(self.queue['inbox']['Job01.pickup_release']['status'], 'stale')
        with self.assertRaises(domain.DomainError):
            self.act('mark_dispatched', job_id='Job01')

    def test_cancelled_dispatched_job_needs_disposition_without_fabricated_receipts(self):
        envelope = self.prepare()
        self.act('mark_dispatched', job_id='Job01')
        self.receipt(envelope, 'pickup_release')
        self.receipt(envelope, 'pickup_accept')
        self.act('cancel', job_id='Job01', reason='synthetic cancellation')
        self.assertTrue(self.queue['jobs']['Job01']['claims'])
        self.act('reconcile', job_id='Job01', outcome='unknown', location=None,
                 manifest=envelope['manifest'], reason='unresolved whereabouts')
        self.assertEqual(self.queue['rack_placements'][envelope['rack_id']]['kind'], 'agent')
        self.assertTrue(self.queue['jobs']['Job01']['claims'])
        self.act('reconcile', job_id='Job01', outcome='performed',
                 location={'kind': 'endpoint', 'endpoint_id': 'LabB.S1'},
                 manifest=envelope['manifest'], reason='explicit synthetic supported disposition')
        self.assertEqual(self.queue['jobs']['Job01']['phase'], 'cancelled_reconciled')
        self.assertEqual(set(self.queue['jobs']['Job01']['receipts']), set(domain.ROLES[:2]))
        self.assertEqual(self.queue['jobs']['Job01']['claims'], [])

    def test_late_terminal_conflict_quarantines_dispatched_followup(self):
        first = self.prepare()
        self.finish(first)
        following = self.prepare('Job02', target='LabA.S1', agent='AgentRobot')
        self.act('mark_dispatched', job_id='Job02')
        self.receipt(first, 'delivery_accept', identity='ContradictoryLateReceipt', rack_id='WrongRack')
        for role in domain.ROLES:
            self.receipt(following, role)
        self.assertEqual(self.queue['jobs']['Job02']['control'], 'held')
        self.assertNotEqual(self.queue['jobs']['Job02']['phase'], 'completed')
        self.assertIn('agent:AgentRobot', self.queue['resources'])
        with self.assertRaises(domain.DomainError):
            self.act('request', job_id='Job03', rack_id=first['rack_id'],
                     target_endpoint='LabA.S1', agent_id='AgentHuman')

    def test_embedded_receipts_and_claims_keep_strict_json_types(self):
        envelope = self.prepare()
        self.act('mark_dispatched', job_id='Job01')
        for invalid in (True, 1.0):
            with self.subTest(epoch=invalid):
                with self.assertRaises(domain.DomainError):
                    self.receipt(envelope, 'pickup_release', assignment_epoch=invalid)
        claim = domain.claim_for(envelope, 'Claim01')
        claim['motion_executed'] = 0
        with self.assertRaises(domain.DomainError):
            self.act('worker_claim', principal=envelope['agent_principal'], job_id='Job01', claim=claim)

    def test_topology_aliases_and_cross_payload_identity_aliases_are_rejected(self):
        topology = copy.deepcopy(self.topology)
        topology['endpoints'][1].update({key: topology['endpoints'][0][key]
            for key in ['site_id', 'lab_id', 'holder_id', 'place_id']})
        with self.assertRaises(domain.DomainError):
            domain.embedded_initial(topology, self.manifests, 'Owner01', 'Session01')
        for field in ('vessel_id', 'material_id'):
            with self.subTest(field=field):
                manifests = copy.deepcopy(self.manifests)
                if field == 'vessel_id':
                    manifests['SYN.Async.Rack02'][0][field] = manifests['SYN.Async.Rack01'][0][field]
                else:
                    manifests['SYN.Async.Rack02'][0]['materials'][0][field] = manifests['SYN.Async.Rack01'][0]['materials'][0][field]
                with self.assertRaises(domain.DomainError):
                    domain.embedded_initial(self.topology, manifests, 'Owner01', 'Session01')

    def test_completed_target_stays_reserved_and_agent_is_released(self):
        envelope = self.prepare()
        self.finish(envelope)
        resources = domain.embedded_resources(self.queue, self.topology, self.manifests)
        self.assertNotIn('agent:AgentHuman', resources)
        endpoint = next(item for item in self.topology['endpoints'] if item['id'] == 'LabB.S1')
        target = 'place:' + '|'.join(endpoint[key] for key in ['site_id', 'lab_id', 'holder_id', 'place_id'])
        self.assertIn(target, resources)
        self.assertIn('rack:' + envelope['rack_id'], resources)
        self.assertTrue(all('vessel:' + item['vessel_id'] in resources for item in envelope['manifest']))


if __name__ == '__main__':
    unittest.main()
