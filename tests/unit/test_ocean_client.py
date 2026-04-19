"""Tests for OceanClient JSON parsing and error handling."""

from decimal import Decimal

import httpx
import pytest

from hashbidder.domain.btc_address import BtcAddress
from hashbidder.domain.hashrate import HashUnit
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.ocean_client import OceanClient, OceanError, OceanTimeWindow

_VALID_JSON = {
    "hashrate_24h": 1885800000000000,
    "hashrate_3h": 1850000000000000,
    "hashrate_1h": 1800000000000000,
    "shares_window": 123,
    "estimated_rewards": 456,
    "next_block_earnings": 789,
}


def _make_client(handler: httpx.MockTransport) -> OceanClient:
    return OceanClient(
        base_url=httpx.URL("https://api.example.com/"),
        http_client=httpx.AsyncClient(transport=handler),
    )


class TestGetAccountStats:
    """Tests for OceanClient.get_account_stats."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        """Valid JSON response is parsed into correct AccountStats."""
        address_str = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"

        def handler(request: httpx.Request) -> httpx.Response:
            assert address_str in str(request.url)
            return httpx.Response(200, json=_VALID_JSON)

        client = _make_client(httpx.MockTransport(handler))
        stats = await client.get_account_stats(BtcAddress(address_str))

        assert len(stats.windows) == 3
        assert stats.windows[0].window == OceanTimeWindow.DAY
        assert stats.windows[0].hashrate.value == Decimal("1885800000000000")
        assert stats.windows[0].hashrate.hash_unit == HashUnit.H
        assert stats.windows[0].hashrate.time_unit == TimeUnit.SECOND

        assert stats.windows[1].window == OceanTimeWindow.THREE_HOURS
        assert stats.windows[2].window == OceanTimeWindow.ONE_HOUR

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
