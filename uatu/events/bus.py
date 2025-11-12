"""Event bus for async publish/subscribe pattern."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any


class EventBus:
    """Central event bus for async communication between watchers and handlers."""

    def __init__(self):
        """Initialize event bus."""
        self.subscribers: dict[str, list[Callable[[Any], Awaitable[None]]]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable[[Any], Awaitable[None]]) -> None:
        """
        Subscribe to an event type.

        Args:
            event_type: Type of event to subscribe to (e.g., "anomaly.cpu")
            handler: Async function to call when event is published
        """
        self.subscribers[event_type].append(handler)

    async def publish(self, event_type: str, event: Any) -> None:
        """
        Publish an event to all subscribers.

        Args:
            event_type: Type of event being published
            event: The event object
        """
        if event_type in self.subscribers:
            # Fan out to all subscribers concurrently
            tasks = [handler(event) for handler in self.subscribers[event_type]]
            await asyncio.gather(*tasks, return_exceptions=True)

    def unsubscribe(self, event_type: str, handler: Callable[[Any], Awaitable[None]]) -> None:
        """
        Unsubscribe from an event type.

        Args:
            event_type: Type of event to unsubscribe from
            handler: Handler function to remove
        """
        if event_type in self.subscribers:
            self.subscribers[event_type].remove(handler)
