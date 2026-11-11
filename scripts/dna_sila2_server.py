"""Authenticated TLS transport for the existing synthetic DNA root coordinator."""
import asyncio
import contextvars
import datetime
import json
import os
from pathlib import Path
import threading
import time

from sila.server import (Server, ServerConfig, Feature, UnobservableCommand, ObservableCommand,
    UnobservableProperty, ObservableProperty, Metadata, InvalidMetadata,
    UndefinedExecutionError, ValidationError, create_certificate)

import build_dna_quantification_sila2 as contract
from cf01_sila2_auth import Access
from dna_sila2_runtime import DNARuntime
from dna_quantification_control import ExecutionInterrupted
from manual_tasks import TaskError

FACTORIES = {'unobservable_command_factory': UnobservableCommand, 'observable_command_factory': ObservableCommand,
             'unobservable_property_factory': UnobservableProperty, 'observable_property_factory': ObservableProperty,
             'metadata_factory': Metadata}
PRINCIPAL = contextvars.ContextVar('dna_sila_principal', default=None)


def parsed(text):
    return Feature.from_definition(text, FACTORIES)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def metadatum(metadata, name):
    values = [value for key, value in metadata.items() if str(key).endswith('/Metadata/' + name)]
    if len(values) != 1:
        raise InvalidMetadata('Exactly one ' + name + ' metadatum required')
    return values[0]


