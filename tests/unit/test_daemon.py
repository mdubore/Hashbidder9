"""Tests for daemon metric selection helpers."""

from decimal import Decimal

from hashbidder import daemon
from hashbidder.domain.hashrate import Hashrate, HashUnit
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.ocean_client import AccountStats, HashrateWindow, OceanTimeWindow


def _ph_s(value: str) -> Hashrate:
    return Hashrate(Decimal(value), HashUnit.PH, TimeUnit.SECOND)


def test_select_actual_ocean_hashrate_prefers_five_minutes_over_ten_minutes() -> None:
    """The dashboard "actual" value should use the 5-minute Ocean window."""
    stats = AccountStats(
        windows=(
            HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.1")),
            HashrateWindow(window=OceanTimeWindow.TEN_MINUTES, hashrate=_ph_s("0.28")),
            HashrateWindow(window=OceanTimeWindow.FIVE_MINUTES, hashrate=_ph_s("0.91")),
        )
    )

    # Accessing the helper for testing
    selected = getattr(daemon, "_select_actual_ocean_hashrate_phs", None)
    assert callable(selected)
    assert selected(stats) == Decimal("0.91")


def test_select_actual_ocean_hashrate_falls_back_to_ten_minutes() -> None:
    """If 5-minute window is missing, fall back to 10-minute."""
    stats = AccountStats(
        windows=(
            HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.1")),
            HashrateWindow(window=OceanTimeWindow.TEN_MINUTES, hashrate=_ph_s("0.28")),
        )
    )
    selected = getattr(daemon, "_select_actual_ocean_hashrate_phs", None)
    assert selected(stats) == Decimal("0.28")


def test_select_actual_ocean_hashrate_falls_back_to_day() -> None:
    """If both 5 and 10-minute windows are missing, fall back to DAY."""
    stats = AccountStats(
        windows=(
            HashrateWindow(window=OceanTimeWindow.DAY, hashrate=_ph_s("0.1")),
        )
    )
    selected = getattr(daemon, "_select_actual_ocean_hashrate_phs", None)
    assert selected(stats) == Decimal("0.1")


def test_select_actual_ocean_hashrate_returns_zero_if_missing_windows() -> None:
    """If no preferred hashrate windows are present, return 0.0."""
    # Case 1: Empty windows
    stats_empty = AccountStats(windows=())
    selected = getattr(daemon, "_select_actual_ocean_hashrate_phs", None)
    assert selected(stats_empty) == Decimal(0)

    # Case 2: Windows present but none match preference (5m, 10m, DAY)
    stats_no_match = AccountStats(
        windows=(
            HashrateWindow(window=OceanTimeWindow.ONE_HOUR, hashrate=_ph_s("0.5")),
        )
    )
    assert selected(stats_no_match) == Decimal(0)
