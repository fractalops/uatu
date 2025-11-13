"""Async handlers for anomaly events."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import psutil
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from uatu.events import EventBus
from uatu.watcher.base import BaseHandler
from uatu.watcher.investigator import Investigator
from uatu.watcher.models import AnomalyEvent, Severity, SystemSnapshot

console = Console()
logger = logging.getLogger(__name__)


class InvestigationLogger(BaseHandler):
    """Log investigation reports to disk."""

    def __init__(self, log_file: Path | None = None):
        """Initialize investigation logger.

        Args:
            log_file: Path to investigation log file (default: ~/.uatu/investigations.jsonl)
        """
        self.log_file = log_file or Path.home() / ".uatu" / "investigations.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    async def on_event(self, event: AnomalyEvent) -> None:
        """Handle event (satisfies BaseHandler interface)."""
        pass  # Not used directly - called by InvestigationHandler

    async def log_investigation(self, event: AnomalyEvent, result: dict[str, str], snapshot: SystemSnapshot) -> None:
        """Log an investigation result.

        Args:
            event: Original anomaly event
            result: Investigation result from investigator
            snapshot: System snapshot at investigation time
        """
        try:
            await asyncio.to_thread(self._write_investigation, event, result, snapshot)
        except Exception as e:
            console.print(f"[red]Failed to log investigation: {e}[/red]")

    def _write_investigation(self, event: AnomalyEvent, result: dict[str, str], snapshot: SystemSnapshot) -> None:
        """Write investigation to log file (runs in thread)."""
        investigation_dict = {
            "timestamp": datetime.now().isoformat(),
            "event": {
                "type": event.type.value,
                "severity": event.severity.string_value,
                "message": event.message,
                "event_timestamp": event.timestamp.isoformat(),
                "details": event.details,
            },
            "system": {
                "cpu_percent": snapshot.cpu_percent,
                "memory_percent": snapshot.memory_percent,
                "memory_used_mb": snapshot.memory_used_mb,
                "load_1min": snapshot.load_1min,
                "process_count": snapshot.process_count,
            },
            "investigation": {
                "analysis": result["analysis"],
                "cached": result.get("cached", False),
                "cache_count": result.get("cache_count", 1),
            },
        }

        with open(self.log_file, "a") as f:
            f.write(json.dumps(investigation_dict) + "\n")


class EventLogger(BaseHandler):
    """Log all anomaly events to disk asynchronously."""

    def __init__(self, event_bus: EventBus, log_file: Path | None = None):
        """
        Initialize event logger.

        Args:
            event_bus: Event bus to subscribe to
            log_file: Path to log file (default: ~/.uatu/events.jsonl)
        """
        self.log_file = log_file or Path.home() / ".uatu" / "events.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Subscribe to all anomaly types
        event_bus.subscribe("anomaly.cpu", self.on_event)
        event_bus.subscribe("anomaly.memory", self.on_event)
        event_bus.subscribe("anomaly.process_crash", self.on_event)
        event_bus.subscribe("anomaly.process_restart", self.on_event)
        event_bus.subscribe("anomaly.load", self.on_event)

    async def on_event(self, event: AnomalyEvent) -> None:
        """
        Log event to disk.

        Args:
            event: Anomaly event to log
        """
        try:
            # Write to log file asynchronously
            await asyncio.to_thread(self._write_event, event)
        except Exception as e:
            console.print(f"[red]Failed to log event: {e}[/red]")

    def _write_event(self, event: AnomalyEvent) -> None:
        """Write event to log file (runs in thread)."""
        event_dict = {
            "timestamp": event.timestamp.isoformat(),
            "type": event.type.value,
            "severity": event.severity.string_value,
            "message": event.message,
            "details": event.details,
        }

        with open(self.log_file, "a") as f:
            f.write(json.dumps(event_dict) + "\n")


class ConsoleDisplayHandler(BaseHandler):
    """Display anomaly events to console."""

    def __init__(self, event_bus: EventBus):
        """
        Initialize console display handler.

        Args:
            event_bus: Event bus to subscribe to
        """
        # Subscribe to all anomaly types
        event_bus.subscribe("anomaly.cpu", self.on_event)
        event_bus.subscribe("anomaly.memory", self.on_event)
        event_bus.subscribe("anomaly.process_crash", self.on_event)
        event_bus.subscribe("anomaly.process_restart", self.on_event)
        event_bus.subscribe("anomaly.load", self.on_event)

    async def on_event(self, event: AnomalyEvent) -> None:
        """
        Display event to console.

        Args:
            event: Anomaly event to display
        """
        # Color based on severity
        color_map = {
            Severity.INFO: "blue",
            Severity.WARNING: "yellow",
            Severity.ERROR: "red",
            Severity.CRITICAL: "red bold",
        }
        color = color_map.get(event.severity, "white")

        # Format timestamp
        time_str = event.timestamp.strftime("%H:%M:%S")

        # Display event
        icon_map = {
            Severity.INFO: "[i]",
            Severity.WARNING: "[!]",
            Severity.ERROR: "[x]",
            Severity.CRITICAL: "[!!]",
        }
        icon = icon_map.get(event.severity, "*")

        console.print(f"[{color}][{time_str}] {icon}  {event.message}[/{color}]")


class InvestigationHandler(BaseHandler):
    """Handle anomaly events with async investigation."""

    def __init__(
        self,
        event_bus: EventBus,
        min_severity: Severity = Severity.WARNING,
        investigation_logger: InvestigationLogger | None = None,
        investigator: Investigator | None = None,
    ):
        """Initialize investigation handler.

        Args:
            event_bus: Event bus to subscribe to
            min_severity: Minimum severity to trigger investigation (default: WARNING)
            investigation_logger: Logger for investigations (creates new one if None)
            investigator: Investigator instance (creates new one if None)
        """
        self.event_bus = event_bus
        self.investigator = investigator or Investigator()
        self.investigation_queue: asyncio.Queue[AnomalyEvent] = asyncio.Queue()
        self.min_severity = min_severity
        self.investigation_logger = investigation_logger or InvestigationLogger()

        # Subscribe to anomalies that warrant investigation
        event_bus.subscribe("anomaly.cpu", self.on_anomaly)
        event_bus.subscribe("anomaly.memory", self.on_anomaly)
        event_bus.subscribe("anomaly.process_crash", self.on_anomaly)
        event_bus.subscribe("anomaly.load", self.on_anomaly)

    async def on_event(self, event: AnomalyEvent) -> None:
        """
        Handle event (satisfies BaseHandler interface).

        Args:
            event: Anomaly event to handle
        """
        await self.on_anomaly(event)

    async def on_anomaly(self, event: AnomalyEvent) -> None:
        """Queue anomaly for investigation (non-blocking).

        Args:
            event: Anomaly event to investigate
        """
        # Check if severity meets minimum threshold
        # IntEnum allows direct comparison: ERROR > WARNING
        if event.severity >= self.min_severity:
            await self.investigation_queue.put(event)

    async def start(self) -> None:
        """Process investigation queue concurrently."""
        while True:
            try:
                # Wait for next event to investigate
                event = await self.investigation_queue.get()

                # Investigate in background (doesn't block queue processing)
                asyncio.create_task(self._investigate_and_display(event))

            except Exception as e:
                console.print(f"[red]Investigation handler error: {e}[/red]")
                await asyncio.sleep(1)

    async def _investigate_and_display(self, event: AnomalyEvent) -> None:
        """Investigate and display/log results.

        Args:
            event: Anomaly event to investigate
        """
        try:
            console.print("\n🔬 [dim]Investigating...[/dim]")

            # Take system snapshot in thread
            snapshot = await asyncio.to_thread(self._take_snapshot)

            # Investigate (already async in investigator)
            result = await self.investigator.investigate(event, snapshot)

            # Log investigation
            await self.investigation_logger.log_investigation(event, result, snapshot)

            # Display investigation result
            self._display_investigation(event, result)

        except Exception as e:
            error_msg = f"Investigation failed: {e}"
            console.print(f"[red]{error_msg}[/red]")
            logger.error(error_msg, exc_info=True)

    def _take_snapshot(self) -> SystemSnapshot:
        """Take current system snapshot (runs in thread)."""
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        load = psutil.getloadavg()

        return SystemSnapshot(
            timestamp=datetime.now(),
            cpu_percent=cpu,
            memory_percent=memory.percent,
            memory_used_mb=memory.used / (1024 * 1024),
            memory_total_mb=memory.total / (1024 * 1024),
            load_1min=load[0],
            load_5min=load[1],
            load_15min=load[2],
            process_count=len(psutil.pids()),
        )

    def _display_investigation(self, event: AnomalyEvent, result: dict[str, str]) -> None:
        """
        Display investigation result in rich panel.

        Args:
            event: Original anomaly event
            result: Investigation result from investigator
        """
        # Color based on severity
        border_color = {
            Severity.INFO: "blue",
            Severity.WARNING: "yellow",
            Severity.ERROR: "red",
            Severity.CRITICAL: "red",
        }.get(event.severity, "white")

        # Add cache indicator
        cache_indicator = ""
        if result.get("cached"):
            count = result.get("cache_count", 1)
            cache_indicator = f" [dim](cached, seen {count}x)[/dim]"

        # Create panel with investigation
        panel = Panel(
            Markdown(result["analysis"]),
            title=f"Investigation Report{cache_indicator}",
            border_style=border_color,
        )

        console.print(panel)
        console.print()  # Extra newline for spacing


class RateLimiter(BaseHandler):
    """Rate limit events to prevent spam."""

    def __init__(self, event_bus: EventBus, max_events_per_minute: int = 10):
        """
        Initialize rate limiter.

        Args:
            event_bus: Event bus to subscribe to
            max_events_per_minute: Maximum events to allow per minute
        """
        self.max_events = max_events_per_minute
        self.event_times: list[datetime] = []

        # Subscribe to all events
        event_bus.subscribe("anomaly.cpu", self.on_event)
        event_bus.subscribe("anomaly.memory", self.on_event)
        event_bus.subscribe("anomaly.process_crash", self.on_event)
        event_bus.subscribe("anomaly.load", self.on_event)

    async def on_event(self, event: AnomalyEvent) -> None:
        """
        Track event rate.

        Args:
            event: Anomaly event
        """
        now = datetime.now()

        # Clean old events (older than 1 minute)
        cutoff = now.timestamp() - 60
        self.event_times = [t for t in self.event_times if t.timestamp() > cutoff]

        # Add current event
        self.event_times.append(now)

        # Check if rate limit exceeded
        if len(self.event_times) > self.max_events:
            console.print(f"[yellow][!] Rate limit: {len(self.event_times)} events in last minute[/yellow]")
