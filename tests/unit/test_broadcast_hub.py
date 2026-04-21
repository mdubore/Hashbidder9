"""Tests for the BroadcastHub class."""

import pytest

from hashbidder.broadcast_hub import OVERFLOW_SIGNAL, BroadcastHub


@pytest.mark.asyncio
async def test_broadcast_hub_lifecycle() -> None:
    """Subscribe, publish, receive, unsubscribe."""
    hub = BroadcastHub()
    queue = await hub.subscribe()
    
    hub.publish("test_message")
    
    message = await queue.get()
    assert message == "test_message"
    
    hub.unsubscribe(queue)
    assert len(hub._subscribers) == 0

@pytest.mark.asyncio
async def test_broadcast_hub_overflow() -> None:
    """Fill queue to 50, then publish 51st to trigger overflow signal."""
    hub = BroadcastHub(maxsize=50)
    queue = await hub.subscribe()
    
    # Fill queue to 50
    for i in range(50):
        hub.publish(f"msg_{i}")
    
    assert queue.qsize() == 50
    
    # Publish 51st to trigger overflow signal
    hub.publish("msg_51")
    
    # Queue should be cleared and contain ONLY OVERFLOW_SIGNAL
    assert queue.qsize() == 1
    message = await queue.get()
    assert message == OVERFLOW_SIGNAL

@pytest.mark.asyncio
async def test_broadcast_hub_disconnect_cleanup() -> None:
    """Verify hub subscriber count."""
    hub = BroadcastHub()
    queue1 = await hub.subscribe()
    queue2 = await hub.subscribe()
    
    assert len(hub._subscribers) == 2
    
    hub.unsubscribe(queue1)
    assert len(hub._subscribers) == 1
    
    hub.unsubscribe(queue2)
    assert len(hub._subscribers) == 0
