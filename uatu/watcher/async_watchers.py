"""Async watchers for different system signals."""

import asyncio
from datetime import datetime
from typing import Any

import psutil
from rich.console import Console

from uatu.events import EventBus
from uatu.watcher.base import BaseWatcher
from uatu.watcher.models import AnomalyEvent, AnomalyType, Severity

console = Console()


class CPUWatcher(BaseWatcher):
    """Watch for CPU anomalies asynchronously."""

    def __init__(
        self,
        event_bus: EventBus,
        baseline: float = 0.0,
        threshold_multiplier: float = 1.5,
        interval: float = 1.0,
    ):
        """
        Initialize CPU watcher.

        Args:
            event_bus: Event bus to publish anomalies to
            baseline: Baseline CPU percentage (learned during warmup)
            threshold_multiplier: Alert when CPU exceeds baseline * multiplier (default: 1.5)
            interval: Check interval in seconds (default: 1.0)
        """
        self.event_bus = event_bus
        self.baseline = baseline
        self.interval = interval
        self.threshold_multiplier = threshold_multiplier
        self._running = False

    async def start(self) -> None:
        """Start watching CPU."""
        self._running = True
        while self._running:
            try:
                # Non-blocking CPU check
                cpu = await asyncio.to_thread(psutil.cpu_percent, interval=0.1)

                # Detect anomaly
                if self.baseline > 0 and cpu > self.baseline * self.threshold_multiplier:
                    event = AnomalyEvent(
                        type=AnomalyType.CPU_SPIKE,
                        severity=Severity.WARNING,
                        message=f"CPU spike: {cpu:.1f}% (baseline: {self.baseline:.1f}%)",
                        timestamp=datetime.now(),
                        details={
                            "current_cpu": cpu,
                            "baseline_cpu": self.baseline,
                            "threshold": self.baseline * self.threshold_multiplier,
                        },
                    )

                    # Publish to event bus (non-blocking)
                    await self.event_bus.publish("anomaly.cpu", event)

                await asyncio.sleep(self.interval)

            except Exception as e:
                console.print(f"[red]CPU watcher error: {e}[/red]")
                await asyncio.sleep(5)  # Back off on error

    async def stop(self) -> None:
        """Stop watching CPU."""
        self._running = False


