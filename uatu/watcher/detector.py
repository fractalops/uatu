"""Anomaly detection heuristics (no LLM needed)."""

from uatu.watcher.models import (
    AnomalyEvent,
    AnomalyType,
    Severity,
    SystemSnapshot,
    WatcherState,
)


class AnomalyDetector:
    """Detects anomalies using simple heuristics."""

    def __init__(self) -> None:
        """Initialize detector."""
        # Configurable thresholds
        self.cpu_spike_threshold = 1.5  # 50% above baseline
        self.memory_spike_threshold = 1.3  # 30% above baseline
        self.cpu_critical = 90.0  # Absolute threshold
        self.memory_critical = 95.0  # Absolute threshold
        self.process_restart_threshold = 3  # 3 restarts = crash loop
        self.restart_window_minutes = 5  # Within 5 minutes

    def detect_anomalies(self, state: WatcherState, snapshot: SystemSnapshot) -> list[AnomalyEvent]:
        """
        Detect anomalies in current snapshot.

        Args:
            state: Current watcher state
            snapshot: New snapshot to analyze

        Returns:
            List of detected anomaly events
        """
        anomalies: list[AnomalyEvent] = []

        # Only start detecting after we have a baseline
        if state.baseline is None:
            return anomalies

        # CPU anomalies
        anomalies.extend(self._detect_cpu_anomalies(state, snapshot))

        # Memory anomalies
        anomalies.extend(self._detect_memory_anomalies(state, snapshot))

        # Process anomalies
        anomalies.extend(self._detect_process_anomalies(state, snapshot))

        return anomalies

    def _detect_cpu_anomalies(self, state: WatcherState, snapshot: SystemSnapshot) -> list[AnomalyEvent]:
        """Detect CPU-related anomalies."""
        anomalies = []

        baseline = state.baseline
        if baseline is None:
            return anomalies

        # Critical CPU usage
        if snapshot.cpu_percent >= self.cpu_critical:
            anomalies.append(
                AnomalyEvent(
                    timestamp=snapshot.timestamp,
                    type=AnomalyType.CPU_SPIKE,
                    severity=Severity.CRITICAL,
                    message=f"CPU usage critical: {snapshot.cpu_percent:.1f}%",
                    details={
                        "current": snapshot.cpu_percent,
                        "top_processes": [
                            {
                                "pid": p.pid,
                                "name": p.name,
                                "cpu": p.cpu_percent,
                            }
                            for p in snapshot.top_cpu_processes[:3]
                        ],
                    },
                )
            )

        # CPU spike above baseline
        elif snapshot.cpu_percent > baseline.cpu_percent * self.cpu_spike_threshold:
            # Get top CPU culprit
            top_proc = snapshot.top_cpu_processes[0] if snapshot.top_cpu_processes else None
            culprit_info = f" - {top_proc.name} (PID {top_proc.pid})" if top_proc else ""

            message = f"CPU spike: {snapshot.cpu_percent:.1f}% (baseline: {baseline.cpu_percent:.1f}%){culprit_info}"
            anomalies.append(
                AnomalyEvent(
                    timestamp=snapshot.timestamp,
                    type=AnomalyType.CPU_SPIKE,
                    severity=Severity.WARNING,
                    message=message,
                    details={
                        "current": snapshot.cpu_percent,
                        "baseline": baseline.cpu_percent,
                        "increase": snapshot.cpu_percent - baseline.cpu_percent,
                        "top_process": {
                            "pid": top_proc.pid,
                            "name": top_proc.name,
                            "cpu": top_proc.cpu_percent,
                        }
                        if top_proc
                        else None,
                    },
                )
            )

        return anomalies

    def _detect_memory_anomalies(self, state: WatcherState, snapshot: SystemSnapshot) -> list[AnomalyEvent]:
        """Detect memory-related anomalies."""
        anomalies = []

        baseline = state.baseline
        if baseline is None:
            return anomalies

        # Critical memory usage
        if snapshot.memory_percent >= self.memory_critical:
            anomalies.append(
                AnomalyEvent(
                    timestamp=snapshot.timestamp,
                    type=AnomalyType.MEMORY_SPIKE,
                    severity=Severity.CRITICAL,
                    message=f"Memory usage critical: {snapshot.memory_percent:.1f}%",
                    details={
                        "current_percent": snapshot.memory_percent,
                        "used_mb": snapshot.memory_used_mb,
                        "total_mb": snapshot.memory_total_mb,
                    },
                )
            )

        # Memory spike above baseline
        elif snapshot.memory_percent > baseline.memory_percent * self.memory_spike_threshold:
            # Get top memory culprit
            top_mem = snapshot.top_memory_processes[0] if snapshot.top_memory_processes else None
            culprit_info = f" - {top_mem.name} (PID {top_mem.pid})" if top_mem else ""

            anomalies.append(
                AnomalyEvent(
                    timestamp=snapshot.timestamp,
                    type=AnomalyType.MEMORY_SPIKE,
                    severity=Severity.WARNING,
                    message=(
                        f"Memory spike: {snapshot.memory_percent:.1f}% "
                        f"(baseline: {baseline.memory_percent:.1f}%){culprit_info}"
                    ),
                    details={
                        "current": snapshot.memory_percent,
                        "baseline": baseline.memory_percent,
                        "increase_mb": snapshot.memory_used_mb - baseline.memory_used_mb,
                        "top_process": {
                            "pid": top_mem.pid,
                            "name": top_mem.name,
                            "memory_mb": top_mem.memory_mb,
                        }
                        if top_mem
                        else None,
                    },
                )
            )

        # Memory leak detection (gradual increase)
        if len(state.history) >= 6:  # Need at least 6 samples (1 minute if 10s interval)
            recent = state.history[-6:]
            if self._is_memory_increasing(recent):
                rate_mb_per_min = self._calculate_memory_growth_rate(recent)

                # Get top memory culprit
                top_mem = snapshot.top_memory_processes[0] if snapshot.top_memory_processes else None
                culprit_info = f" - {top_mem.name} (PID {top_mem.pid})" if top_mem else ""

                anomalies.append(
                    AnomalyEvent(
                        timestamp=snapshot.timestamp,
                        type=AnomalyType.MEMORY_LEAK,
                        severity=Severity.WARNING,
                        message=f"Memory leak: growing at {rate_mb_per_min:.1f} MB/min{culprit_info}",
                        details={
                            "growth_rate_mb_per_min": rate_mb_per_min,
                            "current_mb": snapshot.memory_used_mb,
                            "top_process": {
                                "pid": top_mem.pid,
                                "name": top_mem.name,
                                "memory_mb": top_mem.memory_mb,
                            }
                            if top_mem
                            else None,
                        },
                    )
                )

        return anomalies

    def _detect_process_anomalies(self, state: WatcherState, snapshot: SystemSnapshot) -> list[AnomalyEvent]:
        """Detect process-related anomalies."""
        anomalies = []

        if state.current is None:
            return anomalies

        # Compare process lists
        current_pids = {p.pid for p in snapshot.top_cpu_processes + snapshot.top_memory_processes}
        previous_pids = {p.pid for p in state.current.top_cpu_processes + state.current.top_memory_processes}

        # Detect new high-resource processes
        new_pids = current_pids - previous_pids
        for pid in new_pids:
            # Find the process info
            proc = next(
                (p for p in snapshot.top_cpu_processes + snapshot.top_memory_processes if p.pid == pid),
                None,
            )
            if proc and (proc.cpu_percent > 20 or proc.memory_mb > 500):
                anomalies.append(
                    AnomalyEvent(
                        timestamp=snapshot.timestamp,
                        type=AnomalyType.NEW_PROCESS,
                        severity=Severity.INFO,
                        message=f"New high-resource process detected: {proc.name} (PID {proc.pid})",
                        details={
                            "pid": proc.pid,
                            "name": proc.name,
                            "cpu_percent": proc.cpu_percent,
                            "memory_mb": proc.memory_mb,
                        },
                    )
                )

        # Detect zombie processes
        for proc in snapshot.top_cpu_processes + snapshot.top_memory_processes:
            if "Z" in proc.state.upper() or "zombie" in proc.state.lower():
                anomalies.append(
                    AnomalyEvent(
                        timestamp=snapshot.timestamp,
                        type=AnomalyType.ZOMBIE_PROCESS,
                        severity=Severity.WARNING,
                        message=f"Zombie process detected: {proc.name} (PID {proc.pid})",
                        details={"pid": proc.pid, "name": proc.name},
                    )
                )

        return anomalies

    def _is_memory_increasing(self, snapshots: list[SystemSnapshot]) -> bool:
        """Check if memory is consistently increasing."""
        if len(snapshots) < 3:
            return False

        # Check if each snapshot has more memory than previous
        increases = 0
        for i in range(1, len(snapshots)):
            if snapshots[i].memory_used_mb > snapshots[i - 1].memory_used_mb:
                increases += 1

        # At least 80% of samples show increase
        return increases >= len(snapshots) * 0.8

    def _calculate_memory_growth_rate(self, snapshots: list[SystemSnapshot]) -> float:
        """Calculate memory growth rate in MB per minute."""
        if len(snapshots) < 2:
            return 0.0

        first = snapshots[0]
        last = snapshots[-1]

        memory_delta = last.memory_used_mb - first.memory_used_mb
        time_delta = (last.timestamp - first.timestamp).total_seconds() / 60.0

        if time_delta == 0:
            return 0.0

        return memory_delta / time_delta
