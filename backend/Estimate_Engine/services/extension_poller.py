import asyncio
from contextlib import suppress

from database.config import settings
from services.estimation_engine import estimation_engine


class ExtensionPoller:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not settings.extension_poll_enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            with suppress(Exception):
                await estimation_engine.poll_extension_events()
            await asyncio.sleep(max(settings.extension_poll_interval_seconds, 5))


extension_poller = ExtensionPoller()
