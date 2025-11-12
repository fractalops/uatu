"""Async watcher orchestrator."""

import asyncio
from pathlib import Path

import psutil
from rich.console import Console

from uatu.events import EventBus
from uatu.watcher.async_handlers import (
    ConsoleDisplayHandler,
    EventLogger,
    InvestigationHandler,
    RateLimiter,
)
from uatu.watcher.async_watchers import (
    CPUWatcher,
    LoadWatcher,
    MemoryWatcher,
    ProcessWatcher,
)
from uatu.watcher.base import BaseHandler, BaseWatcher
from uatu.watcher.models import SystemSnapshot

console = Console()


class AsyncWatcher:
    """Async watcher orchestrator with dependency injection."""

    def __init__(
        self,
        interval_seconds: int = 10,
        baseline_duration_minutes: int = 5,
        investigate: bool = False,
        log_file: Path | None = None,
        event_bus: EventBus | None = None,
        watchers: list[BaseWatcher] | None = None,
        handlers: list[BaseHandler] | None = None,
        baseline: SystemSnapshot | None = None,
    ):
        """
        Initialize async watcher with dependency injection.

        Args:
            interval_seconds: Not used in async mode (kept for compatibility)
            baseline_duration_minutes: Duration to learn baseline
            investigate: Whether to run LLM investigations
            log_file: Path to event log file
            event_bus: Event bus (injected for testing, created if None)
            watchers: List of watchers (injected for testing, created if None)
            handlers: List of handlers (injected for testing, created if None)
            baseline: Pre-calculated baseline (for testing, calculated if None)
        """
        self.baseline_duration = baseline_duration_minutes
        self.investigate_mode = investigate
        self._baseline = baseline

        # Event bus (allow injection)
        self.event_bus = event_bus or EventBus()

        # Watchers (allow injection for testing)
        if watchers is not None:
            self.watchers = watchers
        else:
            self.watchers = [
                CPUWatcher(self.event_bus, baseline=0.0),
                MemoryWatcher(self.event_bus, baseline=0.0),
                ProcessWatcher(self.event_bus),
                LoadWatcher(self.event_bus, baseline=0.0),
            ]

        # Handlers (allow injection for testing)
        if handlers is not None:
            self.handlers = handlers
        else:
            self.handlers = [
                EventLogger(self.event_bus, log_file),
                ConsoleDisplayHandler(self.event_bus),
                RateLimiter(self.event_bus, max_events_per_minute=20),
            ]

            if investigate:
                self.handlers.append(InvestigationHandler(self.event_bus))

        # Keep references to specific watchers for baseline updates
        self.cpu_watcher = next((w for w in self.watchers if isinstance(w, CPUWatcher)), None)
        self.memory_watcher = next((w for w in self.watchers if isinstance(w, MemoryWatcher)), None)
        self.load_watcher = next((w for w in self.watchers if isinstance(w, LoadWatcher)), None)

    async def establish_baseline(self) -> None:
        """Learn baseline system metrics asynchronously."""
        # If baseline already provided (for testing), skip
        if self._baseline is not None:
            console.print("[green][+] Using pre-calculated baseline[/green]")
            if self.cpu_watcher:
                self.cpu_watcher.baseline = self._baseline.cpu_percent
            if self.memory_watcher:
                self.memory_watcher.baseline = self._baseline.memory_percent
            if self.load_watcher:
                self.load_watcher.baseline = self._baseline.load_1min
            return

        console.print("\n[yellow][-] Establishing baseline...[/yellow]")

        samples: list[SystemSnapshot] = []
        duration = self.baseline_duration * 60
        sample_interval = 2.0
        num_samples = int(duration / sample_interval)

        for i in range(num_samples):
            # Take snapshot in thread to not block
            snapshot = await asyncio.to_thread(self._take_snapshot)
            samples.append(snapshot)

            # Show progress
            cpu = snapshot.cpu_percent
            mem = snapshot.memory_percent
            progress = f"[dim]Samples: {i + 1}/{num_samples} - CPU: {cpu:.1f}%, Memory: {mem:.1f}%[/dim]"
            console.print(progress, end="\r")

            await asyncio.sleep(sample_interval)

        # Calculate baselines
        avg_cpu = sum(s.cpu_percent for s in samples) / len(samples)
        avg_mem = sum(s.memory_percent for s in samples) / len(samples)
        avg_load = sum(s.load_1min for s in samples) / len(samples)

        # Update watcher baselines
        if self.cpu_watcher:
            self.cpu_watcher.baseline = avg_cpu
        if self.memory_watcher:
            self.memory_watcher.baseline = avg_mem
        if self.load_watcher:
            self.load_watcher.baseline = avg_load

        console.print(
            f"\n[green][+] Baseline established:[/green] CPU {avg_cpu:.1f}%, Memory {avg_mem:.1f}%, Load {avg_load:.2f}"
        )

    def _take_snapshot(self) -> SystemSnapshot:
        """Take system snapshot (runs in thread)."""
        from datetime import datetime

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

    async def start(self) -> None:
        """Start all async watchers and handlers."""
        try:
            # Establish baseline first
            await self.establish_baseline()

            # Display watcher info
            console.print()
            console.print("[bold blue][-] Uatu is watching...[/bold blue]")
            if self.investigate_mode:
                console.print("[dim][*] LLM investigations enabled[/dim]")
            console.print()

            # Start all watchers and handlers concurrently
            async with asyncio.TaskGroup() as tg:
                # Start all watchers
                for watcher in self.watchers:
                    tg.create_task(watcher.start())

                # Start handlers that need background tasks (like InvestigationHandler)
                for handler in self.handlers:
                    if hasattr(handler, "start") and callable(handler.start):
                        tg.create_task(handler.start())

        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping watchers...[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Fatal error in watchers: {e}[/red]")
