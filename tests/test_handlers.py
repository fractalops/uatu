"""Tests for async event handlers."""

import json
from datetime import datetime

import pytest

from uatu.watcher.async_handlers import ConsoleDisplayHandler, EventLogger, InvestigationHandler, RateLimiter
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

    # Add old event (2 minutes ago)
    from datetime import timedelta

    old_time = datetime.now() - timedelta(minutes=2)
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


@pytest.mark.asyncio
async def test_investigation_handler_severity_filtering_warning(event_bus):
    """Test that InvestigationHandler only queues events >= WARNING severity."""
    handler = InvestigationHandler(
        event_bus=event_bus,
        min_severity=Severity.WARNING,
    )

    # Create events with different severities
    info_event = AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.CPU_SPIKE,
        severity=Severity.INFO,
        message="Info event",
        details={},
    )
    warning_event = AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.CPU_SPIKE,
        severity=Severity.WARNING,
        message="Warning event",
        details={},
    )
    error_event = AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.CPU_SPIKE,
        severity=Severity.ERROR,
        message="Error event",
        details={},
    )

    # Queue events
    await handler.on_anomaly(info_event)
    await handler.on_anomaly(warning_event)
    await handler.on_anomaly(error_event)

    # Check queue - INFO should be filtered out
    assert handler.investigation_queue.qsize() == 2

    # Verify correct events are queued
    queued_event1 = await handler.investigation_queue.get()
    queued_event2 = await handler.investigation_queue.get()

    assert queued_event1.severity == Severity.WARNING
    assert queued_event2.severity == Severity.ERROR


@pytest.mark.asyncio
async def test_investigation_handler_severity_filtering_error(event_bus):
    """Test filtering with ERROR minimum severity."""
    handler = InvestigationHandler(
        event_bus=event_bus,
        min_severity=Severity.ERROR,
    )

    # Create events
    warning_event = AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.CPU_SPIKE,
        severity=Severity.WARNING,
        message="Warning event",
        details={},
    )
    error_event = AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.MEMORY_SPIKE,
        severity=Severity.ERROR,
        message="Error event",
        details={},
    )
    critical_event = AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.CRASH_LOOP,
        severity=Severity.CRITICAL,
        message="Critical event",
        details={},
    )

    # Queue events
    await handler.on_anomaly(warning_event)
    await handler.on_anomaly(error_event)
    await handler.on_anomaly(critical_event)

    # WARNING should be filtered out
    assert handler.investigation_queue.qsize() == 2

    queued_event1 = await handler.investigation_queue.get()
    queued_event2 = await handler.investigation_queue.get()

    assert queued_event1.severity == Severity.ERROR
    assert queued_event2.severity == Severity.CRITICAL
