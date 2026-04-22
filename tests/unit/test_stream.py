import asyncio
import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from hashbidder.dashboard import app, broadcast_hub
from hashbidder.metrics import MetricRow, MetricsRepo
from hashbidder.broadcast_hub import OVERFLOW_SIGNAL


@pytest.fixture
def metric_row():
    return MetricRow(
        timestamp=1713634000,
        braiins_hashrate_phs=Decimal("1.0"),
        ocean_hashrate_phs=Decimal("1.1"),
        braiins_connected=True,
        ocean_connected=True,
        mempool_connected=True,
        target_hashrate_phs=Decimal("1.0"),
        needed_hashrate_phs=Decimal("0.0"),
        market_price_sat=500,
        bids_active=1,
        bids_created=0,
        bids_edited=0,
        bids_cancelled=0,
        balance_sat=1000000,
        braiins_shares_accepted=1000,
        braiins_shares_rejected=0,
        ocean_shares_window=500,
        ocean_estimated_rewards_sat=10000,
        ocean_next_block_earnings_sat=5000,
        hashvalue_sat=450,
        active_bid_price_sat=480,
    )

@pytest_asyncio.fixture
async def metrics_repo(tmp_path: Path):
    db_path = tmp_path / "test.sqlite"
    repo = MetricsRepo(str(db_path))
    await repo.init_db()
    return repo

@pytest_asyncio.fixture
async def sse_client(metrics_repo):
    app.state.metrics_repo = metrics_repo
    app.state.broadcast_hub = broadcast_hub
    # Patch lifespan to avoid starting the real daemon
    with patch("hashbidder.dashboard.lifespan") as mock_lifespan:
        mock_lifespan.return_value.__aenter__.return_value = None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

@pytest.mark.asyncio
async def test_serialize_metric_row(metric_row):
    from hashbidder.dashboard import serialize_metric_row
    serialized = serialize_metric_row(metric_row)
    assert serialized["braiins_hashrate_phs"] == "1.0"
    assert isinstance(serialized["braiins_hashrate_phs"], str)

async def read_sse_frame(aiter, timeout=2.0):
    """Read raw text and split into frames."""
    buffer = ""
    try:
        async with asyncio.timeout(timeout):
            async for chunk in aiter:
                buffer += chunk
                if "\n\n" in buffer:
                    break
    except asyncio.TimeoutError:
        pass
    return buffer.split("\n")

@pytest.mark.asyncio
async def test_stream_replay_sequencing(sse_client, metrics_repo, metric_row):
    # 1. Add row to repo
    await metrics_repo.insert(metric_row)
    
    # 2. Test replay via 'since' param
    async with sse_client.stream("GET", "/stream?since=1713633000") as resp:
        frame = await read_sse_frame(resp.aiter_text())
        assert any("id: 1713634000" in l for l in frame)
        assert any("event: metric_row" in l for l in frame)
        assert any('"braiins_hashrate_phs": "1.0"' in l for l in frame)

@pytest.mark.asyncio
async def test_stream_reconnect_via_last_event_id(sse_client, metrics_repo, metric_row):
    await metrics_repo.insert(metric_row)
    headers = {"Last-Event-ID": "1713633000"}
    async with sse_client.stream("GET", "/stream", headers=headers) as resp:
        frame = await read_sse_frame(resp.aiter_text())
        assert any("id: 1713634000" in l for l in frame)

@pytest.mark.asyncio
async def test_stream_unsubscribe_on_exit(sse_client):
    # Ensure hub is clean
    for q in list(broadcast_hub._subscribers):
        broadcast_hub.unsubscribe(q)
    
    initial_count = len(broadcast_hub._subscribers)
    async with sse_client.stream("GET", "/stream"):
        await asyncio.sleep(0.1) # Allow registration
        assert len(broadcast_hub._subscribers) == initial_count + 1
    assert len(broadcast_hub._subscribers) == initial_count

@pytest.mark.asyncio
async def test_stream_overflow(sse_client):
    async with sse_client.stream("GET", "/stream") as resp:
        # Trigger overflow on ALL subscribers (including the one from the request)
        broadcast_hub.publish(OVERFLOW_SIGNAL)
        
        frame = await read_sse_frame(resp.aiter_text())
        assert any("event: overflow" in l for l in frame)
        assert any("data: reset" in l for l in frame)