class MemoryWatcher(BaseWatcher):
    """Watch for memory anomalies asynchronously."""

    def __init__(
        self,
        event_bus: EventBus,
        baseline: float = 0.0,
        threshold_multiplier: float = 1.2,
        interval: float = 2.0,
    ):
        """
        Initialize memory watcher.

        Args:
            event_bus: Event bus to publish anomalies to
            baseline: Baseline memory percentage
            threshold_multiplier: Alert when memory exceeds baseline * multiplier (default: 1.2)
            interval: Check interval in seconds (default: 2.0)
        """
        self.event_bus = event_bus
        self.baseline = baseline
        self.interval = interval
        self.threshold_multiplier = threshold_multiplier
        self._running = False

    async def start(self) -> None:
        """Start watching memory."""
        self._running = True
        while self._running:
            try:
                # Non-blocking memory check
                memory = await asyncio.to_thread(psutil.virtual_memory)

                # Detect anomaly
                if self.baseline > 0 and memory.percent > self.baseline * self.threshold_multiplier:
                    event = AnomalyEvent(
                        type=AnomalyType.MEMORY_SPIKE,
                        severity=Severity.WARNING,
                        message=f"Memory spike: {memory.percent:.1f}% (baseline: {self.baseline:.1f}%)",
                        timestamp=datetime.now(),
                        details={
                            "current_memory": memory.percent,
                            "baseline_memory": self.baseline,
                            "memory_used_mb": memory.used / (1024 * 1024),
                            "memory_total_mb": memory.total / (1024 * 1024),
                        },
                    )

                    await self.event_bus.publish("anomaly.memory", event)

                await asyncio.sleep(self.interval)

            except Exception as e:
                console.print(f"[red]Memory watcher error: {e}[/red]")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop watching memory."""
        self._running = False


class ProcessWatcher(BaseWatcher):
    """Watch for process crashes and restarts."""

    def __init__(self, event_bus: EventBus, interval: float = 3.0):
        """
        Initialize process watcher.

        Args:
            event_bus: Event bus to publish anomalies to
            interval: Check interval in seconds (default: 3.0)
        """
        self.event_bus = event_bus
        self.interval = interval
        self.process_map: dict[int, dict[str, Any]] = {}
        self.recent_deaths: list[tuple[str, datetime]] = []  # Track recent deaths
        self._running = False

    async def start(self) -> None:
        """Start watching processes."""
        self._running = True
        # Initialize process map
        self.process_map = await asyncio.to_thread(self._get_processes)

        while self._running:
            try:
                # Get current processes (in thread to not block)
                current_procs = await asyncio.to_thread(self._get_processes)
                current_pids = set(current_procs.keys())
                previous_pids = set(self.process_map.keys())

                # Detect crashes (processes that died)
                died_pids = previous_pids - current_pids
                for pid in died_pids:
                    proc = self.process_map[pid]
                    self.recent_deaths.append((proc["name"], datetime.now()))

                    event = AnomalyEvent(
                        type=AnomalyType.PROCESS_CRASH,
                        severity=Severity.WARNING,
                        message=f"Process died: {proc['name']} (PID {pid})",
                        timestamp=datetime.now(),
                        details={
                            "pid": pid,
                            "name": proc["name"],
                            "cmdline": proc["cmdline"],
                        },
                    )

                    await self.event_bus.publish("anomaly.process_crash", event)

                # Detect restarts (new process with same name as recently died)
                new_pids = current_pids - previous_pids
                for pid in new_pids:
                    proc = current_procs[pid]

                    # Check if this process name died recently (within 10 seconds)
                    if self._is_likely_restart(proc["name"]):
                        event = AnomalyEvent(
                            type=AnomalyType.PROCESS_RESTART,
                            severity=Severity.INFO,
                            message=f"Process restarted: {proc['name']} (new PID {pid})",
                            timestamp=datetime.now(),
                            details={
                                "pid": pid,
                                "name": proc["name"],
                                "cmdline": proc["cmdline"],
                            },
                        )

                        await self.event_bus.publish("anomaly.process_restart", event)

                # Clean up old deaths (keep only last 60 seconds)
                cutoff = datetime.now().timestamp() - 60
                self.recent_deaths = [
                    (name, ts) for name, ts in self.recent_deaths if ts.timestamp() > cutoff
                ]

                # Update process map
                self.process_map = current_procs

                await asyncio.sleep(self.interval)

            except Exception as e:
                console.print(f"[red]Process watcher error: {e}[/red]")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop watching processes."""
        self._running = False

    def _get_processes(self) -> dict[int, dict[str, Any]]:
        """Get current process list."""
        processes = {}
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                info = proc.info
                processes[info["pid"]] = {
                    "name": info["name"],
                    "cmdline": " ".join(info["cmdline"] or []),
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return processes

    def _is_likely_restart(self, proc_name: str) -> bool:
        """Check if this process likely restarted."""
        # Look for recent death of same name within 10 seconds
        cutoff = datetime.now().timestamp() - 10
        for name, death_time in self.recent_deaths:
            if name == proc_name and death_time.timestamp() > cutoff:
                return True
        return False


class LoadWatcher(BaseWatcher):
    """Watch for high system load."""

    def __init__(
        self,
        event_bus: EventBus,
        baseline: float = 0.0,
        threshold_multiplier: float = 2.0,
        interval: float = 5.0,
    ):
        """
        Initialize load watcher.

        Args:
            event_bus: Event bus to publish anomalies to
            baseline: Baseline load average
            threshold_multiplier: Alert when load exceeds baseline * multiplier (default: 2.0)
            interval: Check interval in seconds (default: 5.0)
        """
        self.event_bus = event_bus
        self.baseline = baseline
        self.interval = interval
        self.threshold_multiplier = threshold_multiplier
        self._running = False

    async def start(self) -> None:
        """Start watching load average."""
        self._running = True
        while self._running:
            try:
                # Non-blocking load check
                load = await asyncio.to_thread(lambda: psutil.getloadavg()[0])

                # Detect anomaly
                if self.baseline > 0 and load > self.baseline * self.threshold_multiplier:
                    event = AnomalyEvent(
                        type=AnomalyType.HIGH_LOAD,
                        severity=Severity.WARNING,
                        message=f"High load: {load:.2f} (baseline: {self.baseline:.2f})",
                        timestamp=datetime.now(),
                        details={
                            "current_load": load,
                            "baseline_load": self.baseline,
                            "threshold": self.baseline * self.threshold_multiplier,
                        },
                    )

                    await self.event_bus.publish("anomaly.load", event)

                await asyncio.sleep(self.interval)

            except Exception as e:
                console.print(f"[red]Load watcher error: {e}[/red]")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop watching load average."""
        self._running = False
