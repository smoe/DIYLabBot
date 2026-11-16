"""Server-wide request receipts across both features of the DNA host.

CreateRun is sufficient for these coordinator cases; no extraction process,
device operation, network server or transport worker is executed.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dna_sila2_runtime import DNARuntime
from extraction_analytics_sila2_runtime import ExtractionAnalyticsRuntime, RECONCILIATION
from manual_tasks import Journal, TaskError


class DNARequestScopeTests(unittest.TestCase):
    FEATURES = ('dna', 'extraction')
    PRINCIPAL = 'account.request-scope-operator'
    WITNESS = 'SYN.RequestScope.Witness'

    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-request-scope-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.hosts = []
        self.addCleanup(self.close_hosts)
        self.serial = 0

    def close_hosts(self):
        for host in self.hosts:
            host.close()

    def start_host(self, directory):
        host = DNARuntime(directory)
        self.hosts.append(host)
        return host, {'dna': host, 'extraction': ExtractionAnalyticsRuntime(host)}

    def new_host(self):
        self.serial += 1
        host, features = self.start_host(self.directory / str(self.serial))
        # An unrelated synthetic Root makes the all-owner comparison nonempty.
        # It has no network receipt and must not enter the server request scope.
        with Journal(host.journal_path) as journal:
            journal.create(self.WITNESS, {'resources': [],
                'inventory': {}, 'bookings': {}})
            state, revision = journal.get_current(self.WITNESS)
            state['resources'] = ['fixture:request-scope-witness']
            journal.append(self.WITNESS, revision, 'fixture_resource_reserved',
                {'evidence': 'test_fixture'}, state)
            self.assertEqual(journal.owners()['fixture:request-scope-witness'], self.WITNESS)
        return host, features

    def reboot(self, host):
        directory, identity, previous_boot = host.directory, host.server_uuid, host.boot_id
        host.close()
        self.hosts.remove(host)
        restarted, features = self.start_host(directory)
        self.assertEqual(restarted.server_uuid, identity)
        self.assertNotEqual(restarted.boot_id, previous_boot)
        return restarted, features

    @staticmethod
    def create_arguments(feature, run_id, request='create-shared', family='dneasy'):
        arguments = {'request_identifier': request, 'run_identifier': run_id}
        if feature == 'extraction':
            arguments['family_identifier'] = family
        return arguments

    def create(self, features, feature, run_id, request='create-shared', family='dneasy'):
        arguments = self.create_arguments(feature, run_id, request, family)
        response = features[feature].command('CreateRun', arguments, self.PRINCIPAL)
        self.assertEqual(response['outcome'], 'completed')
        return response

    def release_unstarted_extraction(self, host, features, run_id):
        """Confirm the unchanged source fixture and cancel before any process."""
        with Journal(host.journal_path) as journal:
            state = journal.get_current(run_id, verify=True)[0]
        self.assertEqual(state['status'], 'created')
        self.assertEqual(state['process']['cursor'], 0)
        self.assertEqual(state['bookings'], {})
        definition = state['definition']
        materials, vessels = definition['initial_materials'], definition['initial_vessels']
        # These are explicitly synthetic observations of the unstarted fixture,
        # derived from its immutable declarations, not an inferred moved state.
        observations = [{'vessel_id': vessel['id'],
            'material_ids': [item['id'] for item in materials if item['vessel_id'] == vessel['id']],
            'location': copy.deepcopy(vessel['location'])} for vessel in vessels]
        document = {'format': RECONCILIATION,
            'reason': 'Explicit synthetic observation: unstarted fixture is unchanged',
            'observations': observations, 'workspace_clear': True,
            'dispositions': [{'material_id': item['id'], 'disposition': 'retained',
                'reason': 'Retain the unchanged synthetic starting material'} for item in materials]}
        for command, request, data in [
                ('CancelRun', 'release-unstarted-cancel', {'reason': document['reason']}),
                ('FinishCancel', 'release-unstarted-finish', {'observation_json': json.dumps(document)})]:
            response = features['extraction'].command(command,
                {'request_identifier': request, 'run_identifier': run_id, **data}, self.PRINCIPAL)
            self.assertEqual(response['outcome'], 'completed')
        with Journal(host.journal_path) as journal:
            after = journal.get_current(run_id, verify=True)[0]
            self.assertEqual(after['status'], 'cancelled')
            self.assertEqual(after['bookings'], {})
            self.assertEqual(after['resources'], [])
            self.assertNotIn(run_id, journal.owners().values())

    @staticmethod
    def storage_snapshot(host):
        """Keep complete event strings and every Root, not only the target."""
        with Journal(host.journal_path) as journal:
            roots = [row[0] for row in journal.connection.execute('SELECT id FROM runs ORDER BY id')]
            states = {identity: journal.get_current(identity, verify=True) for identity in roots}
            return {
                'root_count': journal.connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0],
                'roots': roots,
                'states_and_revisions': states,
                'events': journal.connection.execute(
                    'SELECT run_id, sequence, document, sha256 FROM events ORDER BY run_id, sequence').fetchall(),
                'owners': journal.owners(),
                'artifacts': journal.connection.execute(
                    'SELECT sha256, content FROM artifacts ORDER BY sha256').fetchall(),
            }

    def assert_storage_unchanged(self, host, before):
        after = self.storage_snapshot(host)
        for component in before:
            with self.subTest(persisted_component=component):
                self.assertTrue(after[component] == before[component],
                    'Request changed journal component: ' + component)

    def assert_rejected_without_events(self, host, runtime, command, arguments, principal=None):
        before = self.storage_snapshot(host)
        with self.subTest(check='conflict rejected'):
            with self.assertRaisesRegex(TaskError, r'(?i)request(?:[ _-]?identifier|[ _-]?id)'):
                runtime.command(command, arguments, principal or self.PRINCIPAL)
        # Check storage even when a buggy coordinator accepted the request.
        self.assert_storage_unchanged(host, before)

    @staticmethod
    def sessions(features):
        return {feature: copy.deepcopy(runtime._sessions) for feature, runtime in features.items()}

    def assert_exact_replay(self, host, features, feature, arguments, response):
        before = self.storage_snapshot(host)
        before_sessions = self.sessions(features)
        state = before['states_and_revisions'][arguments['run_identifier']][0]
        stored_response = state['network']['commands'][arguments['request_identifier']]['response']
        self.assertEqual(stored_response, response)
        # Argument mapping order is not part of the normalized request identity.
        reordered = dict(reversed(list(arguments.items())))
        with self.subTest(check='stored response returned'):
            self.assertEqual(features[feature].command('CreateRun', reordered, self.PRINCIPAL), stored_response)
        self.assert_storage_unchanged(host, before)
        self.assertEqual(self.sessions(features), before_sessions,
            'Reading a stored receipt adopted or replaced a server session')

    def test_create_request_cannot_create_another_dna_root(self):
        host, features = self.new_host()
        self.create(features, 'dna', 'SYN.RequestScope.DNA.Original')
        self.assert_rejected_without_events(host, features['dna'], 'CreateRun',
            self.create_arguments('dna', 'SYN.RequestScope.DNA.Other'))

    def test_create_request_cannot_create_another_extraction_root(self):
        host, features = self.new_host()
        self.create(features, 'extraction', 'SYN.RequestScope.Extraction.Original')
        self.release_unstarted_extraction(host, features, 'SYN.RequestScope.Extraction.Original')
        self.assert_rejected_without_events(host, features['extraction'], 'CreateRun',
            self.create_arguments('extraction', 'SYN.RequestScope.Extraction.Other', family='puregene'))

    def test_dna_request_cannot_create_extraction_root(self):
        host, features = self.new_host()
        self.create(features, 'dna', 'SYN.RequestScope.DNA.Original')
        self.assert_rejected_without_events(host, features['extraction'], 'CreateRun',
            self.create_arguments('extraction', 'SYN.RequestScope.Extraction.Other'))

    def test_extraction_request_cannot_create_dna_root(self):
        host, features = self.new_host()
        self.create(features, 'extraction', 'SYN.RequestScope.Extraction.Original')
        self.assert_rejected_without_events(host, features['dna'], 'CreateRun',
            self.create_arguments('dna', 'SYN.RequestScope.DNA.Other'))

    def test_other_command_cannot_reuse_request_on_another_existing_root(self):
        for source in self.FEATURES:
            for target in self.FEATURES:
                with self.subTest(source_feature=source, target_feature=target):
                    host, features = self.new_host()
                    self.create(features, source, 'SYN.RequestScope.Original')
                    if source == target == 'extraction':
                        self.release_unstarted_extraction(host, features, 'SYN.RequestScope.Original')
                    family = 'puregene' if source == target == 'extraction' else 'dneasy'
                    self.create(features, target, 'SYN.RequestScope.Target', request='create-target', family=family)
                    self.assert_rejected_without_events(host, features[target], 'CancelRun', {
                        'request_identifier': 'create-shared', 'run_identifier': 'SYN.RequestScope.Target',
                        'reason': 'A different command must not reuse another Root receipt'})

    def test_other_principal_cannot_reuse_request_on_another_root(self):
        for source in self.FEATURES:
            for target in self.FEATURES:
                with self.subTest(source_feature=source, target_feature=target):
                    host, features = self.new_host()
                    self.create(features, source, 'SYN.RequestScope.Original')
                    if source == target == 'extraction':
                        self.release_unstarted_extraction(host, features, 'SYN.RequestScope.Original')
                    family = 'puregene' if source == target == 'extraction' else 'dneasy'
                    self.assert_rejected_without_events(host, features[target], 'CreateRun',
                        self.create_arguments(target, 'SYN.RequestScope.Other', family=family),
                        principal='account.other-request-scope-operator')

    def test_exact_create_replay_keeps_all_roots_and_sessions_unchanged(self):
        host, features = self.new_host()
        responses = {}
        for feature in self.FEATURES:
            responses[feature] = self.create(features, feature,
                'SYN.RequestScope.' + feature, request='create-' + feature)
        for feature in self.FEATURES:
            self.assert_exact_replay(host, features, feature,
                self.create_arguments(feature, 'SYN.RequestScope.' + feature,
                    request='create-' + feature), responses[feature])

    def test_new_boot_rebuilds_both_feature_scopes_and_replays_without_resume(self):
        for source in self.FEATURES:
            for target in self.FEATURES:
                with self.subTest(source_feature=source, target_feature=target):
                    host, features = self.new_host()
                    responses = {}
                    for feature in self.FEATURES:
                        responses[feature] = self.create(features, feature,
                            'SYN.RequestScope.' + feature, request='create-' + feature)
                    if target == 'extraction':
                        self.release_unstarted_extraction(host, features, 'SYN.RequestScope.extraction')
                    before_reboot = self.storage_snapshot(host)
                    host, features = self.reboot(host)
                    self.assert_storage_unchanged(host, before_reboot)
                    self.assertEqual(self.sessions(features), {'dna': {}, 'extraction': {}})
                    for feature in self.FEATURES:
                        self.assert_exact_replay(host, features, feature,
                            self.create_arguments(feature, 'SYN.RequestScope.' + feature,
                                request='create-' + feature), responses[feature])
                    self.assertEqual(self.sessions(features), {'dna': {}, 'extraction': {}})
                    self.assert_rejected_without_events(host, features[target], 'CreateRun',
                        self.create_arguments(target, 'SYN.RequestScope.AfterRestart',
                            request='create-' + source, family='puregene'))

    def test_distinct_request_ids_allow_independent_creates_in_both_features(self):
        host, features = self.new_host()
        expected_roots = {self.WITNESS}
        for feature in self.FEATURES:
            run_id = 'SYN.RequestScope.' + feature
            self.create(features, feature, run_id, request='create-' + feature)
            expected_roots.add(run_id)
        snapshot = self.storage_snapshot(host)
        self.assertEqual(set(snapshot['roots']), expected_roots)
        self.assertEqual(snapshot['root_count'], len(expected_roots))
        self.assertEqual(snapshot['owners']['fixture:request-scope-witness'], self.WITNESS)


if __name__ == '__main__':
    unittest.main()
