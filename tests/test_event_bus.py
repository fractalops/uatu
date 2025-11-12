"""Tests for the EventBus pub/sub system."""

import pytest

from uatu.watcher.models import AnomalyEvent


@pytest.mark.asyncio
async def test_event_bus_subscribe_and_publish(event_bus, sample_cpu_spike_event):
    """Test basic subscribe and publish functionality."""
    received_events = []

    async def handler(event: AnomalyEvent):
        received_events.append(event)

    # Subscribe to event type
    event_bus.subscribe("test.event", handler)

    # Publish event
    await event_bus.publish("test.event", sample_cpu_spike_event)

    # Verify event was received
    assert len(received_events) == 1
    assert received_events[0] == sample_cpu_spike_event


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers(event_bus, sample_cpu_spike_event):
    """Test that multiple subscribers receive the same event."""
    received_by_handler1 = []
    received_by_handler2 = []

    async def handler1(event: AnomalyEvent):
        received_by_handler1.append(event)

    async def handler2(event: AnomalyEvent):
        received_by_handler2.append(event)

    # Subscribe both handlers
    event_bus.subscribe("test.event", handler1)
    event_bus.subscribe("test.event", handler2)

    # Publish event
    await event_bus.publish("test.event", sample_cpu_spike_event)

    # Both handlers should receive the event
    assert len(received_by_handler1) == 1
    assert len(received_by_handler2) == 1
    assert received_by_handler1[0] == sample_cpu_spike_event
    assert received_by_handler2[0] == sample_cpu_spike_event


@pytest.mark.asyncio
async def test_event_bus_different_event_types(event_bus, sample_cpu_spike_event, sample_memory_spike_event):
    """Test that subscribers only receive events of their subscribed type."""
    cpu_events = []
    memory_events = []

    async def cpu_handler(event: AnomalyEvent):
        cpu_events.append(event)

    async def memory_handler(event: AnomalyEvent):
        memory_events.append(event)

    # Subscribe to different event types
    event_bus.subscribe("cpu.spike", cpu_handler)
    event_bus.subscribe("memory.spike", memory_handler)

    # Publish different events
    await event_bus.publish("cpu.spike", sample_cpu_spike_event)
    await event_bus.publish("memory.spike", sample_memory_spike_event)

    # Each handler should only receive its subscribed event
    assert len(cpu_events) == 1
    assert len(memory_events) == 1
    assert cpu_events[0] == sample_cpu_spike_event
    assert memory_events[0] == sample_memory_spike_event


@pytest.mark.asyncio
async def test_event_bus_publish_with_no_subscribers(event_bus, sample_cpu_spike_event):
    """Test that publishing with no subscribers doesn't error."""
    # Should not raise an exception
    await event_bus.publish("nonexistent.event", sample_cpu_spike_event)


@pytest.mark.asyncio
async def test_event_bus_handler_exception(event_bus, sample_cpu_spike_event):
    """Test that handler exceptions don't prevent other handlers from running."""
    received_events = []

    async def failing_handler(event: AnomalyEvent):
        raise ValueError("Handler failed")

    async def successful_handler(event: AnomalyEvent):
        received_events.append(event)

    # Subscribe both handlers
    event_bus.subscribe("test.event", failing_handler)
    event_bus.subscribe("test.event", successful_handler)

    # Publish event
    await event_bus.publish("test.event", sample_cpu_spike_event)

    # Successful handler should still receive event
    assert len(received_events) == 1
    assert received_events[0] == sample_cpu_spike_event
