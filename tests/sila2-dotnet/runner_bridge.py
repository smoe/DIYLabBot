"""Test-only pipe facade: every station RPC is performed by the Tecan process."""
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid

import build_cf01_sila2 as contract
import build_cf01_sila2_dotnet as build
from cf01_sila2_batch import from_wire
from cf01_sila2_client import UncertainExecution
from centrifuge_control import ControlError
import centrifuge_protocol as protocol


class TecanStation:
    def __init__(self, ready_path, login_path, journal):
        build.verify_build()
        self.ready = json.loads(Path(ready_path).read_text())
        self.username = json.loads(Path(login_path).read_text())['username']
        self.journal = journal
        self.contract = protocol.load()
        self.profile, sources, _ = contract.load()
        self.spec = sources['station']
        self.lock_id = None
        self.jobs = {}
        self.failed = False
        self._epoch = time.monotonic()
        self.responses = queue.Queue()
        self.stderr = Path(ready_path).with_name('tecan-stderr.log').open('w')
        self.process = subprocess.Popen([str(contract.ROOT / 'exports/tools/dotnet/dotnet'), str(build.ASSEMBLY),
            '--bridge', str(ready_path), str(login_path), str(Path(ready_path).with_name('unused-result.json'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1)
        def read():
            for line in self.process.stdout:
                self.responses.put(line)
            self.responses.put(None)
        self.reader = threading.Thread(target=read, name='tecan-response-reader', daemon=True)
        self.reader.start()
        try:
            connected = self._receive()
            if connected.get('ok') is not True:
                raise UncertainExecution(None, 'Independent client did not confirm startup')
            if connected['server_uuid'] != self.ready['server_uuid']:
                raise ValueError('Independent client connected to the wrong server')
            self._state(connected['state'])
            journal.append('connected', implementation='Tecan.Sila2', server_uuid=self.ready['server_uuid'],
                           boot_id=self.ready['boot_id'], tls=True)
        except BaseException:
            self.close()
            raise

    def now(self):
        return time.monotonic() - self._epoch

    def advance(self, seconds):
        time.sleep(seconds)

    def _receive(self):
        try:
            line = self.responses.get(timeout=8)
        except queue.Empty as error:
            self.failed = True
            raise UncertainExecution(None, 'Independent client response deadline expired; do not repeat effects') from error
        if line is None:
            self.failed = True
            raise UncertainExecution(None, 'Independent client disconnected; retain its pending journal')
        try:
            return json.loads(line)
        except ValueError as error:
            self.failed = True
            raise UncertainExecution(None, 'Independent client returned invalid pipe framing') from error

    def exchange(self, action, **arguments):
        if self.failed:
            raise UncertainExecution(None, 'Independent client channel is uncertain; do not send further effects')
        call_id = str(uuid.uuid4())
        self.process.stdin.write(json.dumps({'call_id': call_id, 'action': action, **arguments}) + '\n')
        self.process.stdin.flush()
        value = self._receive()
        if value.get('call_id') != call_id:
            self.failed = True
            raise UncertainExecution(None, 'Independent client response does not match the outstanding call')
        if value.get('ok') is not True:
            raise ControlError(value.get('error_code', 'UnexpectedBackendError'), 'Independent client rejected the request')
        return value['response']

    def _state(self, value):
        state = from_wire(value)
        if (state['boot_id'] != self.ready['boot_id'] or not state['simulation_only']
                or state['clock_mode'] != 'monotonic_realtime'):
            raise UncertainExecution(None, 'Station identity or execution mode changed')
        return state

    def state(self):
        return self._state(self.exchange('state')['state'])

    def effect(self, command, action, arguments, **request):
        request_id = str(uuid.uuid4())
        self.journal.append('intent', request_id=request_id, command=command, arguments=arguments)
        try:
            result = self.exchange(action, request_id=request_id, **request)
        except BaseException:
            self.journal.append('uncertain', request_id=request_id, command=command)
            raise
        return request_id, result

    def dispatch(self, transport, name, parameters):
        if transport != 'sila2':
            raise ValueError('Independent client requires SiLA')
        command = next(c for c in self.contract['commands'] if c['name'] == name)
        identifier = command['id']
        if identifier not in protocol.PUBLIC and parameters.get('ControlToken') != self.lock_id:
            raise ValueError('Runner lock handle mismatch')
        if identifier in {'status', 'heartbeat'}:
            return {'success': True, 'state': self.state()}
        arguments = {contract.base.camel(k): parameters[protocol.wire(transport, k)] for k in command['arguments']}
        if identifier == 'acquire':
            self.lock_id = str(uuid.uuid4())
            request, result = self.effect('LockServer', 'lock', arguments, lock_id=self.lock_id,
                timeout_s=math.ceil(self.spec['handling']['owner_timeout_s'] * 2))
        elif identifier == 'release':
            request, result = self.effect('UnlockServer', 'unlock', arguments)
            self.lock_id = None
        else:
            request, result = self.effect(name, 'submit', arguments, name=name, parameters=arguments)
        if command['observable']:
            execution = result['execution_uuid']
            self.jobs[execution] = {'request': request, 'command': identifier, 'logged': False}
            self.journal.append('accepted', request_id=request, execution_uuid=execution)
            return self.poll(execution)
        self.journal.append('completed', request_id=request)
        return {'success': True, 'control_token': self.lock_id, 'state': self._state(result['state'])}

    def poll(self, execution):
        result = self.exchange('poll', execution_uuid=execution)
        job = self.jobs[execution]
        result['state'] = self._state(result['state'])
        if result['phase'] in {'succeeded', 'failed', 'canceled'} and not job['logged']:
            self.journal.append('terminal', request_id=job['request'], execution_uuid=execution, **result)
            job['logged'] = True
        return {'id': execution, 'command': job['command'], **result}

    def observe_robot(self, event, sample):
        observation = str(uuid.uuid4())
        arguments = {'BootId': self.ready['boot_id'], 'ObservationId': observation, 'ActorId': self.username,
                     'SampleId': sample['id'], 'Slot': sample['rotor_slot'], 'Event': event}
        request, _ = self.effect('ObserveRobotAccess', 'observe_robot', arguments, parameters=arguments)
        self.journal.append('completed', request_id=request, observation_id=observation)

    def evidence(self):
        return {'implementation': 'Tecan.Sila2', 'server_uuid': self.ready['server_uuid'],
                'boot_id': self.ready['boot_id'], 'journal': str(self.journal.path),
                'tls': True, 'client_build': json.loads(build.REPORT.read_text())}

    def close(self):
        try:
            if self.process.poll() is None:
                try:
                    self.process.stdin.write('{"action":"close"}\n')
                    self.process.stdin.flush()
                    self.process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            self.process.stdin.close()
            self.reader.join(timeout=5)
            self.process.stdout.close()
            self.stderr.close()
