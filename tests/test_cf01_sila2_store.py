"""A durable pending intent blocks replay, including after process restart."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cf01_sila2_store import ProcessStore, StoreError, DuplicateIntent


class StoreTests(unittest.TestCase):
    def test_pending_survives_restart_and_duplicate_never_reexecutes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'station.sqlite3'
            request = str(uuid.uuid4())
            with ProcessStore(path, 'source-a') as store:
                identity = store.server_uuid
                store.begin(request, 'boot-a', 'RunCentrifuge', {'rcf_x_g': 100., 'duration_s': 30.}, 'operator')
            with ProcessStore(path, 'source-a') as store:
                self.assertEqual(store.server_uuid, identity)
                self.assertEqual(store.pending()[0]['request_id'], request)
                self.assertEqual(store.pending()[0]['arguments'], {'rcf_x_g': 100., 'duration_s': 30.})
                with self.assertRaises(DuplicateIntent):
                    store.begin(request, 'boot-b', 'OpenLid', {}, 'operator')
                store.reconcile('person', {'acknowledged_uncertain_request_ids': [request]}, {'observed': True})
                self.assertEqual(store.pending(), [])
                self.assertEqual(store.read_snapshot(), {'observed': True})
                with self.assertRaises(DuplicateIntent):
                    store.begin(request, 'boot-c', 'OpenLid', {}, 'operator')

    def test_terminal_result_and_checkpoint_commit_atomically(self):
        with tempfile.TemporaryDirectory() as directory, ProcessStore(Path(directory) / 'station.sqlite3', 'source') as store:
            request = str(uuid.uuid4())
            store.begin(request, 'boot', 'OpenLid', {}, 'operator')
            with self.assertRaises(ValueError):
                store.finish(request, 'succeeded', {}, {'invalid': float('nan')})
            self.assertEqual(len(store.pending()), 1)
            self.assertIsNone(store.read_snapshot())
            store.finish(request, 'succeeded', {'accepted': True}, {'confirmed': True})
            self.assertEqual(store.pending(), [])
            self.assertEqual(store.read_snapshot(), {'confirmed': True})

    def test_process_fence_and_source_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'station.sqlite3'
            with ProcessStore(path, 'source-a'):
                code = ('import sys;sys.path.insert(0,sys.argv[1]);from cf01_sila2_store import ProcessStore;'
                        'ProcessStore(sys.argv[2],"source-a")')
                result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts'), str(path)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Another server owns', result.stderr)
            with self.assertRaisesRegex(StoreError, 'source revision changed'):
                ProcessStore(path, 'source-b')

    def test_snapshot_corruption_is_rejected_before_backend_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'station.sqlite3'
            with ProcessStore(path, 'source') as store:
                store.checkpoint({'confirmed': True})
                store.db.execute('UPDATE snapshot SET payload=?', (json.dumps({'confirmed': False}),))
            with self.assertRaisesRegex(StoreError, 'checksum mismatch'):
                ProcessStore(path, 'source')

    def test_old_schema_and_corrupted_intent_arguments_are_rejected(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / 'old.sqlite3'
            with sqlite3.connect(old) as db:
                db.execute('CREATE TABLE intents (request_id TEXT)')
            with self.assertRaisesRegex(StoreError, 'explicit migration'):
                ProcessStore(old, 'source')
            with sqlite3.connect(old) as db:
                self.assertEqual([row[1] for row in db.execute('PRAGMA table_info(intents)')], ['request_id'])
            path = Path(directory) / 'station.sqlite3'
            with ProcessStore(path, 'source') as store:
                store.begin(str(uuid.uuid4()), 'boot', 'RunCentrifuge', {'duration_s': 30.}, 'operator')
                store.db.execute('UPDATE intents SET arguments=?', (json.dumps({'duration_s': 300.}),))
            with self.assertRaisesRegex(StoreError, 'intent arguments checksum mismatch'):
                ProcessStore(path, 'source')


if __name__ == '__main__':
    unittest.main()
