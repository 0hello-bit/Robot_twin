"""Reliable runtime command send and ACK matching for Task 2.

This module provides the send-lock and Future-based ACK registry that
LiveWifiBridge delegates to.  It is testable without importing cv2 or
the full bridge.
"""

from __future__ import annotations

import asyncio
from typing import Optional


class AckRegistry:
    """Strict campaign/version-correlated ACK Future registry.

    One waiter per (campaign_id, version) key.  Duplicate registration
    raises RuntimeError.  Pending waiters can be failed on disconnect.
    """

    def __init__(self):
        self._futures: dict[tuple[str, int], asyncio.Future] = {}

    def register(self, campaign_id: str, version: int,
                 future: Optional[asyncio.Future] = None
                 ) -> asyncio.Future:
        """Register a waiter and return its Future.

        If no Future is provided, one is created from the running event loop.
        Raises RuntimeError if a waiter for the same key already exists.
        Raises RuntimeError if no Future is provided and no event loop is running.
        """
        key = (campaign_id, version)
        if key in self._futures:
            raise RuntimeError(
                "duplicate ACK waiter for {0} v{1}".format(campaign_id, version))
        if future is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                raise RuntimeError(
                    "no running event loop; pass a Future or call from async context")
            future = loop.create_future()
        self._futures[key] = future
        return future

    def deliver(self, campaign_id: str, version: int, ack: object) -> None:
        """Deliver an ACK to the matching waiter, if any.

        The waiter is unregistered on delivery.
        """
        key = (campaign_id, version)
        future = self._futures.pop(key, None)
        if future is not None and not future.done():
            future.set_result(ack)

    def fail_all(self, reason: str) -> None:
        """Fail all pending waiters with RuntimeError(reason)."""
        exc = RuntimeError("disconnected: {0}".format(reason))
        for key, future in list(self._futures.items()):
            if not future.done():
                future.set_exception(exc)
        self._futures.clear()

    def pending_count(self) -> int:
        return len(self._futures)
