"""Network client primitives. A receipt is not an observable command result."""
import asyncio
import time


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
