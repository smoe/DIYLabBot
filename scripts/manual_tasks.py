"""Local, durable task events and exclusive resources; no device or network I/O."""
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path


class TaskError(ValueError):
    """A rejected task operation; physical reservations remain in place."""


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(content):
    return hashlib.sha256(content).hexdigest()


class Journal:
    """Append-only event history, including state after each committed transition.

    Artifact bytes, events and resource reservations commit in one transaction.
    The final event is the state projection; there is no separately editable state
    file. Hashes detect accidental corruption, not malicious database modification.
    """

    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.connection = sqlite3.connect(self.path, timeout=10)
        try:
            self._initialize()
        except sqlite3.Error as error:
            self.connection.close()
            code = getattr(error, 'sqlite_errorname', 'SQLITE_ERROR')
            raise TaskError('Cannot initialize task journal (' + code + '): ' + str(error)) from error

    def _initialize(self):
        self.connection.execute('PRAGMA foreign_keys=ON')
        # Short local transactions do not need WAL's shared-memory sidecars.
        # EXTRA also syncs the directory when committing a rollback journal.
        mode = self.connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
        if mode != 'delete':
            raise sqlite3.OperationalError('Rollback journal mode could not be enabled')
        self.connection.execute('PRAGMA synchronous=EXTRA')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL REFERENCES runs(id),
                sequence INTEGER NOT NULL,
                document TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence));
            CREATE TABLE IF NOT EXISTS resources (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(id));
            CREATE TABLE IF NOT EXISTS artifacts (
                sha256 TEXT PRIMARY KEY,
                content BLOB NOT NULL);
        ''')

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def history(self, run_id):
        rows = self.connection.execute(
            'SELECT sequence, document, sha256 FROM events WHERE run_id=? ORDER BY sequence',
            (run_id,)).fetchall()
        if not rows:
            raise TaskError('Unknown run: ' + run_id)
        previous = None
        events = []
        for expected, (sequence, document, checksum) in enumerate(rows, 1):
            event = json.loads(document)
            if (sequence != expected or digest(document.encode()) != checksum
                    or event['previous_sha256'] != previous
                    or event['sequence'] != sequence or event['run_id'] != run_id):
                raise TaskError('Corrupt task journal: ' + run_id)
            events.append({**event, 'sha256': checksum})
            previous = checksum
        return events

    def state(self, run_id):
        events = self.history(run_id)
        return events[-1]['state'], len(events)

    def owners(self):
        return dict(self.connection.execute('SELECT id, run_id FROM resources'))

    def artifact(self, checksum):
        row = self.connection.execute(
            'SELECT content FROM artifacts WHERE sha256=?', (checksum,)).fetchone()
        if row is None or digest(row[0]) != checksum:
            raise TaskError('Missing or corrupt artifact: ' + checksum)
        return bytes(row[0])

    def create(self, run_id, state):
        try:
            self.connection.execute('BEGIN IMMEDIATE')
            self.connection.execute('INSERT INTO runs VALUES (?)', (run_id,))
            self._event(run_id, 1, None, 'created', {}, state)
            self.connection.commit()
        except sqlite3.IntegrityError as error:
            self.connection.rollback()
            raise TaskError('Run already exists: ' + run_id) from error
        except Exception:
            self.connection.rollback()
            raise

    def append(self, run_id, revision, kind, payload, state, artifact=None):
        """Optimistic revision check and resource ownership under one write lock."""
        try:
            self.connection.execute('BEGIN IMMEDIATE')
            old, current = self.state(run_id)
            if current != revision:
                raise TaskError('Task changed; reload before confirming the operation')
            old_holds, new_holds = set(old['resources']), set(state['resources'])
            for resource in sorted(new_holds):
                owner = self.connection.execute(
                    'SELECT run_id FROM resources WHERE id=?', (resource,)).fetchone()
                if owner and owner[0] != run_id:
                    raise TaskError('Resource reserved by ' + owner[0] + ': ' + resource)
                self.connection.execute(
                    'INSERT OR IGNORE INTO resources VALUES (?, ?)', (resource, run_id))
            for resource in old_holds - new_holds:
                self.connection.execute(
                    'DELETE FROM resources WHERE id=? AND run_id=?', (resource, run_id))
            if artifact is not None:
                self.connection.execute('INSERT OR IGNORE INTO artifacts VALUES (?, ?)',
                                        (digest(artifact), artifact))
            previous = self.history(run_id)[-1]['sha256']
            self._event(run_id, revision + 1, previous, kind, payload, state)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _event(self, run_id, sequence, previous, kind, payload, state):
        document = encoded({'run_id': run_id, 'sequence': sequence,
                            'event_id': str(uuid.uuid4()), 'time_unix_s': self.clock(),
                            'previous_sha256': previous, 'kind': kind,
                            'payload': payload, 'state': state})
        self.connection.execute('INSERT INTO events VALUES (?, ?, ?, ?)',
                                (run_id, sequence, document, digest(document.encode())))
