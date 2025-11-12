"""Base interfaces for watchers and handlers."""

from abc import ABC, abstractmethod

from uatu.watcher.models import AnomalyEvent


class BaseWatcher(ABC):
    """Base interface for all async watchers."""

    @abstractmethod
    async def start(self) -> None:
        """Start watching for anomalies. This method should run continuously."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop watching and cleanup resources."""
        pass


class BaseHandler(ABC):
    """Base interface for all event handlers."""

    @abstractmethod
    async def on_event(self, event: AnomalyEvent) -> None:
        """Handle an anomaly event.

        Args:
            event: The anomaly event to handle
        """
        pass

    async def start(self) -> None:
        """Optional startup logic for the handler."""
        pass

    async def stop(self) -> None:
        """Optional cleanup logic for the handler."""
        pass
