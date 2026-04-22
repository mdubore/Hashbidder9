"""Tests for the metrics repository."""

import os
import tempfile
from decimal import Decimal

import aiosqlite
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
            ocean_hashrate_60s_phs=Decimal("0.50"),
            ocean_hashrate_600s_phs=Decimal("0.45"),
            ocean_hashrate_86400s_phs=Decimal("0.40"),
            braiins_current_speed_phs=Decimal("0.47"),
            braiins_speed_limit_phs=Decimal("0.49"),
            braiins_delivered_hashrate_phs=Decimal("0.44"),
            target_hashrate_phs=Decimal("5.0"),
            needed_hashrate_phs=Decimal("3.0"),
            market_price_sat=100,
            bids_active=5,
            bids_created=1,
            bids_edited=2,
            bids_cancelled=0,
            balance_sat=1000000,
            braiins_shares_accepted=1000,
            braiins_shares_rejected=10,
            ocean_shares_window=500,
            ocean_estimated_rewards_sat=5000,
            ocean_next_block_earnings_sat=100,
        )
        row2 = MetricRow(
            timestamp=1100,
            braiins_hashrate_phs=Decimal("1.6"),
            ocean_hashrate_phs=Decimal("2.1"),
            braiins_connected=True,
            ocean_connected=False,
            mempool_connected=True,
            ocean_hashrate_60s_phs=None,
            ocean_hashrate_600s_phs=Decimal("0.41"),
            ocean_hashrate_86400s_phs=Decimal("0.39"),
            braiins_current_speed_phs=Decimal("0.48"),
            braiins_speed_limit_phs=Decimal("0.51"),
            braiins_delivered_hashrate_phs=None,
            target_hashrate_phs=Decimal("5.0"),
            needed_hashrate_phs=Decimal("2.9"),
            market_price_sat=101,
            bids_active=6,
            bids_created=1,
            bids_edited=0,
            bids_cancelled=0,
            balance_sat=900000,
            braiins_shares_accepted=None,
            braiins_shares_rejected=None,
            ocean_shares_window=None,
            ocean_estimated_rewards_sat=None,
            ocean_next_block_earnings_sat=None,
        )

        await repo.insert(row1)
        await repo.insert(row2)

        # Test get_history
        history = await repo.get_history(since_timestamp=1000)
        assert len(history) == 2
        assert history[0] == row1
        assert history[1] == row2
        assert history[0].ocean_hashrate_60s_phs == Decimal("0.50")
        assert history[0].braiins_speed_limit_phs == Decimal("0.49")
        assert history[1].braiins_delivered_hashrate_phs is None

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


@pytest.mark.asyncio
async def test_metrics_repo_migration() -> None:
    """Verifies that init_db can handle an existing database without new columns."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        db_path = tmp.name

    try:
        # Manually create an old version of the database
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE metrics (
                    timestamp INTEGER PRIMARY KEY,
                    braiins_hashrate_phs TEXT,
                    ocean_hashrate_phs TEXT,
                    braiins_connected INTEGER,
                    ocean_connected INTEGER,
                    mempool_connected INTEGER,
                    target_hashrate_phs TEXT,
                    needed_hashrate_phs TEXT,
                    market_price_sat INTEGER,
                    bids_active INTEGER,
                    bids_created INTEGER,
                    bids_edited INTEGER,
                    bids_cancelled INTEGER,
                    balance_sat INTEGER
                )
            """)
            await db.commit()

        # Now use MetricsRepo to initialize (migrate) it
        repo = MetricsRepo(db_path)
        await repo.init_db()

        # Check if new columns exist
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("PRAGMA table_info(metrics)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            assert "braiins_shares_accepted" in column_names
            assert "braiins_shares_rejected" in column_names
            assert "ocean_shares_window" in column_names
            assert "ocean_estimated_rewards_sat" in column_names
            assert "ocean_next_block_earnings_sat" in column_names

        # Verify we can insert and retrieve data
        row = MetricRow(
            timestamp=1000,
            braiins_hashrate_phs=Decimal("1.5"),
            ocean_hashrate_phs=Decimal("2.0"),
            braiins_connected=True,
            ocean_connected=True,
            mempool_connected=True,
            ocean_hashrate_60s_phs=Decimal("0.50"),
            ocean_hashrate_600s_phs=Decimal("0.45"),
            ocean_hashrate_86400s_phs=Decimal("0.40"),
            braiins_current_speed_phs=Decimal("0.47"),
            braiins_speed_limit_phs=Decimal("0.49"),
            braiins_delivered_hashrate_phs=None,
            braiins_shares_accepted=1000,
            braiins_shares_rejected=10,
            ocean_shares_window=500,
            ocean_estimated_rewards_sat=5000,
            ocean_next_block_earnings_sat=100,
        )
        await repo.insert(row)
        history = await repo.get_history(since_timestamp=1000)
        assert len(history) == 1
        assert history[0].braiins_shares_accepted == 1000
        assert history[0].ocean_hashrate_600s_phs == Decimal("0.45")
        assert history[0].braiins_speed_limit_phs == Decimal("0.49")
        assert history[0].braiins_delivered_hashrate_phs is None

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
