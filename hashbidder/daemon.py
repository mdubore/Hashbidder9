"""Daemon orchestration logic for periodic reconciliation and metrics collection."""

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from hashbidder import use_cases
from hashbidder.client import HashpowerClient
from hashbidder.config import TargetHashrateConfig, load_config
from hashbidder.domain.btc_address import BtcAddress
from hashbidder.domain.hashrate import Hashrate, HashUnit
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.mempool_client import MempoolSource
from hashbidder.metrics import MetricRow, MetricsRepo
from hashbidder.ocean_client import OceanSource, OceanTimeWindow

logger = logging.getLogger(__name__)


async def daemon_loop(
    config_path: Path,
    braiins_client: HashpowerClient,
    ocean_client: OceanSource,
    mempool_client: MempoolSource,
    metrics_repo: MetricsRepo,
    ocean_address: BtcAddress,
    interval_seconds: int = 300,
) -> None:
    """Run the non-interactive bid-reconciliation and metrics-collection loop.

    Args:
        config_path: Path to the TOML bid config file.
        braiins_client: The hashpower market client to use.
        ocean_client: The Ocean data source to use.
        mempool_client: The mempool data source to use.
        metrics_repo: The repository to store metrics in.
        ocean_address: The Bitcoin address to monitor for Ocean metrics.
        interval_seconds: How often to run the loop (default 300 seconds).
    """
    logger.info("Starting daemon loop with interval=%ds", interval_seconds)
    while True:
        tick_start = datetime.now(UTC)
        try:
            await _tick(
                config_path=config_path,
                braiins_client=braiins_client,
                ocean_client=ocean_client,
                mempool_client=mempool_client,
                metrics_repo=metrics_repo,
                ocean_address=ocean_address,
            )
        except Exception:
            logger.exception("Unexpected error in daemon loop")

        # Wait for the next interval
        elapsed = (datetime.now(UTC) - tick_start).total_seconds()
        sleep_time = max(0, interval_seconds - elapsed)
        await asyncio.sleep(sleep_time)


async def _tick(
    config_path: Path,
    braiins_client: HashpowerClient,
    ocean_client: OceanSource,
    mempool_client: MempoolSource,
    metrics_repo: MetricsRepo,
    ocean_address: BtcAddress,
) -> None:
    """Execute a single tick: metrics collection then reconciliation."""
    # 1. Collect Metrics
    # Initialize with zero and disconnected; update as we successfully fetch data.
    braiins_hashrate = Hashrate(Decimal(0), HashUnit.PH, TimeUnit.SECOND)
    braiins_connected = False
    try:
        current_bids = await braiins_client.get_current_bids()
        for bid in current_bids:
            braiins_hashrate += bid.speed_limit_ph
        braiins_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Braiins metrics: %s", e)

    ocean_hashrate = Hashrate(Decimal(0), HashUnit.PH, TimeUnit.SECOND)
    ocean_connected = False
    try:
        stats = await ocean_client.get_account_stats(ocean_address)
        for window in stats.windows:
            if window.window is OceanTimeWindow.DAY:
                ocean_hashrate = window.hashrate.to(HashUnit.PH, TimeUnit.SECOND)
                break
        ocean_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Ocean metrics: %s", e)

    mempool_connected = False
    try:
        # Ping mempool with a simple request.
        await mempool_client.get_chain_stats(block_count=1)
        mempool_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Mempool metrics: %s", e)

    # 2. Record Metrics
    # We record metrics even if reconciliation fails or connectivity is partial.
    row = MetricRow(
        timestamp=int(datetime.now(UTC).timestamp()),
        braiins_hashrate_phs=braiins_hashrate.value,
        ocean_hashrate_phs=ocean_hashrate.value,
        braiins_connected=braiins_connected,
        ocean_connected=ocean_connected,
        mempool_connected=mempool_connected,
    )
    await metrics_repo.insert(row)

    # 3. Load Config and Reconcile
    try:
        config = load_config(config_path)
        if isinstance(config, TargetHashrateConfig):
            await use_cases.run_set_bids_target(
                client=braiins_client,
                ocean=ocean_client,
                address=ocean_address,
                config=config,
                dry_run=False,
            )
        else:
            await use_cases.run_set_bids(
                client=braiins_client,
                config=config,
                dry_run=False,
            )
        logger.info("Successfully completed bid reconciliation")
    except Exception as e:
        logger.error("Reconciliation failed: %s", e)
