# Bid Price Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two price-discipline controls to target-hashrate mode: (A) a user-configurable `max_price` ceiling on the discovered market price, and (B) a "don't raise price on a bid that's currently being served" rule in the cooldown planner.

**Architecture:** Part A threads an optional `HashratePrice` cap from config → `run_set_bids_target` → `find_market_price`; the cap is aligned down to the tick and rejected at runtime if the aligned cap is zero. Validation is split intentionally: the config parser rejects structurally-bad caps (≤ 0) at save time, while tick-alignment is enforced at bid time because the market tick is not known when `bids.toml` is written. Part B folds served-below-desired bids into the existing price-lock path in `plan_with_cooldowns`: a served bid whose price is strictly below `desired_price` is treated the same as a price-cooldown bid — price preserved, speed re-assigned by `distribute_bids` (still subject to the `speed_cooldown` gate). The "being served" predicate requires both `BidStatus.ACTIVE` and a non-zero `current_speed` to avoid preserving stale-active bids that report no delivery. An additional pre-existing issue — `speed_locked` exceeding `max_bids_count` — is closed by a heuristic that ranks candidates by total locked spend (`effective_plan_price × speed_limit`), with `bid.id` as a deterministic tiebreaker. This is a cost-minimizing heuristic, not a provably optimal selection (see Task 8 design notes for the regime caveat).

**Tech Stack:** Python 3.13, pydantic v2, FastAPI/Jinja2, aiosqlite, pytest + hypothesis. `Decimal` precision is 28 digits; prices compare via `.to(HashUnit.EH, TimeUnit.DAY).sats` (HashratePrice has no `__lt__`).

---

## File Structure

**Modify:**
- `hashbidder/config.py` — add `max_price_sat_per_ph_day` to `TargetHashrateModel` + validator; add `max_price: HashratePrice | None` to `TargetHashrateConfig`; wire through `load_config`.
- `hashbidder/target_hashrate.py` — add `max_price` parameter to `find_market_price` with alignment + cap logic + zero-tick guard; add `_is_being_served`, `_price_lt`, `_price_is_locked`, `_effective_plan_price`, `_truncation_cost_signal` helpers; extend `plan_with_cooldowns`'s price-lock condition; truncate `speed_locked` at `max_bids_count` by total locked spend with `bid.id` tiebreak.
- `hashbidder/use_cases/set_bids_target.py` — pass `config.max_price` into `find_market_price`.
- `hashbidder/dashboard.py` — write `max_price_sat_per_ph_day` in `save_config_to_toml`; accept it in `post_settings`.
- `hashbidder/templates/settings.html` — add optional max-price input inside `#target-hashrate-fields`.
- `tests/conftest.py` — add `current_speed` parameter to `make_user_bid`.

**Modify (tests):**
- `tests/unit/test_config.py` — parse/validate new field.
- `tests/unit/test_target_hashrate.py` — `find_market_price` cap + zero-tick edge; `_is_being_served`; served-cheap price preservation in `plan_with_cooldowns`; `speed_locked` truncation.
- `tests/unit/test_use_cases_set_bids_target.py` — integration: cap threads through to `inputs.price`.

**No new files.**

---

## Part A: Settable Max Price Limit

User-visible contract: when set, `max_price_sat_per_ph_day` is the absolute upper bound on the price we will place bids at. If the cheapest served bid in the order book would otherwise drive our price above the cap, we pin at the cap (aligned down to the tick). A cap that aligns to zero at the current tick is rejected with a clear error. If unset (None), there is no cap — behavior matches today's.

**Validation split (save-time vs bid-time).** The config parser only checks that the cap is positive (a structural / unit-agnostic check). It does **not** reject a cap below one tick, because the market's `price_tick` is state-dependent and not available when `bids.toml` is written. That check lives in `find_market_price` and surfaces at bid time as a `ValueError` with "max_price" in the message, which `daemon._tick` logs via its existing reconciliation try/except. The dashboard form mirrors this by adding UI help text telling the user the cap must be at least one market tick — without attempting to fetch the tick during save.

### Task 1: Add `max_price_sat_per_ph_day` to TargetHashrateModel

**Files:**
- Modify: `hashbidder/config.py:81-104` (TargetHashrateModel)
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to the existing `TestLoadConfig` class in `tests/unit/test_config.py`:

```python
    def test_target_hashrate_with_max_price(self, tmp_path: Path) -> None:
        """max_price_sat_per_ph_day parses into TargetHashrateConfig.max_price."""
        path = _write_toml(
            tmp_path,
            """\
mode = "target-hashrate"
default_amount_sat = 100000
target_hashrate_ph_s = 10.0
max_bids_count = 3
max_price_sat_per_ph_day = 600

[upstream]
url = "stratum+tcp://pool.example.com:3333"
identity = "worker1"
""",
        )
        config = load_config(path)
        assert isinstance(config, TargetHashrateConfig)
        assert config.max_price is not None
        assert config.max_price.sats == Sats(600)
        assert config.max_price.per == Hashrate(
            Decimal(1), HashUnit.PH, TimeUnit.DAY
        )

    def test_target_hashrate_without_max_price_defaults_to_none(
        self, tmp_path: Path
    ) -> None:
        """A target-hashrate config with no max_price_sat_per_ph_day parses as None."""
        path = _write_toml(
            tmp_path,
            """\
mode = "target-hashrate"
default_amount_sat = 100000
target_hashrate_ph_s = 10.0
max_bids_count = 3

[upstream]
url = "stratum+tcp://pool.example.com:3333"
identity = "worker1"
""",
        )
        config = load_config(path)
        assert isinstance(config, TargetHashrateConfig)
        assert config.max_price is None

    def test_target_hashrate_non_positive_max_price(self, tmp_path: Path) -> None:
        """max_price_sat_per_ph_day <= 0 raises ValueError."""
        path = _write_toml(
            tmp_path,
            """\
mode = "target-hashrate"
default_amount_sat = 100000
target_hashrate_ph_s = 10.0
max_bids_count = 3
max_price_sat_per_ph_day = 0

[upstream]
url = "stratum+tcp://pool.example.com:3333"
identity = "worker1"
""",
        )
        with pytest.raises(
            ValueError, match="max_price_sat_per_ph_day must be positive"
        ):
            load_config(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v -k "max_price"`
