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
