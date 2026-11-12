"""Permanent material identity claims share the journal's atomic transaction."""
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError, digest, encoded


def declaration(material='SYN.Aliquot01', vessel='SYN.ReagentTube01', initial=40):
    return {'material_id': material, 'vessel_id': vessel,
            'declaration_sha256': digest(encoded({'material_id': material, 'vessel_id': vessel,
                                                  'initial_ul': initial, 'synthetic': True}).encode())}


def material_state(records=None, resources=None):
    records = [declaration()] if records is None else copy.deepcopy(records)
    return {'format': 'solidcraftbot.material-workflow-state/1',
            'definition': {'format': 'solidcraftbot.material-workflow-definition/1',
                           'material_allocations': records},
            'resources': ['vessel:' + item['vessel_id'] for item in records] if resources is None else resources,
            'counter': 0}


class MaterialAllocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='material-allocation-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tasks.sqlite3'
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.journal.create('SYN.Legacy', {'resources': [], 'counter': 0})
        self.legacy_rows = self.journal.connection.execute(
            'SELECT * FROM events WHERE run_id=?', ('SYN.Legacy',)).fetchall()

    def create(self, run='SYN.Material', state=None, journal=None, **options):
        state = material_state() if state is None else state
        (journal or self.journal).create(run, state, immutable_definition=True,
            material_allocations=state['definition']['material_allocations'], **options)
        return state

    def release(self, run='SYN.Material'):
        state, revision = self.journal.get_current(run)
        state['resources'] = []
        self.journal.append(run, revision, 'completed', {}, state)

    def assert_missing_run(self, run):
        self.assertIsNone(self.journal.connection.execute('SELECT id FROM runs WHERE id=?', (run,)).fetchone())
        self.assertEqual(self.journal.connection.execute(
            'SELECT COUNT(*) FROM events WHERE run_id=?', (run,)).fetchone()[0], 0)

    def test_opt_in_create_claims_aliases_and_initial_holds_with_event_reference(self):
        self.create()
        claims = self.journal.audit_material_allocations()
        self.assertEqual(set(claims), {'material:SYN.Aliquot01', 'vessel:SYN.ReagentTube01'})
        introduction = self.journal.history('SYN.Material')[0]
        for value in claims.values():
            self.assertEqual(value, {'run_id': 'SYN.Material', **declaration(),
                                     'introduction_sha256': introduction['sha256']})
        self.assertEqual(self.journal.owners(), {'vessel:SYN.ReagentTube01': 'SYN.Material'})
        claims['material:SYN.Aliquot01']['run_id'] = 'mutated'
        self.assertEqual(self.journal.audit_material_allocations()['material:SYN.Aliquot01']['run_id'], 'SYN.Material')
        self.assertEqual(self.journal.connection.execute(
            'SELECT * FROM events WHERE run_id=?', ('SYN.Legacy',)).fetchall(), self.legacy_rows)

    def test_empty_explicit_list_enables_component_without_allocating_material(self):
        self.create(state=material_state([], resources=['rack:SYN.NewRack']))
        self.assertEqual(self.journal.audit_material_allocations(), {})
        self.assertEqual(self.journal.connection.execute('SELECT name, format FROM journal_components').fetchall(),
                         [('material_allocations', 'solidcraftbot.material-allocations/1')])
        self.assertEqual(self.journal.owners(), {'rack:SYN.NewRack': 'SYN.Material'})

    def test_legacy_default_create_keeps_original_resource_behavior_and_event_bytes(self):
        self.journal.create('SYN.Legacy2', {'resources': ['rack:SYN.Unreserved']})
        self.assertEqual(self.journal.owners(), {})
        self.assertEqual(self.journal.audit_material_allocations(), {})
        self.assertFalse(self.journal.connection.execute(
            "SELECT name FROM sqlite_master WHERE name='journal_components'").fetchall())
        event = self.journal.history('SYN.Legacy2')[0]
        self.assertNotIn('storage_format', event)
        self.assertEqual(self.journal.connection.execute(
            'SELECT * FROM events WHERE run_id=?', ('SYN.Legacy',)).fetchall(), self.legacy_rows)

    def test_formats_explicit_opt_in_and_exact_definition_match_are_required(self):
        cases = []
        state = material_state();state['format'] = 'unknown/99';cases.append((state, [declaration()]))
        state = material_state();state['definition']['format'] = 'unknown/99';cases.append((state, [declaration()]))
        state = material_state();cases.append((state, []))
        state = material_state();cases.append((state, None))
        state = material_state();state['definition']['material_allocations'].append(declaration());cases.append((state, state['definition']['material_allocations']))
        state = material_state();state['definition']['material_allocations'][0]['declaration_sha256'] = 'bad';cases.append((state, state['definition']['material_allocations']))
        for index, (state, supplied) in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(TaskError):
                self.journal.create('SYN.Invalid', state, material_allocations=supplied)
            self.assert_missing_run('SYN.Invalid')
            self.assertEqual(self.journal.audit_material_allocations(), {})

    def test_material_and_vessel_aliases_cannot_be_swapped_or_reintroduced_after_release(self):
        self.create();self.release()
        self.assertEqual(self.journal.owners(), {})
        with Journal(self.path) as reopened:
            self.assertEqual(len(reopened.audit_material_allocations()), 2)
            for index, record in enumerate((declaration(initial=999),
                    declaration(vessel='SYN.OtherTube'), declaration(material='SYN.OtherAliquot'))):
                run = 'SYN.Reset' + str(index)
                state = material_state([record], resources=[])
                with self.subTest(index=index), self.assertRaisesRegex(TaskError, 'permanently allocated'):
                    self.create(run, state, reopened)
                self.assert_missing_run(run)
                with self.assertRaisesRegex(TaskError, 'Missing or corrupt artifact'):
                    reopened.artifact(digest(encoded(state['definition']).encode()))
            self.assertEqual(len(reopened.audit_material_allocations()), 2)

    def test_claim_cannot_take_a_vessel_already_held_by_an_existing_legacy_run(self):
        state, revision = self.journal.get_current('SYN.Legacy')
        state['resources'] = ['vessel:SYN.ReagentTube01']
        self.journal.append('SYN.Legacy', revision, 'reserved', {}, state)
        with self.assertRaisesRegex(TaskError, 'Resource reserved'):
            self.create(state=material_state(resources=[]))
        self.assert_missing_run('SYN.Material')
        self.assertEqual(self.journal.audit_material_allocations(), {})
        self.assertEqual(self.journal.owners(), {'vessel:SYN.ReagentTube01': 'SYN.Legacy'})

    def test_legacy_append_cannot_bypass_a_released_permanent_vessel_claim(self):
        self.create();self.release()
        state, revision = self.journal.get_current('SYN.Legacy')
        state['resources'] = ['rack:SYN.EarlierWrite', 'vessel:SYN.ReagentTube01']
        with self.assertRaisesRegex(TaskError, 'permanently allocated'):
            self.journal.append('SYN.Legacy', revision, 'reserve_foreign', {}, state, artifact=b'SYN.Failed')
        self.assertEqual(self.journal.get_current('SYN.Legacy')[1], revision)
        self.assertEqual(self.journal.owners(), {})
        with self.assertRaises(TaskError):self.journal.artifact(digest(b'SYN.Failed'))

    def test_material_definition_and_allocation_declaration_cannot_change_on_append(self):
        self.create()
        before = self.journal.audit_material_allocations()
        for field in ('declaration', 'definition', 'format'):
            state, revision = self.journal.get_current('SYN.Material')
            if field == 'declaration':state['definition']['material_allocations'][0] = declaration(initial=999)
            elif field == 'definition':state['definition']['new_initial_quantity'] = 999
            else:state['format'] = 'legacy/1'
            state['resources'] = ['rack:SYN.Invalid']
            with self.subTest(field=field), self.assertRaises(TaskError):
                self.journal.append('SYN.Material', revision, 'reset', {}, state)
            self.assertEqual(self.journal.get_current('SYN.Material')[1], 1)
            self.assertEqual(self.journal.audit_material_allocations(), before)

    def test_allocation_definition_is_immutable_even_without_compact_event_storage(self):
        state = material_state()
        self.journal.create('SYN.Material', state,
                            material_allocations=state['definition']['material_allocations'])
        self.assertNotIn('storage_format', self.journal.history('SYN.Material')[0])
        state, revision = self.journal.get_current('SYN.Material');state['counter'] = 1
        self.journal.append('SYN.Material', revision, 'advance', {}, state)
        state, revision = self.journal.get_current('SYN.Material')
        state['definition']['material_allocations'][0] = declaration(initial=999)
        with self.assertRaisesRegex(TaskError, 'immutable'):
            self.journal.append('SYN.Material', revision, 'reset', {}, state)
        self.assertEqual(self.journal.get_current('SYN.Material')[1], 2)
        self.assertEqual(len(self.journal.audit_material_allocations()), 2)

    def test_initial_resource_conflict_rolls_back_new_holds_component_run_and_definition(self):
        state, revision = self.journal.get_current('SYN.Legacy')
        state['resources'] = ['rack:SYN.ZHeld']
        self.journal.append('SYN.Legacy', revision, 'reserve', {}, state)
        initial = material_state(resources=['rack:SYN.ANew', 'rack:SYN.ZHeld'])
        with self.assertRaisesRegex(TaskError, 'Resource reserved'):
            self.create(state=initial)
        self.assert_missing_run('SYN.Material')
        self.assertEqual(self.journal.owners(), {'rack:SYN.ZHeld': 'SYN.Legacy'})
        self.assertEqual(self.journal.audit_material_allocations(), {})
        with self.assertRaises(TaskError):self.journal.artifact(digest(encoded(initial['definition']).encode()))

    def test_legacy_run_cannot_acquire_material_format_without_an_introduction(self):
        state = material_state(resources=[])
        with self.assertRaisesRegex(TaskError, 'opted-in introduction'):
            self.journal.append('SYN.Legacy', 1, 'change_format', {}, state)
        self.assertEqual(self.journal.get_current('SYN.Legacy')[1], 1)

    def test_stale_material_append_rolls_back_with_two_connections(self):
        self.create()
        stale, revision = self.journal.get_current('SYN.Material')
        with Journal(self.path) as other:
            state, current = other.get_current('SYN.Material');state['counter'] = 1
            other.append('SYN.Material', current, 'advance', {}, state)
        stale.update(counter=999, resources=['rack:SYN.Stale'])
        with self.assertRaisesRegex(TaskError, 'changed'):
            self.journal.append('SYN.Material', revision, 'stale', {}, stale, artifact=b'SYN.Stale')
        self.assertEqual(self.journal.get_current('SYN.Material')[0]['counter'], 1)
        self.assertEqual(self.journal.owners(), {'vessel:SYN.ReagentTube01': 'SYN.Material'})
        self.assertEqual(len(self.journal.audit_material_allocations()), 2)
        with self.assertRaises(TaskError):self.journal.artifact(digest(b'SYN.Stale'))

    def test_two_concurrent_connections_cannot_allocate_the_same_aliquot(self):
        barrier = Barrier(2)
        def allocate(run):
            with Journal(self.path) as journal:
                barrier.wait(timeout=10)
                try:
                    self.create(run, journal=journal)
                    return run, True
                except TaskError:
                    return run, False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(allocate, ['SYN.Concurrent1', 'SYN.Concurrent2']))
        winners = [run for run, success in results if success]
        losers = [run for run, success in results if not success]
        self.assertEqual((len(winners), len(losers)), (1, 1))
        self.assert_missing_run(losers[0])
        claims = self.journal.audit_material_allocations()
        self.assertEqual({value['run_id'] for value in claims.values()}, set(winners))
        self.assertEqual(self.journal.owners(), {'vessel:SYN.ReagentTube01': winners[0]})

    def test_failure_after_event_and_partial_aliases_rolls_back_component_and_every_write(self):
        state = material_state()
        original = self.journal._claim_material_alias
        def claim_then_fail(alias, value):
            original(alias, value)
            raise OSError('Synthetic failure after first alias and event')
        with patch.object(self.journal, '_claim_material_alias', side_effect=claim_then_fail):
            with self.assertRaisesRegex(OSError, 'first alias'):
                self.create(state=state)
        self.assert_missing_run('SYN.Material')
        self.assertEqual(self.journal.owners(), {})
        self.assertEqual(self.journal.audit_material_allocations(), {})
        with self.assertRaises(TaskError):self.journal.artifact(digest(encoded(state['definition']).encode()))
        self.assertFalse(self.journal.connection.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('journal_components','material_allocations')").fetchall())
        self.create(state=state)
        self.assertEqual(len(self.journal.audit_material_allocations()), 2)

    def test_failure_after_actual_event_insert_also_rolls_back_introduction(self):
        original = self.journal._event
        def event_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('Synthetic failure after event insert')
        with patch.object(self.journal, '_event', side_effect=event_then_fail):
            with self.assertRaisesRegex(OSError, 'event insert'):self.create()
        self.assert_missing_run('SYN.Material')
        self.assertEqual(self.journal.owners(), {})
        self.assertEqual(self.journal.audit_material_allocations(), {})

    def test_append_failure_preserves_existing_claims_and_rolls_back_new_effects(self):
        self.create();claims = self.journal.audit_material_allocations()
        state, revision = self.journal.get_current('SYN.Material')
        state.update(counter=1, resources=['rack:SYN.New'])
        with patch.object(self.journal, '_event', side_effect=OSError('Synthetic append failure')):
            with self.assertRaises(OSError):
                self.journal.append('SYN.Material', revision, 'failure', {}, state, artifact=b'SYN.Append')
        self.assertEqual(self.journal.get_current('SYN.Material')[1], revision)
        self.assertEqual(self.journal.audit_material_allocations(), claims)
        self.assertEqual(self.journal.owners(), {'vessel:SYN.ReagentTube01': 'SYN.Material'})
        with self.assertRaises(TaskError):self.journal.artifact(digest(b'SYN.Append'))

    def test_missing_changed_and_fake_index_rows_fail_audit_and_block_new_create(self):
        self.create();self.release()
        original = self.journal.connection.execute('SELECT * FROM material_allocations').fetchall()
        changes = [
            "DELETE FROM material_allocations WHERE alias LIKE 'material:%'",
            "UPDATE material_allocations SET declaration_sha256='" + '0' * 64 + "'",
            "UPDATE material_allocations SET introduction_sha256='" + '0' * 64 + "'",
            "INSERT INTO material_allocations SELECT 'material:SYN.Fake', run_id, 'SYN.Fake', vessel_id, declaration_sha256, introduction_sha256 FROM material_allocations LIMIT 1"]
        for command in changes:
            with self.subTest(command=command):
                self.journal.connection.execute(command);self.journal.connection.commit()
                with self.assertRaisesRegex(TaskError, 'index does not match'):
                    self.journal.audit_material_allocations()
                with self.assertRaises(TaskError):self.create('SYN.Reset', material_state(resources=[]))
                self.assert_missing_run('SYN.Reset')
                self.journal.connection.execute('DELETE FROM material_allocations')
                self.journal.connection.executemany('INSERT INTO material_allocations VALUES (?, ?, ?, ?, ?, ?)', original)
                self.journal.connection.commit()
                self.assertEqual(len(self.journal.audit_material_allocations()), 2)

    def test_deleting_the_entire_extension_cannot_reintroduce_a_material_as_fresh(self):
        self.create();self.release()
        self.journal.connection.execute('DROP TABLE material_allocations')
        self.journal.connection.execute('DROP TABLE journal_components');self.journal.connection.commit()
        with self.assertRaisesRegex(TaskError, 'Missing material allocation store extension'):
            self.create('SYN.Reset', material_state(resources=[]))
        self.assert_missing_run('SYN.Reset')
        self.assertEqual(self.journal.history('SYN.Material')[0]['state']['format'],
                         'solidcraftbot.material-workflow-state/1')

    def test_unknown_component_versions_block_writes_but_keep_historical_reads(self):
        self.create()
        self.journal.connection.execute('UPDATE journal_components SET format=?',
                                        ('solidcraftbot.material-allocations/99',));self.journal.connection.commit()
        self.assertEqual(len(self.journal.history('SYN.Material')), 1)
        self.assertEqual(self.journal.get_current('SYN.Legacy')[1], 1)
        with self.assertRaisesRegex(TaskError, 'Unsupported journal component version'):
            self.journal.create('SYN.Unknown', {'resources': []})
        state, revision = self.journal.get_current('SYN.Legacy');state['counter'] += 1
        with self.assertRaisesRegex(TaskError, 'Unsupported journal component version'):
            self.journal.append('SYN.Legacy', revision, 'advance', {}, state)
        self.assert_missing_run('SYN.Unknown')
        self.assertEqual(self.journal.get_current('SYN.Legacy')[1], 1)


if __name__ == '__main__':
    unittest.main()
