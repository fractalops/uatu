"""Tests for anomaly detector."""

from datetime import datetime

import pytest

from uatu.watcher.detector import AnomalyDetector
from uatu.watcher.models import (
    AnomalyType,
    ProcessInfo,
    Severity,
    SystemSnapshot,
    WatcherState,
)


@pytest.fixture
def detector():
    """Create anomaly detector."""
    return AnomalyDetector()


@pytest.fixture
def baseline_snapshot():
    """Create baseline snapshot."""
    return SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=40.0,
        memory_percent=60.0,
        memory_used_mb=8000.0,
        memory_total_mb=16000.0,
        load_1min=2.0,
        load_5min=1.8,
        load_15min=1.5,
        process_count=150,
        top_cpu_processes=[
            ProcessInfo(pid=100, name="normal_proc", user="test", cpu_percent=5.0, memory_mb=100.0),
            # Include test processes at baseline levels
            ProcessInfo(pid=999, name="cpu_hog", user="test", cpu_percent=10.0, memory_mb=100.0),
            ProcessInfo(pid=888, name="critical_proc", user="test", cpu_percent=10.0, memory_mb=100.0),
        ],
        top_memory_processes=[
            ProcessInfo(pid=200, name="mem_proc", user="test", cpu_percent=2.0, memory_mb=500.0),
            ProcessInfo(pid=777, name="mem_hog", user="test", cpu_percent=5.0, memory_mb=800.0),
        ],
    )


@pytest.fixture
def state_with_baseline(baseline_snapshot):
    """Create watcher state with baseline and current snapshot."""
    state = WatcherState()
    state.baseline = baseline_snapshot
    # Set current to baseline so we have a reference point
    state.current = baseline_snapshot
    # Add baseline to history so process tracking works
    state.add_snapshot(baseline_snapshot)
    return state


def test_cpu_spike_detected(detector, state_with_baseline):
    """Test CPU spike detection includes process info."""
    # Create snapshot with CPU spike (40% -> 70% = 1.75x baseline)
    spike_snapshot = SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=70.0,
        memory_percent=60.0,
        memory_used_mb=8000.0,
        memory_total_mb=16000.0,
        load_1min=3.0,
        load_5min=2.5,
        load_15min=2.0,
        process_count=150,
        top_cpu_processes=[ProcessInfo(pid=999, name="cpu_hog", user="test", cpu_percent=50.0, memory_mb=100.0)],
        top_memory_processes=[],
    )

    anomalies = detector.detect_anomalies(state_with_baseline, spike_snapshot)

    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly.type == AnomalyType.CPU_SPIKE
    assert anomaly.severity == Severity.WARNING
    # Check that message includes process name and PID
    assert "cpu_hog" in anomaly.message
    assert "999" in anomaly.message
    assert "70.0%" in anomaly.message
    # Check details contain process info
    assert anomaly.details["top_process"]["pid"] == 999
    assert anomaly.details["top_process"]["name"] == "cpu_hog"


def test_cpu_critical_threshold(detector, state_with_baseline):
    """Test critical CPU threshold (>=90%)."""
    critical_snapshot = SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=92.0,
        memory_percent=60.0,
        memory_used_mb=8000.0,
        memory_total_mb=16000.0,
        load_1min=5.0,
        load_5min=4.5,
        load_15min=4.0,
        process_count=150,
        top_cpu_processes=[ProcessInfo(pid=888, name="critical_proc", user="test", cpu_percent=80.0, memory_mb=100.0)],
        top_memory_processes=[],
    )

    anomalies = detector.detect_anomalies(state_with_baseline, critical_snapshot)

    assert len(anomalies) == 1
    assert anomalies[0].severity == Severity.CRITICAL
    assert "critical" in anomalies[0].message.lower()


def test_memory_spike_detected(detector, state_with_baseline):
    """Test memory spike detection includes process info."""
    # Memory spike: 60% -> 85% = 1.42x baseline (threshold is 1.3x)
    spike_snapshot = SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=40.0,
        memory_percent=85.0,
        memory_used_mb=12000.0,
        memory_total_mb=16000.0,
        load_1min=2.0,
        load_5min=1.8,
        load_15min=1.5,
        process_count=150,
        top_cpu_processes=[],
        top_memory_processes=[ProcessInfo(pid=777, name="mem_hog", user="test", cpu_percent=5.0, memory_mb=3000.0)],
    )

    anomalies = detector.detect_anomalies(state_with_baseline, spike_snapshot)

    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly.type == AnomalyType.MEMORY_SPIKE
    # Check message includes process info
    assert "mem_hog" in anomaly.message
    assert "777" in anomaly.message