Expected: FAIL — Pydantic rejects the unknown field (`extra = "forbid"`) or `TargetHashrateConfig` has no `max_price` attribute.

- [ ] **Step 3: Add the field to TargetHashrateModel**

In `hashbidder/config.py`, replace `TargetHashrateModel` (lines 81-104) with:

```python
class TargetHashrateModel(BaseConfigModel):
    """Configuration model for target-hashrate mode."""

    model_config = {"extra": "forbid"}
    mode: Literal["target-hashrate"]
    upstream: UpstreamModel
    target_hashrate_ph_s: Decimal
    max_bids_count: int
    max_price_sat_per_ph_day: int | None = None

    @field_validator("target_hashrate_ph_s")
    @classmethod
    def validate_target(cls, v: Decimal) -> Decimal:
        """Ensure target hashrate is positive."""
        if v <= 0:
            raise ValueError("target_hashrate_ph_s must be positive")
        return v

    @field_validator("max_bids_count")
    @classmethod
    def validate_max_bids(cls, v: int) -> int:
        """Ensure max bids count is at least 1."""
        if v < 1:
            raise ValueError("max_bids_count must be >= 1")
        return v

    @field_validator("max_price_sat_per_ph_day")
    @classmethod
    def validate_max_price(cls, v: int | None) -> int | None:
        """Ensure max price, when set, is positive."""
        if v is not None and v <= 0:
            raise ValueError("max_price_sat_per_ph_day must be positive")
        return v
```

- [ ] **Step 4: Add `max_price` to TargetHashrateConfig and wire through load_config**

Replace `TargetHashrateConfig` (lines 107-115) with:

```python
@dataclass(frozen=True)
class TargetHashrateConfig:
    """Parsed set-bids configuration for target-hashrate mode."""

    default_amount: Sats
    upstream: Upstream
    target_hashrate: Hashrate
    max_bids_count: int
    max_price: HashratePrice | None = None
```

In `load_config`, replace the target-hashrate construction:

```python
    if mode_raw == ConfigMode.TARGET_HASHRATE.value:
        try:
            parsed_target = TargetHashrateModel.model_validate(data)
        except Exception as e:
            raise ValueError(str(e)) from e
        max_price = (
            HashratePrice(
                sats=Sats(parsed_target.max_price_sat_per_ph_day),
                per=Hashrate(Decimal(1), HashUnit.PH, TimeUnit.DAY),
            )
            if parsed_target.max_price_sat_per_ph_day is not None
            else None
        )
        return TargetHashrateConfig(
            default_amount=Sats(parsed_target.default_amount_sat),
            upstream=Upstream(
                url=StratumUrl(parsed_target.upstream.url),
                identity=parsed_target.upstream.identity,
            ),
            target_hashrate=Hashrate(
                parsed_target.target_hashrate_ph_s, HashUnit.PH, TimeUnit.SECOND
            ),
            max_bids_count=parsed_target.max_bids_count,
            max_price=max_price,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: PASS — all new + existing tests.

- [ ] **Step 6: Commit**

```bash
git add hashbidder/config.py tests/unit/test_config.py
git commit -m "feat: parse max_price_sat_per_ph_day in target-hashrate config

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Cap `find_market_price` at `max_price` with zero-tick guard

**Files:**
- Modify: `hashbidder/target_hashrate.py:148-161` (find_market_price)
- Test: `tests/unit/test_target_hashrate.py` (TestFindMarketPrice)

- [ ] **Step 1: Write the failing tests**

Add to `TestFindMarketPrice`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_target_hashrate.py::TestFindMarketPrice -v`
Expected: FAIL — `TypeError: find_market_price() got an unexpected keyword argument 'max_price'`.

- [ ] **Step 3: Add the cap logic and zero-tick guard**

Replace `find_market_price` in `hashbidder/target_hashrate.py` (lines 148-161) with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_hashrate.py::TestFindMarketPrice -v`
Expected: PASS — 10 tests (4 existing + 6 new).

- [ ] **Step 5: Commit**

