"""Serialize synchronous Google operations without blocking Telegram's event loop."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Callable, TypeVar

T = TypeVar("T")


class WorkerBusyError(RuntimeError):
    """The bounded IO queue is full; this call was never submitted."""


class IOWorker:
    def __init__(self, *, max_pending: int = 64, timeout_seconds: float = 45):
        if max_pending < 1 or timeout_seconds <= 0:
            raise ValueError("Worker limits must be positive")
        self.max_pending = max_pending
        self.timeout_seconds = timeout_seconds
        self._executor: ThreadPoolExecutor | None = None
        self._pending: set[asyncio.Future] = set()
        self._closed = False

    async def call(
        self, function: Callable[..., T], *args, timeout: float | None = None, **kwargs
    ) -> T:
        if self._closed:
            raise RuntimeError("IO worker is closed")
        if len(self._pending) >= self.max_pending:
            raise WorkerBusyError("Google IO queue is full; try again later")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="google-io"
            )
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            self._executor, partial(function, *args, **kwargs)
        )
        self._pending.add(future)

        def completed(done: asyncio.Future) -> None:
            self._pending.discard(done)
            # A timed-out caller may no longer await this future. Retrieve its
            # exception while preserving the result for other awaiting callers.
            if not done.cancelled():
                done.exception()

        future.add_done_callback(completed)
        # Cancellation/timeout does not cancel a submitted financial write.
        # Its durable operation ID remains the authority for reconciliation.
        effective_timeout = self.timeout_seconds if timeout is None else timeout
        return await asyncio.wait_for(
            asyncio.shield(future), timeout=effective_timeout
        )

    async def drain(self) -> None:
        while self._pending:
            await asyncio.gather(
                *(asyncio.shield(item) for item in tuple(self._pending)),
                return_exceptions=True,
            )

    async def close(self) -> None:
        self._closed = True
        await self.drain()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None


io_worker = IOWorker()