class DNAServer:
    def __init__(self, directory, users, certificate_directory, hostname='127.0.0.1', port=0,
                 pause_after=None, runtime=None, lease_clock=time.monotonic):
        if hostname not in {'127.0.0.1', 'localhost'}:
            raise ValueError('This DNA adapter supports synthetic loopback operation only')
        self.runtime = runtime or DNARuntime(directory, pause_after=pause_after)
        self.profile = self.runtime.profile
        self.interval = self.profile['publish_interval_s']
        self._clock = lease_clock
        self._mutex = threading.RLock()
        self.lock_id = self.lock_principal = self.lock_deadline = None
        self.lock_timeout = None
        self._workers = set()
        self._executions = {}
        self._ticker = None
        self._stopping = False
        try:
            cert, key = self._certificate(Path(certificate_directory), hostname)
            self.certificate = cert
            self.server = Server(ServerConfig(hostname=hostname, port=port, tls=True,
                uuid=self.runtime.server_uuid, type='SolidCraftBotDNA', name='Synthetic DNA quantification',
                description='Synthetic NanoDrop/Qubit coordinator; no device, pipette, motion or qualified safety interface.',
                vendor_url='https://github.com/smoe/DIYLabBot', version='0.1.0', certificate_chain=cert, private_key=key))
            self.standard = {ref['identifier']: parsed((contract.ROOT / ref['source']).read_text(encoding='utf-8-sig'))
                             for ref in self.profile['standard_features'] if ref['identifier'] != 'SiLAService'}
            self.feature = parsed(contract.feature(self.profile))
            self.access = Access(users, self.runtime.server_uuid,
                {str(feature.fully_qualified_identifier) for feature in [self.feature, *self.standard.values()]})
            for name in ['AuthenticationService', 'AuthorizationService', 'LockController', 'CancelController', 'SimulationController']:
                self.server.register_feature(self.standard[name])
            self.server.register_feature(self.feature)
            self._bind()
        except BaseException:
            self.runtime.close()
            raise

    def _certificate(self, directory, hostname):
        """Keep the DNA identity separate; never overwrite CF01 or old TLS files."""
        directory.mkdir(parents=True, exist_ok=True)
        cert_path, key_path = directory / 'server.crt', directory / 'server.key'
        if cert_path.exists() != key_path.exists():
            raise ValueError('Incomplete DNA TLS identity; explicit repair required')
        if not cert_path.exists():
            identity = create_certificate(self.runtime.server_uuid,
                ip_addresses=[hostname] if hostname.replace('.', '').isdigit() else None, dns_names=['localhost'])
            for path, content in [(key_path, identity.pem_private_key), (cert_path, identity.pem_certificate)]:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, 'wb') as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
        cert, key = cert_path.read_bytes(), key_path.read_bytes()
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        certificate = x509.load_pem_x509_certificate(cert)
        private_key = serialization.load_pem_private_key(key, password=None)
        identifier = certificate.extensions.get_extension_for_oid(x509.ObjectIdentifier('1.3.6.1.4.1.58583')).value.value.decode()
        if identifier != self.runtime.server_uuid:
            raise ValueError('DNA TLS certificate belongs to a different server UUID')
        encoding = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if certificate.public_key().public_bytes(*encoding) != private_key.public_key().public_bytes(*encoding):
            raise ValueError('DNA TLS certificate and private key do not match')
        now = datetime.datetime.now(datetime.timezone.utc)
        if not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc:
            raise ValueError('DNA TLS certificate requires explicit renewal')
        return cert, key

    def _expire(self):
        with self._mutex:
            if self.lock_id is not None and self.lock_deadline is not None and self._clock() >= self.lock_deadline:
                self.lock_id = self.lock_principal = self.lock_deadline = None

    def _lease(self, identifier, principal, touch=False):
        self._expire()
        with self._mutex:
            if self._stopping or self.lock_id is None or identifier != self.lock_id or principal != self.lock_principal:
                raise PermissionError('DNA write lease is absent, expired or belongs to another principal')
            if touch and self.lock_timeout:
                self.lock_deadline = self._clock() + self.lock_timeout

    def _error(self, error):
        if getattr(error, 'identifier', None) in self.feature.errors:
            raise error
        if isinstance(error, PermissionError):
            raise InvalidMetadata('DNA authorization or write lease is no longer valid') from error
        if isinstance(error, ExecutionInterrupted):
            raise self.feature.errors['CommandCanceled']('DNA execution cancellation requested') from error
        code = getattr(error, 'code', None)
        if isinstance(error, OSError):
            code = 'PersistenceFailure'
        if code in self.feature.errors:
            raise self.feature.errors[code](str(error)) from error
        if isinstance(error, (TaskError, ValueError, RuntimeError)):
            raise self.feature.errors['WorkflowRejected'](str(error)) from error
        raise UndefinedExecutionError('DNA operation failed; inspect the authoritative root journal') from error

    def _bind(self):
        authentication, authorization = self.standard['AuthenticationService'], self.standard['AuthorizationService']
        lock, cancellation, simulation = self.standard['LockController'], self.standard['CancelController'], self.standard['SimulationController']

        async def login(metadata, **parameters):
            try:
                token, lifetime = await asyncio.to_thread(self.access.login, parameters['UserIdentification'],
                    parameters['Password'], parameters['RequestedServer'], parameters['RequestedFeatures'])
                return {'AccessToken': token, 'TokenLifetime': lifetime}
            except PermissionError as error:
                raise authentication.errors['AuthenticationFailed']('Authentication failed') from error

        async def logout(metadata, AccessToken):
            try:
                self.access.logout(AccessToken)
                return {}
            except PermissionError as error:
                raise authentication.errors['InvalidAccessToken']('Invalid access token') from error

        authentication.commands['Login'].function = login
        authentication.commands['Logout'].function = logout
        access = authorization.metadata['AccessToken']
        access.affects = [str(feature.fully_qualified_identifier) for feature in [self.feature, lock, cancellation, simulation]]

        def authorize(token, handler):
            try:
                PRINCIPAL.set(self.access.authorize(token, handler))
            except PermissionError as error:
                raise authorization.errors['InvalidAccessToken']('Access is not authorized') from error

        access.function = staticmethod(authorize)
        lease = lock.metadata['LockIdentifier']
        lease.affects = [str(command.fully_qualified_identifier) for command in self.feature.commands.values()]
        original = lease.from_buffer.__func__

        async def optional_lock(cls, handler, supplied=None):
            if not supplied or cls.rpc_header() not in supplied:
                return await cls.from_native(handler.feature.context, '')
            return await original(cls, handler, supplied)

        lease.from_buffer = classmethod(optional_lock)

        def touch(identifier, handler):
            try:
                self._lease(identifier, PRINCIPAL.get(), touch=True)
            except PermissionError as error:
                raise lock.errors['InvalidLockIdentifier']('A current DNA write lease is required') from error

        lease.function = staticmethod(touch)

        async def lock_server(metadata, LockIdentifier, Timeout):
            if not isinstance(LockIdentifier, str) or not LockIdentifier.strip() or type(Timeout) is not int or Timeout < 0:
                raise ValidationError('Nonempty lock identifier and nonnegative integer timeout required')
            self._expire()
            with self._mutex:
                if self.lock_id is not None:
                    raise lock.errors['ServerAlreadyLocked']('DNA server already locked')
                self.lock_id, self.lock_principal, self.lock_timeout = LockIdentifier, PRINCIPAL.get(), Timeout
                self.lock_deadline = self._clock() + Timeout if Timeout else None
            return {}

        async def unlock(metadata, LockIdentifier):
            self._expire()
            with self._mutex:
                if self.lock_id is None:
                    raise lock.errors['ServerNotLocked']('DNA server is not locked')
                if LockIdentifier != self.lock_id or PRINCIPAL.get() != self.lock_principal:
                    raise lock.errors['InvalidLockIdentifier']('DNA lease belongs to another principal')
                self.lock_id = self.lock_principal = self.lock_deadline = None
            return {}  # Root resources and pending custody remain authoritative.

        async def is_locked(metadata):
            self._expire()
            return {'IsLocked': self.lock_id is not None}

        lock.commands['LockServer'].function = lock_server
        lock.commands['UnlockServer'].function = unlock
        lock.properties['IsLocked'].function = is_locked

        async def cancel(metadata, CommandExecutionUUID):
            entry = self._executions.get(CommandExecutionUUID)
            if entry is None or entry['principal'] != PRINCIPAL.get():
                raise cancellation.errors['InvalidCommandExecutionUUID']('Unknown execution for this principal')
            entry['cancel'].set()
            try:
                self.runtime.cancel_execution(CommandExecutionUUID)
            except TaskError:
                pass  # Its server-known pre-dispatch guard already carries the signal.
            return {}  # A cancellation signal is not a root clearance observation.

        async def cancel_all(metadata):
            for execution, entry in list(self._executions.items()):
                if entry['principal'] == PRINCIPAL.get():
                    entry['cancel'].set()
                    try:
                        self.runtime.cancel_execution(execution)
                    except TaskError:
                        pass
            return {}

        cancellation.commands['CancelCommand'].function = cancel
        cancellation.commands['CancelAll'].function = cancel_all

        async def simulation_mode(metadata):
            return {'SimulationMode': True}

        async def start_simulation(metadata):
            return {}

        async def real_mode(metadata):
            raise simulation.errors['StartRealModeFailed']('No DNA hardware backend exists')

        simulation.properties['SimulationMode'].function = simulation_mode
        simulation.commands['StartSimulationMode'].function = start_simulation
        simulation.commands['StartRealMode'].function = real_mode
        for source in self.profile['commands']:
            self.feature.commands[source['name']].function = self._operation(source)

        async def status(metadata):
            while True:
                yield {'Status': encoded(self.runtime.status())}
                await asyncio.sleep(self.interval)

        async def report(metadata):
            return {'Report': encoded(self.runtime.report())}

        self.feature.properties['Status'].function = status
        self.feature.properties['Report'].function = report

    def _operation(self, source):
        async def invoke(metadata, command_execution=None, **parameters):
            arguments = {field['name']: parameters[contract.camel(field['name'])] for field in source['arguments']}
            token, identifier = metadatum(metadata, 'AccessToken'), metadatum(metadata, 'LockIdentifier')
            implementation = self.feature.commands[source['name']]
            principal = self.access.authorize(token, implementation)
            execution = command_execution.command_execution_uuid if command_execution is not None else None
            cancelled = threading.Event()

            def guard():
                if cancelled.is_set():
                    raise ExecutionInterrupted('CommandCanceled')
                if self.access.authorize(token, implementation) != principal:
                    raise PermissionError('DNA command principal changed')
                self._lease(identifier, principal)

            worker = None
            try:
                guard()
                if execution is not None:
                    self._executions[execution] = {'principal': principal, 'cancel': cancelled}
                worker = asyncio.create_task(asyncio.to_thread(self.runtime.command, source['name'], arguments,
                    principal, execution_uuid=execution, guard=guard))
                self._workers.add(worker)
                worker.add_done_callback(self._workers.discard)
                result = await asyncio.shield(worker)
                if result.get('outcome') in {'interrupted', 'failed', 'accepted', 'uncertain'}:
                    code = 'ReconciliationRequired' if result['outcome'] in {'accepted', 'uncertain'} else result.get('error')
                    code = 'RecoveryRequired' if code == 'ReconciliationRequired' else code
                    if code not in self.feature.errors:
                        code = 'WorkflowRejected'
                    raise self.feature.errors[code]('DNA execution requires review; inspect its durable root receipt')
                return {'StatusJson': encoded(result)}
            except Exception as error:
                self._error(error)
            finally:
                # A dropped RPC never cancels the root worker. Keep it reachable
                # by CancelController until the guarded root operation exits.
                if execution is not None and worker is not None:
                    worker.add_done_callback(lambda _: self._executions.pop(execution, None))
        return invoke

    async def start(self):
        await self.server.start()
        self.port = int(self.server._address.rsplit(':', 1)[1])
        self.runtime.transport = 'sila2_tls_loopback'

        async def tick():
            while True:
                self._expire()
                await asyncio.sleep(self.interval)

        self._ticker = asyncio.create_task(tick())

    async def stop(self):
        self._stopping = True
        self.server._stopping.set()
        for execution, entry in list(self._executions.items()):
            entry['cancel'].set()
            try:
                self.runtime.cancel_execution(execution)
            except TaskError:
                pass
        if self._workers:
            await asyncio.gather(*list(self._workers), return_exceptions=True)
        await self.server.stop(grace=1000)
        if self._ticker is not None:
            self._ticker.cancel()
            await asyncio.gather(self._ticker, return_exceptions=True)
        self.runtime.close()
