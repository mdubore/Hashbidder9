"""Metrics repository for historical data."""

import os
from dataclasses import dataclass
from decimal import Decimal

import aiosqlite


@dataclass
class MetricRow:
    """A single row of metrics in the database."""

    timestamp: int
    braiins_hashrate_phs: Decimal
    ocean_hashrate_phs: Decimal
    braiins_connected: bool
    ocean_connected: bool
    mempool_connected: bool
    # New Fields
    target_hashrate_phs: Decimal | None = None
    needed_hashrate_phs: Decimal | None = None
    market_price_sat: int | None = None
    bids_active: int | None = None
    bids_created: int | None = None
    bids_edited: int | None = None
    bids_cancelled: int | None = None
    balance_sat: int | None = None
    # Braiins Shares
    braiins_shares_accepted: int | None = None
    braiins_shares_rejected: int | None = None
    # Ocean Rewards
    ocean_shares_window: int | None = None
    ocean_estimated_rewards_sat: int | None = None
    ocean_next_block_earnings_sat: int | None = None


class MetricsRepo:
    """SQLite abstraction for storing and retrieving metrics."""

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize the repository.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path or os.environ.get(
            "HASHBIDDER_SQLITE_PATH", "hashbidder.sqlite"
        )

    async def init_db(self) -> None:
        """Initialize the database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
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
                    balance_sat INTEGER,
                    braiins_shares_accepted INTEGER,
                    braiins_shares_rejected INTEGER,
                    ocean_shares_window INTEGER,
                    ocean_estimated_rewards_sat INTEGER,
                    ocean_next_block_earnings_sat INTEGER
                )
            """)

            # Safely add new columns if they don't exist
            columns = [
                ("braiins_shares_accepted", "INTEGER"),
                ("braiins_shares_rejected", "INTEGER"),
                ("ocean_shares_window", "INTEGER"),
                ("ocean_estimated_rewards_sat", "INTEGER"),
                ("ocean_next_block_earnings_sat", "INTEGER"),
            ]
            for col_name, col_type in columns:
                try:
                    await db.execute(
                        f"ALTER TABLE metrics ADD COLUMN {col_name} {col_type}"
                    )
                except aiosqlite.OperationalError:
                    pass  # Column already exists

            await db.commit()

    async def insert(self, row: MetricRow) -> None:
        """Insert a new metric row.

        Args:
            row: The MetricRow to insert.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.timestamp,
                    str(row.braiins_hashrate_phs),
                    str(row.ocean_hashrate_phs),
                    int(row.braiins_connected),
                    int(row.ocean_connected),
                    int(row.mempool_connected),
                    str(row.target_hashrate_phs)
                    if row.target_hashrate_phs is not None
                    else None,
                    str(row.needed_hashrate_phs)
                    if row.needed_hashrate_phs is not None
                    else None,
                    row.market_price_sat,
                    row.bids_active,
                    row.bids_created,
                    row.bids_edited,
                    row.bids_cancelled,
                    row.balance_sat,
                    row.braiins_shares_accepted,
                    row.braiins_shares_rejected,
                    row.ocean_shares_window,
                    row.ocean_estimated_rewards_sat,
                    row.ocean_next_block_earnings_sat,
                ),
            )
            await db.commit()

    async def get_history(self, since_timestamp: int) -> list[MetricRow]:
        """Retrieve historical metrics since a given timestamp.

        Args:
            since_timestamp: The starting timestamp (inclusive).

        Returns:
            A list of MetricRow objects sorted by timestamp.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM metrics WHERE timestamp >= ? ORDER BY timestamp ASC",
                (since_timestamp,),
            )
            rows = await cursor.fetchall()
            return [
                MetricRow(
                    timestamp=r["timestamp"],
                    braiins_hashrate_phs=Decimal(r["braiins_hashrate_phs"]),
                    ocean_hashrate_phs=Decimal(r["ocean_hashrate_phs"]),
                    braiins_connected=bool(r["braiins_connected"]),
                    ocean_connected=bool(r["ocean_connected"]),
                    mempool_connected=bool(r["mempool_connected"]),
                    target_hashrate_phs=Decimal(r["target_hashrate_phs"])
                    if r["target_hashrate_phs"] is not None
                    else None,
                    needed_hashrate_phs=Decimal(r["needed_hashrate_phs"])
                    if r["needed_hashrate_phs"] is not None
                    else None,
                    market_price_sat=r["market_price_sat"],
                    bids_active=r["bids_active"],
                    bids_created=r["bids_created"],
                    bids_edited=r["bids_edited"],
                    bids_cancelled=r["bids_cancelled"],
                    balance_sat=r["balance_sat"],
                    braiins_shares_accepted=r["braiins_shares_accepted"],
                    braiins_shares_rejected=r["braiins_shares_rejected"],
                    ocean_shares_window=r["ocean_shares_window"],
                    ocean_estimated_rewards_sat=r["ocean_estimated_rewards_sat"],
                    ocean_next_block_earnings_sat=r["ocean_next_block_earnings_sat"],
                )
                for r in rows
            ]
