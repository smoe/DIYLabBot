"""TLS SiLA 2 transport over the existing CF01 core, without hardware I/O."""
import asyncio
import contextvars
import datetime
import os
from pathlib import Path
import uuid
import time

from sila.server import (Server, ServerConfig, Feature, UnobservableCommand, ObservableCommand,
                         UnobservableProperty, ObservableProperty, Metadata,
                         InvalidMetadata, UndefinedExecutionError, ValidationError, create_certificate)

import build_cf01_sila2 as contract
from cf01_sila2_auth import Access
from cf01_sila2_runtime import StationRuntime
from cf01_sila2_store import StoreError
from centrifuge_control import ControlError

FACTORIES = {'unobservable_command_factory': UnobservableCommand, 'observable_command_factory': ObservableCommand,
             'unobservable_property_factory': UnobservableProperty, 'observable_property_factory': ObservableProperty,
             'metadata_factory': Metadata}
PRINCIPAL = contextvars.ContextVar('cf01_sila_principal', default=None)


def parsed(text):
    return Feature.from_definition(text, FACTORIES)


def wire_state(state):
    if isinstance(state, dict):
        return {contract.base.camel(k): wire_state(v) for k, v in state.items()}
    if isinstance(state, list):
        return [wire_state(v) for v in state]
    return state


def metadatum(metadata, name):
    values = [v for k, v in metadata.items() if str(k).endswith('/Metadata/' + name)]
    if len(values) != 1:
        raise InvalidMetadata('Exactly one ' + name + ' metadatum required')
    return values[0]