def test_memory_leak_detection(detector, baseline_snapshot):
    """Test memory leak detection with growing memory."""
    state = WatcherState()
    state.baseline = baseline_snapshot

    # Create 6 snapshots with increasing memory
    for i in range(6):
        snapshot = SystemSnapshot(
            timestamp=datetime.now(),
            cpu_percent=40.0,
            memory_percent=60.0 + i * 2,  # Growing memory
            memory_used_mb=8000.0 + i * 500,  # +500MB per sample
            memory_total_mb=16000.0,
            load_1min=2.0,
            load_5min=1.8,
            load_15min=1.5,
            process_count=150,
            top_cpu_processes=[],
            top_memory_processes=[
                ProcessInfo(pid=666, name="leaky_app", user="test", cpu_percent=5.0, memory_mb=1000.0 + i * 400)
            ],
        )
        state.add_snapshot(snapshot)

    # Detect on the last snapshot
    anomalies = detector.detect_anomalies(state, state.history[-1])

    # Should detect memory leak
    leak_anomalies = [a for a in anomalies if a.type == AnomalyType.MEMORY_LEAK]
    assert len(leak_anomalies) > 0
    anomaly = leak_anomalies[0]
    # Check process info in message
    assert "leaky_app" in anomaly.message
    assert "666" in anomaly.message
    assert "MB/min" in anomaly.message


def test_no_anomaly_when_within_threshold(detector, state_with_baseline):
    """Test no anomaly when metrics are within thresholds."""
    # Small increase, within 50% threshold
    normal_snapshot = SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=45.0,  # 40% -> 45% = only 1.125x
        memory_percent=65.0,  # 60% -> 65% = only 1.08x
        memory_used_mb=8500.0,
        memory_total_mb=16000.0,
        load_1min=2.2,
        load_5min=2.0,
        load_15min=1.8,
        process_count=155,
        top_cpu_processes=[],
        top_memory_processes=[],
    )

    anomalies = detector.detect_anomalies(state_with_baseline, normal_snapshot)

    assert len(anomalies) == 0


def test_no_detection_without_baseline(detector):
    """Test that no anomalies are detected without a baseline."""
    state = WatcherState()  # No baseline set
    snapshot = SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=99.0,  # Would trigger if baseline existed
        memory_percent=99.0,
        memory_used_mb=15000.0,
        memory_total_mb=16000.0,
        load_1min=10.0,
        load_5min=9.0,
        load_15min=8.0,
        process_count=500,
        top_cpu_processes=[],
        top_memory_processes=[],
    )

    anomalies = detector.detect_anomalies(state, snapshot)

    assert len(anomalies) == 0


def test_zombie_process_detection(detector, state_with_baseline):
    """Test zombie process detection."""
    zombie_snapshot = SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=40.0,
        memory_percent=60.0,
        memory_used_mb=8000.0,
        memory_total_mb=16000.0,
        load_1min=2.0,
        load_5min=1.8,
        load_15min=1.5,
        process_count=150,
        top_cpu_processes=[ProcessInfo(pid=555, name="zombie", user="test", cpu_percent=0.0, memory_mb=0.0, state="Z")],
        top_memory_processes=[],
    )

    anomalies = detector.detect_anomalies(state_with_baseline, zombie_snapshot)

    zombie_anomalies = [a for a in anomalies if a.type == AnomalyType.ZOMBIE_PROCESS]
    assert len(zombie_anomalies) == 1
    assert "zombie" in zombie_anomalies[0].message
    assert "555" in zombie_anomalies[0].message


def test_new_high_resource_process(detector, state_with_baseline):
    """Test detection of new high-resource processes."""
    # Snapshot with a new process using >20% CPU
    new_proc_snapshot = SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=40.0,
        memory_percent=60.0,
        memory_used_mb=8000.0,
        memory_total_mb=16000.0,
        load_1min=2.0,
        load_5min=1.8,
        load_15min=1.5,
        process_count=151,
        top_cpu_processes=[ProcessInfo(pid=9999, name="new_proc", user="test", cpu_percent=25.0, memory_mb=100.0)],
        top_memory_processes=[],
    )

    anomalies = detector.detect_anomalies(state_with_baseline, new_proc_snapshot)

    new_proc_anomalies = [a for a in anomalies if a.type == AnomalyType.NEW_PROCESS]
    assert len(new_proc_anomalies) == 1
    assert "new_proc" in new_proc_anomalies[0].message
    assert "9999" in new_proc_anomalies[0].message
