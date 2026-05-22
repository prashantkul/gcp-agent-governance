"""Execution state management for background ADK runs."""

import asyncio
import time
import logging

logger = logging.getLogger(__name__)


class ExecutionState:
    """Tracks the state of a background ADK execution."""

    def __init__(
        self,
        task: asyncio.Task,
        thread_id: str,
        event_queue: asyncio.Queue,
    ):
        self.task = task
        self.thread_id = thread_id
        self.event_queue = event_queue
        self.start_time = time.time()
        self.is_complete = False

    def is_stale(self, timeout_seconds: int) -> bool:
        return time.time() - self.start_time > timeout_seconds

    async def cancel(self):
        if not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.is_complete = True

    def get_execution_time(self) -> float:
        return time.time() - self.start_time
