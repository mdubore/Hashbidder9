"""Tests for target-hashrate pure computations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hashbidder.client import BidItem, BidStatus, MarketSettings, OrderBook
from hashbidder.domain.hashrate import Hashrate, HashratePrice, HashUnit
from hashbidder.domain.price_tick import PriceTick
from hashbidder.domain.sats import Sats
from hashbidder.domain.time_unit import TimeUnit
from hashbidder.target_hashrate import (
    BidWithCooldown,
    CooldownInfo,
    _is_being_served,
    check_cooldowns,
    compute_needed_hashrate,
    distribute_bids,
    find_market_price,
    plan_with_cooldowns,
)
from tests.conftest import make_user_bid

EH_DAY = Hashrate(Decimal(1), HashUnit.EH, TimeUnit.DAY)
PH_DAY = Hashrate(Decimal(1), HashUnit.PH, TimeUnit.DAY)


def _ph_s(value: str) -> Hashrate:
    return Hashrate(Decimal(value), HashUnit.PH, TimeUnit.SECOND)


def _bid_item(price_sat: int, hr_matched: str, speed_limit: str = "10") -> BidItem:
    return BidItem(
        price=HashratePrice(sats=Sats(price_sat), per=EH_DAY),
        amount_sat=Sats(100_000),
        hr_matched_ph=Hashrate(Decimal(hr_matched), HashUnit.PH, TimeUnit.SECOND),
        speed_limit_ph=Hashrate(Decimal(speed_limit), HashUnit.PH, TimeUnit.SECOND),
    )


class TestComputeNeededHashrate:
    """Tests for compute_needed_hashrate."""

    def test_below_target(self) -> None:
        """Current 5, target 10 → needed 15 (= 2*10 - 5)."""
        result = compute_needed_hashrate(
            target=Hashrate(Decimal("10"), HashUnit.PH, TimeUnit.SECOND),
            current_24h=Hashrate(Decimal("5"), HashUnit.PH, TimeUnit.SECOND),
        )
        assert result == Hashrate(Decimal("15"), HashUnit.PH, TimeUnit.SECOND)

    def test_at_target_keeps_running(self) -> None:
        """Current equal to target → keep running at target (2*10 - 10 = 10)."""
        result = compute_needed_hashrate(
            target=Hashrate(Decimal("10"), HashUnit.PH, TimeUnit.SECOND),
            current_24h=Hashrate(Decimal("10"), HashUnit.PH, TimeUnit.SECOND),
        )
        assert result == Hashrate(Decimal("10"), HashUnit.PH, TimeUnit.SECOND)

    def test_modestly_above_target_undershoots(self) -> None:
        """Target 12, current 15 → 9 (= 2*12 - 15) to pull average down."""
        result = compute_needed_hashrate(
            target=Hashrate(Decimal("12"), HashUnit.PH, TimeUnit.SECOND),
            current_24h=Hashrate(Decimal("15"), HashUnit.PH, TimeUnit.SECOND),
        )
        assert result == Hashrate(Decimal("9"), HashUnit.PH, TimeUnit.SECOND)

    def test_far_above_target_clamps_to_zero(self) -> None:
        """Current >= 2*target → 0 (can't go negative)."""
        result = compute_needed_hashrate(
            target=Hashrate(Decimal("10"), HashUnit.PH, TimeUnit.SECOND),
            current_24h=Hashrate(Decimal("25"), HashUnit.PH, TimeUnit.SECOND),
        )
        assert result == Hashrate(Decimal("0"), HashUnit.PH, TimeUnit.SECOND)

    def test_result_in_ph_per_second(self) -> None:
        """Result is always denominated in PH/s regardless of input units."""
        target = Hashrate(Decimal("864"), HashUnit.PH, TimeUnit.DAY)  # = 0.01 PH/s
        current = Hashrate(Decimal("0"), HashUnit.PH, TimeUnit.SECOND)
        result = compute_needed_hashrate(target, current)
        assert result.hash_unit == HashUnit.PH
        assert result.time_unit == TimeUnit.SECOND


class TestDistributeBids:
    """Tests for distribute_bids."""

    def test_five_phs_max_three(self) -> None:
        """5 PH/s into 3 bids: 3 equal shares quantized to 0.01 PH/s."""
        speeds = distribute_bids(
            Hashrate(Decimal("5"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=3
        )
        assert len(speeds) == 3
        assert all(
            s >= Hashrate(Decimal("1"), HashUnit.PH, TimeUnit.SECOND) for s in speeds
        )
        assert speeds == (
            Hashrate(Decimal("1.67"), HashUnit.PH, TimeUnit.SECOND),
            Hashrate(Decimal("1.67"), HashUnit.PH, TimeUnit.SECOND),
            Hashrate(Decimal("1.67"), HashUnit.PH, TimeUnit.SECOND),
        )

    def test_three_phs_max_seven_uses_three_bids(self) -> None:
        """3 PH/s with room for 7: 3 bids at 1 each (each >= 1 PH/s)."""
        speeds = distribute_bids(
            Hashrate(Decimal("3"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=7
        )
        one = Hashrate(Decimal("1.00"), HashUnit.PH, TimeUnit.SECOND)
        assert speeds == (one, one, one)

    def test_two_point_five_phs_max_four_uses_two_bids(self) -> None:
        """2.5 PH/s with room for 4: 2 bids at 1.25 (3 would need 3 PH/s)."""
        speeds = distribute_bids(
            Hashrate(Decimal("2.5"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=4
        )
        assert speeds == (
            Hashrate(Decimal("1.25"), HashUnit.PH, TimeUnit.SECOND),
            Hashrate(Decimal("1.25"), HashUnit.PH, TimeUnit.SECOND),
        )

    def test_below_half_returns_empty(self) -> None:
        """0.3 PH/s rounds to zero → cancel all."""
        assert (
            distribute_bids(
                Hashrate(Decimal("0.3"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=3
            )
            == ()
        )

    def test_zero_returns_empty(self) -> None:
        """0 PH/s → empty (cancel all)."""
        assert (
            distribute_bids(
                Hashrate(Decimal("0"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=3
            )
            == ()
        )

    def test_between_half_and_one_rounds_up_to_single_bid(self) -> None:
        """0.7 PH/s → single bid at 1 PH/s minimum."""
        speeds = distribute_bids(
            Hashrate(Decimal("0.7"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=3
        )
        assert speeds == (Hashrate(Decimal("1"), HashUnit.PH, TimeUnit.SECOND),)

    def test_exactly_one_phs_max_one(self) -> None:
        """1 PH/s with max_bids_count=1 → single bid at 1 PH/s."""
        speeds = distribute_bids(
            Hashrate(Decimal("1"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=1
        )
        assert speeds == (Hashrate(Decimal("1.00"), HashUnit.PH, TimeUnit.SECOND),)

    def test_uneven_split_quantized(self) -> None:
        """7/3 → three shares of 2.33 PH/s (rounded to 0.01)."""
        speeds = distribute_bids(
            Hashrate(Decimal("7"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=3
        )
        assert speeds == (
            Hashrate(Decimal("2.33"), HashUnit.PH, TimeUnit.SECOND),
            Hashrate(Decimal("2.33"), HashUnit.PH, TimeUnit.SECOND),
            Hashrate(Decimal("2.33"), HashUnit.PH, TimeUnit.SECOND),
        )

    def test_max_bids_count_must_be_positive(self) -> None:
        """max_bids_count < 1 raises ValueError."""
        with pytest.raises(ValueError, match="max_bids_count"):
            distribute_bids(
                Hashrate(Decimal("5"), HashUnit.PH, TimeUnit.SECOND), max_bids_count=0
            )


_TICK = PriceTick(sats=Sats(100))


class TestFindMarketPrice:
    """Tests for find_market_price."""

    def test_picks_lowest_served_plus_one_tick(self) -> None:
        """Among served bids, picks the lowest aligned price and adds one tick."""
        orderbook = OrderBook(
            bids=(
                _bid_item(price_sat=1000, hr_matched="0"),
                _bid_item(price_sat=500, hr_matched="0"),
                _bid_item(price_sat=800, hr_matched="3"),
                _bid_item(price_sat=700, hr_matched="2"),
                _bid_item(price_sat=900, hr_matched="1"),
            ),
            asks=(),
        )
        price = find_market_price(orderbook, _TICK)
        assert price.sats == Sats(800)
        assert price.per == EH_DAY

    def test_single_served_bid(self) -> None:
        """A single served bid → that price aligned down, plus one tick."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=1234, hr_matched="0.5"),),
            asks=(),
        )
        price = find_market_price(orderbook, _TICK)
        # 1234 → align_down to 1200 → +100 tick = 1300
        assert price.sats == Sats(1300)

    def test_result_is_tick_aligned(self) -> None:
        """Result is always aligned to the supplied tick."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=12345, hr_matched="1"),),
            asks=(),
        )
        tick = PriceTick(sats=Sats(1000))
        price = find_market_price(orderbook, tick)
        assert int(price.sats) % 1000 == 0

    def test_no_served_bids_raises(self) -> None:
        """Order book with no served bids raises ValueError."""
        orderbook = OrderBook(
            bids=(
                _bid_item(price_sat=500, hr_matched="0"),
                _bid_item(price_sat=800, hr_matched="0"),
            ),
            asks=(),
        )
        with pytest.raises(ValueError, match="no served bids"):
            find_market_price(orderbook, _TICK)

    def test_empty_orderbook_raises(self) -> None:
        """Empty bids tuple raises ValueError."""
        with pytest.raises(ValueError, match="no served bids"):
            find_market_price(OrderBook(bids=(), asks=()), _TICK)

    def test_max_price_caps_result(self) -> None:
        """When cheapest-served + 1 tick exceeds max_price, return the cap."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=1500, hr_matched="2"),),
            asks=(),
        )
        max_price = HashratePrice(sats=Sats(1200), per=EH_DAY)
        price = find_market_price(orderbook, _TICK, max_price=max_price)
        # Without cap: 1500 → aligned 1500 + 100 tick = 1600. Capped at 1200.
        assert price.sats == Sats(1200)

    def test_max_price_not_reached_returns_market(self) -> None:
        """When the cap is above the market price, cap has no effect."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=500, hr_matched="2"),),
            asks=(),
        )
        max_price = HashratePrice(sats=Sats(1200), per=EH_DAY)
        price = find_market_price(orderbook, _TICK, max_price=max_price)
        assert price.sats == Sats(600)

    def test_max_price_aligned_down_to_tick(self) -> None:
        """A max_price not on the tick grid is aligned down before capping."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=2000, hr_matched="2"),),
            asks=(),
        )
        max_price = HashratePrice(sats=Sats(1234), per=EH_DAY)
        price = find_market_price(orderbook, _TICK, max_price=max_price)
        assert price.sats == Sats(1200)

    def test_max_price_in_ph_day_units(self) -> None:
        """Cap provided in sat/PH/Day is correctly converted to sat/EH/Day."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=2_000_000, hr_matched="2"),),
            asks=(),
        )
        # 1000 sat/PH/Day == 1_000_000 sat/EH/Day
        max_price = HashratePrice(sats=Sats(1000), per=PH_DAY)
        price = find_market_price(orderbook, _TICK, max_price=max_price)
        assert price.sats == Sats(1_000_000)
        assert price.per == EH_DAY

    def test_no_max_price_matches_old_behavior(self) -> None:
        """Omitting max_price leaves existing behavior unchanged."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=800, hr_matched="3"),),
            asks=(),
        )
        price = find_market_price(orderbook, _TICK)
        assert price.sats == Sats(900)

    def test_max_price_below_one_tick_raises(self) -> None:
        """A max_price that aligns down to zero is rejected."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=500, hr_matched="2"),),
            asks=(),
        )
        # _TICK is 100 sat/EH/Day; a cap of 50 sat/EH/Day aligns down to 0.
        max_price = HashratePrice(sats=Sats(50), per=EH_DAY)
        with pytest.raises(ValueError, match="max_price"):
            find_market_price(orderbook, _TICK, max_price=max_price)

    def test_max_price_exactly_equal_to_candidate_returns_candidate(self) -> None:
        """When candidate equals cap, candidate is returned (strict > comparison)."""
        orderbook = OrderBook(
            bids=(_bid_item(price_sat=500, hr_matched="2"),),
            asks=(),
        )
        # candidate = align_down(500) + 100 = 600.
        max_price = HashratePrice(sats=Sats(600), per=EH_DAY)
        price = find_market_price(orderbook, _TICK, max_price=max_price)
        assert price.sats == Sats(600)


_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=UTC)
_SETTINGS = MarketSettings(
    min_bid_price_decrease_period=timedelta(seconds=600),
    min_bid_speed_limit_decrease_period=timedelta(seconds=600),
    price_tick=_TICK,
)
DESIRED_PRICE = HashratePrice(sats=Sats(500), per=PH_DAY)


def _annotated(bid: object, price_cd: bool, speed_cd: bool) -> BidWithCooldown:
    return BidWithCooldown(
        bid=bid,  # type: ignore[arg-type]
        cooldown=CooldownInfo(price_cooldown=price_cd, speed_cooldown=speed_cd),
    )


class TestCheckCooldowns:
    """Tests for check_cooldowns."""

    def test_recent_bid_in_both_cooldowns(self) -> None:
        """A bid updated 10s ago is in both cooldown windows."""
        bid = make_user_bid("B1", 500, "5.0", last_updated=_NOW - timedelta(seconds=10))
        (entry,) = check_cooldowns((bid,), _SETTINGS, _NOW)
        assert entry.bid is bid
        assert entry.cooldown == CooldownInfo(price_cooldown=True, speed_cooldown=True)

    def test_old_bid_in_neither_cooldown(self) -> None:
        """A bid updated well past both cooldown windows is free."""
        bid = make_user_bid(
            "B1", 500, "5.0", last_updated=_NOW - timedelta(seconds=3600)
        )
        (entry,) = check_cooldowns((bid,), _SETTINGS, _NOW)
        assert entry.cooldown == CooldownInfo(
            price_cooldown=False, speed_cooldown=False
        )

    def test_distinct_windows(self) -> None:
        """Different periods can leave one cooldown active and the other not."""
        settings = MarketSettings(
            min_bid_price_decrease_period=timedelta(seconds=600),
            min_bid_speed_limit_decrease_period=timedelta(seconds=60),
            price_tick=_TICK,
        )
        bid = make_user_bid(
            "B1", 500, "5.0", last_updated=_NOW - timedelta(seconds=120)
        )
        (entry,) = check_cooldowns((bid,), settings, _NOW)
        assert entry.cooldown == CooldownInfo(price_cooldown=True, speed_cooldown=False)


class TestPlanWithCooldowns:
    """Tests for plan_with_cooldowns."""

    def test_no_cooldowns_matches_naive_distribution(self) -> None:
        """No cooldowns → result mirrors plain distribute_bids at desired_price."""
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("5"),
            max_bids_count=3,
            bids=(),
        )
        assert len(result) == 3
        assert all(b.price == DESIRED_PRICE for b in result)
        # distribute_bids quantizes shares to 0.01 PH/s.
        total = sum((b.speed_limit.value for b in result), Decimal(0))
        assert abs(total - Decimal("5")) <= Decimal("0.03")

    def test_price_cooldown_only_keeps_old_price(self) -> None:
        """A price-locked bid keeps its price; speed comes from the distribution."""
        bid = make_user_bid("B1", 900, "2.0", last_updated=_NOW - timedelta(seconds=10))
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("4"),
            max_bids_count=2,
            bids=(_annotated(bid, price_cd=True, speed_cd=False),),
        )
        assert len(result) == 2
        assert result[0].price == bid.price
        assert result[0].speed_limit == _ph_s("2")
        assert result[1].price == DESIRED_PRICE
        assert result[1].speed_limit == _ph_s("2")

    def test_speed_cooldown_freezes_speed_and_redistributes(self) -> None:
        """Speed-locked bid keeps its current speed; remainder goes to free slots."""
        bid = make_user_bid("B1", 500, "3.0", last_updated=_NOW - timedelta(seconds=10))
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("5"),
            max_bids_count=3,
            bids=(_annotated(bid, price_cd=False, speed_cd=True),),
        )
        assert len(result) == 3
        assert result[0].speed_limit == _ph_s("3")
        assert result[0].price == DESIRED_PRICE  # not price-locked
        for entry in result[1:]:
            assert entry.price == DESIRED_PRICE
        free_total = sum((b.speed_limit.value for b in result[1:]), Decimal(0))
        assert free_total == Decimal("2")

    def test_both_cooldowns_freeze_bid_completely(self) -> None:
        """A fully-frozen bid keeps both fields and consumes a slot+budget."""
        bid = make_user_bid("B1", 900, "3.0", last_updated=_NOW - timedelta(seconds=10))
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("5"),
            max_bids_count=3,
            bids=(_annotated(bid, price_cd=True, speed_cd=True),),
        )
        assert result[0].price == bid.price
        assert result[0].speed_limit == _ph_s("3")
        assert len(result) == 3
        for entry in result[1:]:
            assert entry.price == DESIRED_PRICE
        assert sum((b.speed_limit.value for b in result[1:]), Decimal(0)) == Decimal(
            "2"
        )

    def test_all_bids_in_cooldown_no_free_slots(self) -> None:
        """All slots taken by frozen bids: no new entries, no errors."""
        b1 = make_user_bid("B1", 800, "2.0", last_updated=_NOW - timedelta(seconds=10))
        b2 = make_user_bid("B2", 900, "3.0", last_updated=_NOW - timedelta(seconds=10))
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("5"),
            max_bids_count=2,
            bids=(
                _annotated(b1, price_cd=True, speed_cd=True),
                _annotated(b2, price_cd=True, speed_cd=True),
            ),
        )
        assert len(result) == 2
        assert {r.price for r in result} == {b1.price, b2.price}

    def test_speed_lock_exceeds_needed_clamps_remainder(self) -> None:
        """Locked speed greater than needed leaves zero for free slots."""
        bid = make_user_bid(
            "B1", 500, "10.0", last_updated=_NOW - timedelta(seconds=10)
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("5"),
            max_bids_count=3,
            bids=(_annotated(bid, price_cd=False, speed_cd=True),),
        )
        # Only the locked bid; no extras since remaining is 0.
        assert len(result) == 1
        assert result[0].speed_limit == _ph_s("10")

    def test_served_cheap_bid_keeps_price_redistributes_speed(self) -> None:
        """Served bid below desired_price.

        Price preserved, speed freely redistributed.
        """
        bid = make_user_bid(
            "B1",
            400,
            "2.0",
            current_speed=_ph_s("2"),
            last_updated=_NOW - timedelta(seconds=3600),
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,  # 500 sat/PH/Day
            needed=_ph_s("4"),
            max_bids_count=2,
            bids=(_annotated(bid, price_cd=False, speed_cd=False),),
        )
        # distribute_bids(4, 2) → (2, 2). Slot 0 inherits bid.price; slot 1 desired.
        assert len(result) == 2
        assert result[0].price == bid.price
        assert result[0].speed_limit == _ph_s("2")
        assert result[1].price == DESIRED_PRICE
        assert result[1].speed_limit == _ph_s("2")

    def test_served_cheap_bid_speed_can_be_reduced(self) -> None:
        """Served-cheap + no speed cooldown: current speed drops when needed drops."""
        bid = make_user_bid(
            "B1",
            400,
            "10.0",
            current_speed=_ph_s("10"),
            last_updated=_NOW - timedelta(seconds=3600),
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("2"),
            max_bids_count=3,
            bids=(_annotated(bid, price_cd=False, speed_cd=False),),
        )
        # distribute_bids(2, 3) → (1, 1). Bid's speed DROPS from 10 to 1 (price kept).
        assert len(result) == 2
        assert result[0].price == bid.price
        assert result[0].speed_limit == _ph_s("1")
        assert result[1].price == DESIRED_PRICE
        assert result[1].speed_limit == _ph_s("1")

    def test_served_cheap_with_speed_cooldown_keeps_both(self) -> None:
        """Served-cheap + speed cooldown: keep price (served) + speed (cooldown)."""
        bid = make_user_bid(
            "B1",
            400,
            "2.0",
            current_speed=_ph_s("2"),
            last_updated=_NOW - timedelta(seconds=10),
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("5"),
            max_bids_count=3,
            bids=(_annotated(bid, price_cd=False, speed_cd=True),),
        )
        assert result[0].price == bid.price
        assert result[0].speed_limit == _ph_s("2")
        assert len(result) == 3
        for entry in result[1:]:
            assert entry.price == DESIRED_PRICE

    def test_served_at_equal_price_not_preserved(self) -> None:
        """Served bid exactly at desired_price is not preserved (strict less-than)."""
        bid = make_user_bid(
            "B1",
            500,
            "2.0",
            current_speed=_ph_s("2"),
            last_updated=_NOW - timedelta(seconds=3600),
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("4"),
            max_bids_count=2,
            bids=(_annotated(bid, price_cd=False, speed_cd=False),),
        )
        assert len(result) == 2
        for entry in result:
            assert entry.price == DESIRED_PRICE

    def test_served_above_desired_not_preserved(self) -> None:
        """Served bid above desired_price is replanned at desired_price."""
        bid = make_user_bid(
            "B1",
            600,
            "2.0",
            current_speed=_ph_s("2"),
            last_updated=_NOW - timedelta(seconds=3600),
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("4"),
            max_bids_count=2,
            bids=(_annotated(bid, price_cd=False, speed_cd=False),),
        )
        assert len(result) == 2
        for entry in result:
            assert entry.price == DESIRED_PRICE

    def test_stale_active_zero_speed_not_preserved(self) -> None:
        """ACTIVE status but zero current_speed → not preserved (allows repricing)."""
        bid = make_user_bid(
            "B1",
            400,
            "2.0",
            current_speed=_ph_s("0"),
            last_updated=_NOW - timedelta(seconds=3600),
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("4"),
            max_bids_count=2,
            bids=(_annotated(bid, price_cd=False, speed_cd=False),),
        )
        assert len(result) == 2
        for entry in result:
            assert entry.price == DESIRED_PRICE

    def test_speed_locked_exceeding_max_bids_is_truncated(self) -> None:
        """All speed-locked + all price-locked: keep the cheapest up to the cap."""
        cheap = make_user_bid(
            "B1", 300, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
        mid = make_user_bid("B2", 500, "1.0", last_updated=_NOW - timedelta(seconds=10))
        dear = make_user_bid(
            "B3", 900, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("5"),
            max_bids_count=2,
            bids=(
                _annotated(cheap, price_cd=True, speed_cd=True),
                _annotated(mid, price_cd=True, speed_cd=True),
                _annotated(dear, price_cd=True, speed_cd=True),
            ),
        )
        assert len(result) == 2
        kept_prices = {r.price for r in result}
        assert cheap.price in kept_prices
        assert mid.price in kept_prices
        assert dear.price not in kept_prices

    def test_speed_locked_truncation_uses_effective_plan_price(self) -> None:
        """Truncation cost signal uses effective plan price, not raw bid.price.

        Three speed-locked bids at 300/400/450 sat/PH/Day, all 1 PH/s, only
        the 450 bid is price-locked. desired_price=500, max_bids_count=2.

        - cheap (id=B1, 300, not price-locked): repriced to 500 -> effective = 500
        - mid   (id=B2, 400, not price-locked): repriced to 500 -> effective = 500
        - dear  (id=B3, 450, price-locked):      keeps price    -> effective = 450

        Cost signals (effective x speed): cheap=500, mid=500, dear=450.
        Tuple keys with bid.id tiebreak: (450,B3) < (500,B1) < (500,B2).
        Truncated to 2: dear + cheap. mid is dropped.

        A raw-bid.price sort would have kept [cheap, mid] (both repriced
        to 500), costing 1000 vs the correct plan's 950.
        """
        cheap = make_user_bid(
            "B1", 300, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
        mid = make_user_bid("B2", 400, "1.0", last_updated=_NOW - timedelta(seconds=10))
        dear = make_user_bid(
            "B3", 450, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,  # 500 sat/PH/Day
            needed=_ph_s("5"),
            max_bids_count=2,
            bids=(
                _annotated(cheap, price_cd=False, speed_cd=True),
                _annotated(mid, price_cd=False, speed_cd=True),
                _annotated(dear, price_cd=True, speed_cd=True),
            ),
        )
        assert len(result) == 2
        prices = [r.price for r in result]
        # dear (price-locked) kept at its 450 price
        assert dear.price in prices
        # cheap (B1) kept and repriced to desired_price; B2 (mid) dropped
        # because its bid.id sorts after B1 on the equal-cost-signal tie.
        assert DESIRED_PRICE in prices
        assert mid.price not in prices

    def test_speed_locked_truncation_uses_total_cost_not_unit_price(
        self,
    ) -> None:
        """Truncation uses effective_price x speed, not unit price alone.

        Three speed-locked, all price-locked bids:
        - cheap_high (id=B1, 300, 10 PH/s): effective=300, signal=3000
        - exp_mid    (id=B2, 460,  5 PH/s): effective=460, signal=2300
        - mid_low    (id=B3, 450,  1 PH/s): effective=450, signal=450
        desired_price=500, max_bids_count=2.

        By unit price alone we would keep [cheap_high (300), mid_low (450)],
        paying 300x10 + 450x1 = 3450.
        By total cost we keep [mid_low (450), exp_mid (460x5=2300)], paying
        2750 - cheaper despite a higher unit price on exp_mid.

        Note: this minimizes spend among kept bids but can under-supply
        `needed` since cancelled speed-locked speed is not replaced
        (remaining_slots is 0 after a full truncation). See plan design
        notes for the regime-A caveat.
        """
        cheap_high = make_user_bid(
            "B1", 300, "10.0", last_updated=_NOW - timedelta(seconds=10)
        )
        exp_mid = make_user_bid(
            "B2", 460, "5.0", last_updated=_NOW - timedelta(seconds=10)
        )
        mid_low = make_user_bid(
            "B3", 450, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
        result = plan_with_cooldowns(
            desired_price=DESIRED_PRICE,
            needed=_ph_s("12"),
            max_bids_count=2,
            bids=(
                _annotated(cheap_high, price_cd=True, speed_cd=True),
                _annotated(exp_mid, price_cd=True, speed_cd=True),
                _annotated(mid_low, price_cd=True, speed_cd=True),
            ),
        )
        assert len(result) == 2
        prices = {r.price for r in result}
        assert mid_low.price in prices  # signal 450, lowest
        assert exp_mid.price in prices  # signal 2300, second lowest
        assert cheap_high.price not in prices  # signal 3000, highest - dropped


class TestIsBeingServed:
    """Tests for _is_being_served."""

    def test_active_with_positive_current_speed_is_served(self) -> None:
        """ACTIVE + non-zero current_speed -> being served."""
        bid = make_user_bid(
            "B1",
            500,
            "1.0",
            status=BidStatus.ACTIVE,
            current_speed=_ph_s("0.9"),
        )
        assert _is_being_served(bid) is True

    def test_active_with_none_current_speed_is_not_served_deliberate_false_negative(
        self,
    ) -> None:
        """ACTIVE but no current_speed report -> not served.

        This is a deliberate false negative: during transient telemetry gaps
        we prefer the (rare) cost of allowing a repricing that pays more for
        one tick over persistently locking in a bid that may no longer be
        served. Upstream clients are responsible for handling sustained
        telemetry loss — this predicate uses only the signals the UserBid
        carries, with no staleness fallback.
        """
        bid = make_user_bid(
            "B1",
            500,
            "1.0",
            status=BidStatus.ACTIVE,
            current_speed=None,
        )
        assert _is_being_served(bid) is False

    def test_active_with_zero_current_speed_is_not_served(self) -> None:
        """Stale ACTIVE with zero delivery -> not served.

        Avoids preserving dead bids that the API hasn't transitioned yet.
        """
        bid = make_user_bid(
            "B1",
            500,
            "1.0",
            status=BidStatus.ACTIVE,
            current_speed=_ph_s("0"),
        )
        assert _is_being_served(bid) is False

    def test_created_is_not_served(self) -> None:
        """CREATED = accepted but not matched yet."""
        bid = make_user_bid(
            "B1",
            500,
            "1.0",
            status=BidStatus.CREATED,
            current_speed=_ph_s("1.0"),
        )
        assert _is_being_served(bid) is False

    def test_paused_is_not_served(self) -> None:
        """PAUSED bids are not matching."""
        bid = make_user_bid(
            "B1",
            500,
            "1.0",
            status=BidStatus.PAUSED,
            current_speed=_ph_s("1.0"),
        )
        assert _is_being_served(bid) is False

    def test_canceled_is_not_served(self) -> None:
        """CANCELED bids are not matching."""
        bid = make_user_bid(
            "B1",
            500,
            "1.0",
            status=BidStatus.CANCELED,
            current_speed=_ph_s("1.0"),
        )
        assert _is_being_served(bid) is False
