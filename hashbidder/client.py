"""Braiins Hashpower API client."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import unquote

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from hashbidder.domain.hashrate import Hashrate, HashratePrice, HashUnit
from hashbidder.domain.price_tick import PriceTick
from hashbidder.domain.progress import Progress
from hashbidder.domain.sats import Sats
from hashbidder.domain.stratum_url import StratumUrl
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.domain.upstream import Upstream
from hashbidder.domain.user_bid import BidId, BidStatus, ClOrderId, UserBid

logger = logging.getLogger(__name__)

# Use the verified working base URL
API_BASE = httpx.URL("https://hashpower.braiins.com/v1")

__all__ = [
    "API_BASE",
    "AccountBalance",
    "ApiError",
    "AskItem",
    "BidId",
    "BidItem",
    "BidStatus",
    "BraiinsClient",
    "ClOrderId",
    "CreateBidResult",
    "HashpowerClient",
    "MarketSettings",
    "OrderBook",
    "Upstream",
    "UserBid",
]


class ApiError(Exception):
    """An error returned by the Braiins API."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize with the HTTP status code and error message."""
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")

    @property
    def is_transient(self) -> bool:
        """True if the error is likely a temporary network or rate-limiting issue."""
        return self.status_code == 429 or self.status_code >= 500


@dataclass(frozen=True)
class BidItem:
    """A single bid on the order book."""

    price: HashratePrice
    hr_matched_ph: Hashrate
    amount_sat: Sats
    speed_limit_ph: Hashrate


@dataclass(frozen=True)
class AskItem:
    """A single ask on the order book."""

    price: HashratePrice
    hr_matched_ph: Hashrate
    hr_available_ph: Hashrate


@dataclass(frozen=True)
class OrderBook:
    """A snapshot of the spot market order book."""

    bids: tuple[BidItem, ...]
    asks: tuple[AskItem, ...]


@dataclass(frozen=True)
class MarketSettings:
    """Global parameters for the spot market."""

    price_tick: PriceTick
    min_bid_price_decrease_period: timedelta
    min_bid_speed_limit_decrease_period: timedelta

    @property
    def speed_cooldown_period(self) -> timedelta:
        """Alias for min_bid_speed_limit_decrease_period."""
        return self.min_bid_speed_limit_decrease_period

    @property
    def price_cooldown_period(self) -> timedelta:
        """Alias for min_bid_price_decrease_period."""
        return self.min_bid_price_decrease_period


@dataclass(frozen=True)
class AccountBalance:
    """Balances for a Braiins account."""

    available_sat: Sats
    total_sat: Sats
    blocked_sat: Sats


@dataclass(frozen=True)
class CreateBidResult:
    """The result of a successful create bid request."""

    id: BidId


class HashpowerClient(Protocol):
    """Interface for interacting with a hashpower market."""

    async def get_orderbook(self) -> OrderBook:
        """Fetch the current market order book."""
        ...

    async def get_market_settings(self) -> MarketSettings:
        """Fetch global market parameters like price ticks and cooldowns."""
        ...

    async def get_current_bids(self) -> tuple[UserBid, ...]:
        """Fetch the current user's active bids."""
        ...

    async def create_bid(
        self,
        price: HashratePrice,
        speed_limit: Hashrate,
        amount_sat: Sats,
        upstream: Upstream,
        cl_order_id: ClOrderId,
    ) -> CreateBidResult:
        """Place a new spot bid."""
        ...

    async def edit_bid(
        self,
        id: BidId,
        new_price: HashratePrice,
        new_speed_limit: Hashrate,
    ) -> None:
        """Update an existing bid's price or speed limit."""
        ...

    async def cancel_bid(self, id: BidId) -> None:
        """Cancel an existing bid."""
        ...

    async def get_account_balance(self) -> AccountBalance:
        """Fetch the authenticated account's balance."""
        ...


