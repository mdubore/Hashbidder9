"""Daemon orchestration logic for periodic reconciliation and metrics collection."""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from hashbidder import use_cases
from hashbidder.broadcast_hub import BroadcastHub
from hashbidder.client import BidStatus, HashpowerClient
from hashbidder.config import TargetHashrateConfig, load_config
from hashbidder.domain.bid_planning import CancelAction, CreateAction, EditAction
from hashbidder.domain.btc_address import BtcAddress
from hashbidder.domain.hashrate import HashUnit
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.mempool_client import MempoolSource
from hashbidder.metrics import MetricRow, MetricsRepo
from hashbidder.ocean_client import OceanSource, OceanTimeWindow

logger = logging.getLogger(__name__)


def _select_actual_ocean_hashrate_phs(stats: any) -> Decimal:
    """Select the best window for 'actual' hashrate, preferring 5m."""
    # API uses seconds: 86400s (24h), 10800s (3h), 3600s (1h), 600s (10m), 300s (5m), 60s (1m)
    # We prefer the smallest window that is likely to be stable.
    windows = {w.window: w.hashrate for w in stats.windows}

    for win in [
        OceanTimeWindow.FIVE_MINUTES,
        OceanTimeWindow.TEN_MINUTES,
        OceanTimeWindow.ONE_HOUR,
        OceanTimeWindow.THREE_HOURS,
        OceanTimeWindow.DAY,
    ]:
        if win in windows:
            return windows[win].to(HashUnit.PH, TimeUnit.SECOND).value

    return Decimal(0)


