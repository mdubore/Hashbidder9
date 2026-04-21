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

    selected = getattr(daemon, "_select_actual_ocean_hashrate_phs", None)

    assert callable(selected)
    assert selected(stats) == Decimal("0.91")
