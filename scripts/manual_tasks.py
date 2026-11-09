"""Local, durable task events and exclusive resources; no device or network I/O."""
import copy
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
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

    ``state(run_id)`` remains the fully verified legacy read. ``get_current``
    is the opt-in fast read: a verified prefix may be reused on this connection
    while SQLite's data_version, total_changes and the actual tail still match.
    Any unexpected write requires a new full check. ``history`` always verifies
    every event; callers should retain it for open, reports and final acceptance.
    There are no schema changes, persistent cache files or mutable state aliases.
    """

    def __init__(self, path, clock=time.time, clock_mode=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.clock_mode = clock_mode or ('wall_clock' if clock is time.time else 'injected')
        self._verified = {}
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
        self._verified.clear()
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def _stamp(self):
        # data_version detects commits on OTHER connections. total_changes also
        # detects direct writes on this public legacy connection, even rollbacks.
        return (self.connection.execute('PRAGMA data_version').fetchone()[0],
                self.connection.total_changes)

    @contextmanager
    def _reading(self):
        owned = not self.connection.in_transaction
        if owned:
            self.connection.execute('BEGIN')
        try:
            yield
        finally:
            if owned:
                self.connection.rollback()  # End the read snapshot, never a write.

    def _remember(self, run_id, row, state, stamp):
        self._verified[run_id] = {
            'row': row, 'state': copy.deepcopy(state),
            'stamp': stamp if self._stamp() == stamp else None}

    def history(self, run_id):
        """Fully verify the chain, even when a current-state cache is warm."""
        self._verified.pop(run_id, None)
        with self._reading():
            stamp = self._stamp()
            rows = self.connection.execute(
                'SELECT sequence, document, sha256 FROM events WHERE run_id=? ORDER BY sequence',
                (run_id,)).fetchall()
            if not rows:
                raise TaskError('Unknown run: ' + run_id)
            previous = None
            events = []
            for expected, (sequence, document, checksum) in enumerate(rows, 1):
                try:
                    event = json.loads(document)
                    valid = (isinstance(document, str) and isinstance(event, dict)
                             and 'state' in event and sequence == expected
                             and digest(document.encode()) == checksum
                             and event['previous_sha256'] == previous
                             and event['sequence'] == sequence and event['run_id'] == run_id)
                except (ValueError, KeyError, TypeError):
                    valid = False
                if not valid:
                    raise TaskError('Corrupt task journal: ' + run_id)
                events.append({**event, 'sha256': checksum})
                previous = checksum
            self._remember(run_id, rows[-1], events[-1]['state'], stamp)
            return events

    def state(self, run_id):
        """Legacy full-chain read; return a detached state and its revision."""
        events = self.history(run_id)
        return events[-1]['state'], len(events)

    def _current(self, run_id, verify=False):
        stamp = self._stamp()
        row = self.connection.execute(
            'SELECT sequence, document, sha256 FROM events WHERE run_id=? '
            'ORDER BY sequence DESC LIMIT 1', (run_id,)).fetchone()
        cached = self._verified.get(run_id)
        if (verify or not cached or cached['stamp'] != stamp or cached['row'] != row
                or self._stamp() != stamp):
            # A foreign writer may have changed an OLD event, not merely appended
            # a suffix. Verifying only the new tail would miss that corruption.
            self.history(run_id)
            cached = self._verified[run_id]
        return copy.deepcopy(cached['state']), cached['row'][0], cached['row'][2]

    def get_current(self, run_id, *, verify=False):
        """Return ``(detached_state, revision)`` using a verified prefix cache.

        ``verify=True`` forces a full-chain audit. This read does not reserve a
        revision; append still compares it under BEGIN IMMEDIATE. An external
        writer, an unexpected direct SQL write, or a different tail invalidates
        the prefix. Raw file tampering is outside the cache's trust boundary;
        open/report/final acceptance must still perform a full history audit.
        """
        with self._reading():
            state, revision, _ = self._current(run_id, verify)
            return state, revision

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
            row = self._event(run_id, 1, None, 'created', {}, state)
            stamp = self._stamp()
            self.connection.commit()
            self._remember(run_id, row, json.loads(row[1])['state'], stamp)
        except sqlite3.IntegrityError as error:
            self.connection.rollback()
            self._verified.clear()
            raise TaskError('Run already exists: ' + run_id) from error
        except Exception:
            self.connection.rollback()
            self._verified.clear()
            raise

    def append(self, run_id, revision, kind, payload, state, artifact=None):
        """CAS, resources, artifact and event still commit under one write lock.

        Signature and return value remain unchanged. A matching verified prefix
        avoids rereading the whole chain; the current database tail and revision
        are checked inside BEGIN IMMEDIATE. Failed writes discard the cache.
        """
        try:
            self.connection.execute('BEGIN IMMEDIATE')
            old, current, previous = self._current(run_id)
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
            row = self._event(run_id, revision + 1, previous, kind, payload, state)
            stamp = self._stamp()
            self.connection.commit()
            self._remember(run_id, row, json.loads(row[1])['state'], stamp)
        except Exception:
            self.connection.rollback()
            self._verified.clear()
            raise

    def _event(self, run_id, sequence, previous, kind, payload, state):
        document = encoded({'run_id': run_id, 'sequence': sequence,
                            'event_id': str(uuid.uuid4()), 'time_unix_s': self.clock(),
                            'previous_sha256': previous, 'kind': kind,
                            'payload': payload, 'state': state})
        row = (sequence, document, digest(document.encode()))
        self.connection.execute('INSERT INTO events VALUES (?, ?, ?, ?)',
                                (run_id, *row))
        return row