```bash
git add hashbidder/target_hashrate.py tests/unit/test_target_hashrate.py
git commit -m "feat: optional max_price cap in find_market_price

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Thread `max_price` through `run_set_bids_target`

**Files:**
- Modify: `hashbidder/use_cases/set_bids_target.py:83`
- Test: `tests/unit/test_use_cases_set_bids_target.py`

- [ ] **Step 1: Write the failing tests**

Add to the existing `TestSetBidsTarget` class:

```python
    @pytest.mark.asyncio
    async def test_max_price_caps_discovered_market_price(self) -> None:
        """config.max_price pins the planner's price when market is above it."""
        client = FakeClient(orderbook=_orderbook(served_price_sat=2_000_000))
        ocean = FakeOceanSource(account_stats=_account_stats("5"))

        config = TargetHashrateConfig(
            default_amount=Sats(100_000),
            upstream=UPSTREAM,
            target_hashrate=_ph_s("10"),
            max_bids_count=3,
            max_price=HashratePrice(
                sats=Sats(1000),
                per=Hashrate(Decimal(1), HashUnit.PH, TimeUnit.DAY),
            ),
        )

        result = await run_set_bids_target(
            client, ocean, ADDRESS, config, dry_run=True
        )
        assert result.inputs.price.sats == Sats(1_000_000)
        assert result.inputs.price.per == EH_DAY

    @pytest.mark.asyncio
    async def test_no_max_price_uses_market_price_unchanged(self) -> None:
        """When config.max_price is None, price equals cheapest + 1 tick."""
        client = FakeClient(orderbook=_orderbook(served_price_sat=800_000))
        ocean = FakeOceanSource(account_stats=_account_stats("5"))

        result = await run_set_bids_target(
            client, ocean, ADDRESS, _config("10"), dry_run=True
        )
        assert result.inputs.price.sats == Sats(801_000)

    @pytest.mark.asyncio
    async def test_sub_tick_max_price_raises_at_bid_time(self) -> None:
        """A cap that aligns to zero at the market tick is rejected here.

        Config parsing only enforces `max_price > 0` (a structural check),
        because the market's price_tick is not known when bids.toml is
        written. Tick-alignment is checked at bid time by find_market_price.
        """
        client = FakeClient(orderbook=_orderbook(served_price_sat=800_000))
        ocean = FakeOceanSource(account_stats=_account_stats("5"))

        config = TargetHashrateConfig(
            default_amount=Sats(100_000),
            upstream=UPSTREAM,
            target_hashrate=_ph_s("10"),
            max_bids_count=3,
            # 1 sat/EH/Day is positive (passes config validation) but
            # aligns to zero at any realistic market tick.
            max_price=HashratePrice(sats=Sats(1), per=EH_DAY),
        )

        with pytest.raises(ValueError, match="max_price"):
            await run_set_bids_target(
                client, ocean, ADDRESS, config, dry_run=True
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_use_cases_set_bids_target.py -v -k "max_price"`
Expected: FAIL — `test_max_price_caps_discovered_market_price` sees `price.sats == 2_001_000`; the sub-tick test passes only after Task 2's guard is in place (it should already pass once Task 2 is complete since `find_market_price` is where the guard lives).

- [ ] **Step 3: Pass `config.max_price` to `find_market_price`**

In `hashbidder/use_cases/set_bids_target.py` line 83, replace:

```python
    price = find_market_price(orderbook, settings.price_tick)
```

with:

```python
    price = find_market_price(
        orderbook, settings.price_tick, max_price=config.max_price
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_use_cases_set_bids_target.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hashbidder/use_cases/set_bids_target.py tests/unit/test_use_cases_set_bids_target.py
git commit -m "feat: pass max_price from config into find_market_price

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Dashboard TOML round-trip for `max_price_sat_per_ph_day`

**Files:**
- Modify: `hashbidder/dashboard.py:120-144` (save_config_to_toml), `hashbidder/dashboard.py:248-288` (post_settings)
- Test: `tests/unit/test_dashboard_index.py` (new TestSaveConfigToToml class)

**Scope note.** The dashboard only does structural validation at save time (positive integer, via `TargetHashrateModel.model_validate`). It does **not** fetch market settings to verify the cap is at least one tick: the tick is state-dependent and the daemon caches it separately, and fetching it on every save would couple the settings form to Braiins availability. Tick-alignment failures surface at bid time in `find_market_price` and are logged by `daemon._tick`'s existing `except Exception: logger.error(...)` block. The UI instead carries a one-line help text (Task 5) pointing the user at the tick visible in logs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_dashboard_index.py`:

```python
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

    def test_target_hashrate_without_max_price_round_trip(
        self, tmp_path: Path
    ) -> None:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_dashboard_index.py::TestSaveConfigToToml -v`
Expected: FAIL — `max_price` is `None` even though `750` was provided.

- [ ] **Step 3: Update `save_config_to_toml`**

Replace `save_config_to_toml` in `hashbidder/dashboard.py` (lines 120-144) with:

```python
def save_config_to_toml(data: dict[str, Any], path: Path) -> None:
    """Write configuration data to TOML file."""
    lines = []
    if "mode" in data:
        lines.append(f'mode = "{data["mode"]}"')

    lines.append(f"default_amount_sat = {data['default_amount_sat']}")

    if data.get("mode") == "target-hashrate":
        lines.append(f"target_hashrate_ph_s = {data['target_hashrate_ph_s']}")
        lines.append(f"max_bids_count = {data['max_bids_count']}")
        max_price = data.get("max_price_sat_per_ph_day")
        if max_price is not None:
            lines.append(f"max_price_sat_per_ph_day = {max_price}")

    lines.append("")
    lines.append("[upstream]")
    lines.append(f'url = "{data["upstream"]["url"]}"')
    lines.append(f'identity = "{data["upstream"]["identity"]}"')

    if data.get("mode") == "explicit-bids" and "bids" in data:
        for bid in data["bids"]:
            lines.append("")
            lines.append("[[bids]]")
            lines.append(f"price_sat_per_ph_day = {bid['price_sat_per_ph_day']}")
            lines.append(f"speed_limit_ph_s = {bid['speed_limit_ph_s']}")

    path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_dashboard_index.py::TestSaveConfigToToml -v`
Expected: PASS.

- [ ] **Step 5: Update `post_settings` to accept the form field**

Replace `post_settings` in `hashbidder/dashboard.py` (lines 248-288) with:

```python
@app.post("/settings", response_class=HTMLResponse)
async def post_settings(
    request: Request,
    mode: Annotated[str, Form()],
    default_amount_sat: Annotated[int, Form()],
    upstream_url: Annotated[str, Form()],
    upstream_identity: Annotated[str, Form()],
    target_hashrate_ph_s: Annotated[str | None, Form()] = None,
    max_bids_count: Annotated[str | None, Form()] = None,
    max_price_sat_per_ph_day: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """Save updated settings to config file."""
    try:
        data: dict[str, Any] = {
            "mode": mode,
            "default_amount_sat": default_amount_sat,
            "upstream": {
                "url": upstream_url,
                "identity": upstream_identity,
            },
        }

        if mode == "target-hashrate":
            data["target_hashrate_ph_s"] = (
                Decimal(target_hashrate_ph_s) if target_hashrate_ph_s else None
            )
            data["max_bids_count"] = int(max_bids_count) if max_bids_count else None
            data["max_price_sat_per_ph_day"] = (
                int(max_price_sat_per_ph_day)
                if max_price_sat_per_ph_day
                else None
            )
            TargetHashrateModel.model_validate(data)
        else:
            data["bids"] = []
            ExplicitBidsModel.model_validate(data)

        save_config_to_toml(data, BIDS_CONFIG_PATH)
        success_msg = "Settings saved successfully!"
        return HTMLResponse(
            f'<div style="color: green; margin-top: 1rem;">{success_msg}</div>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<div style="color: red; margin-top: 1rem;">Error: {e!s}</div>'
        )
```

- [ ] **Step 6: Commit**

```bash
git add hashbidder/dashboard.py tests/unit/test_dashboard_index.py
git commit -m "feat: persist max_price_sat_per_ph_day via dashboard settings

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Add `max_price` input to `settings.html`

**Files:**
- Modify: `hashbidder/templates/settings.html:136-146`

No automated test — template change verified by loading the page.

- [ ] **Step 1: Add the form field**

Replace lines 136-146 of `hashbidder/templates/settings.html` with:

```html
            <div id="target-hashrate-fields" style="display: {% if config.get('mode', 'target-hashrate') == 'target-hashrate' %}flex{% else %}none{% endif %};">
                <div class="form-group">
                    <label for="target_hashrate_ph_s">Target Hashrate (PH/s)</label>
                    <input type="number" step="0.1" id="target_hashrate_ph_s" name="target_hashrate_ph_s" value="{{ config.get('target_hashrate_ph_s', 0) }}">
                </div>

                <div class="form-group">
                    <label for="max_bids_count">Max Bids Count</label>
                    <input type="number" id="max_bids_count" name="max_bids_count" value="{{ config.get('max_bids_count', 1) }}">
                </div>

                <div class="form-group">
                    <label for="max_price_sat_per_ph_day">Max Price (sat/PH/day, optional)</label>
                    <input type="number" min="1" id="max_price_sat_per_ph_day" name="max_price_sat_per_ph_day" value="{{ config.get('max_price_sat_per_ph_day', '') }}" placeholder="leave blank for no cap">
                    <small style="display: block; color: #666; margin-top: 0.25rem;">Must be at least one market tick; check the current tick in daemon logs.</small>
                </div>
            </div>
```

- [ ] **Step 2: Start the dashboard and verify the field renders**

Run: `uv run hashbidder web --port 8000` (in one shell).
In a browser at `http://localhost:8000/settings`:
- "Max Price (sat/PH/day, optional)" appears under Target Hashrate mode only.
- Leaving it blank and saving succeeds; `bids.toml` has no `max_price_sat_per_ph_day` line.
- Entering `750` and saving succeeds; `bids.toml` has `max_price_sat_per_ph_day = 750`; reloading the page pre-fills `750`.
- `0` or `-1` produces a red error message about positivity.

Stop the server with Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add hashbidder/templates/settings.html
git commit -m "feat: add max_price input to target-hashrate settings form

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Part B: Don't Raise Price on Served Bids

The stated rule applies to price only: when a bid is currently matched in the auction and priced below the newly-discovered `desired_price`, raising it would pay more sats for hashrate we're already buying cheaper. Speed must still flow through the existing `distribute_bids` / `speed_cooldown` logic — forcing the old speed would cause avoidable over-buying when `needed` drops.

The implementation collapses into the existing price-lock branch of `plan_with_cooldowns`: a served-below-desired bid is treated the same as a price-cooldown bid. The "being served" predicate requires both `BidStatus.ACTIVE` and a non-zero `current_speed` report, so stale-active-with-no-delivery bids don't block repricing.

### Task 6: Add `_is_being_served` helper and extend `make_user_bid`

**Files:**
- Modify: `hashbidder/target_hashrate.py` (new helper + top-level `BidStatus` import)
- Modify: `tests/conftest.py:68-93` (make_user_bid signature)
- Test: `tests/unit/test_target_hashrate.py` (new TestIsBeingServed class)

- [ ] **Step 1: Extend `make_user_bid` to accept `current_speed`**

This helper change is pre-test scaffolding and has no dedicated test of its own; existing callers remain unchanged because `current_speed` defaults to `None`.

Replace the body of `make_user_bid` in `tests/conftest.py` (lines 68-93) with:

```python
def make_user_bid(
    bid_id: str,
    price_sat_per_ph_day: int,
    speed: str,
    status: BidStatus = BidStatus.ACTIVE,
    amount: int = 100_000,
    remaining: int | None = None,
    upstream: Upstream | None = None,
    last_updated: datetime = DEFAULT_LAST_UPDATED,
    current_speed: Hashrate | None = None,
) -> UserBid:
    """Build a UserBid for tests.

    Price is specified in sat/PH/Day for convenience. Internally converts
    to sat/EH/Day (the API's native unit) by multiplying by 1000.
    """
    return UserBid(
        id=BidId(bid_id),
        price=HashratePrice(sats=Sats(price_sat_per_ph_day * 1000), per=EH_DAY),
        speed_limit_ph=Hashrate(Decimal(speed), HashUnit.PH, TimeUnit.SECOND),
        amount_sat=Sats(amount),
        status=status,
        progress=Progress.from_percentage(Decimal("0")),
        amount_remaining_sat=Sats(remaining if remaining is not None else amount),
        last_updated=last_updated,
        upstream=upstream or UPSTREAM,
        current_speed=current_speed,
    )
```

- [ ] **Step 2: Write the failing tests**

At the top of `tests/unit/test_target_hashrate.py`, update the `hashbidder.client` import to add `BidStatus` and the `hashbidder.target_hashrate` import to add `_is_being_served`:

```python
from hashbidder.client import BidItem, BidStatus, MarketSettings, OrderBook
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
```

Then add a new class after `TestFindMarketPrice`:

```python
class TestIsBeingServed:
    """Tests for _is_being_served."""

    def test_active_with_positive_current_speed_is_served(self) -> None:
        """ACTIVE + non-zero current_speed → being served."""
        bid = make_user_bid(
            "B1", 500, "1.0",
            status=BidStatus.ACTIVE,
            current_speed=_ph_s("0.9"),
        )
        assert _is_being_served(bid) is True

    def test_active_with_none_current_speed_is_not_served_deliberate_false_negative(
        self,
    ) -> None:
        """ACTIVE but no current_speed report → not served.

        This is a deliberate false negative: during transient telemetry gaps
        we prefer the (rare) cost of allowing a repricing that pays more for
        one tick over persistently locking in a bid that may no longer be
        served. Upstream clients are responsible for handling sustained
        telemetry loss — this predicate uses only the signals the UserBid
        carries, with no staleness fallback.
        """
        bid = make_user_bid(
            "B1", 500, "1.0",
            status=BidStatus.ACTIVE,
            current_speed=None,
        )
        assert _is_being_served(bid) is False

    def test_active_with_zero_current_speed_is_not_served(self) -> None:
        """Stale ACTIVE with zero delivery → not served (avoids preserving dead bids)."""
        bid = make_user_bid(
            "B1", 500, "1.0",
            status=BidStatus.ACTIVE,
            current_speed=_ph_s("0"),
        )
        assert _is_being_served(bid) is False

    def test_created_is_not_served(self) -> None:
        """CREATED = accepted but not matched yet."""
        bid = make_user_bid(
            "B1", 500, "1.0",
            status=BidStatus.CREATED,
            current_speed=_ph_s("1.0"),
        )
        assert _is_being_served(bid) is False

    def test_paused_is_not_served(self) -> None:
        """PAUSED bids are not matching."""
        bid = make_user_bid(
            "B1", 500, "1.0",
            status=BidStatus.PAUSED,
            current_speed=_ph_s("1.0"),
        )
        assert _is_being_served(bid) is False

    def test_canceled_is_not_served(self) -> None:
        """CANCELED bids are not matching."""
        bid = make_user_bid(
            "B1", 500, "1.0",
            status=BidStatus.CANCELED,
            current_speed=_ph_s("1.0"),
        )
        assert _is_being_served(bid) is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_target_hashrate.py::TestIsBeingServed -v`
Expected: FAIL — `ImportError: cannot import name '_is_being_served' from 'hashbidder.target_hashrate'`.

- [ ] **Step 4: Add the helper to `target_hashrate.py`**

In `hashbidder/target_hashrate.py`, change line 7 from:

```python
from hashbidder.client import MarketSettings, OrderBook, UserBid
```

to:

```python
from hashbidder.client import BidStatus, MarketSettings, OrderBook, UserBid
```

Then insert this helper immediately after the imports (before `compute_needed_hashrate`):

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_hashrate.py -v`
Expected: PASS — new tests pass and all existing tests still pass (they use `make_user_bid` with default `current_speed=None`, which returns `False` — unchanged from pre-feature behavior).

Also run: `uv run lint-imports`
Expected: PASS — `hashbidder.client` imports into `target_hashrate` were already present.

- [ ] **Step 6: Commit**

```bash
git add hashbidder/target_hashrate.py tests/conftest.py tests/unit/test_target_hashrate.py
git commit -m "feat: add _is_being_served helper requiring status + delivery

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Fold served-cheap bids into the price-lock path in `plan_with_cooldowns`

**Files:**
- Modify: `hashbidder/target_hashrate.py:92-145` (plan_with_cooldowns)
- Test: `tests/unit/test_target_hashrate.py` (TestPlanWithCooldowns — new cases)

The existing `plan_with_cooldowns` preserves price when `b.cooldown.price_cooldown` is True. The change: preserve price when the bid is *either* in a price cooldown *or* served-below-desired. This reuses every existing code path — the only thing that changes is the predicate that says "is this bid's price locked?".

- [ ] **Step 1: Write the failing tests**

Add these cases to `TestPlanWithCooldowns`:

```python
    def test_served_cheap_bid_keeps_price_redistributes_speed(self) -> None:
        """Served bid below desired_price: price preserved, speed freely redistributed."""
        bid = make_user_bid(
            "B1", 400, "2.0",
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
            "B1", 400, "10.0",
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
            "B1", 400, "2.0",
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
            "B1", 500, "2.0",
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
            "B1", 600, "2.0",
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
            "B1", 400, "2.0",
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_target_hashrate.py::TestPlanWithCooldowns -v`
Expected: FAIL — new cases fail because today `plan_with_cooldowns` resets the served-cheap bid's price to `desired_price`.

- [ ] **Step 3: Extend the price-lock predicate in `plan_with_cooldowns`**

In `hashbidder/target_hashrate.py`, insert these helpers immediately above `plan_with_cooldowns`:

```python
def _price_lt(a: HashratePrice, b: HashratePrice) -> bool:
    """Strict less-than on two HashratePrice values (normalized to sat/EH/Day)."""
    a_sats = int(a.to(HashUnit.EH, TimeUnit.DAY).sats)
    b_sats = int(b.to(HashUnit.EH, TimeUnit.DAY).sats)
    return a_sats < b_sats


def _price_is_locked(
    entry: BidWithCooldown, desired_price: HashratePrice
) -> bool:
    """Whether this bid's current price should be preserved rather than reset.

    Two independent reasons to preserve:
      - the price-decrease cooldown has not elapsed (can't lower it yet); or
      - the bid is actively served at a price below desired_price (raising
        would pay more for hashrate we're already buying cheaper).
    """
    if entry.cooldown.price_cooldown:
        return True
    return _is_being_served(entry.bid) and _price_lt(
        entry.bid.price, desired_price
    )
```

Then replace `plan_with_cooldowns` (lines 92-145) with:

```python
def plan_with_cooldowns(
    desired_price: HashratePrice,
    needed: Hashrate,
    max_bids_count: int,
    bids: tuple[BidWithCooldown, ...],
) -> tuple[BidConfig, ...]:
    """Build a bid plan that respects per-bid cooldown and served-price constraints.

    Price preservation rules (via `_price_is_locked`):
      - price_cooldown=True: keep the bid's current price (cannot lower yet).
      - served at a price strictly below desired_price: keep the bid's price
        (raising it would pay more for hashrate already being served cheaper).
      - otherwise: use desired_price.

    Speed rules:
      - speed_cooldown=True: keep the current speed_limit_ph. Consumes one
        slot from max_bids_count and its speed counts against `needed`.
      - otherwise: speed is re-assigned by distribute_bids.

    The remaining hashrate budget is split via distribute_bids and assigned
    first to price-locked bids (preserving their old price), then to free
    slots at desired_price.
    """
    speed_locked = [b for b in bids if b.cooldown.speed_cooldown]
    price_locked_only = [
        b
        for b in bids
        if _price_is_locked(b, desired_price) and not b.cooldown.speed_cooldown
    ]

    locked_speed_total = Hashrate(Decimal(0), HashUnit.PH, TimeUnit.SECOND)
    for entry in speed_locked:
        locked_speed_total = locked_speed_total + entry.bid.speed_limit_ph

    locked_entries = tuple(
        BidConfig(
            price=(
                entry.bid.price
                if _price_is_locked(entry, desired_price)
                else desired_price
            ),
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_hashrate.py -v`
Expected: PASS — all new served-cheap tests pass; all existing tests still pass (they use the default `current_speed=None` on their `UserBid` fixtures, so `_is_being_served` returns `False` and the served-cheap branch is never triggered).

Run the full suite: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hashbidder/target_hashrate.py tests/unit/test_target_hashrate.py
git commit -m "feat: preserve served-below-desired prices in plan_with_cooldowns

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: Truncate `speed_locked` at `max_bids_count` (heuristic by total locked spend)

**Pre-existing issue, closed here as a small follow-on.** Today, if the number of speed-cooldown bids exceeds `max_bids_count`, the planner returns more entries than requested. Cancellation isn't rate-limited the way decrease-edits are (cancel ends the bid; it's not a downward edit), so dropping excess speed-locked bids is safe and restores the user's intended cap.

**Why "heuristic" and not "optimal".** After truncation, `len(speed_locked) == max_bids_count`, so `remaining_slots == 0` and there are no free slots to replace dropped speed. Total plan cost is literally `sum(effective_plan_price × speed_limit_ph)` over kept entries — which is what we minimize. But cost-minimization can under-supply `needed` when `sum(speed_locked) ≤ needed` (regime A): dropping locked speed reduces delivered hashrate with no replacement available. The user's stated priority is "cheapest while achieving target," which means the correct objective in regime A would be to keep high-speed-locked bids ranked by cost *savings*, not pure cost. Implementing regime-awareness is meaningful complexity for a corner case that's already rare (the user has to have configured more cooldown-locked bids than `max_bids_count`); we're explicitly choosing the simpler cost-min heuristic and documenting the regime-A failure mode for future iteration.

**Sort key.** Tuple `(effective_plan_price × speed_limit, bid.id)`:
- Primary: `effective_plan_price × speed_limit_ph`, where `effective_plan_price = bid.price` if the bid's price is locked (price-cooldown or served-below-desired), else `desired_price`. This is the actual cost contribution of keeping the bid. Sorting ascending and taking the first `max_bids_count` keeps the cheapest bids by total spend.
- Secondary: `str(bid.id)`. Deterministic across runs regardless of upstream response order. Without this, ties on the primary key resolve via Python's stable sort — which is only stable on the input iterable, and `HashpowerClient.get_current_bids()` doesn't guarantee a stable order.

**Files:**
- Modify: `hashbidder/target_hashrate.py` (inside `plan_with_cooldowns`; add `_effective_plan_price` and `_truncation_cost_signal` helpers)
- Test: `tests/unit/test_target_hashrate.py` (TestPlanWithCooldowns)

- [ ] **Step 1: Write the failing tests**

Add all three of these to `TestPlanWithCooldowns`. The first is the simple "too many speed-locked" case; the second demonstrates why the cost signal must use *effective* plan price (not raw `bid.price`); the third demonstrates why it must include `× speed_limit` (not just unit price).

```python
    def test_speed_locked_exceeding_max_bids_is_truncated(self) -> None:
        """All speed-locked + all price-locked: keep the cheapest up to the cap."""
        cheap = make_user_bid(
            "B1", 300, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
        mid = make_user_bid(
            "B2", 500, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
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

        - cheap (id=B1, 300, not price-locked): repriced to 500 → effective = 500
        - mid   (id=B2, 400, not price-locked): repriced to 500 → effective = 500
        - dear  (id=B3, 450, price-locked):      keeps price    → effective = 450

        Cost signals (effective × speed): cheap=500, mid=500, dear=450.
        Tuple keys with bid.id tiebreak: (450,B3) < (500,B1) < (500,B2).
        Truncated to 2: dear + cheap. mid is dropped.

        A raw-bid.price sort would have kept [cheap, mid] (both repriced
        to 500), costing 1000 vs the correct plan's 950.
        """
        cheap = make_user_bid(
            "B1", 300, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
        mid = make_user_bid(
            "B2", 400, "1.0", last_updated=_NOW - timedelta(seconds=10)
        )
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
        """Truncation uses effective_price × speed, not unit price alone.

        Three speed-locked, all price-locked bids:
        - cheap_high (id=B1, 300, 10 PH/s): effective=300, signal=3000
        - exp_mid    (id=B2, 460,  5 PH/s): effective=460, signal=2300
        - mid_low    (id=B3, 450,  1 PH/s): effective=450, signal=450
        desired_price=500, max_bids_count=2.

        By unit price alone we would keep [cheap_high (300), mid_low (450)],
        paying 300×10 + 450×1 = 3450.
        By total cost we keep [mid_low (450), exp_mid (460×5=2300)], paying
        2750 — cheaper despite a higher unit price on exp_mid.

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
        assert cheap_high.price not in prices  # signal 3000, highest — dropped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_target_hashrate.py::TestPlanWithCooldowns -v -k "truncat"`
Expected: FAIL —
- `test_speed_locked_exceeding_max_bids_is_truncated`: result contains 3 entries, not 2.
- `test_speed_locked_truncation_uses_effective_plan_price`: result contains 3 entries; a raw-bid.price sort keeps the wrong pair.
- `test_speed_locked_truncation_uses_total_cost_not_unit_price`: result contains 3 entries; a unit-price sort keeps `cheap_high` (300) which costs 3000 because of its 10 PH/s.

- [ ] **Step 3: Add `_effective_plan_price` and `_truncation_cost_signal` helpers and rewrite the sort**

In `hashbidder/target_hashrate.py`, add these two helpers immediately after `_price_is_locked` (introduced in Task 7). `Decimal` is already imported at the top of the module via `domain/hashrate.py`'s usage; if not, add `from decimal import Decimal`.

```python
def _effective_plan_price(
    entry: BidWithCooldown, desired_price: HashratePrice
) -> HashratePrice:
    """Price this bid will end up at in the next plan.

    Price-locked bids keep their current price; everything else is
    repriced to desired_price. This is the correct price signal when
    reasoning about a kept bid's cost contribution, because
    `entry.bid.price` alone misleads whenever a bid would be repriced.
    """
    if _price_is_locked(entry, desired_price):
        return entry.bid.price
    return desired_price


def _truncation_cost_signal(
    entry: BidWithCooldown, desired_price: HashratePrice
) -> Decimal:
    """Total spend contribution of keeping this speed-locked bid.

    `effective_plan_price × speed_limit_ph`, normalized to a fixed
    unit pair (sat/EH/Day × EH/s) so signals from bids with different
    natural units are directly comparable. Used as the primary key
    when truncating speed_locked at max_bids_count: smaller signal =
    cheaper to keep, ranked first.

    Heuristic, not provably optimal — see plan_with_cooldowns
    docstring and Task 8 design notes for the regime-A caveat.
    """
    eff_sats = int(
        _effective_plan_price(entry, desired_price)
        .to(HashUnit.EH, TimeUnit.DAY)
        .sats
    )
    speed_eh_s = entry.bid.speed_limit_ph.to(
        HashUnit.EH, TimeUnit.SECOND
    ).value
    return Decimal(eff_sats) * speed_eh_s
```

Then replace the `speed_locked` selection line at the top of `plan_with_cooldowns` with:

```python
    speed_locked = sorted(
        (b for b in bids if b.cooldown.speed_cooldown),
        key=lambda b: (
            _truncation_cost_signal(b, desired_price),
            str(b.bid.id),
        ),
    )[:max_bids_count]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_target_hashrate.py -v`
Expected: PASS — both new cases pass; the effective-plan-price case validates that raw-bid.price sorting would have produced a worse (more expensive) plan.

Run the full suite: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hashbidder/target_hashrate.py tests/unit/test_target_hashrate.py
git commit -m "fix: truncate speed_locked at max_bids_count by total locked spend

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Lint + typecheck + import contracts**

Run: `make check`
Then: `uv run lint-imports`
Expected: PASS on format, lint, typecheck, tests, and import contracts.

- [ ] **Step 3: End-to-end dashboard smoke test**

Run (in a shell): `uv run hashbidder web --port 8000`
In a browser:
1. `http://localhost:8000/settings` — set Mode=Target Hashrate, Target=`1.0`, Max Bids=`2`, Max Price=`750`, fill upstream, Save.
2. Reload — Max Price pre-fills `750`.
3. Clear Max Price, Save — reload shows empty.
4. Enter `0` or `-1`, Save — red positivity error.

Stop server.

- [ ] **Step 4: Sub-tick max_price daemon-log verification**

This exercises the save-time/bid-time validation split end-to-end: the dashboard accepts a positive cap (structural check), then the daemon surfaces the tick-alignment failure on the next tick.

Run (in a shell): `uv run hashbidder web --port 8000`. Watch its stdout in this shell.

In a browser at `http://localhost:8000/settings`:
1. Set Mode=Target Hashrate, Target=`1.0`, Max Bids=`2`, Max Price=`1` (a positive sub-tick value), fill upstream, Save.
2. Wait for the next reconciliation tick (≤ `HASHBIDDER_INTERVAL_SECONDS`, default 300s — set `HASHBIDDER_INTERVAL_SECONDS=10` before launching for a faster check).

In the daemon shell, expected log line:
```
ERROR ... Reconciliation failed: max_price ... aligns to zero at tick ... sat/EH/Day; choose a cap >= one tick
```

Then in the browser, restore Max Price to a sane value (e.g. `750`) and Save; the next tick's log should show normal reconciliation output (no `max_price` error).

Stop server.

---

## Self-Review Notes

**Spec coverage:**
- Part A (#1) Settable max price limit → Tasks 1–5 (config parsing, cap+zero-tick guard, use-case wiring, dashboard persistence, UI).
- Part B (#2) Don't raise served prices → Tasks 6–7 (`_is_being_served` + make_user_bid extension; extend `_price_is_locked` predicate in `plan_with_cooldowns`).
- Orthogonal cleanup → Task 8 (`max_bids_count` enforcement against `speed_locked`).

**Type consistency:**
- `TargetHashrateConfig.max_price: HashratePrice | None` — dataclass field, constructor kwarg.
- `find_market_price(orderbook, tick, max_price: HashratePrice | None = None)` — keyword-optional.
- `_is_being_served(bid: UserBid) -> bool`, `_price_lt(a: HashratePrice, b: HashratePrice) -> bool`, `_price_is_locked(entry: BidWithCooldown, desired_price: HashratePrice) -> bool`, `_effective_plan_price(entry: BidWithCooldown, desired_price: HashratePrice) -> HashratePrice`, `_truncation_cost_signal(entry: BidWithCooldown, desired_price: HashratePrice) -> Decimal`.
- `BidStatus` imported at top level (no circular risk — `hashbidder.client` already imports from `hashbidder.target_hashrate`'s dependencies, not the other way).

**Design notes / why these specific choices:**

- *Strict less-than in served-cheap check.* If `bid.price == desired_price`, re-planning at `desired_price` is a no-op in reconcile (no edit emitted), so there's no economic reason to preserve. Strict `<` keeps the rule conservative.

- *`_is_being_served` requires non-zero `current_speed`.* `BidStatus.ACTIVE` can lag runtime delivery. Preserving a bid whose status hasn't flipped yet but whose delivery has stopped would block needed repricing. Cross-referencing with `current_speed` uses signals the `UserBid` already carries without adding new state. This is a deliberate false-negative tradeoff: transient telemetry gaps may briefly allow a repricing that could have been suppressed, which is preferable to persistently locking a dead bid. Persistent telemetry loss is the upstream client's concern, not this predicate's.

- *Served-cheap reuses the price-lock branch (no separate bucket).* The economic asymmetry is about price only — speed reductions are always allowed (subject to `speed_cooldown`). Folding served-cheap into `price_locked_only` means the existing `distribute_bids(remaining, remaining_slots)` logic continues to enforce `max_bids_count` for these bids.

- *`max_price` aligns down, not up.* Aligning down is the conservative (user-friendlier) direction: the cap becomes a valid market price and is strictly ≤ the stated cap. Aligning up would silently raise the cap above what the user typed.

- *Save-time validation is structural; tick-alignment is bid-time.* `TargetHashrateModel` only enforces `max_price > 0` — a unit-agnostic structural check that works without any knowledge of the market. The tick-alignment check lives in `find_market_price` because the market's `price_tick` is state-dependent and not available when `bids.toml` is written. A sub-tick cap surfaces as a `ValueError` with "max_price" in the message, caught by `daemon._tick`'s existing reconciliation `try/except` and written to the log. The dashboard UI carries help text pointing the user to the tick visible in those logs — a deliberate choice to keep the settings form decoupled from Braiins availability.

- *Truncation sort signal: `effective_plan_price × speed_limit`, with `bid.id` tiebreak.* When forced to drop a speed-locked bid, the cost contribution of keeping it is its effective price (the price it'll end up at in the next plan) times its locked speed. Sorting by unit price alone misranks bids whose speeds differ, and sorting by `entry.bid.price` directly is wrong whenever a bid would be repriced. `bid.id` as the secondary key gives a deterministic order across runs without depending on `HashpowerClient.get_current_bids()` returning bids in any particular order.

- *Why this is a heuristic, not the optimum.* After truncation, `len(speed_locked) == max_bids_count`, so `remaining_slots == 0` and there are no free slots to absorb dropped speed. Two regimes diverge:
  - **Regime A (`sum(speed_locked) ≤ needed`):** dropping any locked bid under-supplies `needed` with no replacement. The user's stated priority — "cheapest while achieving target" — would prefer keeping high-speed-locked bids, ranked by *savings* `(desired − effective) × speed`, not by total spend. Our heuristic minimizes spend but can under-deliver here.
  - **Regime B (`sum(speed_locked) > needed`):** over-supply exists; dropping reduces waste. Total-spend ranking is the right objective.
  Implementing regime-awareness adds meaningful complexity for a corner case that's already rare (it only fires when the user has more cooldown-locked bids than `max_bids_count`). We choose the simpler total-spend heuristic and call out the regime-A failure mode here so a future iteration can upgrade to regime-aware ranking with concrete evidence in hand.
