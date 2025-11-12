"""Data models for the watcher system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AnomalyType(Enum):
    """Types of anomalies the watcher can detect."""

    CPU_SPIKE = "cpu_spike"
    MEMORY_SPIKE = "memory_spike"
    MEMORY_LEAK = "memory_leak"
    PROCESS_CRASH = "process_crash"
    PROCESS_RESTART = "process_restart"
    CRASH_LOOP = "crash_loop"
    NEW_PROCESS = "new_process"
    PROCESS_DIED = "process_died"
    PORT_CHANGE = "port_change"
    ZOMBIE_PROCESS = "zombie_process"
    HIGH_LOAD = "high_load"
    LOG_ERROR = "log_error"


class Severity(Enum):
    """Severity levels for anomalies."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ProcessInfo:
    """Lightweight process information for snapshots."""

    pid: int
    name: str
    user: str
    cpu_percent: float
    memory_mb: float
    state: str = ""


@dataclass
class SystemSnapshot:
    """Point-in-time snapshot of system state."""

    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    load_1min: float
    load_5min: float
    load_15min: float
    process_count: int
    top_cpu_processes: list[ProcessInfo] = field(default_factory=list)
    top_memory_processes: list[ProcessInfo] = field(default_factory=list)
    listening_ports: set[int] = field(default_factory=set)

    def __str__(self) -> str:
        """Human-readable summary."""
        return (
            f"SystemSnapshot({self.timestamp.strftime('%H:%M:%S')}: "
            f"CPU={self.cpu_percent:.1f}%, "
            f"Mem={self.memory_percent:.1f}%, "
            f"Procs={self.process_count})"
        )


@dataclass
class AnomalyEvent:
    """Detected anomaly event."""

    timestamp: datetime
    type: AnomalyType
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Human-readable event description."""
        severity_emoji = {
            Severity.INFO: "ℹ️",
            Severity.WARNING: "⚠️",
            Severity.CRITICAL: "🔴",
        }
        emoji = severity_emoji.get(self.severity, "")
        time_str = self.timestamp.strftime("%H:%M:%S")
        return f"[{time_str}] {emoji} {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "type": self.type.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class WatcherState:
    """State maintained by the watcher."""

    # Baseline learned after initial observation period
    baseline: SystemSnapshot | None = None

    # Current snapshot
    current: SystemSnapshot | None = None

    # Recent history (ring buffer)
    history: list[SystemSnapshot] = field(default_factory=list)
    max_history: int = 100

    # Detected events
    events: list[AnomalyEvent] = field(default_factory=list)

    # Process tracking for crash detection
    process_restart_counts: dict[str, int] = field(default_factory=dict)
    process_last_seen: dict[int, datetime] = field(default_factory=dict)

    def add_snapshot(self, snapshot: SystemSnapshot) -> None:
        """Add a snapshot to history."""
        self.current = snapshot
        self.history.append(snapshot)

        # Keep ring buffer size
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def add_event(self, event: AnomalyEvent) -> None:
        """Add an anomaly event."""
        self.events.append(event)

    def get_recent_history(self, minutes: int = 5) -> list[SystemSnapshot]:
        """Get snapshots from last N minutes."""
        if not self.history:
            return []

        cutoff = datetime.now()
        cutoff = cutoff.replace(minute=cutoff.minute - minutes if cutoff.minute >= minutes else 0)

        return [s for s in self.history if s.timestamp >= cutoff]