def _parse_user_bid(item: dict[str, Any]) -> UserBid:
    bid = item["bid"]
    state = item.get("state_estimate", {})
    counters = item.get("counters", {})
    upstream = bid.get("dest_upstream")

    def parse_phs(val: Any) -> Hashrate | None:
        if val is None:
            return None
        return Hashrate(Decimal(str(val)), HashUnit.PH, TimeUnit.SECOND)

    # Braiins v1 API Field mapping:
    # counters_estimate.shares_accepted_m -> Shares in millions
    # counters_estimate.shares_rejected_m -> Shares in millions
    def parse_shares(val: Any) -> int:
        if val is None:
            return 0
        try:
            return int(float(val) * 1_000_000)
        except (ValueError, TypeError):
            return 0

    current_speed = parse_phs(state.get("avg_speed_ph"))
    delivered_hr = parse_phs(counters.get("delivered_hr_ph"))

    return UserBid(
        id=BidId(bid["id"]),
        price=HashratePrice(
            sats=Sats(int(bid["price_sat"])),
            per=Hashrate(Decimal(1), HashUnit.EH, TimeUnit.DAY),
        ),
        speed_limit_ph=Hashrate(
            Decimal(bid["speed_limit_ph"]), HashUnit.PH, TimeUnit.SECOND
        ),
        amount_sat=Sats(int(bid["amount_sat"])),
        status=BidStatus(bid["status"]),
        progress=Progress.from_percentage(Decimal(state["progress_pct"]))
        if "progress_pct" in state
        else None,
        amount_remaining_sat=Sats(int(state["amount_remaining_sat"]))
        if "amount_remaining_sat" in state
        else None,
        last_updated=datetime.fromisoformat(bid["last_updated"]),
        upstream=Upstream(
            url=StratumUrl(upstream["url"]),
            identity=upstream["identity"],
        )
        if upstream is not None
        else None,
        shares_accepted=parse_shares(counters.get("shares_accepted_m")),
        shares_rejected=parse_shares(counters.get("shares_rejected_m")),
        current_speed=current_speed,
        delivered_hashrate=delivered_hr
        if delivered_hr and delivered_hr.value > 0
        else current_speed,
    )


def _is_transient_braiins_error(e: BaseException) -> bool:
    if isinstance(e, (httpx.TimeoutException, httpx.RequestError)):
        return True
    if isinstance(e, ApiError):
        return e.is_transient
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code == 429 or e.response.status_code >= 500
    return False


braiins_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_transient_braiins_error),
    reraise=True,
)


