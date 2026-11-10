"""Network client primitives. A receipt is not an observable command result."""
import asyncio
import math
from pathlib import Path
import re
import time


def from_wire(value):
    if isinstance(value, dict):
        return {re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower(): from_wire(item) for key, item in value.items()}
    if isinstance(value, list):
        return [from_wire(item) for item in value]
    return value


async def connect_station(ready, username, password, timeout_s=5.):
    """Verify server identity and authenticate without acquiring a process lock."""
    from sila.client import Client, ClientConfig
    if (ready.get('tls') is not True or ready.get('simulation_only') is not True
            or ready.get('hardware_available') is not False):
        raise ValueError('Explicit TLS simulation-only endpoint required')
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError('Finite positive RPC timeout required')
    client = Client(ClientConfig(hostname=ready['bind'], port=ready['port'], tls=True,
                    root_certificates=Path(ready['certificate']).read_bytes(), default_timeout=timeout_s * 1000))
    try:
        await client.open()
        if await client.SiLAService.ServerUUID.read() != ready['server_uuid']:
            raise ValueError('SiLA server identity mismatch')
        response = await client.AuthenticationService.Login(UserIdentification=username, Password=password,
                        RequestedServer=ready['server_uuid'], RequestedFeatures=[])
        auth = await client.AuthorizationService.AccessToken.from_native(client, response.AccessToken)
        return client, auth
    except BaseException:
        await asyncio.wait_for(client.close(), timeout=timeout_s)
        raise


async def read_station_status(ready, username, password, timeout_s=5.):
    """Reconnect for a bounded observation, including changed boots or held work.

    No lock, heartbeat, command replay or client process journal is created.
    Station and client times remain separate observations.
    """
    client = None
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout_s):
            client, auth = await connect_station(ready, username, password, timeout_s)
            state = from_wire(await client.CentrifugeControl.Status.read(metadata=[auth], timeout=timeout_s * 1000))
            if state.get('simulation_only') is not True or state.get('hardware_qualified') is not False:
                raise ValueError('Observed station is not the declared synthetic endpoint')
            return {'observation': 'authenticated_live_status', 'server_uuid': ready['server_uuid'],
                    'expected_boot_id': ready.get('boot_id'), 'observed_boot_id': state['boot_id'],
                    'boot_changed': state['boot_id'] != ready.get('boot_id'), 'tls': True,
                    'client_request_started_monotonic_s': started,
                    'client_response_received_monotonic_s': time.monotonic(),
                    'workflow_clock_advanced': False, 'process_effects_dispatched': False,
                    'state': state}
    except Exception as error:
        raise RuntimeError('Could not read authenticated CF01 station status') from error
    finally:
        if client is not None:
            await asyncio.wait_for(client.close(), timeout=timeout_s)


class UncertainExecution(RuntimeError):
    def __init__(self, execution_uuid, message):
        super().__init__(message)
        self.execution_uuid = execution_uuid


async def wait_for_execution(execution, timeout_s):
    """Observe a terminal status before fetching its response, with one deadline.

    A lost stream or deadline never retries the original command. Keep its UUID
    and reconcile the uncertain intent; subscriptions may be re-established by
    an explicit caller decision without dispatching a new effect.
    """
    deadline = time.monotonic() + timeout_s
    stream = None
    try:
        async def completed():
            nonlocal stream
            stream = await execution.subscribe_status(timeout=max(.001, deadline - time.monotonic()) * 1000)
            async for _ in stream:
                pass
            if not execution.done:
                raise UncertainExecution(execution.command_execution_uuid, 'Status stream ended without a terminal execution state')
            return await execution.get_responses(timeout=max(.001, deadline - time.monotonic()) * 1000)
        return await asyncio.wait_for(completed(), timeout=max(.001, deadline - time.monotonic()))
    except TimeoutError as error:
        raise UncertainExecution(execution.command_execution_uuid, 'Execution deadline expired; do not repeat the command') from error
    finally:
        if stream is not None:
            stream.close()
