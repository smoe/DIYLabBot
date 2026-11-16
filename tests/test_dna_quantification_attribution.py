"""Root completion retains the evidence that first confirmed return or disposal."""
import unittest

import test_dna_quantification_control as control_fixtures


class DnaConfirmationAttributionTests(unittest.TestCase):
    setUp = control_fixtures.DNAControlTests.setUp
    tearDown = control_fixtures.DNAControlTests.tearDown
    command = control_fixtures.DNAControlTests.command
    state = control_fixtures.DNAControlTests.state
    history = control_fixtures.DNAControlTests.history
    create = control_fixtures.DNAControlTests.create
    run_pair = control_fixtures.DNAControlTests.run_pair

    def standard_network_run(self):
        self.create()
        self.run_pair()
        report = self.runtime.report(self.run_id)
        self.assertTrue(report['passed'])
        self.assertEqual(report['inventory']['vessels']['SYN.DNA.Tube01']['remaining_volume_ul'], 36.5)
        return report, self.history()

    def test_return_confirmation_names_observed_goal_and_agent_and_survives_completion(self):
        report, history = self.standard_network_run()
        returns = []
        for event in history:
            if event['kind'] != 'task.observed':
                continue
            goal_id = event['payload']['goal_id']
            record = event['state']['task_port']['goals'][goal_id]
            if record['goal']['target_kind'] == 'rack':
                returns.append(event)
        self.assertEqual(len(returns), 2)
        for event in returns:
            with self.subTest(sequence=event['sequence']):
                goal_id = event['payload']['goal_id']
                record = event['state']['task_port']['goals'][goal_id]
                goal = record['goal']
                vessel = event['state']['inventory']['vessels']['SYN.DNA.Tube01']
                confirmation = vessel['return_confirmation']
                self.assertEqual(vessel['location'], vessel['home'])
                self.assertEqual(confirmation.get('goal_id'), goal_id)
                self.assertEqual(confirmation.get('executing_agent_id'), goal['executing_agent_id'])
                self.assertNotEqual(goal['executing_agent_id'], event['state']['responsible_person_id'])
                self.assertEqual(confirmation['evidence'], 'synthetic_backend')
                self.assertEqual(confirmation['evidence'], record['observation_evidence'])
                self.assertEqual(confirmation['rack_id'], goal['target_rack_id'])
                self.assertEqual(confirmation['place_id'], goal['target_place_id'])
        last_return = returns[-1]['state']['inventory']['vessels']['SYN.DNA.Tube01']
        final = report['inventory']['vessels']['SYN.DNA.Tube01']
        self.assertEqual(final['location'], final['home'])
        self.assertEqual(final['return_confirmation'], last_return['return_confirmation'])

    def test_disposed_sample_and_standard_confirmations_survive_completion_unchanged(self):
        report, history = self.standard_network_run()
        disposals = {event['payload']['vessel_id']: event for event in history
                     if event['kind'] == 'device.dispose_vessel'}
        disposed = {identity: vessel for identity, vessel in report['inventory']['vessels'].items()
                    if vessel['location']['kind'] == 'discarded'}
        self.assertEqual(set(disposals), set(disposed))
        self.assertEqual(len(disposed), 3)
        self.assertEqual({vessel['kind'] for vessel in disposed.values()}, {'sample', 'standard'})
        for identity, final in disposed.items():
            with self.subTest(vessel=identity):
                event = disposals[identity]
                original = event['state']['inventory']['vessels'][identity]
                self.assertEqual(original['location'], {'kind': 'discarded'})
                self.assertEqual(original['disposition_confirmation']['actor_id'], self.runtime.actor_id)
                self.assertEqual(original['disposition_confirmation']['reason'],
                                 'Explicit synthetic DNA assay/standard tube disposal')
                self.assertEqual(final['disposition_confirmation'], original['disposition_confirmation'])


if __name__ == '__main__':
    unittest.main()