class BraiinsClient:
    """HTTP client for the Braiins Hashpower API."""

    def __init__(
        self, base_url: httpx.URL, api_key: str | None, http_client: httpx.AsyncClient
    ) -> None:
        """Initialize the client.

        Args:
            base_url: The base URL of the API.
            api_key: The user's API key. Read-only keys work for many methods.
            http_client: The httpx.AsyncClient to use for requests.
        """
        self._base_url = base_url
        self._api_key = api_key
        self._http = http_client

    @braiins_retry
    async def get_orderbook(self) -> OrderBook:
        """Fetch the current market order book."""
        data = await self._request("GET", "/spot/orderbook")
        return OrderBook(
            bids=tuple(
                BidItem(
                    price=HashratePrice(
                        sats=Sats(int(item["price_sat"])),
                        per=Hashrate(Decimal(1), HashUnit.EH, TimeUnit.DAY),
                    ),
                    hr_matched_ph=Hashrate(
                        Decimal(item["hr_matched_ph"]), HashUnit.PH, TimeUnit.SECOND
                    ),
                    amount_sat=Sats(int(item.get("amount_sat", 0))),
                    speed_limit_ph=Hashrate(
                        Decimal(item.get("speed_limit_ph", 0)),
                        HashUnit.PH,
                        TimeUnit.SECOND,
                    ),
                )
                for item in data["bids"]
            ),
            asks=tuple(
                AskItem(
                    price=HashratePrice(
                        sats=Sats(int(item["price_sat"])),
                        per=Hashrate(Decimal(1), HashUnit.EH, TimeUnit.DAY),
                    ),
                    hr_matched_ph=Hashrate(
                        Decimal(item["hr_matched_ph"]), HashUnit.PH, TimeUnit.SECOND
                    ),
                    hr_available_ph=Hashrate(
                        Decimal(item.get("hr_available_ph", 0)),
                        HashUnit.PH,
                        TimeUnit.SECOND,
                    ),
                )
                for item in data["asks"]
            ),
        )

    @braiins_retry
    async def get_market_settings(self) -> MarketSettings:
        """Fetch global market parameters."""
        data = await self._request("GET", "/spot/settings")
        return MarketSettings(
            price_tick=PriceTick(sats=Sats(int(data["tick_size_sat"]))),
            min_bid_price_decrease_period=timedelta(
                seconds=int(data["min_bid_price_decrease_period_s"])
            ),
            min_bid_speed_limit_decrease_period=timedelta(
                seconds=int(data["min_bid_speed_limit_decrease_period_s"])
            ),
        )

    @braiins_retry
    async def get_current_bids(self) -> tuple[UserBid, ...]:
        """Fetch the current user's active bids."""
        data = await self._request("GET", "/spot/bid/current")
        return tuple(_parse_user_bid(item) for item in data["items"])

    async def create_bid(
        self,
        price: HashratePrice,
        speed_limit: Hashrate,
        amount_sat: Sats,
        upstream: Upstream,
        cl_order_id: ClOrderId,
    ) -> CreateBidResult:
        """Place a new spot bid."""
        body = {
            "cl_order_id": str(cl_order_id),
            "price_sat": int(price.to(HashUnit.EH, TimeUnit.DAY).sats),
            "speed_limit_ph": float(speed_limit.to(HashUnit.PH, TimeUnit.SECOND).value),
            "amount_sat": int(amount_sat),
            "dest_upstream": {
                "url": str(upstream.url),
                "identity": upstream.identity,
            },
        }
        data = await self._request("POST", "/spot/bid", body=body)
        return CreateBidResult(id=BidId(data["id"]))

    async def edit_bid(
        self,
        id: BidId,
        new_price: HashratePrice,
        new_speed_limit: Hashrate,
    ) -> None:
        """Update an existing bid."""
        body = {
            "bid_id": str(id),
            "new_price_sat": int(new_price.to(HashUnit.EH, TimeUnit.DAY).sats),
            "new_speed_limit_ph": {
                "value": float(new_speed_limit.to(HashUnit.PH, TimeUnit.SECOND).value)
            },
        }
        await self._request("PUT", "/spot/bid", body=body)

    async def cancel_bid(self, id: BidId) -> None:
        """Cancel an existing bid."""
        body = {"order_id": str(id)}
        await self._request("DELETE", "/spot/bid", body=body)

    @braiins_retry
    async def get_account_balance(self) -> AccountBalance:
        """Fetch the authenticated account's balance."""
        data = await self._request("GET", "/account/balance")
        accounts = data["accounts"]
        if len(accounts) != 1:
            raise ValueError(
                f"expected exactly one account in balance response, got {len(accounts)}"
            )
        account = accounts[0]
        return AccountBalance(
            available_sat=Sats(int(account["available_balance_sat"])),
            total_sat=Sats(int(account["total_balance_sat"])),
            blocked_sat=Sats(int(account["blocked_balance_sat"])),
        )

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        """Issue an authenticated request to the Braiins API."""
        url = f"{self._base_url}{path}"
        logger.debug("Braiins Request: %s %s", method, url)
        response = await self._http.request(
            method, url, json=body, headers=self._auth_headers()
        )
        logger.debug("Response %s (%d bytes)", response.status_code, len(response.text))
        if not response.is_success:
            self._raise_api_error(response)

        if not response.text:
            return None

        data = response.json()
        logger.debug("Braiins JSON: %s", data)
        return data

    def _auth_headers(self) -> dict[str, str]:
        """Build the required authentication headers."""
        if not self._api_key:
            return {}
        return {"apikey": self._api_key}

    def _raise_api_error(self, response: httpx.Response) -> None:
        """Parse error message from response and raise ApiError."""
        grpc_msg = response.headers.get("grpc-message")
        if grpc_msg:
            message = unquote(grpc_msg)
        else:
            try:
                data = response.json()
                message = data.get("message") or response.text
            except ValueError:
                message = response.text

        raise ApiError(response.status_code, message)