async def _tick(
    config_path: Path,
    braiins_client: HashpowerClient,
    ocean_client: OceanSource,
    mempool_client: MempoolSource,
    metrics_repo: MetricsRepo,
    ocean_address: BtcAddress,
) -> MetricRow:
    """Perform a single reconciliation and metrics collection tick."""
    # 1. Load Config
    config = load_config(config_path)

    # 2. Run Reconciliation (if in target-hashrate mode)
    bids_created = 0
    bids_edited = 0
    bids_cancelled = 0
    target_hashrate_phs = None
    needed_hashrate_phs = None
    market_price_sat = None

    try:
        if isinstance(config, TargetHashrateConfig):
            result = await use_cases.run_set_bids_target(
                client=braiins_client,
                ocean=ocean_client,
                address=ocean_address,
                config=config,
                dry_run=False,
            )
            target_hashrate_phs = config.target_hashrate.to(
                HashUnit.PH, TimeUnit.SECOND
            ).value
            needed_hashrate_phs = result.inputs.needed.to(
                HashUnit.PH, TimeUnit.SECOND
            ).value
            market_price_sat = int(result.inputs.price.sats)

            for outcome in result.set_bids_result.outcomes:
                if outcome.status.name == "SUCCEEDED":
                    if isinstance(outcome.action, CreateAction):
                        bids_created += 1
                    elif isinstance(outcome.action, EditAction):
                        bids_edited += 1
                    elif isinstance(outcome.action, CancelAction):
                        bids_cancelled += 1
    except Exception as e:
        logger.error("Reconciliation failed: %s", e)
        # Try to log the raw stats to help debug "missing window" issues
        with contextlib.suppress(Exception):
            raw_stats = await ocean_client.get_account_stats(ocean_address)
            logger.debug("Ocean stats for debug: %s", raw_stats)

    # 3. Final Metrics Collection
    braiins_hashrate_phs = Decimal(0)
    bids_active = 0
    braiins_shares_accepted = 0
    braiins_shares_rejected = 0
    active_bid_price_sat = None
    try:
        current_bids = await braiins_client.get_current_bids()
        bids_active = len(current_bids)
        if not current_bids:
            logger.warning("No active bids found on Braiins account.")
        for bid in current_bids:
            # Pick the price of any valid bid we find (Active, Created, or Paused)
            # to ensure the "Active Bid" line is populated on the graph.
            if active_bid_price_sat is None and bid.status in (
                BidStatus.ACTIVE,
                BidStatus.CREATED,
                BidStatus.PAUSED,
            ):
                active_bid_price_sat = int(
                    bid.price.to(HashUnit.PH, TimeUnit.DAY).sats
                )

            # Use Delivered Hashrate (Averaged) for the primary Braiins line.
            # Use Current Speed (Momentary) if you wanted to see the jitter.
            # We'll use delivered_hashrate as it's more stable for the dashboard.
            if bid.delivered_hashrate:
                braiins_hashrate_phs += bid.delivered_hashrate.to(
                    HashUnit.PH, TimeUnit.SECOND
                ).value

            if bid.shares_accepted is not None:
                braiins_shares_accepted += bid.shares_accepted
            if bid.shares_rejected is not None:
                braiins_shares_rejected += bid.shares_rejected

        braiins_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Braiins metrics: %s", e)
        braiins_connected = False

    ocean_hashrate_phs = Decimal(0)
    ocean_shares_window = None
    ocean_estimated_rewards_sat = None
    ocean_next_block_earnings_sat = None
    try:
        stats = await ocean_client.get_account_stats(ocean_address)
        ocean_hashrate_phs = _select_actual_ocean_hashrate_phs(stats)
        ocean_shares_window = stats.shares_window
        ocean_estimated_rewards_sat = stats.estimated_rewards
        ocean_next_block_earnings_sat = stats.next_block_earnings
        ocean_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Ocean metrics: %s", e)
        ocean_connected = False

    hashvalue_sat = None
    try:
        hashvalue_comp = await use_cases.run_hashvalue(mempool_client)
        hashvalue_sat = int(hashvalue_comp.hashvalue.sats)
        mempool_connected = True
    except Exception as e:
        logger.warning("Failed to fetch Mempool metrics: %s", e)
        mempool_connected = False

    balance_sat = None
    try:
        balance = await braiins_client.get_account_balance()
        balance_sat = int(balance.available_sat)
    except Exception as e:
        logger.warning("Failed to fetch balance: %s", e)

    # 4. Persistence
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
        hashvalue_sat=hashvalue_sat,
        active_bid_price_sat=active_bid_price_sat,
    )
    await metrics_repo.insert(row)

    # 5. Logging
    logger.info(
        "Tick complete: Target %s PH/s, Ocean actual %s PH/s. "
        "Market Price %s sat, Active Bid %s sat. "
        "Actions: %d CREATE, %d EDIT, %d CANCEL. Balance %s sat.",
        f"{target_hashrate_phs:.2f}" if target_hashrate_phs is not None else "N/A",
        f"{ocean_hashrate_phs:.2f}",
        market_price_sat if market_price_sat is not None else "N/A",
        active_bid_price_sat if active_bid_price_sat is not None else "N/A",
        bids_created,
        bids_edited,
        bids_cancelled,
        f"{balance_sat}" if balance_sat is not None else "N/A",
    )
    return row


async def daemon_loop(
    config_path: Path,
    braiins_client: HashpowerClient,
    ocean_client: OceanSource,
    mempool_client: MempoolSource,
    metrics_repo: MetricsRepo,
    ocean_address: BtcAddress,
    interval_seconds: int = 300,
    hub: BroadcastHub | None = None,
) -> None:
    """Continuously run reconciliation and collect metrics."""
    logger.info("Starting daemon loop with interval=%ds", interval_seconds)
    while True:
        try:
            row = await _tick(
                config_path=config_path,
                braiins_client=braiins_client,
                ocean_client=ocean_client,
                mempool_client=mempool_client,
                metrics_repo=metrics_repo,
                ocean_address=ocean_address,
            )
            if hub:
                hub.publish(row)
        except Exception:
            logger.exception("Unexpected error in daemon loop")

        await asyncio.sleep(interval_seconds)
