"""Pytest fixtures for Uatu tests."""

from datetime import datetime

import pytest

from uatu.events import EventBus
from uatu.watcher.base import BaseHandler, BaseWatcher
from uatu.watcher.models import AnomalyEvent, AnomalyType, Severity, SystemSnapshot


@pytest.fixture
def event_bus():
    """Create a fresh event bus for testing."""
    return EventBus()


@pytest.fixture
def sample_baseline():
    """Create a sample baseline snapshot for testing."""
    return SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=50.0,
        memory_percent=60.0,
        memory_used_mb=8000.0,
        memory_total_mb=16000.0,
        load_1min=2.0,
        load_5min=1.8,
        load_15min=1.5,
        process_count=150,
    )


@pytest.fixture
def sample_snapshot():
    """Create a sample system snapshot for testing."""
    return SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=75.0,
        memory_percent=80.0,
        memory_used_mb=12000.0,
        memory_total_mb=16000.0,
        load_1min=4.0,
        load_5min=3.5,
        load_15min=3.0,
        process_count=200,
    )


@pytest.fixture
def sample_cpu_spike_event():
    """Create a sample CPU spike anomaly event."""
    return AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.CPU_SPIKE,
        severity=Severity.WARNING,
        message="CPU spike: 85.0% (baseline: 50.0%)",
        details={"current_cpu": 85.0, "baseline_cpu": 50.0, "threshold": 75.0},
    )


@pytest.fixture
def sample_memory_spike_event():
    """Create a sample memory spike anomaly event."""
    return AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.MEMORY_SPIKE,
        severity=Severity.WARNING,
        message="Memory spike: 90.0% (baseline: 60.0%)",
        details={"current_memory": 90.0, "baseline_memory": 60.0},
    )


@pytest.fixture
def mock_watcher(event_bus):
    """Create a mock watcher for testing."""

    class MockWatcher(BaseWatcher):
        def __init__(self, event_bus: EventBus):
            self.event_bus = event_bus
            self.started = False
            self.stopped = False

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    return MockWatcher(event_bus)


@pytest.fixture
def mock_handler(event_bus):
    """Create a mock handler for testing."""

    class MockHandler(BaseHandler):
        def __init__(self, event_bus: EventBus):
            self.event_bus = event_bus
            self.events_received = []

        async def on_event(self, event: AnomalyEvent) -> None:
            self.events_received.append(event)

    return MockHandler(event_bus)


@pytest.fixture
def temp_log_file(tmp_path):
    """Create a temporary log file for testing."""
    return tmp_path / "test_events.jsonl"


@pytest.fixture
def mock_investigator():
    """Create a mock investigator for testing."""

    class MockInvestigator:
        async def investigate(self, event: AnomalyEvent, snapshot: SystemSnapshot):
            return {"analysis": f"Test analysis for {event.type.value}", "cached": False}

    return MockInvestigator()
