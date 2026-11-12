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


MATERIAL_COMPONENT = 'solidcraftbot.material-allocations/1'
MATERIAL_STATE = 'solidcraftbot.material-workflow-state/1'
MATERIAL_DEFINITION = 'solidcraftbot.material-workflow-definition/1'


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
    New callers may opt into definition references. Legacy event bytes are never
    rewritten; both formats expose detached, fully reconstructed state views.
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

    @staticmethod
    def _definition_reference(event):
        if 'storage_format' not in event and 'definition_sha256' not in event:
            return None
        checksum = event.get('definition_sha256')
        if (event.get('storage_format') != 'solidcraftbot.task-event/2'
                or not isinstance(checksum, str) or len(checksum) != 64
                or any(character not in '0123456789abcdef' for character in checksum)
                or not isinstance(event.get('state'), dict) or 'definition' in event['state']):
            raise TaskError('Corrupt task journal definition reference')
        return checksum

    def _expanded(self, event, definitions=None):
        checksum = self._definition_reference(event)
        if checksum is None:
            return event
        definitions = {} if definitions is None else definitions
        if checksum not in definitions:
            try:
                definition = json.loads(self.artifact(checksum))
            except (TypeError, ValueError) as error:
                raise TaskError('Missing or corrupt immutable definition: ' + checksum) from error
            if not isinstance(definition, dict):
                raise TaskError('Corrupt task journal definition')
            definitions[checksum] = definition
        return {**event, 'state': {**event['state'], 'definition': copy.deepcopy(definitions[checksum])}}

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
            definition_reference = None
            definitions = {}
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
                reference = self._definition_reference(event) if valid else None
                if expected == 1:
                    definition_reference = reference
                if not valid or reference != definition_reference:
                    raise TaskError('Corrupt task journal: ' + run_id)
                events.append({**self._expanded(event, definitions), 'sha256': checksum})
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

    def _material_component(self):
        tables = {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('journal_components', 'material_allocations')")}
        if not tables:
            return False
        if tables != {'journal_components', 'material_allocations'}:
            raise TaskError('Incomplete material allocation store extension')
        try:
            components = self.connection.execute('SELECT name, format FROM journal_components').fetchall()
            columns = {row[1] for row in self.connection.execute('PRAGMA table_info(material_allocations)')}
        except sqlite3.Error as error:
            raise TaskError('Invalid material allocation store extension') from error
        if components != [('material_allocations', MATERIAL_COMPONENT)]:
            raise TaskError('Unsupported journal component version')
        if columns != {'alias', 'run_id', 'material_id', 'vessel_id',
                       'declaration_sha256', 'introduction_sha256'}:
            raise TaskError('Invalid material allocation index schema')
        return True

    def _enable_material_component(self):
        if self._material_component():
            return
        # DDL belongs to the introducing event's transaction. executescript()
        # would implicitly commit and is intentionally not used here.
        self.connection.execute('CREATE TABLE journal_components '
                                '(name TEXT PRIMARY KEY, format TEXT NOT NULL)')
        self.connection.execute('INSERT INTO journal_components VALUES (?, ?)',
                                ('material_allocations', MATERIAL_COMPONENT))
        self.connection.execute('''CREATE TABLE material_allocations (
            alias TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            material_id TEXT NOT NULL,
            vessel_id TEXT NOT NULL,
            declaration_sha256 TEXT NOT NULL,
            introduction_sha256 TEXT NOT NULL)''')

    @staticmethod
    def _is_material_state(state):
        return isinstance(state, dict) and state.get('format') == MATERIAL_STATE

    @staticmethod
    def _allocation_records(state, supplied=None):
        if (not Journal._is_material_state(state)
                or not isinstance(state.get('definition'), dict)
                or state['definition'].get('format') != MATERIAL_DEFINITION):
            raise TaskError('Versioned material workflow state and definition required')
        records = state['definition'].get('material_allocations')
        if not isinstance(records, list) or (supplied is not None and supplied != records):
            raise TaskError('Material allocations must equal the immutable definition')
        materials, vessels = set(), set()
        result = []
        for record in records:
            if not isinstance(record, dict) or set(record) != {'material_id', 'vessel_id', 'declaration_sha256'}:
                raise TaskError('Invalid material allocation declaration')
            for field, seen in (('material_id', materials), ('vessel_id', vessels)):
                value = record[field]
                if not isinstance(value, str) or not value.strip() or value in seen:
                    raise TaskError('Missing or duplicate material allocation identity: ' + field)
                seen.add(value)
            checksum = record['declaration_sha256']
            if (not isinstance(checksum, str) or len(checksum) != 64
                    or any(character not in '0123456789abcdef' for character in checksum)):
                raise TaskError('Invalid material allocation declaration checksum')
            result.append(copy.deepcopy(record))
        return result

    def audit_material_allocations(self):
        """Verify the permanent identity index against all material introductions.

        The index has no quantities and is never released. Its rows are derived
        from new-format introduction events, including empty opted-in runs.
        Historical reads do not require this extension to be understood.
        """
        with self._reading():
            enabled = self._material_component()
            expected, found_material_run = {}, False
            introductions = self.connection.execute(
                'SELECT run_id, document FROM events WHERE sequence=1 ORDER BY run_id').fetchall()
            for run_id, document in introductions:
                try:
                    event = self._expanded(json.loads(document))
                except (ValueError, TypeError, KeyError, AttributeError) as error:
                    raise TaskError('Cannot audit material allocation introduction: ' + run_id) from error
                if not self._is_material_state(event.get('state')):
                    continue
                found_material_run = True
                events = self.history(run_id)
                state = events[0]['state']
                records = self._allocation_records(state)
                definition = encoded(state['definition'])
                for item in events:
                    if (not self._is_material_state(item['state'])
                            or encoded(item['state'].get('definition')) != definition):
                        raise TaskError('Material allocation definition changed: ' + run_id)
                for record in records:
                    value = {'run_id': run_id, **record, 'introduction_sha256': events[0]['sha256']}
                    for alias in ('material:' + record['material_id'], 'vessel:' + record['vessel_id']):
                        if alias in expected:
                            raise TaskError('Material identity has multiple introductions: ' + alias)
                        expected[alias] = value
            if found_material_run and not enabled:
                raise TaskError('Missing material allocation store extension')
            actual = {}
            if enabled:
                for row in self.connection.execute(
                        'SELECT alias, run_id, material_id, vessel_id, declaration_sha256, '
                        'introduction_sha256 FROM material_allocations'):
                    actual[row[0]] = dict(zip(('run_id', 'material_id', 'vessel_id',
                                              'declaration_sha256', 'introduction_sha256'), row[1:]))
            if actual != expected:
                raise TaskError('Material allocation index does not match introduction events')
            return copy.deepcopy(actual)

    def _acquire_resources(self, run_id, resources, *, material_component=False):
        for resource in sorted(resources):
            if material_component:
                owner = self.connection.execute(
                    'SELECT run_id FROM material_allocations WHERE alias=?', (resource,)).fetchone()
                if owner and owner[0] != run_id:
                    raise TaskError('Material identity permanently allocated to ' + owner[0] + ': ' + resource)
            owner = self.connection.execute(
                'SELECT run_id FROM resources WHERE id=?', (resource,)).fetchone()
            if owner and owner[0] != run_id:
                raise TaskError('Resource reserved by ' + owner[0] + ': ' + resource)
            self.connection.execute('INSERT OR IGNORE INTO resources VALUES (?, ?)', (resource, run_id))

    def _claim_material_alias(self, alias, value):
        owner = self.connection.execute(
            'SELECT run_id FROM material_allocations WHERE alias=?', (alias,)).fetchone()
        if owner is not None:
            raise TaskError('Material identity permanently allocated to ' + owner[0] + ': ' + alias)
        held = self.connection.execute('SELECT run_id FROM resources WHERE id=?', (alias,)).fetchone()
        if held is not None and held[0] != value['run_id']:
            raise TaskError('Resource reserved by ' + held[0] + ': ' + alias)
        self.connection.execute('INSERT INTO material_allocations VALUES (?, ?, ?, ?, ?, ?)',
                                (alias, value['run_id'], value['material_id'], value['vessel_id'],
                                 value['declaration_sha256'], value['introduction_sha256']))

    def create(self, run_id, state, *, immutable_definition=False, material_allocations=None):
        if type(immutable_definition) is not bool:
            raise TaskError('Explicit immutable-definition storage option required')
        try:
            self.connection.execute('BEGIN IMMEDIATE')
            enabled = self._material_component()
            if enabled or material_allocations is not None or self._is_material_state(state):
                self.audit_material_allocations()
            allocations = None
            if material_allocations is not None:
                if not isinstance(material_allocations, list):
                    raise TaskError('Explicit material allocation list required')
                allocations = self._allocation_records(state, material_allocations)
                self._enable_material_component()
                enabled = True
            elif self._is_material_state(state):
                raise TaskError('Material workflow creation requires explicit material allocations')
            self.connection.execute('INSERT INTO runs VALUES (?)', (run_id,))
            reference = None
            if immutable_definition:
                if not isinstance(state.get('definition'), dict):
                    raise TaskError('Immutable definition must be an object')
                content = encoded(state['definition']).encode()
                reference = digest(content)
                self.connection.execute('INSERT OR IGNORE INTO artifacts VALUES (?, ?)', (reference, content))
            if allocations is not None:
                resources = state.get('resources')
                if (not isinstance(resources, list)
                        or any(not isinstance(item, str) or not item.strip() for item in resources)
                        or len(resources) != len(set(resources))):
                    raise TaskError('Material workflow initial resources must be unique strings')
                self._acquire_resources(run_id, resources, material_component=enabled)
            row = self._event(run_id, 1, None, 'created', {}, state, definition_sha256=reference)
            if allocations is not None:
                for record in allocations:
                    value = {'run_id': run_id, **record, 'introduction_sha256': row[2]}
                    for alias in ('material:' + record['material_id'], 'vessel:' + record['vessel_id']):
                        self._claim_material_alias(alias, value)
            persisted = self._expanded(json.loads(row[1]))['state']
            stamp = self._stamp()
            self.connection.commit()
            self._remember(run_id, row, persisted, stamp)
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
            enabled = self._material_component()
            if enabled:
                self.audit_material_allocations()
            old, current, previous = self._current(run_id)
            if current != revision:
                raise TaskError('Task changed; reload before confirming the operation')
            if self._is_material_state(old):
                if not enabled:
                    raise TaskError('Missing material allocation store extension')
                self._allocation_records(state)
                if encoded(state['definition']) != encoded(old['definition']):
                    raise TaskError('Material allocation definition is immutable')
            elif self._is_material_state(state):
                raise TaskError('Material workflow requires an opted-in introduction event')
            old_holds, new_holds = set(old['resources']), set(state['resources'])
            self._acquire_resources(run_id, new_holds, material_component=enabled)
            for resource in old_holds - new_holds:
                self.connection.execute(
                    'DELETE FROM resources WHERE id=? AND run_id=?', (resource, run_id))
            if artifact is not None:
                self.connection.execute('INSERT OR IGNORE INTO artifacts VALUES (?, ?)',
                                        (digest(artifact), artifact))
            reference = self._definition_reference(json.loads(self._verified[run_id]['row'][1]))
            row = self._event(run_id, revision + 1, previous, kind, payload, state,
                              definition_sha256=reference)
            persisted = self._expanded(json.loads(row[1]))['state']
            stamp = self._stamp()
            self.connection.commit()
            self._remember(run_id, row, persisted, stamp)
        except Exception:
            self.connection.rollback()
            self._verified.clear()
            raise

    def _event(self, run_id, sequence, previous, kind, payload, state, *, definition_sha256=None):
        metadata = {}
        if definition_sha256 is not None:
            if ('definition' not in state
                    or digest(encoded(state['definition']).encode()) != definition_sha256):
                raise TaskError('Immutable definition cannot change during a run')
            state = {key: value for key, value in state.items() if key != 'definition'}
            metadata = {'storage_format': 'solidcraftbot.task-event/2',
                        'definition_sha256': definition_sha256}
        document = encoded({'run_id': run_id, 'sequence': sequence,
                            'event_id': str(uuid.uuid4()), 'time_unix_s': self.clock(),
                            'previous_sha256': previous, 'kind': kind,
                            'payload': payload, 'state': state, **metadata})
        row = (sequence, document, digest(document.encode()))
        self.connection.execute('INSERT INTO events VALUES (?, ?, ?, ?)',
                                (run_id, *row))
        return row
