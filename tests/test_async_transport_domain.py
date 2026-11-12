import copy
import itertools
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import async_transport_domain as domain


class AsyncTransportDomainTests(unittest.TestCase):
    def setUp(self):
        self.definition = domain.load_definition()
        self.owner = self.definition['owner_principal']
        self.state = domain.initial_state(self.definition, 'SYN.Test.Root', 'Session01')

    def act(self, operation, principal=None, **args):
        self.state = domain.apply(self.state, operation, args, principal or self.owner)
        return self.state

    def prepared(self, job_id='Job01', rack_id='SYN.Async.Rack01', target='LabB.S1', agent='AgentHuman'):
        if not self.state['admitted']: self.act('admit')
        self.act('request', job_id=job_id, rack_id=rack_id, target_endpoint=target, agent_id=agent)
        self.act('reserve', job_id=job_id)
        self.act('prepare', job_id=job_id)
        return domain.envelope(self.state, job_id)

    def receipt(self, env, role, identity=None):
        observation = domain.observation_for(env, role, identity or env['job_id'] + '.' + role)
        return self.act('observe', domain.principal_for(env, role), job_id=env['job_id'], observation=observation)

    def complete(self, env):
        self.act('mark_dispatched', job_id=env['job_id'])
        for role in domain.ROLES: self.receipt(env, role)

    def test_created_fixture_has_no_inventory_holds_or_implicit_acceptance(self):
        self.assertFalse(self.state['admitted'])
        self.assertEqual(self.state['inventory'], {})
        self.assertEqual(self.state['resources'], [])
        with self.assertRaises(domain.DomainError):
            self.act('request', job_id='Job01', rack_id='SYN.Async.Rack01', target_endpoint='LabB.S1', agent_id='AgentHuman')
        self.act('admit')
        self.assertEqual(len(self.state['inventory']['vessels']), 4)
        self.assertEqual(len(self.state['resources']), 13)
        self.assertTrue(any(m['initial_quantity']['value'] is None for m in self.state['inventory']['materials'].values()))
        with self.assertRaises(domain.DomainError): self.act('admit')

    def test_all_24_receipt_orders_apply_same_causal_custody(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01'); base = copy.deepcopy(self.state)
        for order in itertools.permutations(domain.ROLES):
            self.state = copy.deepcopy(base)
            for index, role in enumerate(order):
                self.receipt(env, role)
                job = self.state['jobs']['Job01']
                if not set(domain.ROLES[:2]) <= set(order[:index+1]):
                    self.assertEqual(job['phase'], 'pickup_pending')
                    self.assertEqual(self.state['rack_placements'][env['rack_id']], {'kind':'endpoint','endpoint_id':'LabA.S1'})
            self.assertEqual(self.state['jobs']['Job01']['phase'], 'completed')
            self.assertEqual(self.state['rack_placements'][env['rack_id']], {'kind':'endpoint','endpoint_id':'LabB.S1'})
            self.assertTrue(all(entry['status'] == 'applied' for entry in self.state['inbox'].values()))

    def test_delivery_pair_before_pickup_stays_in_durable_causal_inbox(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01')
        for role in domain.ROLES[2:]: self.receipt(env, role)
        self.assertTrue(all(entry['status'] == 'pending' for entry in self.state['inbox'].values()))
        self.assertEqual(self.state['jobs']['Job01']['phase'], 'pickup_pending')
        self.receipt(env, 'pickup_accept')
        self.assertEqual(self.state['jobs']['Job01']['phase'], 'pickup_pending')
        self.receipt(env, 'pickup_release')
        self.assertEqual(self.state['jobs']['Job01']['phase'], 'completed')

    def test_manifest_quantities_and_slots_do_not_change_across_roundtrip(self):
        env = self.prepared(); inventory = copy.deepcopy(self.state['inventory'])
        self.complete(env)
        env2 = self.prepared('Return', target='LabA.S1', agent='AgentRobot')
        self.complete(env2)
        self.assertEqual(self.state['inventory'], inventory)
        self.assertEqual(self.state['bookings'], {})
        self.assertIsNone(self.state['pending_operation'])
        self.assertEqual(self.state['jobs']['Job01']['manifest'], self.state['jobs']['Return']['manifest'])

    def test_pure_detached_reducer_never_reads_files_or_mutates_input(self):
        before = copy.deepcopy(self.state)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('Reducer must not perform I/O')):
            proposal = domain.apply(self.state, 'admit', {}, self.owner)
        self.assertEqual(self.state, before)
        proposal['inventory']['vessels'].clear()
        self.assertEqual(self.state, before)

    def test_worker_claim_changes_no_custody_and_cannot_promote_evidence(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01')
        initial = copy.deepcopy(self.state['rack_placements'])
        claim = domain.claim_for(env, 'Claim01')
        self.act('worker_claim', env['agent_principal'], job_id='Job01', claim=claim)
        self.assertEqual(self.state['rack_placements'], initial)
        self.assertEqual(self.state['jobs']['Job01']['phase'], 'pickup_pending')
        bad = copy.deepcopy(claim); bad['motion_executed'] = True
        with self.assertRaises(domain.DomainError): self.act('worker_claim', env['agent_principal'], job_id='Job01', claim=bad)

    def test_principal_role_authorization_is_not_taken_from_payload(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01')
        observation = domain.observation_for(env, 'pickup_accept', 'Obs01')
        before = copy.deepcopy(self.state)
        with self.assertRaises(domain.DomainError): self.act('observe', env['source_principal'], job_id='Job01', observation=observation)
        self.assertEqual(self.state, before)
        observation['principal'] = env['agent_principal']
        with self.assertRaises(domain.DomainError): self.act('observe', env['agent_principal'], job_id='Job01', observation=observation)

    def test_missing_or_wrong_rack_manifest_endpoint_and_epoch_hold_preserving_claims(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01'); baseline = copy.deepcopy(self.state)
        for field, value in [('rack_id','OtherRack'), ('manifest_sha256','0'*64), ('source_endpoint','LabA.S2'),
                             ('target_endpoint','LabB.S2'), ('agent_id','AgentRobot'), ('assignment_epoch',2)]:
            self.state = copy.deepcopy(baseline)
            observation = domain.observation_for(env, 'pickup_accept', 'Obs01'); observation[field] = value
            self.act('observe', env['agent_principal'], job_id='Job01', observation=observation)
            self.assertEqual(self.state['jobs']['Job01']['control'], 'held')
            self.assertEqual(self.state['resources'], baseline['resources'])
            self.assertEqual(self.state['rack_placements'], baseline['rack_placements'])
            self.assertEqual(len(self.state['inbox']), 1)

    def test_identical_observation_is_noop_and_new_id_cannot_repeat_handover(self):
        env = self.prepared(); self.complete(env)
        before = copy.deepcopy(self.state)
        self.receipt(env, 'delivery_accept')
        self.assertEqual(self.state, before)
        self.receipt(env, 'delivery_accept', 'RetryNewId')
        self.assertEqual(self.state['jobs'], before['jobs'])
        self.assertEqual(self.state['rack_placements'], before['rack_placements'])
        self.assertEqual(self.state['inbox']['RetryNewId']['status'], 'duplicate')

    def test_handover_authorization_is_bound_to_root_not_only_shared_source_ids(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01')
        other = domain.initial_state(self.definition, 'OtherRoot', 'OtherSession')
        for operation,args in [('admit',{}),('request',{'job_id':'Job01','rack_id':'SYN.Async.Rack01','target_endpoint':'LabB.S1','agent_id':'AgentHuman'}),
                               ('reserve',{'job_id':'Job01'}),('prepare',{'job_id':'Job01'}),('mark_dispatched',{'job_id':'Job01'})]:
            other = domain.apply(other,operation,args,self.owner)
        other_env = domain.envelope(other,'Job01')
        self.assertNotEqual(env['pickup_handover_id'], other_env['pickup_handover_id'])
        foreign_observation = domain.observation_for(other_env,'pickup_accept','ForeignWorld')
        self.act('observe',env['agent_principal'],job_id='Job01',observation=foreign_observation)
        self.assertEqual(self.state['jobs']['Job01']['control'],'held')

    def test_conflicting_observation_id_is_retained_without_overwriting_original(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01')
        self.receipt(env, 'pickup_accept', 'SameId')
        original = copy.deepcopy(self.state['inbox']['SameId'])
        observation = domain.observation_for(env, 'pickup_accept', 'SameId'); observation['rack_id'] = 'WrongRack'
        self.act('observe', env['agent_principal'], job_id='Job01', observation=observation)
        self.assertEqual(self.state['inbox']['SameId'], original)
        self.assertEqual(len(self.state['inbox']), 2)
        self.assertEqual(self.state['jobs']['Job01']['control'], 'held')

    def test_late_conflict_on_completed_job_blocks_new_request_and_prepared_dispatch(self):
        env = self.prepared(); self.complete(env)
        completed = copy.deepcopy(self.state)
        following = self.prepared('Return',target='LabA.S1',agent='AgentRobot')
        observation = domain.observation_for(env,'delivery_accept','LateConflict'); observation['rack_id'] = 'WrongRack'
        self.act('observe',env['target_principal'],job_id='Job01',observation=observation)
        self.assertEqual(self.state['jobs']['Job01']['control'],'held')
        self.assertEqual(self.state['jobs']['Job01']['claims'],[])
        with self.assertRaises(domain.DomainError): self.act('mark_dispatched',job_id=following['job_id'])
        self.state = completed
        self.act('observe',env['target_principal'],job_id='Job01',observation=observation)
        with self.assertRaises(domain.DomainError):
            self.act('request',job_id='New',rack_id=env['rack_id'],target_endpoint='LabA.S1',agent_id='AgentRobot')

    def test_old_epoch_after_reconciled_cancel_blocks_following_job_reservation(self):
        env = self.prepared(); self.act('mark_dispatched',job_id='Job01')
        self.act('resume',session='Session02')
        self.act('reconcile',job_id='Job01',outcome='not_performed',location={'kind':'endpoint','endpoint_id':'LabA.S1'},
                 manifest=env['manifest'],reason='Observed not performed')
        self.act('request',job_id='Retry',rack_id=env['rack_id'],target_endpoint='LabB.S1',agent_id='AgentRobot')
        self.receipt(env,'pickup_accept','OldEpochLate')
        self.assertEqual(self.state['jobs']['Job01']['control'],'held')
        with self.assertRaises(domain.DomainError): self.act('reserve',job_id='Retry')

    def test_late_history_conflict_blocks_already_dispatched_following_receipts(self):
        first = self.prepared(); self.complete(first)
        following = self.prepared('Return',target='LabA.S1',agent='AgentRobot')
        self.act('mark_dispatched',job_id='Return')
        observation = domain.observation_for(first,'delivery_accept','LateConflict'); observation['rack_id'] = 'WrongRack'
        self.act('observe',first['target_principal'],job_id='Job01',observation=observation)
        held_claims = copy.deepcopy(self.state['jobs']['Return']['claims'])
        for role in domain.ROLES: self.receipt(following,role)
        job = self.state['jobs']['Return']
        self.assertEqual(job['control'],'held')
        self.assertEqual(job['hold_reason'],'rack_history_uncertain')
        self.assertNotEqual(job['phase'],'completed')
        self.assertEqual(job['claims'],held_claims)
        self.assertIn('agent:AgentRobot',self.state['resources'])
        self.assertTrue(all(self.state['inbox'][i]['status']=='pending' for i in job['receipts'].values()))

    def test_two_disjoint_jobs_reserve_without_global_blocking(self):
        self.prepared()
        self.prepared('Job02','SYN.Async.Rack02','LabB.S2','AgentRobot')
        self.assertEqual(len(self.state['jobs']), 2)
        self.assertTrue(all(j['control'] == 'active' for j in self.state['jobs'].values()))
        self.assertTrue(set(self.state['jobs']['Job01']['claims']).isdisjoint(self.state['jobs']['Job02']['claims']))

    def test_same_owner_subclaims_prevent_same_rack_target_or_agent(self):
        self.prepared(); baseline = copy.deepcopy(self.state)
        for rack, target, agent in [('SYN.Async.Rack01','LabB.S2','AgentRobot'),
                                    ('SYN.Async.Rack02','LabB.S1','AgentRobot'),
                                    ('SYN.Async.Rack02','LabB.S2','AgentHuman')]:
            self.state = copy.deepcopy(baseline)
            self.act('request', job_id='Other', rack_id=rack, target_endpoint=target, agent_id=agent)
            with self.assertRaises(domain.DomainError): self.act('reserve', job_id='Other')

    def test_occupied_endpoint_and_endpoint_alias_are_rejected(self):
        self.act('admit')
        self.act('request', job_id='Occupied', rack_id='SYN.Async.Rack01', target_endpoint='LabA.S2', agent_id='AgentHuman')
        with self.assertRaises(domain.DomainError): self.act('reserve', job_id='Occupied')
        definition = copy.deepcopy(self.definition)
        definition['endpoints'][1].update({k:definition['endpoints'][0][k] for k in ['site_id','lab_id','holder_id','place_id']})
        with self.assertRaises(domain.DomainError): domain.initial_state(definition,'Other','Session')

    def test_root_holds_survive_completion_but_agent_and_empty_source_release(self):
        env = self.prepared(); root_holds = {x for x in self.state['resources'] if x.startswith(('rack:','material:','vessel:'))}
        self.complete(env)
        self.assertTrue(root_holds <= set(self.state['resources']))
        self.assertNotIn('agent:AgentHuman', self.state['resources'])
        self.assertIn('place:SYN.Site01|LabB|LabB.Handover|S1', self.state['resources'])
        self.assertNotIn('place:SYN.Site01|LabA|LabA.Handover|S1', self.state['resources'])

    def test_cancel_pending_outbox_withdraws_before_any_dispatch(self):
        self.prepared(); self.act('cancel', job_id='Job01', reason='operator_cancel')
        self.assertEqual(self.state['jobs']['Job01']['phase'], 'cancelled')
        self.assertEqual(self.state['outbox']['Job01']['status'], 'withdrawn')
        with self.assertRaises(domain.DomainError): self.act('mark_dispatched', job_id='Job01')

    def test_cancel_after_pickup_keeps_custody_until_explicit_supported_disposition(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01')
        for role in domain.ROLES[:2]: self.receipt(env, role)
        self.act('cancel', job_id='Job01', reason='operator_cancel')
        self.assertEqual(self.state['rack_placements'][env['rack_id']], {'kind':'agent','agent_id':'AgentHuman'})
        self.assertIn('agent:AgentHuman', self.state['resources'])
        self.act('reconcile', job_id='Job01', outcome='unknown', location=None, manifest=env['manifest'], reason='not_observed')
        self.assertEqual(self.state['jobs']['Job01']['control'], 'held')
        self.act('reconcile', job_id='Job01', outcome='performed', location={'kind':'endpoint','endpoint_id':'LabA.S1'}, manifest=env['manifest'], reason='observed_return')
        self.assertEqual(self.state['jobs']['Job01']['phase'], 'cancelled_reconciled')
        self.assertNotEqual(set(self.state['jobs']['Job01']['receipts']), set(domain.ROLES))

    def test_resume_uncertain_dispatch_never_replays_or_accepts_old_epoch(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01')
        before_holds = copy.deepcopy(self.state['resources'])
        self.act('resume', session='Session02')
        self.assertEqual(self.state['assignment_epoch'], 2)
        self.assertEqual(self.state['outbox']['Job01']['status'], 'uncertain')
        with self.assertRaises(domain.DomainError): self.act('mark_dispatched', job_id='Job01')
        self.receipt(env, 'pickup_accept')
        self.assertEqual(self.state['resources'], before_holds)
        self.assertEqual(next(iter(self.state['inbox'].values()))['status'], 'stale')

    def test_timeout_hold_is_not_time_based_resource_release(self):
        self.prepared(); self.act('mark_dispatched', job_id='Job01'); before = copy.deepcopy(self.state['resources'])
        self.act('hold', job_id='Job01', reason='timeout')
        self.assertEqual(self.state['resources'], before)
        self.assertEqual(self.state['outbox']['Job01']['status'], 'uncertain')

    def test_reconcile_nonperformance_requires_source_and_no_performed_role(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01'); self.receipt(env, 'pickup_accept')
        self.act('hold', job_id='Job01', reason='unknown')
        with self.assertRaises(domain.DomainError):
            self.act('reconcile', job_id='Job01', outcome='not_performed', location={'kind':'endpoint','endpoint_id':'LabA.S1'}, manifest=env['manifest'], reason='claim')

    def test_audit_rejects_forged_completion_missing_receipt_and_content_drift(self):
        env = self.prepared(); self.complete(env); complete = copy.deepcopy(self.state)
        bad = copy.deepcopy(complete); del bad['jobs']['Job01']['receipts']['delivery_accept']
        with self.assertRaises(domain.DomainError): domain.audit(bad)
        bad = copy.deepcopy(complete); bad['inventory']['vessels']['SYN.Async.Vessel01']['content_revision'] += 1
        with self.assertRaises(domain.DomainError): domain.audit(bad)
        bad = copy.deepcopy(complete); bad['jobs']['Job01']['manifest'][0]['content_revision'] += 1
        with self.assertRaises(domain.DomainError): domain.audit(bad)

    def test_exact_fields_and_unknown_versions_rejected(self):
        for key,value in [('format','solidcraftbot.async-lab-transport/2'),('mode','hardware')]:
            definition = copy.deepcopy(self.definition); definition[key] = value
            with self.assertRaises(domain.DomainError): domain.initial_state(definition,'Other','Session')
        with self.assertRaises(domain.DomainError): self.act('admit', extra=True)
        env = self.prepared(); env['extra'] = 'forbidden'
        with self.assertRaises(domain.DomainError): domain.decode_envelope(env)

    def test_reconciled_terminal_projection_requires_explicit_owner_evidence(self):
        env = self.prepared(); self.act('mark_dispatched', job_id='Job01')
        self.act('hold', job_id='Job01', reason='unknown')
        self.act('reconcile', job_id='Job01', outcome='not_performed',
                 location={'kind':'endpoint','endpoint_id':'LabA.S1'}, manifest=env['manifest'], reason='observed_source')
        corrupted = copy.deepcopy(self.state); corrupted['jobs']['Job01']['reconciliations'].clear()
        with self.assertRaises(domain.DomainError): domain.audit(corrupted)

    def test_formal_schema_accepts_actual_sources_messages_and_rejects_extra_fields(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema unavailable; execute this test in the existing validation venv')
        schema = json.loads((domain.ROOT/'model/async-lab-transport.schema.json').read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        raw = json.loads(domain.SOURCE.read_bytes())
        jsonschema.Draft202012Validator(schema).validate(raw)
        env = self.prepared()
        for name, value in [('envelope',env),('observation',domain.observation_for(env,'pickup_accept','SchemaObs')),
                            ('worker_claim',domain.claim_for(env,'SchemaClaim'))]:
            selected = {**schema,'$ref':'#/$defs/'+name}
            validator = jsonschema.Draft202012Validator(selected); validator.validate(value)
            with self.assertRaises(jsonschema.ValidationError): validator.validate({**value,'unknown':True})

    def test_source_snapshot_pins_current_bytes_and_protocol(self):
        for name, expected in self.definition['source_files_sha256'].items():
            self.assertEqual(domain.digest((domain.ROOT/name).read_bytes()), expected)
        self.assertEqual(self.definition['protocol']['source_sha256'], domain.load_contract()['source_sha256'])

    def test_duplicate_json_fields_and_nonfinite_numbers_are_not_silently_normalized(self):
        for raw in ['{"mode":"hardware","mode":"synthetic_only"}', '{"quantity":NaN}', '{"quantity":Infinity}']:
            with self.assertRaises(domain.DomainError): domain._json(raw)

    def test_operator_reason_is_text_not_an_identifier(self):
        self.prepared(); self.act('cancel', job_id='Job01', reason='Empfangsstelle ist noch nicht bereit.')
        self.assertEqual(self.state['jobs']['Job01']['phase'], 'cancelled')

    def test_observation_and_claim_epochs_reject_bool_and_float_even_when_equal(self):
        env = self.prepared(); self.act('mark_dispatched',job_id='Job01')
        original = copy.deepcopy(self.state)
        for value in (True,1.0):
            observation = domain.observation_for(env,'pickup_accept','TypedObservation')
            observation['assignment_epoch'] = value
            with self.assertRaises(domain.DomainError):
                self.act('observe',env['agent_principal'],job_id='Job01',observation=observation)
            claim = domain.claim_for(env,'TypedClaim'); claim['assignment_epoch'] = value
            with self.assertRaises(domain.DomainError):
                self.act('worker_claim',env['agent_principal'],job_id='Job01',claim=claim)
            self.assertEqual(self.state,original)

    def test_claim_numeric_flags_and_boolean_or_float_mock_time_are_rejected(self):
        env = self.prepared(); self.act('mark_dispatched',job_id='Job01')
        for field,value in [('motion_executed',0),('hardware_executed',0),('transport_time_s',False),('transport_time_s',0.0)]:
            claim = domain.claim_for(env,'TypedClaim'); claim[field] = value
            with self.assertRaises(domain.DomainError):
                self.act('worker_claim',env['agent_principal'],job_id='Job01',claim=claim)

    def test_audit_rejects_numerically_equal_observation_and_claim_type_mutations(self):
        env = self.prepared(); self.act('mark_dispatched',job_id='Job01')
        self.act('worker_claim',env['agent_principal'],job_id='Job01',claim=domain.claim_for(env,'AuditClaim'))
        self.receipt(env,'pickup_accept','AuditObservation')
        for value in (True,1.0):
            bad = copy.deepcopy(self.state); bad['inbox']['AuditObservation']['observation']['assignment_epoch'] = value
            with self.assertRaises(domain.DomainError): domain.audit(bad)
        for field,value in [('assignment_epoch',True),('assignment_epoch',1.0),('motion_executed',0),
                            ('hardware_executed',0),('transport_time_s',False),('transport_time_s',0.0)]:
            bad = copy.deepcopy(self.state); bad['outbox']['Job01']['claim'][field] = value
            with self.assertRaises(domain.DomainError): domain.audit(bad)


if __name__ == '__main__':
    unittest.main()
