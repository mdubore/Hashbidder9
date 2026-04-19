"""Braiins Hashpower API client."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from hashbidder.domain.hashrate import Hashrate, HashratePrice, HashUnit
from hashbidder.domain.progress import Progress
from hashbidder.domain.sats import Sats
from hashbidder.domain.stratum_url import StratumUrl
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.domain.upstream import Upstream
from hashbidder.domain.user_bid import BidId, BidStatus, UserBid

logger = logging.getLogger(__name__)

API_BASE = httpx.URL("https://hashpower.braiins.com/api/v1")


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


@dataclass(frozen=True)
class AskItem:
    """A single ask on the order book."""

    price: HashratePrice
    hr_matched_ph: Hashrate


@dataclass(frozen=True)
class OrderBook:
    """A snapshot of the spot market order book."""

    bids: tuple[BidItem, ...]
    asks: tuple[AskItem, ...]


@dataclass(frozen=True)
class MarketSettings:
    """Global parameters for the spot market."""

    price_tick: Sats
    speed_cooldown_period: timedelta
    price_cooldown_period: timedelta


@dataclass(frozen=True)
class AccountBalance:
    """Balances for a Braiins account."""

    available_sat: Sats
    total_sat: Sats


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
        amount: Sats,
        upstream: Upstream,
    ) -> BidId:
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
    state = item.get("state_estimate")
    counters = item.get("counters")
    upstream = bid.get("dest_upstream")

    # Current speed and delivered hashrate are typically in H/s as integers
    def parse_hr(val: Any) -> Hashrate | None:
        if val is None:
            return None
        return Hashrate(Decimal(str(val)), HashUnit.H, TimeUnit.SECOND)

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
        if state and "progress_pct" in state
        else None,
        amount_remaining_sat=Sats(int(state["amount_remaining_sat"]))
        if state and "amount_remaining_sat" in state
        else None,
        last_updated=datetime.fromisoformat(bid["last_updated"]),
        upstream=Upstream(
            url=StratumUrl(upstream["url"]),
            identity=upstream["identity"],
        )
        if upstream is not None
        else None,
        shares_accepted=int(counters["accepted_shares"])
        if counters and "accepted_shares" in counters
        else None,
        shares_rejected=int(counters["rejected_shares"])
        if counters and "rejected_shares" in counters
        else None,
        current_speed=parse_hr(state.get("speed_hr")) if state else None,
        delivered_hashrate=parse_hr(counters.get("delivered_hr")) if counters else None,
    )


def _is_transient_braiins_error(e: BaseException) -> bool:
    if isinstance(e, (httpx.TimeoutException, httpx.RequestError)):
        return True
    if isinstance(e, ApiError):
        return e.is_transient
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code == 429 or e.response.status_code >= 500
    return False


# Define a decorator for reuse
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
                )
                for item in data["asks"]
            ),
        )

    @braiins_retry
    async def get_market_settings(self) -> MarketSettings:
        """Fetch global market parameters."""
        data = await self._request("GET", "/spot/settings")
        return MarketSettings(
            price_tick=Sats(int(data["price_tick_sat"])),
            speed_cooldown_period=timedelta(seconds=int(data["speed_edit_cooldown_s"])),
            price_cooldown_period=timedelta(seconds=int(data["price_edit_cooldown_s"])),
        )

    @braiins_retry
    async def get_current_bids(self) -> tuple[UserBid, ...]:
        """Fetch the current user's active bids."""
        data = await self._request("GET", "/spot/bid/current")
        return tuple(_parse_user_bid(item) for item in data)

    async def create_bid(
        self,
        price: HashratePrice,
        speed_limit: Hashrate,
        amount: Sats,
        upstream: Upstream,
    ) -> BidId:
        """Place a new spot bid."""
        body = {
            "price_sat": int(price.to(HashUnit.EH, TimeUnit.DAY).sats),
            "speed_limit_ph": float(speed_limit.to(HashUnit.PH, TimeUnit.SECOND).value),
            "amount_sat": int(amount),
            "dest_upstream": {
                "url": str(upstream.url),
                "identity": upstream.identity,
            },
        }
        data = await self._request("POST", "/spot/bid/create", body=body)
        return BidId(data["id"])

    async def edit_bid(
        self,
        id: BidId,
        new_price: HashratePrice,
        new_speed_limit: Hashrate,
    ) -> None:
        """Update an existing bid."""
        body = {
            "id": str(id),
            "price_sat": int(new_price.to(HashUnit.EH, TimeUnit.DAY).sats),
            "speed_limit_ph": float(
                new_speed_limit.to(HashUnit.PH, TimeUnit.SECOND).value
            ),
        }
        await self._request("POST", "/spot/bid/edit", body=body)

    async def cancel_bid(self, id: BidId) -> None:
        """Cancel an existing bid."""
        body = {"id": str(id)}
        await self._request("POST", "/spot/bid/cancel", body=body)

    @braiins_retry
    async def get_account_balance(self) -> AccountBalance:
        """Fetch the authenticated account's balance."""
        data = await self._request("GET", "/account/balance")
        # The API returns a list of balances by asset; we assume BTC for now.
        for bal in data:
            if bal["asset"] == "BTC":
                return AccountBalance(
                    available_sat=Sats(int(bal["available_sat"])),
                    total_sat=Sats(int(bal["total_sat"])),
                )
        raise ApiError(200, "BTC balance not found in account response")

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        """Issue an authenticated request to the Braiins API."""
        url = f"{self._base_url}{path}"
        response = await self._http.request(
            method, url, json=body, headers=self._auth_headers()
        )
        logger.debug("Response %s (%d bytes)", response.status_code, len(response.text))
        if not response.is_success:
            self._raise_api_error(response)

        # Some endpoints return empty body on success
        if not response.text:
            return None

        return response.json()

    def _auth_headers(self) -> dict[str, str]:
        """Build the required authentication headers."""
        if not self._api_key:
            return {}
        return {"X-Api-Key": self._api_key}

    def _raise_api_error(self, response: httpx.Response) -> None:
        """Parse error message from response and raise ApiError."""
        try:
            data = response.json()
            # The API often returns errors in a "message" field or nested.
            message = data.get("message") or response.text
        except ValueError:
            # Fallback to gRPC header if present (Braiins API style)
            message = response.headers.get("grpc-message") or response.text

        raise ApiError(response.status_code, message)