class CF01Server:
    def __init__(self, store, users, certificate_directory, hostname='127.0.0.1', port=0, clock=None):
        self.runtime = StationRuntime(store, clock=clock)
        self.profile = self.runtime.profile
        self.interval = self.profile['clock']['publish_interval_s']
        self._ticker = None
        self.discovery = None
        try:
            cert, key = self._certificate(Path(certificate_directory), hostname)
            self.server = Server(ServerConfig(hostname=hostname, port=port, tls=True,
                                 uuid=self.runtime.store.server_uuid, type='SolidCraftBotCF01', name='CF01 simulation',
                                 description='CF01 simulation only; no hardware interface or qualified safety function.',
                                 vendor_url='https://github.com/smoe/DIYLabBot', version='0.1.0',
                                 certificate_chain=cert, private_key=key))
            self.certificate = cert
            self.standard = {}
            for ref in self.profile['standard_features']:
                if ref['identifier'] == 'SiLAService':
                    continue  # SDK supplies the mandatory service and live feature list.
                self.standard[ref['identifier']] = parsed((contract.ROOT / ref['source']).read_text(encoding='utf-8-sig'))
            self.feature = parsed(contract.feature())
            self.observation = parsed(contract.simulation_feature())
            all_features = {str(f.fully_qualified_identifier) for f in [self.feature, self.observation, *self.standard.values()]}
            self.access = Access(users, self.runtime.store.server_uuid, all_features)
            # Metadata interceptors execute in feature registration order: access
            # is checked before a lease is touched or an intent is created.
            for name in ['AuthenticationService', 'AuthorizationService', 'LockController', 'CancelController', 'SimulationController']:
                self.server.register_feature(self.standard[name])
            self.server.register_feature(self.feature)
            self.server.register_feature(self.observation)
            self._bind()
        except BaseException:
            self.runtime.close()
            raise

    def _certificate(self, directory, hostname):
        directory.mkdir(parents=True, exist_ok=True)
        cert_path, key_path = directory / 'server.crt', directory / 'server.key'
        if cert_path.exists() != key_path.exists():
            raise ValueError('Incomplete TLS identity; explicit certificate repair required')
        if not cert_path.exists():
            certificate = create_certificate(self.runtime.store.server_uuid,
                                             ip_addresses=[hostname] if hostname.replace('.', '').isdigit() else None,
                                             dns_names=['localhost'])
            # Exclusive creation avoids silently replacing an existing identity.
            for path, content in [(key_path, certificate.pem_private_key), (cert_path, certificate.pem_certificate)]:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, 'wb') as file:
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
        cert, key = cert_path.read_bytes(), key_path.read_bytes()
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        certificate = x509.load_pem_x509_certificate(cert)
        private_key = serialization.load_pem_private_key(key, password=None)
        actual_uuid = certificate.extensions.get_extension_for_oid(x509.ObjectIdentifier('1.3.6.1.4.1.58583')).value.value.decode()
        if actual_uuid != self.runtime.store.server_uuid:
            raise ValueError('TLS certificate belongs to a different SiLA server UUID')
        encoding = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if private_key.public_key().public_bytes(*encoding) != certificate.public_key().public_bytes(*encoding):
            raise ValueError('TLS private key and certificate do not match')
        now = datetime.datetime.now(datetime.timezone.utc)
        if not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc:
            raise ValueError('TLS certificate is not currently valid; explicit renewal required')
        return cert, key

    def _error(self, feature, error):
        if isinstance(error, ControlError):
            code = self.profile['framework_error_mapping'].get(error.code, error.code)
            if code == 'ValidationError':
                raise ValidationError(message=str(error)) from error
            if code in feature.errors:
                raise feature.errors[code](str(error)) from error
        if isinstance(error, StoreError):
            raise InvalidMetadata(str(error)) from error
        raise UndefinedExecutionError('Operation failed; inspect CF01 status and recovery journal') from error

    def _bind(self):
        authentication = self.standard['AuthenticationService']
        authorization = self.standard['AuthorizationService']
        lock = self.standard['LockController']
        cancellation = self.standard['CancelController']
        simulation = self.standard['SimulationController']

        async def login(metadata, **params):
            try:
                token, lifetime = await asyncio.to_thread(self.access.login, params['UserIdentification'], params['Password'],
                                                          params['RequestedServer'], params['RequestedFeatures'])
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

        access_metadata = authorization.metadata['AccessToken']
        access_metadata.affects = [str(f.fully_qualified_identifier) for f in
                                   [self.feature, self.observation, lock, cancellation, simulation]]

        def authorize(token, handler):
            try:
                PRINCIPAL.set(self.access.authorize(token, handler))
            except PermissionError as error:
                raise authorization.errors['InvalidAccessToken']('Access is not authorized') from error

        access_metadata.function = staticmethod(authorize)
        lock_metadata = lock.metadata['LockIdentifier']
        lock_metadata.affects = [str(c.fully_qualified_identifier) for c in self.feature.commands.values() if c.identifier != 'Stop']
        lock_metadata.affects.append(str(self.observation.fully_qualified_identifier))
        original_from_buffer = lock_metadata.from_buffer.__func__

        async def optional_lock(cls, handler, supplied=None):
            if not supplied or cls.rpc_header() not in supplied:
                return await cls.from_native(handler.feature.context, '')
            return await original_from_buffer(cls, handler, supplied)

        lock_metadata.from_buffer = classmethod(optional_lock)

        def touch(identifier, handler):
            try:
                self.runtime.touch(identifier, PRINCIPAL.get())
            except ControlError as error:
                self._error(lock, error)

        lock_metadata.function = staticmethod(touch)
        request_metadata = self.feature.metadata['RequestIdentifier']
        request_metadata.affects = [str(c.fully_qualified_identifier) for c in self.feature.commands.values()
                                    if c.identifier not in {'GetStatus', 'GetRotationFeedback'}]
        request_metadata.function = staticmethod(lambda value, handler: None)

        async def lock_server(metadata, LockIdentifier, Timeout):
            try:
                self.runtime.lock(LockIdentifier, Timeout, PRINCIPAL.get())
                return {}
            except (ControlError, StoreError) as error:
                self._error(lock, error)

        async def unlock_server(metadata, LockIdentifier):
            try:
                self.runtime.unlock(LockIdentifier, PRINCIPAL.get())
                return {}
            except (ControlError, StoreError) as error:
                self._error(lock, error)

        lock.commands['LockServer'].function = lock_server
        lock.commands['UnlockServer'].function = unlock_server

        async def is_locked(metadata):
            self.runtime.tick()
            return {'IsLocked': self.runtime.lock_id is not None}

        lock.properties['IsLocked'].function = is_locked

        async def cancel(metadata, CommandExecutionUUID):
            try:
                self.runtime.cancel(CommandExecutionUUID, PRINCIPAL.get())
                return {}
            except ControlError as error:
                self._error(cancellation, error)

        async def cancel_all(metadata):
            for identifier, job in list(self.runtime.jobs.items()):
                if job['phase'] not in {'succeeded', 'failed', 'canceled'}:
                    self.runtime.cancel(identifier, PRINCIPAL.get())
            return {}

        cancellation.commands['CancelCommand'].function = cancel
        cancellation.commands['CancelAll'].function = cancel_all

        async def simulation_mode(metadata):
            return {'SimulationMode': True}

        async def start_simulation(metadata):
            return {}  # Already simulation-only; never reset an active process.

        async def start_real(metadata):
            raise simulation.errors['StartRealModeFailed']('No hardware backend exists; real mode is unavailable')

        simulation.properties['SimulationMode'].function = simulation_mode
        simulation.commands['StartSimulationMode'].function = start_simulation
        simulation.commands['StartRealMode'].function = start_real

        by_name = {c['name']: c for c in self.runtime.commands}
        for name, implementation in self.feature.commands.items():
            source = by_name[name]
            implementation.function = self._operation(source)

        async def status(metadata):
            while True:
                yield {'Status': wire_state(self.runtime.status())}
                await asyncio.sleep(self.interval)

        self.feature.properties['Status'].function = status

        async def observe_robot(metadata, **parameters):
            fields = self.profile['simulation_feature']['parameters']
            arguments = {field['name']: parameters[contract.base.camel(field['name'])] for field in fields}
            try:
                self.runtime.observe_robot(**arguments, principal=PRINCIPAL.get())
                return {}
            except (ControlError, StoreError) as error:
                self._error(self.observation, error)

        self.observation.commands[self.profile['simulation_feature']['command']].function = observe_robot

    def _operation(self, source):
        async def invoke(metadata, command_execution=None, **parameters):
            arguments = {name: parameters[contract.base.camel(name)] for name in source['arguments']}
            request_id = None if source['id'] in {'status', 'rotation_feedback'} else metadatum(metadata, 'RequestIdentifier')
            execution_id = command_execution.command_execution_uuid if command_execution is not None else None
            principal = self.access.authorize(metadatum(metadata, 'AccessToken'))
            try:
                self.runtime.invoke(source['id'], arguments, principal, request_id, execution_id)
                if source['observable']:
                    while True:
                        result = self.runtime.poll(execution_id)
                        if result['phase'] == 'succeeded':
                            break
                        if result['phase'] in {'canceled', 'failed'}:
                            code = 'CommandCanceled' if result['phase'] == 'canceled' else result['error_code']
                            self._error(self.feature, ControlError(code, 'Execution terminated after confirmed station stop'))
                        command_execution.send_intermediate_responses({'State': wire_state(self.runtime.status())})
                        await asyncio.sleep(self.interval)
                return {'State': wire_state(self.runtime.status())}
            except (ControlError, StoreError) as error:
                self._error(self.feature, error)
        return invoke

    async def start(self, discovery=False):
        await self.server.start()
        self.port = int(self.server._address.rsplit(':', 1)[1])

        async def tick():
            while True:
                try:
                    self.runtime.tick()
                except ControlError:
                    # Disk errors latch recovery; status and priority stop remain
                    # available. Do not silently kill the independent watchdog.
                    pass
                await asyncio.sleep(self.interval)

        self._ticker = asyncio.create_task(tick())
        if discovery:
            from sila.server.discovery import Discovery
            self.discovery = Discovery(self.server)
            await self.discovery.start()

    async def stop(self):
        if self.discovery is not None:
            await self.discovery.stop()
        # Stop accepting new effects before requesting a controlled stop. The
        # existing observable worker continues through braking during the grace
        # period; a forced shutdown leaves its durable intent pending.
        self.server._stopping.set()
        active = any(j['phase'] not in {'succeeded', 'failed', 'canceled'} for j in self.runtime.jobs.values())
        if active or self.runtime.sim.rpm != 0:
            try:
                self.runtime.invoke('stop', {}, 'server-shutdown', str(uuid.uuid4()))
            except (ControlError, StoreError):
                self.runtime.sim.execute('stop')
            # A restarted station has no replayed observable worker. Graceful
            # shutdown must still progress its braking before stopping the
            # ticker, independently of gRPC's active-call grace period.
            deadline = time.monotonic() + self.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + 1
            while self.runtime.sim.rpm != 0 and time.monotonic() < deadline:
                try:
                    self.runtime.tick()
                except ControlError:
                    pass  # Disk failure already latched; controlled braking continues.
                await asyncio.sleep(self.interval)
            try:
                self.runtime._checkpoint()
            except ControlError:
                pass
        await self.server.stop(grace=(self.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s'] + 1) * 1000)
        if self._ticker is not None:
            self._ticker.cancel()
            await asyncio.gather(self._ticker, return_exceptions=True)
        self.runtime.close()
