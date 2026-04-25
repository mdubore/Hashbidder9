"""Pure computations for target-hashrate mode."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from hashbidder.client import BidStatus, MarketSettings, OrderBook, UserBid
from hashbidder.domain.bid_config import BidConfig
from hashbidder.domain.hashrate import Hashrate, HashratePrice, HashUnit
from hashbidder.domain.price_tick import PriceTick
from hashbidder.domain.time_unit import TimeUnit


def _is_being_served(bid: UserBid) -> bool:
    """Whether this bid is currently matched AND delivering.

    Requires BidStatus.ACTIVE plus a positive current_speed report.

    Why both signals (deliberate false-negative tradeoff):
      - BidStatus.ACTIVE alone can lag reality. A bid may briefly show
        ACTIVE after delivery has stopped; preserving such a bid would
        suppress needed repricing.
      - A missing current_speed (None) also fails this check. We
        deliberately choose false negatives over false positives: during
        a transient telemetry gap we'd rather allow a one-tick repricing
        than persistently lock a bid that may no longer be served.
      - Sustained telemetry loss is out of scope for this predicate.
        The upstream client owns that concern; we use only the signals
        the UserBid carries, without staleness fallbacks.
    """
    if bid.status != BidStatus.ACTIVE:
        return False
    return bid.current_speed is not None and bid.current_speed.value > 0


def compute_needed_hashrate(target: Hashrate, current_24h: Hashrate) -> Hashrate:
    """Hashrate to buy now so the 12h-forward 24h average equals target.

    Assumes a 12-hour horizon: if we add `needed` for the next 12 hours, the
    rolling 24h average will land at `target`. Clamped to zero when already
    at or above target.
    """
    twice = target + target
    if current_24h >= twice:
        return Hashrate(Decimal(0), HashUnit.PH, TimeUnit.SECOND)
    return (twice - current_24h).to(HashUnit.PH, TimeUnit.SECOND)


def distribute_bids(needed: Hashrate, max_bids_count: int) -> tuple[Hashrate, ...]:
    """Split a needed hashrate into per-bid speed limits in PH/s.

    Uses as many bids as possible up to `max_bids_count`, with each bid >= 1 PH/s
    and the total summing to `needed` (rounded to 0.01 PH/s precision).
    Returns an empty tuple to mean "cancel all bids".
    """
    if max_bids_count < 1:
        raise ValueError(f"max_bids_count must be >= 1, got {max_bids_count}")

    needed_ph = needed.to(HashUnit.PH, TimeUnit.SECOND).value
    if needed_ph < Decimal("0.5"):
        return ()
    if needed_ph < 1:
        return (Hashrate(Decimal(1), HashUnit.PH, TimeUnit.SECOND),)

    n = min(max_bids_count, int(needed_ph))
    share = (needed_ph / Decimal(n)).quantize(Decimal("0.01"))
    return tuple(Hashrate(share, HashUnit.PH, TimeUnit.SECOND) for _ in range(n))


@dataclass(frozen=True)
class CooldownInfo:
    """Whether a bid is still in its decrease cooldown windows.

    A True flag means the corresponding field cannot be lowered yet — the
    Braiins API enforces a minimum delay between consecutive decreases.
    Increases are always allowed.
    """

    price_cooldown: bool
    speed_cooldown: bool


@dataclass(frozen=True)
class BidWithCooldown:
    """A bid paired with its current cooldown status."""

    bid: UserBid
    cooldown: CooldownInfo


def check_cooldowns(
    bids: tuple[UserBid, ...],
    settings: MarketSettings,
    now: datetime,
) -> tuple[BidWithCooldown, ...]:
    """Annotate each bid with its current price/speed cooldown status."""
    return tuple(
        BidWithCooldown(
            bid=bid,
            cooldown=CooldownInfo(
                price_cooldown=(
                    now - bid.last_updated < settings.min_bid_price_decrease_period
                ),
                speed_cooldown=(
                    now - bid.last_updated
                    < settings.min_bid_speed_limit_decrease_period
                ),
            ),
        )
        for bid in bids
    )


def plan_with_cooldowns(
    desired_price: HashratePrice,
    needed: Hashrate,
    max_bids_count: int,
    bids: tuple[BidWithCooldown, ...],
) -> tuple[BidConfig, ...]:
    """Build a bid plan that respects per-bid cooldown constraints.

    Rules:
      - speed_cooldown=True: keep the bid's current speed limit (cannot lower).
        Such a bid consumes one slot from `max_bids_count` and its current
        speed is subtracted from `needed`.
      - price_cooldown=True (and not speed_cooldown): keep the bid's current
        price; speed is freely re-assigned from the remaining distribution.
      - Bids with no cooldown are treated as fresh slots at `desired_price`.

    The remaining hashrate budget is split via `distribute_bids` and assigned
    first to price-locked bids (preserving their old price), then to brand-new
    slots at `desired_price`.
    """
    speed_locked = [b for b in bids if b.cooldown.speed_cooldown]
    price_locked_only = [
        b for b in bids if b.cooldown.price_cooldown and not b.cooldown.speed_cooldown
    ]

    locked_speed_total = Hashrate(Decimal(0), HashUnit.PH, TimeUnit.SECOND)
    for entry in speed_locked:
        locked_speed_total = locked_speed_total + entry.bid.speed_limit_ph

    locked_entries = tuple(
        BidConfig(
            price=entry.bid.price if entry.cooldown.price_cooldown else desired_price,
            speed_limit=entry.bid.speed_limit_ph,
        )
        for entry in speed_locked
    )

    if needed > locked_speed_total:
        remaining = needed - locked_speed_total
    else:
        remaining = Hashrate(Decimal(0), HashUnit.PH, TimeUnit.SECOND)

    remaining_slots = max(0, max_bids_count - len(speed_locked))
    speeds = distribute_bids(remaining, remaining_slots) if remaining_slots else ()

    free_entries: list[BidConfig] = []
    for i, speed in enumerate(speeds):
        if i < len(price_locked_only):
            entry = price_locked_only[i]
            free_entries.append(BidConfig(price=entry.bid.price, speed_limit=speed))
        else:
            free_entries.append(BidConfig(price=desired_price, speed_limit=speed))

    return locked_entries + tuple(free_entries)


def find_market_price(
    orderbook: OrderBook,
    tick: PriceTick,
    max_price: HashratePrice | None = None,
) -> HashratePrice:
    """Lowest served bid, undercut (from above) by one price tick.

    The cheapest served price is aligned down to the tick grid first to
    guarantee the result lands on a valid tick. If `max_price` is provided,
    the result is capped at `max_price` aligned down to the tick. A cap
    that aligns to zero at the current tick is rejected to avoid silently
    pinning at a sub-market price.

    Raises:
        ValueError: If the order book has no served bid, or if
            max_price aligns to zero at the current tick.
    """
    served = [b for b in orderbook.bids if b.hr_matched_ph.value > 0]
    if not served:
        raise ValueError("Order book has no served bids; cannot pick a price")
    cheapest = min(served, key=lambda b: b.price.sats)
    candidate = tick.add_one(tick.align_down(cheapest.price))
    if max_price is None:
        return candidate
    cap = tick.align_down(max_price)
    cap_sats = int(cap.to(HashUnit.EH, TimeUnit.DAY).sats)
    if cap_sats == 0:
        raise ValueError(
            f"max_price {max_price} aligns to zero at tick "
            f"{int(tick.sats)} sat/EH/Day; choose a cap >= one tick"
        )
    candidate_sats = int(candidate.to(HashUnit.EH, TimeUnit.DAY).sats)
    if candidate_sats > cap_sats:
        return cap
    return candidate
