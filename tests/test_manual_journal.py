"""Verified current-state caching, full audits and atomic journal writes."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError, digest, encoded

RUN = 'SYN.Journal'


class ManualJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='manual-journal-')
        self.path = Path(self.temp.name) / 'tasks.sqlite3'
        self.journal = Journal(self.path)
        self.initial = {'resources': [], 'counter': 0,
                        'inventory': {'Tube01': {'remaining_ul': 40}}}
        self.journal.create(RUN, self.initial)

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def advance(self, journal=None):
        journal = journal or self.journal
        state, revision = journal.get_current(RUN)
        state['counter'] += 1
        journal.append(RUN, revision, 'advanced', {'synthetic': True}, state)
        return state, revision + 1

    def corrupt(self, connection, sequence=1, document='not JSON'):
        connection.execute('UPDATE events SET document=? WHERE run_id=? AND sequence=?',
                           (document, RUN, sequence))
        connection.commit()

    def test_fast_reads_and_appends_reuse_verified_prefix(self):
        with patch.object(self.journal, 'history', wraps=self.journal.history) as history:
            for _ in range(25):
                self.advance()
            state, revision = self.journal.get_current(RUN)
            self.assertEqual((state['counter'], revision), (25, 26))
            self.assertEqual(history.call_count, 0)
        self.assertEqual(len(self.journal.history(RUN)), 26)

    def test_new_connection_verifies_before_fast_reads(self):
        self.advance()
        with Journal(self.path) as other:
            with patch.object(other, 'history', wraps=other.history) as history:
                for _ in range(3):
                    self.assertEqual(other.get_current(RUN)[1], 2)
                self.assertEqual(history.call_count, 1)

    def test_state_history_and_forced_current_reads_always_audit(self):
        with patch.object(self.journal, 'history', wraps=self.journal.history) as history:
            self.journal.state(RUN)
            self.journal.get_current(RUN, verify=True)
            self.journal.get_current(RUN, verify=True)
            self.assertEqual(history.call_count, 3)

    def test_reads_and_history_do_not_expose_mutable_cache_aliases(self):
        self.initial['inventory']['Tube01']['remaining_ul'] = 999
        current, _ = self.journal.get_current(RUN)
        current['inventory']['Tube01']['remaining_ul'] = 888
        events = self.journal.history(RUN)
        events[-1]['state']['inventory']['Tube01']['remaining_ul'] = 777
        legacy, _ = self.journal.state(RUN)
        legacy['inventory']['Tube01']['remaining_ul'] = 666
        self.assertEqual(self.journal.get_current(RUN)[0]['inventory']['Tube01']['remaining_ul'], 40)

    def test_append_input_is_detached_and_uses_persisted_json_types(self):
        state, revision = self.journal.get_current(RUN)
        state['tuple_input'] = (1, 2)
        self.journal.append(RUN, revision, 'tuple', {}, state)
        state['inventory']['Tube01']['remaining_ul'] = 0
        current, _ = self.journal.get_current(RUN)
        self.assertEqual(current['tuple_input'], [1, 2])
        self.assertEqual(current['inventory']['Tube01']['remaining_ul'], 40)

    def test_foreign_append_invalidates_prefix_and_stale_cas_rolls_back(self):
        stale, revision = self.journal.get_current(RUN)
        with Journal(self.path) as other:
            self.advance(other)
        stale['resources'] = ['rack:STALE']
        with self.assertRaisesRegex(TaskError, 'changed'):
            self.journal.append(RUN, revision, 'stale', {}, stale)
        self.assertEqual(self.journal.owners(), {})
        self.assertEqual(self.journal.get_current(RUN)[0]['counter'], 1)
        self.assertEqual(self.journal.get_current(RUN)[1], 2)

    def test_foreign_old_event_corruption_is_detected_even_with_unchanged_tail(self):
        self.advance()
        with closing(sqlite3.connect(self.path)) as other:
            self.corrupt(other)
        with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
            self.journal.get_current(RUN)
        with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
            self.journal.append(RUN, 2, 'must_not_append', {}, copy.deepcopy(self.initial))

    def test_direct_same_connection_corruption_invalidates_prefix(self):
        self.advance()
        self.corrupt(self.journal.connection)
        with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
            self.journal.get_current(RUN)
        with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
            self.journal.history(RUN)

    def test_warm_cache_does_not_hide_corrupt_tail(self):
        self.advance()
        self.corrupt(self.journal.connection, sequence=2)
        with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
            self.journal.get_current(RUN)

    def test_changed_stamp_during_tail_read_forces_a_full_audit(self):
        self.advance()
        old_stamp = self.journal._stamp()
        self.corrupt(self.journal.connection)
        actual_stamp = self.journal._stamp
        first = [True]
        def changing_stamp():
            if first[0]:
                first[0] = False
                return old_stamp
            return actual_stamp()
        with patch.object(self.journal, '_stamp', side_effect=changing_stamp):
            with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
                self.journal.get_current(RUN)

    def test_rehashed_event_missing_state_is_still_corrupt(self):
        event = self.journal.history(RUN)[-1]
        event.pop('sha256')
        event.pop('state')
        document = encoded(event)
        self.journal.connection.execute(
            'UPDATE events SET document=?, sha256=? WHERE run_id=?',
            (document, digest(document.encode()), RUN))
        self.journal.connection.commit()
        with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
            self.journal.get_current(RUN)

    def test_valid_checksum_does_not_hide_broken_predecessor(self):
        self.advance()
        document = self.journal.connection.execute(
            'SELECT document FROM events WHERE run_id=? AND sequence=2', (RUN,)).fetchone()[0]
        event = json.loads(document)
        event['previous_sha256'] = '0' * 64
        document = encoded(event)
        self.journal.connection.execute(
            'UPDATE events SET document=?, sha256=? WHERE run_id=? AND sequence=2',
            (document, digest(document.encode()), RUN))
        self.journal.connection.commit()
        with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
            self.journal.get_current(RUN)

    def test_sequence_gap_cannot_be_treated_as_a_valid_new_tail(self):
        tail = self.journal.history(RUN)[-1]
        event = {**tail, 'sequence': 3, 'previous_sha256': tail['sha256']}
        event.pop('sha256')
        document = encoded(event)
        with closing(sqlite3.connect(self.path)) as other:
            other.execute('INSERT INTO events VALUES (?, ?, ?, ?)',
                          (RUN, 3, document, digest(document.encode())))
            other.commit()
        with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
            self.journal.get_current(RUN)

    def test_rollback_of_a_direct_uncommitted_tail_invalidates_its_cached_state(self):
        tail = self.journal.history(RUN)[-1]
        self.journal.connection.execute('BEGIN IMMEDIATE')
        changed = copy.deepcopy(self.initial)
        changed['counter'] = 12
        self.journal._event(RUN, 2, tail['sha256'], 'uncommitted', {}, changed)
        self.assertEqual(self.journal.get_current(RUN)[0]['counter'], 12)
        self.journal.connection.rollback()
        self.assertEqual(self.journal.get_current(RUN)[0]['counter'], 0)
        self.assertEqual(self.journal.get_current(RUN)[1], 1)

    def test_resource_conflict_rolls_back_earlier_reservations(self):
        other_state = {'resources': ['rack:ZHeld']}
        self.journal.create('Other', {'resources': []})
        self.journal.append('Other', 1, 'reserve', {}, other_state)
        state, revision = self.journal.get_current(RUN)
        state['resources'] = ['rack:ANew', 'rack:ZHeld']
        with self.assertRaisesRegex(TaskError, 'Resource reserved'):
            self.journal.append(RUN, revision, 'conflict', {}, state)
        self.assertEqual(self.journal.owners(), {'rack:ZHeld': 'Other'})
        self.assertEqual(self.journal.get_current(RUN)[1], 1)

    def test_failed_append_rolls_back_event_artifact_resources_and_cache(self):
        state, revision = self.journal.get_current(RUN)
        state['resources'] = ['vessel:Tube01']
        artifact = b'SYNTHETIC ORIGINAL REPORT'
        with patch.object(self.journal, '_event', side_effect=RuntimeError('Synthetic disk error')):
            with self.assertRaisesRegex(RuntimeError, 'Synthetic disk error'):
                self.journal.append(RUN, revision, 'failure', {}, state, artifact=artifact)
        with patch.object(self.journal, 'history', wraps=self.journal.history) as history:
            self.assertEqual(self.journal.get_current(RUN)[1], 1)
            self.assertEqual(history.call_count, 1)
        self.assertEqual(self.journal.owners(), {})
        with self.assertRaisesRegex(TaskError, 'Missing or corrupt artifact'):
            self.journal.artifact(digest(artifact))

    def test_serialization_failure_does_not_leave_partial_writes(self):
        state, revision = self.journal.get_current(RUN)
        state.update(resources=['vessel:Tube01'], invalid=float('nan'))
        with self.assertRaises(ValueError):
            self.journal.append(RUN, revision, 'invalid', {}, state, artifact=b'SYN')
        self.assertEqual(self.journal.owners(), {})
        self.assertEqual(self.journal.get_current(RUN)[1], 1)

    def test_successful_append_keeps_resource_release_and_original_artifact_atomic(self):
        state, revision = self.journal.get_current(RUN)
        state['resources'] = ['vessel:Tube01']
        content = b'SYNTHETIC REPORT'
        self.journal.append(RUN, revision, 'reserved', {}, state, artifact=content)
        state, revision = self.journal.get_current(RUN)
        state['resources'] = []
        self.journal.append(RUN, revision, 'released', {}, state)
        self.assertEqual(self.journal.owners(), {})
        self.assertEqual(self.journal.artifact(digest(content)), content)
        self.assertEqual(len(self.journal.history(RUN)), 3)

    def test_duplicate_create_and_unknown_run_do_not_poison_reads(self):
        with self.assertRaisesRegex(TaskError, 'Run already exists'):
            self.journal.create(RUN, self.initial)
        with self.assertRaisesRegex(TaskError, 'Unknown run'):
            self.journal.get_current('Unknown')
        self.assertEqual(self.journal.get_current(RUN)[1], 1)
        self.assertFalse(self.journal.connection.in_transaction)


class ImmutableDefinitionTests(unittest.TestCase):
    """The opt-in storage format must preserve the shared journal guarantees."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='compact-journal-')
        self.path = Path(self.temp.name) / 'tasks.sqlite3'
        self.journal = Journal(self.path)
        self.initial = {'resources': [], 'counter': 0}
        self.journal.create(RUN, self.initial)
        self.definition = {'synthetic': True, 'source': 'SYNTHETIC-' * 6000,
                           'nested': {'samples': ['Sample01', 'Sample02']}}
        self.initial['definition'] = copy.deepcopy(self.definition)
        self.journal.create('SYN.Compact', self.initial, immutable_definition=True)

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def compact_advance(self):
        state, revision = self.journal.get_current('SYN.Compact')
        state['counter'] += 1
        self.journal.append('SYN.Compact', revision, 'advanced', {}, state)

    def test_definition_is_stored_once_and_history_rehydrates_detached_states(self):
        for _ in range(20):
            self.compact_advance()
        rows = self.journal.connection.execute(
            'SELECT document FROM events WHERE run_id=? ORDER BY sequence', ('SYN.Compact',)).fetchall()
        self.assertLess(sum(len(row[0]) for row in rows), len(encoded(self.definition)))
        references = {json.loads(row[0])['definition_sha256'] for row in rows}
        self.assertEqual(len(references), 1)
        self.assertTrue(all('definition' not in json.loads(row[0])['state'] for row in rows))
        self.assertEqual(json.loads(self.journal.artifact(references.pop())), self.definition)
        history = self.journal.history('SYN.Compact')
        self.assertTrue(all(event['state']['definition'] == self.definition for event in history))
        history[0]['state']['definition']['nested']['samples'].clear()
        self.assertEqual(history[-1]['state']['definition'], self.definition)
        self.assertEqual(self.journal.get_current('SYN.Compact')[0]['definition'], self.definition)
        with Journal(self.path) as reopened:
            self.assertEqual(reopened.get_current('SYN.Compact')[0]['definition'], self.definition)

    def test_definition_change_rolls_back_resources_artifacts_and_event(self):
        state, revision = self.journal.get_current('SYN.Compact')
        state['definition']['nested']['samples'].append('Foreign')
        state['resources'] = ['vessel:NEW']
        with self.assertRaisesRegex(TaskError, 'Immutable definition'):
            self.journal.append('SYN.Compact', revision, 'invalid', {}, state, artifact=b'SYN.INVALID')
        self.assertEqual(self.journal.get_current('SYN.Compact')[1], revision)
        self.assertEqual(self.journal.owners(), {})
        with self.assertRaises(TaskError):
            self.journal.artifact(digest(b'SYN.INVALID'))

    def test_definition_blob_corruption_invalidates_a_warm_prefix(self):
        self.compact_advance()
        checksum = digest(encoded(self.definition).encode())
        with sqlite3.connect(self.path) as writer:
            writer.execute('UPDATE artifacts SET content=? WHERE sha256=?', (b'SYN.CORRUPTED', checksum))
        with self.assertRaisesRegex(TaskError, 'corrupt|Corrupt'):
            self.journal.get_current('SYN.Compact')

    def test_rehashed_reference_change_and_unknown_storage_version_are_rejected(self):
        self.compact_advance()
        original, checksum = self.journal.connection.execute(
            'SELECT document, sha256 FROM events WHERE run_id=? AND sequence=2', ('SYN.Compact',)).fetchone()
        foreign = encoded({'synthetic': 'foreign definition'}).encode()
        foreign_checksum = digest(foreign)
        self.journal.connection.execute('INSERT INTO artifacts VALUES (?, ?)', (foreign_checksum, foreign))
        self.journal.connection.commit()
        for change in [{'definition_sha256': foreign_checksum}, {'storage_format': 'unknown/99'}]:
            with self.subTest(change=change):
                event = {**json.loads(original), **change}
                document = encoded(event)
                self.journal.connection.execute('UPDATE events SET document=?, sha256=? WHERE run_id=? AND sequence=2',
                                                (document, digest(document.encode()), 'SYN.Compact'))
                self.journal.connection.commit()
                with self.assertRaisesRegex(TaskError, 'Corrupt task journal'):
                    self.journal.history('SYN.Compact')
                self.journal.connection.execute('UPDATE events SET document=?, sha256=? WHERE run_id=? AND sequence=2',
                                                (original, checksum, 'SYN.Compact'))
                self.journal.connection.commit()

    def test_failed_compact_create_does_not_leave_a_definition_or_run(self):
        definition = {'synthetic': 'unique failed definition'}
        state = {'resources': [], 'definition': definition}
        with patch.object(self.journal, '_event', side_effect=OSError('Synthetic disk error')):
            with self.assertRaises(OSError):
                self.journal.create('SYN.Failed', state, immutable_definition=True)
        self.assertIsNone(self.journal.connection.execute('SELECT id FROM runs WHERE id=?', ('SYN.Failed',)).fetchone())
        with self.assertRaises(TaskError):
            self.journal.artifact(digest(encoded(definition).encode()))

    def test_legacy_rows_are_never_rewritten_and_keep_their_storage_format(self):
        before = self.journal.connection.execute('SELECT * FROM events WHERE run_id=?', (RUN,)).fetchall()
        self.compact_advance()
        self.assertEqual(self.journal.connection.execute('SELECT * FROM events WHERE run_id=?', (RUN,)).fetchall(), before)
        state, revision = self.journal.get_current(RUN)
        state['counter'] += 1
        self.journal.append(RUN, revision, 'advanced', {}, state)
        legacy = json.loads(self.journal.connection.execute(
            'SELECT document FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1', (RUN,)).fetchone()[0])
        self.assertNotIn('storage_format', legacy)


if __name__ == '__main__':
    unittest.main()
