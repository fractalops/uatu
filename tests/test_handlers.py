"""Tests for async event handlers."""

import json
from datetime import datetime

import pytest

from uatu.watcher.async_handlers import ConsoleDisplayHandler, EventLogger, RateLimiter
from uatu.watcher.models import AnomalyEvent, AnomalyType, Severity


@pytest.mark.asyncio
async def test_event_logger_writes_to_file(event_bus, temp_log_file, sample_cpu_spike_event):
    """Test that EventLogger writes events to log file."""
    # Create logger
    logger = EventLogger(event_bus, temp_log_file)

    # Manually call handler
    await logger.on_event(sample_cpu_spike_event)

    # Verify file was written
    assert temp_log_file.exists()

    # Read and verify content
    with open(temp_log_file) as f:
        lines = f.readlines()
        assert len(lines) == 1

        event_dict = json.loads(lines[0])
        assert event_dict["type"] == "cpu_spike"
        assert event_dict["severity"] == "warning"
        assert "CPU spike" in event_dict["message"]


@pytest.mark.asyncio
async def test_event_logger_multiple_events(
    event_bus, temp_log_file, sample_cpu_spike_event, sample_memory_spike_event
):
    """Test that EventLogger appends multiple events."""
    logger = EventLogger(event_bus, temp_log_file)

    # Log multiple events
    await logger.on_event(sample_cpu_spike_event)
    await logger.on_event(sample_memory_spike_event)

    # Verify both events logged
    with open(temp_log_file) as f:
        lines = f.readlines()
        assert len(lines) == 2

        event1 = json.loads(lines[0])
        event2 = json.loads(lines[1])

        assert event1["type"] == "cpu_spike"
        assert event2["type"] == "memory_spike"


@pytest.mark.asyncio
async def test_console_display_handler(event_bus, sample_cpu_spike_event):
    """Test that ConsoleDisplayHandler doesn't error on events."""
    handler = ConsoleDisplayHandler(event_bus)

    # Should not raise exception
    await handler.on_event(sample_cpu_spike_event)


@pytest.mark.asyncio
async def test_rate_limiter_tracks_events(event_bus):
    """Test that RateLimiter tracks event frequency."""
    rate_limiter = RateLimiter(event_bus, max_events_per_minute=5)

    # Send several events
    for i in range(7):
        event = AnomalyEvent(
            timestamp=datetime.now(),
            type=AnomalyType.CPU_SPIKE,
            severity=Severity.WARNING,
            message=f"Event {i}",
            details={},
        )
        await rate_limiter.on_event(event)

    # Verify rate limiter tracked events
    assert len(rate_limiter.event_times) == 7


@pytest.mark.asyncio
async def test_rate_limiter_cleans_old_events(event_bus):
    """Test that RateLimiter removes old events."""
    rate_limiter = RateLimiter(event_bus, max_events_per_minute=10)

    # Add old event
    old_time = datetime.now()
    old_time = old_time.replace(minute=old_time.minute - 2)
    rate_limiter.event_times.append(old_time)

    # Add new event
    new_event = AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.CPU_SPIKE,
        severity=Severity.WARNING,
        message="New event",
        details={},
    )
    await rate_limiter.on_event(new_event)

    # Old event should be removed, only new event remains
    assert len(rate_limiter.event_times) == 1
