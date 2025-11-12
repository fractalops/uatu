"""Core watcher implementation."""

import asyncio
import json
import signal
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from uatu.capabilities import ToolCapabilities
from uatu.tools import create_tool_registry
from uatu.watcher.detector import AnomalyDetector
from uatu.watcher.investigator import Investigator
from uatu.watcher.models import (
    AnomalyEvent,
    ProcessInfo,
    Severity,
    SystemSnapshot,
    WatcherState,
)


class Watcher:
    """Continuous system observer and anomaly detector."""

    def __init__(
        self,
        interval_seconds: int = 10,
        baseline_duration_minutes: int = 5,
        log_file: Path | None = None,
        investigate: bool = False,
    ):
        """
        Initialize the watcher.

        Args:
            interval_seconds: How often to take snapshots
            baseline_duration_minutes: How long to observe before establishing baseline
            log_file: Where to write event logs (JSON lines)
            investigate: Whether to use LLM to investigate anomalies
        """
        self.interval = interval_seconds
        self.baseline_duration = baseline_duration_minutes
        self.log_file = log_file or Path.home() / ".uatu" / "events.jsonl"
        self.investigate_mode = investigate

        # Ensure log directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.capabilities = ToolCapabilities.detect()
        self.registry = create_tool_registry(self.capabilities)
        self.detector = AnomalyDetector()
        self.state = WatcherState()
        self.console = Console()

        # Investigator (Phase 2)
        self.investigator = Investigator() if investigate else None

        # Control flags
        self.running = False
        self.baseline_established = False

    async def start(self) -> None:
        """Start watching the system."""
        self.running = True

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        mode = "Investigation Mode" if self.investigate_mode else "Detection Mode"
        self.console.print(f"[bold blue][-] Uatu is watching... ({mode})[/bold blue]")
        self.console.print(f"Interval: {self.interval}s | Baseline: {self.baseline_duration}min | Log: {self.log_file}")
        if self.investigate_mode:
            self.console.print("[yellow][*] LLM investigations enabled[/yellow]")
        self.console.print()

        # Establish baseline
        await self._establish_baseline()

        # Start observation loop
        await self._observation_loop()

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        self.console.print("\n[yellow]Shutting down watcher...[/yellow]")
        self.running = False

    async def _establish_baseline(self) -> None:
        """Observe system for a period to establish baseline."""
        self.console.print("[cyan]Establishing baseline...[/cyan]")

        baseline_samples: list[SystemSnapshot] = []
        samples_needed = (self.baseline_duration * 60) // self.interval

        with Live(self._get_baseline_table(0, samples_needed), console=self.console) as live:
            for i in range(samples_needed):
                if not self.running:
                    break

                snapshot = await self._take_snapshot()
                self.state.add_snapshot(snapshot)
                baseline_samples.append(snapshot)

                live.update(self._get_baseline_table(i + 1, samples_needed))

                await asyncio.sleep(self.interval)

        # Calculate baseline from samples
        if baseline_samples:
            self.state.baseline = self._calculate_baseline(baseline_samples)
            self.baseline_established = True
            self.console.print(
                f"[green][+] Baseline established: "
                f"CPU ~{self.state.baseline.cpu_percent:.1f}%, "
                f"Memory ~{self.state.baseline.memory_percent:.1f}%[/green]"
            )
            self.console.print()

    def _get_baseline_table(self, current: int, total: int) -> Table:
        """Create table showing baseline progress."""
        table = Table(title="Baseline Learning")
        table.add_column("Progress", style="cyan")
        table.add_column("Samples", style="green")

        progress_pct = (current / total * 100) if total > 0 else 0
        bar_width = 20
        filled = int(bar_width * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)

        table.add_row(
            f"{bar} {progress_pct:.0f}%",
            f"{current}/{total}",
        )

        return table

    async def _observation_loop(self) -> None:
        """Main observation loop."""
        self.console.print("[bold green]👁️  Watching for anomalies...[/bold green]")
        self.console.print()

        while self.running:
            # Take snapshot
            snapshot = await self._take_snapshot()
            self.state.add_snapshot(snapshot)

            # Detect anomalies
            anomalies = self.detector.detect_anomalies(self.state, snapshot)

            # Log and display anomalies
            for anomaly in anomalies:
                self._log_event(anomaly)
                self._display_event(anomaly)

                # Phase 2: Investigate if enabled
                if self.investigate_mode and self.investigator:
                    await self._investigate_anomaly(anomaly, snapshot)

            # Wait for next interval
            await asyncio.sleep(self.interval)

    async def _take_snapshot(self) -> SystemSnapshot:
        """Take a snapshot of current system state."""
        # Get system info
        system_info = self.registry.execute_tool("get_system_info")

        # Get process list
        all_processes = self.registry.execute_tool("list_processes")

        # Sort by CPU and memory
        by_cpu = sorted(all_processes, key=lambda p: p.get("cpu_percent", 0), reverse=True)
        by_memory = sorted(all_processes, key=lambda p: p.get("memory_mb", 0), reverse=True)

        # Create ProcessInfo objects for top processes
        top_cpu = [
            ProcessInfo(
                pid=p["pid"],
                name=p.get("name", "?"),
                user=p.get("user", "?"),
                cpu_percent=p.get("cpu_percent", 0.0),
                memory_mb=p.get("memory_mb", 0.0),
                state=p.get("state", ""),
            )
            for p in by_cpu[:10]
        ]

        top_memory = [
            ProcessInfo(
                pid=p["pid"],
                name=p.get("name", "?"),
                user=p.get("user", "?"),
                cpu_percent=p.get("cpu_percent", 0.0),
                memory_mb=p.get("memory_mb", 0.0),
                state=p.get("state", ""),
            )
            for p in by_memory[:10]
        ]

        # Create snapshot
        memory = system_info["memory"]
        load = system_info["load"]

        # Get actual CPU utilization using psutil
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.1)  # Quick sample

        snapshot = SystemSnapshot(
            timestamp=datetime.now(),
            cpu_percent=cpu_percent,
            memory_percent=memory["percent"],
            memory_used_mb=memory["used_mb"],
            memory_total_mb=memory["total_mb"],
            load_1min=load["1min"],
            load_5min=load["5min"],
            load_15min=load["15min"],
            process_count=len(all_processes),
            top_cpu_processes=top_cpu,
            top_memory_processes=top_memory,
        )

        return snapshot

    def _calculate_baseline(self, samples: list[SystemSnapshot]) -> SystemSnapshot:
        """Calculate average baseline from samples."""
        if not samples:
            raise ValueError("No samples to calculate baseline")

        avg_cpu = sum(s.cpu_percent for s in samples) / len(samples)
        avg_memory_pct = sum(s.memory_percent for s in samples) / len(samples)
        avg_memory_mb = sum(s.memory_used_mb for s in samples) / len(samples)
        avg_load_1min = sum(s.load_1min for s in samples) / len(samples)
        avg_load_5min = sum(s.load_5min for s in samples) / len(samples)
        avg_load_15min = sum(s.load_15min for s in samples) / len(samples)
        avg_process_count = int(sum(s.process_count for s in samples) / len(samples))

        # Use last sample for structure, replace with averages
        last = samples[-1]

        return SystemSnapshot(
            timestamp=last.timestamp,
            cpu_percent=avg_cpu,
            memory_percent=avg_memory_pct,
            memory_used_mb=avg_memory_mb,
            memory_total_mb=last.memory_total_mb,
            load_1min=avg_load_1min,
            load_5min=avg_load_5min,
            load_15min=avg_load_15min,
            process_count=avg_process_count,
            top_cpu_processes=[],
            top_memory_processes=[],
        )

    def _log_event(self, event: AnomalyEvent) -> None:
        """Log event to JSON lines file."""
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as e:
            self.console.print(f"[red]Failed to log event: {e}[/red]")

    def _display_event(self, event: AnomalyEvent) -> None:
        """Display event to console."""
        # Color by severity
        color = {
            Severity.INFO: "blue",
            Severity.WARNING: "yellow",
            Severity.CRITICAL: "red",
        }.get(event.severity, "white")

        self.console.print(f"[{color}]{event}[/{color}]")

    async def _investigate_anomaly(self, event: AnomalyEvent, snapshot: SystemSnapshot) -> None:
        """Investigate an anomaly using LLM."""
        self.console.print()
        self.console.print("[cyan]🔬 Investigating...[/cyan]")

        try:
            result = await self.investigator.investigate(event, snapshot)

            # Show investigation result
            cache_indicator = " [dim](from cache)[/dim]" if result["cached"] else ""
            title = f"Investigation Report{cache_indicator}"

            panel = Panel(
                Markdown(result["analysis"]),
                title=title,
                border_style="cyan",
                padding=(1, 2),
            )

            self.console.print(panel)
            self.console.print()

        except Exception as e:
            self.console.print(f"[red]Investigation failed: {e}[/red]")
            self.console.print()

    def get_status(self) -> dict[str, Any]:
        """Get current watcher status."""
        return {
            "running": self.running,
            "baseline_established": self.baseline_established,
            "snapshots_collected": len(self.state.history),
            "events_detected": len(self.state.events),
            "current_state": str(self.state.current) if self.state.current else "None",
        }
