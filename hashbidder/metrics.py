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
                    mempool_connected INTEGER
                )
            """)
            await db.commit()

    async def insert(self, row: MetricRow) -> None:
        """Insert a new metric row.

        Args:
            row: The MetricRow to insert.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO metrics VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row.timestamp,
                    str(row.braiins_hashrate_phs),
                    str(row.ocean_hashrate_phs),
                    int(row.braiins_connected),
                    int(row.ocean_connected),
                    int(row.mempool_connected),
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
                )
                for r in rows
            ]
