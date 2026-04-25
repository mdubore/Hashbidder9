"""Tests for daemon metric selection helpers."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import hashbidder.daemon as daemon
from hashbidder.daemon import _select_ocean_hashrate_phs, _tick
from hashbidder.domain.btc_address import BtcAddress
from hashbidder.domain.hashrate import Hashrate, HashUnit
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.metrics import MetricsRepo
from hashbidder.ocean_client import AccountStats, HashrateWindow, OceanTimeWindow
from tests.conftest import FakeClient, make_user_bid


def _ph_s(value: str) -> Hashrate:
    return Hashrate(Decimal(value), HashUnit.PH, TimeUnit.SECOND)


def test_select_ocean_hashrate_returns_requested_window() -> None:
    """A specific Ocean window is returned without cross-window fallback."""
    stats = AccountStats(
        windows=(
            HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.1")),
            HashrateWindow(window=OceanTimeWindow.TEN_MINUTES, hashrate=_ph_s("0.28")),
            HashrateWindow(
                window=OceanTimeWindow.SIXTY_SECONDS, hashrate=_ph_s("0.91")
            ),
        )
    )

    assert _select_ocean_hashrate_phs(stats, OceanTimeWindow.SIXTY_SECONDS) == Decimal(
        "0.91"
    )


def test_select_ocean_hashrate_returns_none_when_requested_window_is_missing() -> None:
    """Missing requested windows should not fall back to another series."""
    stats = AccountStats(
        windows=(
            HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.1")),
            HashrateWindow(window=OceanTimeWindow.TEN_MINUTES, hashrate=_ph_s("0.28")),
        )
    )
    assert _select_ocean_hashrate_phs(stats, OceanTimeWindow.SIXTY_SECONDS) is None


def test_select_ocean_hashrate_returns_day_when_day_is_requested() -> None:
    """The 24-hour trend source should use the Ocean day window only."""
    stats = AccountStats(
        windows=(HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.1")),)
    )
    assert _select_ocean_hashrate_phs(stats, OceanTimeWindow.DAY) == Decimal("0.1")


def test_select_ocean_hashrate_returns_none_if_windows_are_empty() -> None:
    """Empty responses should remain missing rather than becoming zero."""
    stats_empty = AccountStats(windows=())
    assert _select_ocean_hashrate_phs(stats_empty, OceanTimeWindow.DAY) is None


class _StaticOceanSource:
    def __init__(self, stats: AccountStats) -> None:
        self._stats = stats

    async def get_account_stats(self, _address: BtcAddress) -> AccountStats:
        return self._stats


@pytest.mark.asyncio
async def test_tick_persists_braiins_estimated_speed_and_speed_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The daemon should persist Braiins estimated speed and configured limit."""
    config_path = tmp_path / "bids.toml"
    config_path.write_text(
        "\n".join(
            [
                'mode = "explicit-bids"',
                "default_amount_sat = 100000",
                "",
                "[upstream]",
                'url = "stratum+tcp://pool.example.com:3333"',
                'identity = "worker1"',
                "",
                "[[bids]]",
                "price_sat_per_ph_day = 500",
                "speed_limit_ph_s = 1.0",
            ]
        )
        + "\n"
    )
    repo = MetricsRepo(str(tmp_path / "metrics.sqlite"))
    await repo.init_db()

    current_bid = replace(
        make_user_bid("B1", 500, "1.13"),
        current_speed=Hashrate(Decimal("1.404"), HashUnit.PH, TimeUnit.SECOND),
        delivered_hashrate=None,
    )
    braiins_client = FakeClient(current_bids=(current_bid,))
    ocean_source = _StaticOceanSource(
        AccountStats(
            windows=(
                HashrateWindow(
                    window=OceanTimeWindow.SIXTY_SECONDS, hashrate=_ph_s("0")
                ),
                HashrateWindow(window=OceanTimeWindow.TEN_MINUTES, hashrate=_ph_s("0")),
                HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.86")),
            ),
            shares_window=10,
            estimated_rewards=100,
            next_block_earnings=20,
        )
    )

    async def fake_hashvalue(_mempool: object) -> SimpleNamespace:
        return SimpleNamespace(hashvalue=SimpleNamespace(sats=43000))

    monkeypatch.setattr(daemon.use_cases, "run_hashvalue", fake_hashvalue)

    row = await _tick(
        config_path=config_path,
        braiins_client=braiins_client,
        ocean_client=ocean_source,
        mempool_client=object(),
        metrics_repo=repo,
        ocean_address=BtcAddress("bc1qdazee75g3zz3zhd43awhnmjqqmx50qjh9l0v23"),
    )

    assert row.braiins_current_speed_phs == Decimal("1.404")
    assert row.braiins_speed_limit_phs == Decimal("1.13")
    history = await repo.get_history(row.timestamp)
    assert len(history) == 1
    assert history[0].braiins_speed_limit_phs == Decimal("1.13")


@pytest.mark.asyncio
async def test_tick_collects_metrics_without_bids_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing bids.toml should skip reconciliation, not kill metrics collection."""
    repo = MetricsRepo(str(tmp_path / "metrics.sqlite"))
    await repo.init_db()

    current_bid = replace(
        make_user_bid("B1", 500, "1.13"),
        current_speed=Hashrate(Decimal("1.404"), HashUnit.PH, TimeUnit.SECOND),
        delivered_hashrate=None,
    )
    braiins_client = FakeClient(current_bids=(current_bid,))
    ocean_source = _StaticOceanSource(
        AccountStats(
            windows=(
                HashrateWindow(
                    window=OceanTimeWindow.SIXTY_SECONDS, hashrate=_ph_s("0")
                ),
                HashrateWindow(window=OceanTimeWindow.TEN_MINUTES, hashrate=_ph_s("0")),
                HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.86")),
            ),
            shares_window=10,
            estimated_rewards=100,
            next_block_earnings=20,
        )
    )

    async def fake_hashvalue(_mempool: object) -> SimpleNamespace:
        return SimpleNamespace(hashvalue=SimpleNamespace(sats=43000))

    monkeypatch.setattr(daemon.use_cases, "run_hashvalue", fake_hashvalue)

    row = await _tick(
        config_path=tmp_path / "missing-bids.toml",
        braiins_client=braiins_client,
        ocean_client=ocean_source,
        mempool_client=object(),
        metrics_repo=repo,
        ocean_address=BtcAddress("bc1qdazee75g3zz3zhd43awhnmjqqmx50qjh9l0v23"),
    )

    assert row.target_hashrate_phs is None
    assert row.market_price_sat is None
    assert row.braiins_current_speed_phs == Decimal("1.404")
    assert row.braiins_speed_limit_phs == Decimal("1.13")
    history = await repo.get_history(row.timestamp)
    assert len(history) == 1
