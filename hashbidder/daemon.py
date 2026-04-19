"""Daemon orchestration logic for periodic reconciliation and metrics collection."""

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from hashbidder import use_cases
from hashbidder.bid_runner import ActionStatus
from hashbidder.client import HashpowerClient
from hashbidder.config import TargetHashrateConfig, load_config
from hashbidder.domain.bid_planning import CancelAction, CreateAction, EditAction
from hashbidder.domain.btc_address import BtcAddress
from hashbidder.domain.hashrate import HashUnit
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
    # 1. Setup & Config
    braiins_connected = False
    ocean_connected = False
    mempool_connected = False

    target_hashrate_phs = None
    needed_hashrate_phs = None
    market_price_sat = None
    bids_created = 0
    bids_edited = 0
    bids_cancelled = 0

    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        return

    # 2. Reconcile
    try:
        if isinstance(config, TargetHashrateConfig):
            res = await use_cases.run_set_bids_target(
                client=braiins_client,
                ocean=ocean_client,
                address=ocean_address,
                config=config,
                dry_run=False,
            )
            set_bids_result = res.set_bids_result
            target_hashrate_phs = res.inputs.target.to(
                HashUnit.PH, TimeUnit.SECOND
            ).value
            needed_hashrate_phs = res.inputs.needed.to(
                HashUnit.PH, TimeUnit.SECOND
            ).value
            market_price_sat = int(res.inputs.price.to(HashUnit.PH, TimeUnit.DAY).sats)
            ocean_connected = True
        else:
            set_bids_result = await use_cases.run_set_bids(
                client=braiins_client,
                config=config,
                dry_run=False,
            )
        braiins_connected = True

        if set_bids_result.execution:
            for outcome in set_bids_result.execution.outcomes:
                if outcome.status == ActionStatus.SUCCEEDED:
                    if isinstance(outcome.action, CreateAction):
                        bids_created += 1
                    elif isinstance(outcome.action, EditAction):
                        bids_edited += 1
                    elif isinstance(outcome.action, CancelAction):
                        bids_cancelled += 1
    except Exception as e:
        logger.error("Reconciliation failed: %s", e)

    # 3. Final Metrics Collection
    braiins_hashrate_phs = Decimal(0)
    bids_active = 0
    braiins_shares_accepted = 0
    braiins_shares_rejected = 0
    try:
        current_bids = await braiins_client.get_current_bids()
        bids_active = len(current_bids)
        for bid in current_bids:
            braiins_hashrate_phs += bid.speed_limit_ph.value
            if bid.shares_accepted is not None:
                braiins_shares_accepted += bid.shares_accepted
            if bid.shares_rejected is not None:
                braiins_shares_rejected += bid.shares_rejected
        braiins_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Braiins metrics: %s", e)

    ocean_hashrate_phs = Decimal(0)
    ocean_shares_window = None
    ocean_estimated_rewards_sat = None
    ocean_next_block_earnings_sat = None
    try:
        stats = await ocean_client.get_account_stats(ocean_address)
        ocean_shares_window = stats.shares_window
        ocean_estimated_rewards_sat = stats.estimated_rewards
        ocean_next_block_earnings_sat = stats.next_block_earnings
        for window in stats.windows:
            if window.window is OceanTimeWindow.DAY:
                ocean_hashrate_phs = window.hashrate.to(
                    HashUnit.PH, TimeUnit.SECOND
                ).value
                break
        ocean_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Ocean metrics: %s", e)

    try:
        await mempool_client.get_chain_stats(block_count=1)
        mempool_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Mempool metrics: %s", e)

    balance_sat = None
    try:
        balance = await braiins_client.get_account_balance()
        balance_sat = balance.available_sat
    except Exception as e:
        logger.warning("Failed to fetch balance: %s", e)

    # 4. Record Metrics
    row = MetricRow(
        timestamp=int(datetime.now(UTC).timestamp()),
        braiins_hashrate_phs=braiins_hashrate_phs,
        ocean_hashrate_phs=ocean_hashrate_phs,
        braiins_connected=braiins_connected,
        ocean_connected=ocean_connected,
        mempool_connected=mempool_connected,
        target_hashrate_phs=target_hashrate_phs,
        needed_hashrate_phs=needed_hashrate_phs,
        market_price_sat=market_price_sat,
        bids_active=bids_active,
        bids_created=bids_created,
        bids_edited=bids_edited,
        bids_cancelled=bids_cancelled,
        balance_sat=balance_sat,
        braiins_shares_accepted=braiins_shares_accepted,
        braiins_shares_rejected=braiins_shares_rejected,
        ocean_shares_window=ocean_shares_window,
        ocean_estimated_rewards_sat=ocean_estimated_rewards_sat,
        ocean_next_block_earnings_sat=ocean_next_block_earnings_sat,
    )
    await metrics_repo.insert(row)

    # 5. Logging
    logger.info(
        "Tick complete: Target %s PH/s, Ocean actual %s PH/s. "
        "Market Price %s sat. Actions: %d CREATE, %d EDIT, %d CANCEL. "
        "Balance %s sat.",
        f"{target_hashrate_phs:.2f}" if target_hashrate_phs is not None else "N/A",
        f"{ocean_hashrate_phs:.2f}",
        market_price_sat if market_price_sat is not None else "N/A",
        bids_created,
        bids_edited,
        bids_cancelled,
        f"{balance_sat}" if balance_sat is not None else "N/A",
    )
