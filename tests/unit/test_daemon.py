"""Tests for daemon metric selection helpers."""

from decimal import Decimal

from hashbidder.daemon import _select_ocean_hashrate_phs
from hashbidder.domain.hashrate import Hashrate, HashUnit
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.ocean_client import AccountStats, HashrateWindow, OceanTimeWindow


def _ph_s(value: str) -> Hashrate:
    return Hashrate(Decimal(value), HashUnit.PH, TimeUnit.SECOND)


def test_select_ocean_hashrate_returns_requested_window() -> None:
    """A specific Ocean window is returned without cross-window fallback."""
    stats = AccountStats(
        windows=(
            HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.1")),
            HashrateWindow(window=OceanTimeWindow.TEN_MINUTES, hashrate=_ph_s("0.28")),
            HashrateWindow(window=OceanTimeWindow.SIXTY_SECONDS, hashrate=_ph_s("0.91")),
        )
    )

    assert (
        _select_ocean_hashrate_phs(stats, OceanTimeWindow.SIXTY_SECONDS)
        == Decimal("0.91")
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
