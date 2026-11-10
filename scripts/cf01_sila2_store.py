"""Durable CF01 network intents; state-changing effects follow a committed intent.

One server process owns one store. Restart never replays an unfinished command.
This station journal is not a second lab inventory or a hardware state sensor.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


class StoreError(RuntimeError):
    pass


class DuplicateIntent(StoreError):
    pass


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class ProcessStore:
    def __init__(self, path, source_sha256):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A dedicated SQLite file holds an OS-backed exclusive transaction for
        # this process lifetime. It is independent of station writes and works
        # on Windows as well as Unix; no stale PID/timeout can steal a live lock.
        self._lock = sqlite3.connect(str(self.path) + '.server-lock', timeout=0, isolation_level=None)
        try:
            os.chmod(str(self.path) + '.server-lock', 0o600)
            self._lock.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError as error:
            self._lock.close()
            self._lock = None
            raise StoreError('Another server owns this station store') from error
        try:
            self.db = sqlite3.connect(self.path, isolation_level=None)
            os.chmod(self.path, 0o600)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA busy_timeout=5000')
            existing = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='intents'").fetchone()
            if existing and self.db.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise StoreError('Unsupported station journal schema; explicit migration or a separate store required')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    server_uuid TEXT NOT NULL, source_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshot (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    payload TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS intents (request_id TEXT PRIMARY KEY, boot_id TEXT NOT NULL,
                    command TEXT NOT NULL, arguments TEXT NOT NULL, fingerprint TEXT NOT NULL, principal TEXT NOT NULL,
                    execution_uuid TEXT, status TEXT NOT NULL, result TEXT, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS reconciliations (id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                    observation TEXT NOT NULL, created_at REAL NOT NULL);
            ''')
            columns = [row[1] for row in self.db.execute('PRAGMA table_info(intents)')]
            if columns != ['request_id', 'boot_id', 'command', 'arguments', 'fingerprint', 'principal',
                           'execution_uuid', 'status', 'result', 'created_at']:
                raise StoreError('Unsupported station journal columns; no automatic migration is allowed')
            if not existing:
                self.db.execute('PRAGMA user_version=1')
            self.db.execute('INSERT OR IGNORE INTO identity VALUES (1,?,?)', (str(uuid.uuid4()), source_sha256))
            self.server_uuid, recorded = self.db.execute('SELECT server_uuid,source_sha256 FROM identity').fetchone()
            if recorded != source_sha256:
                raise StoreError('Station source revision changed; use an explicitly migrated or separate store')
            # Check the persisted checkpoint immediately, before any backend use.
            self.read_snapshot()
            self.pending()
        except BaseException:
            self.close()
            raise

    def read_snapshot(self):
        row = self.db.execute('SELECT payload,sha256 FROM snapshot WHERE singleton=1').fetchone()
        if row is None:
            return None
        text, digest = row
        if hashlib.sha256(text.encode()).hexdigest() != digest:
            raise StoreError('Station snapshot checksum mismatch')
        return json.loads(text)

    def pending(self):
        result = []
        for row in self.db.execute('SELECT request_id,boot_id,command,arguments,fingerprint,execution_uuid,status FROM intents WHERE status="pending" ORDER BY created_at'):
            request, boot, command, text, fingerprint, execution, status = row
            arguments = json.loads(text)
            actual = hashlib.sha256(encode({'command': command, 'arguments': arguments}).encode()).hexdigest()
            if actual != fingerprint:
                raise StoreError('Station intent arguments checksum mismatch')
            result.append({'request_id': request, 'boot_id': boot, 'command': command, 'arguments': arguments,
                           'execution_uuid': execution, 'status': status})
        return result

    def begin(self, request_id, boot_id, command, arguments, principal, execution_uuid=None):
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError('canonical UUID required')
        except (ValueError, TypeError, AttributeError) as error:
            raise StoreError('RequestIdentifier must be a canonical UUID') from error
        fingerprint = hashlib.sha256(encode({'command': command, 'arguments': arguments}).encode()).hexdigest()
        try:
            self.db.execute('INSERT INTO intents VALUES (?,?,?,?,?,?,?,"pending",NULL,?)',
                            (request_id, boot_id, command, encode(arguments), fingerprint, principal, execution_uuid, time.time()))
        except sqlite3.IntegrityError as error:
            raise DuplicateIntent('RequestIdentifier was already used; inspect the original outcome before any new intent') from error

    def _snapshot(self, snapshot):
        text = encode(snapshot)
        self.db.execute('INSERT OR REPLACE INTO snapshot VALUES (1,?,?)',
                        (text, hashlib.sha256(text.encode()).hexdigest()))

    def checkpoint(self, snapshot):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self._snapshot(snapshot)
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def finish(self, request_id, status, result, snapshot):
        if status not in ('succeeded', 'failed', 'canceled'):
            raise StoreError('A terminal intent result is required')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            changed = self.db.execute('UPDATE intents SET status=?,result=? WHERE request_id=? AND status="pending"',
                                      (status, encode(result), request_id)).rowcount
            if changed != 1:
                raise StoreError('No unique pending intent to complete')
            self._snapshot(snapshot)
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def reconcile(self, actor, observation, snapshot):
        """Caller validates a complete explicit synthetic observation first."""
        if not isinstance(actor, str) or not actor.strip():
            raise StoreError('Explicit reconciliation actor required')
        expected = {r['request_id'] for r in self.pending()}
        if set(observation.get('acknowledged_uncertain_request_ids', [])) != expected:
            raise StoreError('Every uncertain request must be acknowledged explicitly')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('INSERT INTO reconciliations VALUES (?,?,?,?)',
                            (str(uuid.uuid4()), actor, encode(observation), time.time()))
            self.db.execute('UPDATE intents SET status="reconciled_unknown",result=? WHERE status="pending"',
                            (encode({'resolution': 'Explicit synthetic observation; original execution outcome remains unknown'}),))
            self._snapshot(snapshot)
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def close(self):
        if getattr(self, 'db', None) is not None:
            self.db.close()
            self.db = None
        if getattr(self, '_lock', None) is not None:
            self._lock.close()
            self._lock = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
