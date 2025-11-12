"""Tests for async watchers."""

import asyncio
from unittest.mock import patch

import pytest

from uatu.watcher.async_watchers import CPUWatcher, LoadWatcher, MemoryWatcher
from uatu.watcher.models import AnomalyType


@pytest.mark.asyncio
@patch("uatu.watcher.async_watchers.psutil.cpu_percent")
async def test_cpu_watcher_detects_spike(mock_cpu_percent, event_bus):
    """Test that CPUWatcher detects CPU spikes above threshold."""
    # Mock CPU returning high value
    mock_cpu_percent.return_value = 90.0

    # Create watcher with baseline
    watcher = CPUWatcher(event_bus, baseline=50.0, threshold_multiplier=1.5, interval=0.01)

    # Subscribe to events
    events_received = []

    async def event_handler(event):
        events_received.append(event)
        # Stop watcher after first event
        await watcher.stop()

    event_bus.subscribe("anomaly.cpu", event_handler)

    # Start watcher (will run once and stop)
    await asyncio.wait_for(watcher.start(), timeout=1.0)

    # Verify CPU spike detected
    assert len(events_received) == 1
    assert events_received[0].type == AnomalyType.CPU_SPIKE
    assert events_received[0].details["current_cpu"] == 90.0
    assert events_received[0].details["baseline_cpu"] == 50.0


@pytest.mark.asyncio
@patch("uatu.watcher.async_watchers.psutil.cpu_percent")
async def test_cpu_watcher_ignores_normal_cpu(mock_cpu_percent, event_bus):
    """Test that CPUWatcher doesn't alert on normal CPU."""
    # Mock CPU returning normal value
    mock_cpu_percent.return_value = 55.0

    # Create watcher
    watcher = CPUWatcher(event_bus, baseline=50.0, threshold_multiplier=1.5, interval=0.01)

    # Subscribe to events
    events_received = []

    async def event_handler(event):
        events_received.append(event)

    event_bus.subscribe("anomaly.cpu", event_handler)

    # Start watcher for short duration
    async def stop_after_delay():
        await asyncio.sleep(0.05)
        await watcher.stop()

    await asyncio.gather(watcher.start(), stop_after_delay())

    # No events should be generated
    assert len(events_received) == 0


@pytest.mark.asyncio
@patch("uatu.watcher.async_watchers.psutil.virtual_memory")
async def test_memory_watcher_detects_spike(mock_memory, event_bus):
    """Test that MemoryWatcher detects memory spikes."""

    # Mock memory object
    class MockMemory:
        percent = 85.0
        used = 14000 * 1024 * 1024
        total = 16000 * 1024 * 1024

    mock_memory.return_value = MockMemory()

    # Create watcher
    watcher = MemoryWatcher(event_bus, baseline=60.0, threshold_multiplier=1.2, interval=0.01)

    # Subscribe to events
    events_received = []

    async def event_handler(event):
        events_received.append(event)
        await watcher.stop()

    event_bus.subscribe("anomaly.memory", event_handler)

    # Start watcher
    await asyncio.wait_for(watcher.start(), timeout=1.0)

    # Verify memory spike detected
    assert len(events_received) == 1
    assert events_received[0].type == AnomalyType.MEMORY_SPIKE


@pytest.mark.asyncio
@patch("uatu.watcher.async_watchers.psutil.getloadavg")
async def test_load_watcher_detects_high_load(mock_loadavg, event_bus):
    """Test that LoadWatcher detects high system load."""
    # Mock high load
    mock_loadavg.return_value = (8.0, 7.0, 6.0)

    # Create watcher
    watcher = LoadWatcher(event_bus, baseline=2.0, threshold_multiplier=2.0, interval=0.01)

    # Subscribe to events
    events_received = []

    async def event_handler(event):
        events_received.append(event)
        await watcher.stop()

    event_bus.subscribe("anomaly.load", event_handler)

    # Start watcher
    await asyncio.wait_for(watcher.start(), timeout=1.0)

    # Verify high load detected
    assert len(events_received) == 1
    assert events_received[0].type == AnomalyType.HIGH_LOAD
    assert events_received[0].details["current_load"] == 8.0


@pytest.mark.asyncio
async def test_watcher_stop_method(event_bus):
    """Test that watcher stop() method works correctly."""
    watcher = CPUWatcher(event_bus, baseline=50.0, interval=0.01)

    # Start watcher in background
    watcher_task = asyncio.create_task(watcher.start())

    # Give it time to start
    await asyncio.sleep(0.02)

    # Stop watcher
    await watcher.stop()

    # Watcher task should complete within short time
    await asyncio.wait_for(watcher_task, timeout=0.5)

    # Verify watcher stopped
    assert not watcher._running
