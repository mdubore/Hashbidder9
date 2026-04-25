"""Tests for dashboard index page rendering."""

import json
import re
import time
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

import hashbidder.dashboard as dashboard
from hashbidder.metrics import MetricRow, MetricsRepo


@pytest_asyncio.fixture
async def metrics_repo(tmp_path: Path) -> MetricsRepo:
    """Create a temporary metrics repository for dashboard tests."""
    db_path = tmp_path / "dashboard.sqlite"
    repo = MetricsRepo(str(db_path))
    await repo.init_db()
    return repo


@pytest.mark.asyncio
async def test_index_embeds_parseable_history_json(
    monkeypatch: pytest.MonkeyPatch, metrics_repo: MetricsRepo
) -> None:
    """The embedded history-json script should contain valid JSON."""
    await metrics_repo.insert(
        MetricRow(
            timestamp=int(time.time()),
            braiins_hashrate_phs=Decimal("1.125"),
            ocean_hashrate_phs=Decimal("1.585"),
            braiins_connected=True,
            ocean_connected=True,
            mempool_connected=True,
            ocean_hashrate_60s_phs=Decimal("1.585"),
            ocean_hashrate_600s_phs=Decimal("1.250"),
            ocean_hashrate_86400s_phs=Decimal("0.950"),
            braiins_current_speed_phs=Decimal("1.210"),
            braiins_speed_limit_phs=Decimal("1.130"),
            braiins_delivered_hashrate_phs=Decimal("1.040"),
            target_hashrate_phs=Decimal("1.000"),
            needed_hashrate_phs=Decimal("0.000"),
            market_price_sat=47072,
            balance_sat=161064,
            braiins_shares_accepted=8877768704,
            braiins_shares_rejected=2883584,
            ocean_shares_window=31090000000,
            ocean_estimated_rewards_sat=71649,
            ocean_next_block_earnings_sat=8916,
            hashvalue_sat=43000,
            active_bid_price_sat=47072,
        )
    )
    monkeypatch.setattr(dashboard, "repo", metrics_repo)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=dashboard.app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    match = re.search(
        r'<script id="history-json" type="application/json">\s*(\[.*?\])\s*</script>',
        response.text,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert payload[-1]["ocean_hashrate_60s_phs"] == "1.585"
    assert payload[-1]["braiins_current_speed_phs"] == "1.210"
    assert payload[-1]["braiins_speed_limit_phs"] == "1.130"
    assert "Braiins Estimated Speed" in response.text
    assert "Braiins Speed Limit" in response.text
    assert "Braiins Delivered Avg" not in response.text


class TestSaveConfigToToml:
    """Round-trip tests for dashboard.save_config_to_toml."""

    def test_target_hashrate_with_max_price_round_trip(self, tmp_path: Path) -> None:
        """Writing + reading target-hashrate config with max_price is lossless."""
        from hashbidder.config import TargetHashrateConfig, load_config
        from hashbidder.dashboard import save_config_to_toml

        path = tmp_path / "bids.toml"
        save_config_to_toml(
            {
                "mode": "target-hashrate",
                "default_amount_sat": 100000,
                "target_hashrate_ph_s": Decimal("10.0"),
                "max_bids_count": 3,
                "max_price_sat_per_ph_day": 750,
                "upstream": {
                    "url": "stratum+tcp://pool.example.com:3333",
                    "identity": "worker1",
                },
            },
            path,
        )
        config = load_config(path)
        assert isinstance(config, TargetHashrateConfig)
        assert config.max_price is not None
        assert int(config.max_price.sats) == 750

    def test_target_hashrate_without_max_price_round_trip(self, tmp_path: Path) -> None:
        """Writing target-hashrate config without max_price is lossless."""
        from hashbidder.config import TargetHashrateConfig, load_config
        from hashbidder.dashboard import save_config_to_toml

        path = tmp_path / "bids.toml"
        save_config_to_toml(
            {
                "mode": "target-hashrate",
                "default_amount_sat": 100000,
                "target_hashrate_ph_s": Decimal("10.0"),
                "max_bids_count": 3,
                "max_price_sat_per_ph_day": None,
                "upstream": {
                    "url": "stratum+tcp://pool.example.com:3333",
                    "identity": "worker1",
                },
            },
            path,
        )
        config = load_config(path)
        assert isinstance(config, TargetHashrateConfig)
        assert config.max_price is None
