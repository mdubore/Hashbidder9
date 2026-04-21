"""Ocean.xyz API and Scraper client for account statistics."""

import logging
import re
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
STATS_PAGE_URL = "https://ocean.xyz/stats/"


class OceanTimeWindow(Enum):
    """Hashrate averaging windows returned by Ocean."""

    DAY = "24 hrs"
    THREE_HOURS = "3 hrs"
    ONE_HOUR = "1 hr"
    TEN_MINUTES = "10 min"
    FIVE_MINUTES = "5 min"
    SIXTY_SECONDS = "60 sec"


class OceanError(Exception):
    """An error returned by or when parsing the Ocean API/Scraper."""

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


def _parse_ocean_html(html: str) -> dict[str, int]:
    """Scrape rewards and shares from the Ocean stats HTML."""
    res = {}
    
    # Shares In Reward Window
    # Pattern: <div class="blocks-label">Shares In Reward Window</div> <span>11.78G</span>
    share_match = re.search(r"Shares In Reward Window.*?<span>([\d.]+)([KMG]?)", html, re.DOTALL | re.IGNORECASE)
    if share_match:
        val = float(share_match.group(1))
        suffix = share_match.group(2).upper()
        multiplier = 1
        if suffix == 'K': multiplier = 1_000
        elif suffix == 'M': multiplier = 1_000_000
        elif suffix == 'G': multiplier = 1_000_000_000
        res["shares_window"] = int(val * multiplier)

    # Estimated Rewards In Window
    # Pattern: <span>0.00027141 BTC</span>
    reward_match = re.search(r"Estimated Rewards In Window.*?<span>([\d.]+) BTC</span>", html, re.DOTALL | re.IGNORECASE)
    if reward_match:
        btc_val = Decimal(reward_match.group(1))
        res["estimated_rewards"] = int(btc_val * 100_000_000)

    # Estimated Earnings Next Block
    # Pattern: <span>0.00003374 BTC</span>
    next_match = re.search(r"Estimated Earnings Next Block.*?<span>([\d.]+) BTC</span>", html, re.DOTALL | re.IGNORECASE)
    if next_match:
        btc_val = Decimal(next_match.group(1))
        res["next_block_earnings"] = int(btc_val * 100_000_000)

    return res


class OceanClient:
    """Hybrid client for Ocean.xyz stats (API for hashrate, Scraper for rewards)."""

    def __init__(self, base_url: httpx.URL, http_client: httpx.AsyncClient) -> None:
        """Initialize the client.

        Args:
            base_url: The base URL of the Ocean.xyz API instance.
            http_client: The httpx.AsyncClient to use for requests.
        """
        self._base_url = base_url
        self._http = http_client

    @ocean_retry
    async def get_account_stats(self, address: BtcAddress) -> AccountStats:
        """Fetch hashrate stats and scraped reward data."""
        # 1. Fetch JSON hashrate (Reliable API)
        api_url = f"{self._base_url}{address.value}"
        api_resp = await self._http.get(api_url)
        
        windows: list[HashrateWindow] = []
        if api_resp.is_success:
            data = api_resp.json()
            result = data.get("result", {})
            
            mapping = {
                "hashrate_86400s": OceanTimeWindow.DAY,
                "hashrate_10800s": OceanTimeWindow.THREE_HOURS,
                "hashrate_3600s": OceanTimeWindow.ONE_HOUR,
                "hashrate_600s": OceanTimeWindow.TEN_MINUTES,
                "hashrate_300s": OceanTimeWindow.FIVE_MINUTES,
                "hashrate_60s": OceanTimeWindow.SIXTY_SECONDS,
            }
            for key, window_enum in mapping.items():
                if key in result:
                    hashrate = Hashrate(
                        value=Decimal(str(result[key])),
                        hash_unit=HashUnit.H,
                        time_unit=TimeUnit.SECOND,
                    )
                    windows.append(HashrateWindow(window=window_enum, hashrate=hashrate))

        # 2. Fetch HTML stats (Scrape rewards/shares)
        html_url = f"{STATS_PAGE_URL}{address.value}"
        html_resp = await self._http.get(html_url)
        scraped = {}
        if html_resp.is_success:
            scraped = _parse_ocean_html(html_resp.text)
        else:
            logger.warning("Failed to scrape Ocean stats page: %s", html_resp.status_code)

        return AccountStats(
            windows=tuple(windows),
            shares_window=scraped.get("shares_window"),
            estimated_rewards=scraped.get("estimated_rewards"),
            next_block_earnings=scraped.get("next_block_earnings"),
        )
