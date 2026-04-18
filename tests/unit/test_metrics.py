"""Tests for the metrics repository."""

import os
import tempfile
from decimal import Decimal

import pytest

from hashbidder.metrics import MetricRow, MetricsRepo


@pytest.mark.asyncio
async def test_metrics_repo_flow() -> None:
    """Verifies that init_db, insert, and get_history work together."""
    # Use a temporary file for testing because :memory: is wiped on
    # every connection close, and MetricsRepo opens/closes a connection
    # for every operation.
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        db_path = tmp.name

    try:
        repo = MetricsRepo(db_path)
        await repo.init_db()

        row1 = MetricRow(
            timestamp=1000,
            braiins_hashrate_phs=Decimal("1.5"),
            ocean_hashrate_phs=Decimal("2.0"),
            braiins_connected=True,
            ocean_connected=True,
            mempool_connected=True,
        )
        row2 = MetricRow(
            timestamp=1100,
            braiins_hashrate_phs=Decimal("1.6"),
            ocean_hashrate_phs=Decimal("2.1"),
            braiins_connected=True,
            ocean_connected=False,
            mempool_connected=True,
        )

        await repo.insert(row1)
        await repo.insert(row2)

        # Test get_history
        history = await repo.get_history(since_timestamp=1000)
        assert len(history) == 2
        assert history[0] == row1
        assert history[1] == row2

        # Test filtering by timestamp
        history_filtered = await repo.get_history(since_timestamp=1050)
        assert len(history_filtered) == 1
        assert history_filtered[0] == row2

        # Test empty result
        history_empty = await repo.get_history(since_timestamp=2000)
        assert len(history_empty) == 0
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
