"""Simple streaming test for the dashboard SSE endpoint."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from hashbidder.broadcast_hub import BroadcastHub
from hashbidder.dashboard import app, stream
from hashbidder.metrics import MetricRow, MetricsRepo


@pytest.mark.asyncio
async def test_stream_simple() -> None:
    """Verify that the /stream endpoint can receive live metric events."""
    mock_repo = AsyncMock(spec=MetricsRepo)
    mock_repo.get_history.return_value = []

    mock_hub = MagicMock(spec=BroadcastHub)
    live_queue: asyncio.Queue[MetricRow | str] = asyncio.Queue()
    mock_hub.subscribe.return_value = live_queue

    app.state.metrics_repo = mock_repo
    app.state.broadcast_hub = mock_hub
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/stream",
            "headers": [],
            "app": app,
        }
    )
    response = await stream(request)
    assert response.status_code == 200

    async def publish_later() -> None:
        await asyncio.sleep(0.1)
        row = MetricRow(
            timestamp=100,
            braiins_hashrate_phs=Decimal("1.0"),
            ocean_hashrate_phs=Decimal("1.0"),
            braiins_connected=True,
            ocean_connected=True,
            mempool_connected=True,
        )
        await live_queue.put(row)

    task = asyncio.create_task(publish_later())
    chunk = await asyncio.wait_for(response.body_iterator.__anext__(), timeout=2.0)
    text = chunk.decode() if isinstance(chunk, bytes) else chunk
    assert "id: 100" in text
    await task
    await response.body_iterator.aclose()
