"""A bounded-queue broadcast hub for broadcasting messages to multiple subscribers."""

from __future__ import annotations

import asyncio
from typing import Any, Final

OVERFLOW_SIGNAL: Final = "OVERFLOW"


class BroadcastHub:
    """A bounded-queue broadcast hub with overflow signaling."""

    def __init__(self, maxsize: int = 50) -> None:
        """Initialize the hub.

        Args:
            maxsize: The maximum size for subscriber queues.
        """
        self.maxsize = maxsize
        self._subscribers: set[asyncio.Queue[Any]] = set()

    async def subscribe(self) -> asyncio.Queue[Any]:
        """Subscribe to the hub, returning a new bounded queue."""
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=self.maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Any]) -> None:
        """Unsubscribe a queue from the hub."""
        self._subscribers.discard(queue)

    def publish(self, message: Any) -> None:
        """Publish a message to all subscribers."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Clear the queue
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                # Send overflow signal
                queue.put_nowait(OVERFLOW_SIGNAL)
