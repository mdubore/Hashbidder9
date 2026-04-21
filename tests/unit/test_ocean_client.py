"""Tests for OceanClient JSON parsing and error handling."""

from decimal import Decimal

import httpx
import pytest

from hashbidder.domain.btc_address import BtcAddress
from hashbidder.ocean_client import OceanClient, OceanError, OceanTimeWindow

_VALID_API_JSON = {
    "result": {
        "hashrate_86400s": 1885800000000000,
        "hashrate_10800s": 1850000000000000,
        "hashrate_3600s": 1800000000000000,
    }
}

_VALID_HTML = """
<div class="blocks-label">Shares In Reward Window</div> <span>123</span>
<div class="blocks-label">Estimated Rewards In Window</div> 
<span>0.00000456 BTC</span>
<div class="blocks-label">Estimated Earnings Next Block</div> 
<span>0.00000789 BTC</span>
"""


def _make_client(handler: httpx.MockTransport) -> OceanClient:
    return OceanClient(
        base_url=httpx.URL("https://api.example.com/"),
        http_client=httpx.AsyncClient(transport=handler),
    )


class TestGetAccountStats:
    """Tests for OceanClient.get_account_stats."""

    @pytest.mark.asyncio
    async def test_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid JSON and HTML are parsed into correct AccountStats."""
        address_str = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
        monkeypatch.setattr(
            "hashbidder.ocean_client.STATS_PAGE_URL", "https://html.example.com/"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if "api.example.com" in str(request.url):
                return httpx.Response(200, json=_VALID_API_JSON)
            return httpx.Response(200, text=_VALID_HTML)

        client = _make_client(httpx.MockTransport(handler))
        stats = await client.get_account_stats(BtcAddress(address_str))

        assert len(stats.windows) == 3
        assert stats.windows[0].window == OceanTimeWindow.DAY
        assert stats.windows[0].hashrate.value == Decimal("1885800000000000")

        assert stats.shares_window == 123
        assert stats.estimated_rewards == 456
        assert stats.next_block_earnings == 789

    @pytest.mark.asyncio
    async def test_invalid_json(self) -> None:
        """Invalid JSON raises OceanError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(OceanError, match="invalid JSON response"):
            await client.get_account_stats(
                BtcAddress("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
            )

    @pytest.mark.asyncio
    async def test_not_an_object(self) -> None:
        """JSON that isn't a dict raises OceanError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[1, 2, 3])

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(OceanError, match="expected JSON object"):
            await client.get_account_stats(
                BtcAddress("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
            )

    @pytest.mark.asyncio
    async def test_http_error(self) -> None:
        """Non-2xx response raises OceanError with status code."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal server error")

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(OceanError) as exc_info:
            await client.get_account_stats(
                BtcAddress("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
            )
        assert exc_info.value.status_code == 500
