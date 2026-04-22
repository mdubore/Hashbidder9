"""Tests for SSE streaming functionality in the dashboard."""

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from starlette.requests import Request

from hashbidder.broadcast_hub import OVERFLOW_SIGNAL
from hashbidder.dashboard import app, broadcast_hub, stream
from hashbidder.metrics import MetricRow, MetricsRepo


@pytest.fixture
def metric_row() -> MetricRow:
    """Return a sample MetricRow for testing."""
    return MetricRow(
        timestamp=1713634000,
        braiins_hashrate_phs=Decimal("1.0"),
        ocean_hashrate_phs=Decimal("1.1"),
        braiins_connected=True,
        ocean_connected=True,
        mempool_connected=True,
        ocean_hashrate_60s_phs=Decimal("1.05"),
        ocean_hashrate_600s_phs=Decimal("1.02"),
        ocean_hashrate_86400s_phs=Decimal("0.98"),
        braiins_current_speed_phs=Decimal("1.08"),
        braiins_speed_limit_phs=Decimal("1.15"),
        braiins_delivered_hashrate_phs=Decimal("1.01"),
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
async def metrics_repo(tmp_path: Path) -> MetricsRepo:
    """Fixture for an initialized in-memory/temporary SQLite metrics repo."""
    db_path = tmp_path / "test.sqlite"
    repo = MetricsRepo(str(db_path))
    await repo.init_db()
    return repo


@pytest.mark.asyncio
async def test_serialize_metric_row(metric_row: MetricRow) -> None:
    """Test that MetricRow is correctly serialized for JSON transport."""
    from hashbidder.dashboard import serialize_metric_row

    serialized = serialize_metric_row(metric_row)
    assert serialized["braiins_hashrate_phs"] == "1.0"
    assert isinstance(serialized["braiins_hashrate_phs"], str)
    assert serialized["ocean_hashrate_60s_phs"] == "1.05"
    assert serialized["ocean_hashrate_600s_phs"] == "1.02"
    assert serialized["ocean_hashrate_86400s_phs"] == "0.98"
    assert serialized["braiins_current_speed_phs"] == "1.08"
    assert serialized["braiins_speed_limit_phs"] == "1.15"
    assert serialized["braiins_delivered_hashrate_phs"] == "1.01"


def make_request(last_event_id: str | None = None) -> Request:
    """Create a minimal ASGI request for the stream endpoint."""
    headers: list[tuple[bytes, bytes]] = []
    if last_event_id is not None:
        headers.append((b"last-event-id", last_event_id.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/stream",
        "headers": headers,
        "app": app,
    }
    return Request(scope)


async def read_stream_chunk(
    body_iterator: AsyncIterator[bytes | str], timeout: float = 2.0
) -> str:
    """Read a single emitted SSE chunk from a StreamingResponse iterator."""
    chunk = await asyncio.wait_for(body_iterator.__anext__(), timeout)
    return chunk.decode() if isinstance(chunk, bytes) else chunk


@pytest.mark.asyncio
async def test_stream_replay_sequencing(
    metrics_repo: MetricsRepo, metric_row: MetricRow
) -> None:
    """Test that old metrics are replayed correctly when 'since' is provided."""
    app.state.metrics_repo = metrics_repo
    app.state.broadcast_hub = broadcast_hub
    # 1. Add row to repo
    await metrics_repo.insert(metric_row)

    # 2. Test replay via 'since' param
    response = await stream(make_request(), since=1713633000)
    chunk = await read_stream_chunk(response.body_iterator)
    assert "id: 1713634000" in chunk
    assert "event: metric_row" in chunk
    assert '"braiins_hashrate_phs": "1.0"' in chunk
    assert '"ocean_hashrate_60s_phs": "1.05"' in chunk
    assert '"braiins_current_speed_phs": "1.08"' in chunk
    assert '"braiins_speed_limit_phs": "1.15"' in chunk
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_stream_reconnect_via_last_event_id(
    metrics_repo: MetricsRepo, metric_row: MetricRow
) -> None:
    """Test that Last-Event-ID header is respected for metric replay."""
    app.state.metrics_repo = metrics_repo
    app.state.broadcast_hub = broadcast_hub
    await metrics_repo.insert(metric_row)
    response = await stream(make_request(last_event_id="1713633000"))
    chunk = await read_stream_chunk(response.body_iterator)
    assert "id: 1713634000" in chunk
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_stream_unsubscribe_on_exit(metrics_repo: MetricsRepo) -> None:
    """Test that clients are correctly unsubscribed when the stream closes."""
    app.state.metrics_repo = metrics_repo
    app.state.broadcast_hub = broadcast_hub
    # Ensure hub is clean
    for q in list(broadcast_hub._subscribers):
        broadcast_hub.unsubscribe(q)

    initial_count = len(broadcast_hub._subscribers)
    response = await stream(make_request())
    consume_task = asyncio.create_task(read_stream_chunk(response.body_iterator, 15.5))
    await asyncio.sleep(0.1)
    assert len(broadcast_hub._subscribers) == initial_count + 1
    consume_task.cancel()
    await asyncio.gather(consume_task, return_exceptions=True)
    await response.body_iterator.aclose()
    await asyncio.sleep(0)
    assert len(broadcast_hub._subscribers) == initial_count


@pytest.mark.asyncio
async def test_stream_overflow(metrics_repo: MetricsRepo) -> None:
    """Test that overflow signals are correctly broadcast to stream clients."""
    app.state.metrics_repo = metrics_repo
    app.state.broadcast_hub = broadcast_hub
    response = await stream(make_request())
    read_task = asyncio.create_task(read_stream_chunk(response.body_iterator))
    await asyncio.sleep(0.1)
    broadcast_hub.publish(OVERFLOW_SIGNAL)
    chunk = await read_task
    assert "event: overflow" in chunk
    assert "data: reset" in chunk
    await response.body_iterator.aclose()
