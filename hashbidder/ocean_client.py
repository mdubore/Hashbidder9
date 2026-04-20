"""Ocean.xyz API client for account hashrate stats."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from hashbidder.domain.btc_address import BtcAddress
from hashbidder.domain.hashrate import Hashrate, HashUnit
from hashbidder.domain.time_unit import TimeUnit

logger = logging.getLogger(__name__)

DEFAULT_OCEAN_URL = httpx.URL("https://api.ocean.xyz/v1/user_hashrate/")


class OceanTimeWindow(Enum):
    """Hashrate averaging windows returned by Ocean."""

    DAY = "24 hrs"
    THREE_HOURS = "3 hrs"
    ONE_HOUR = "1 hr"
    TEN_MINUTES = "10 min"
    FIVE_MINUTES = "5 min"
    SIXTY_SECONDS = "60 sec"


class OceanError(Exception):
    """An error returned by or when parsing the Ocean API."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize with the HTTP status code and error message."""
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


def _is_transient_ocean_error(e: BaseException) -> bool:
    if isinstance(e, (httpx.TimeoutException, httpx.RequestError)):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code == 429 or e.response.status_code >= 500
    if isinstance(e, OceanError):
        return e.status_code == 429 or e.status_code >= 500
    return False


ocean_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_transient_ocean_error),
    reraise=True,
)


@dataclass(frozen=True)
class HashrateWindow:
    """A single hashrate measurement over a time window."""

    window: OceanTimeWindow
    hashrate: Hashrate


@dataclass(frozen=True)
class AccountStats:
    """Hashrate stats for an Ocean account across all time windows."""

    windows: tuple[HashrateWindow, ...]
    shares_window: int | None = None
    estimated_rewards: int | None = None
    next_block_earnings: int | None = None


class OceanSource(Protocol):
    """Protocol for Ocean data sources."""

    async def get_account_stats(self, address: BtcAddress) -> AccountStats:
        """Fetch hashrate stats for the given address."""
        ...


def _parse_json(data: dict[str, Any]) -> AccountStats:
    """Parse the Ocean hashrate JSON response into AccountStats."""
    logger.debug("Parsing Ocean JSON: %s", data)
    windows: list[HashrateWindow] = []

    # Map API keys to internal enum members.
    mapping = {
        "hashrate_24h": OceanTimeWindow.DAY,
        "hashrate_3h": OceanTimeWindow.THREE_HOURS,
        "hashrate_1h": OceanTimeWindow.ONE_HOUR,
        "hashrate_15m": OceanTimeWindow.TEN_MINUTES,
        "hashrate_5m": OceanTimeWindow.FIVE_MINUTES,
    }

    # Some versions of the API use hashrate_day instead of hashrate_24h
    if "hashrate_day" in data and "hashrate_24h" not in data:
        data["hashrate_24h"] = data["hashrate_day"]

    for key, window_enum in mapping.items():
        val = data.get(key)
        if val is not None:
            # Handle both raw numbers and nested objects {"value": 1.2, ...}
            if isinstance(val, dict):
                raw_val = val.get("value") or val.get("hashrate") or 0
            else:
                raw_val = val

            hashrate = Hashrate(
                value=Decimal(str(raw_val)),
                hash_unit=HashUnit.H,
                time_unit=TimeUnit.SECOND,
            )
            windows.append(HashrateWindow(window=window_enum, hashrate=hashrate))

    # Also handle nested objects if present
    if "hashrates" in data and isinstance(data["hashrates"], dict):
        for key, val in data["hashrates"].items():
            if key in mapping:
                hashrate = Hashrate(
                    value=Decimal(str(val)),
                    hash_unit=HashUnit.H,
                    time_unit=TimeUnit.SECOND,
                )
                windows.append(HashrateWindow(window=mapping[key], hashrate=hashrate))

    return AccountStats(
        windows=tuple(windows),
        shares_window=data.get("shares_in_window") or data.get("shares_window"),
        estimated_rewards=data.get("estimated_rewards_in_window")
        or data.get("estimated_rewards"),
        next_block_earnings=data.get("estimated_earnings_next_block")
        or data.get("next_block_earnings")
        or data.get("estimated_earnings"),
    )


class OceanClient:
    """HTTP client for Ocean.xyz hashrate stats."""

    def __init__(self, base_url: httpx.URL, http_client: httpx.AsyncClient) -> None:
        """Initialize the client.

        Args:
            base_url: The base URL of the Ocean.xyz instance.
            http_client: The httpx.AsyncClient to use for requests.
        """
        self._base_url = base_url
        self._http = http_client

    @ocean_retry
    async def get_account_stats(self, address: BtcAddress) -> AccountStats:
        """Fetch hashrate stats for the given address.

        Raises:
            OceanError: On HTTP errors or unexpected response schema.
        """
        url = f"{self._base_url}{address.value}"
        resp = await self._http.get(url)
        if not resp.is_success:
            raise OceanError(
                resp.status_code,
                resp.text or resp.reason_phrase or "Unknown error",
            )
        try:
            data = resp.json()
        except ValueError as e:
            raise OceanError(200, f"invalid JSON response: {e}") from e

        if not isinstance(data, dict):
            raise OceanError(200, f"expected JSON object, got {type(data).__name__}")

        return _parse_json(data)
