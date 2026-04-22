# Hashrate Diagnostic Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the dashboard hashrate visualization into a diagnostic comparison chart and a long-term trend chart, using raw nullable upstream metrics with frontend carry-forward only.

**Architecture:** The daemon will persist raw Ocean and Braiins hashrate metrics without cross-metric fallback. The frontend will render two charts from those raw values, carrying forward the last non-null plotted value per series. SSE payloads will include the new raw fields so live updates match historical rendering.

**Tech Stack:** FastAPI, aiosqlite, Jinja2, Chart.js, Vanilla JS, pytest, pytest-asyncio.

---

### Task 1: Ocean Window Selection Helpers (TDD)

**Files:**
- Modify: `hashbidder/daemon.py`
- Modify: `tests/unit/test_daemon.py`

- [ ] **Step 1: Write failing tests for raw Ocean window extraction**

```python
def test_select_ocean_60s_only() -> None:
    stats = AccountStats(
        windows=(
            HashrateWindow(window=OceanTimeWindow.SIXTY_SECONDS, hashrate=_ph_s("0.50")),
            HashrateWindow(window=OceanTimeWindow.FIVE_MINUTES, hashrate=_ph_s("0.60")),
        )
    )
    assert _select_ocean_hashrate_for_window(stats, OceanTimeWindow.SIXTY_SECONDS) == Decimal("0.50")


def test_select_ocean_window_returns_none_when_missing() -> None:
    stats = AccountStats(
        windows=(HashrateWindow(window=OceanTimeWindow.TEN_MINUTES, hashrate=_ph_s("0.28")),)
    )
    assert _select_ocean_hashrate_for_window(stats, OceanTimeWindow.SIXTY_SECONDS) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_daemon.py -v`
Expected: FAIL with missing helper errors.

- [ ] **Step 3: Implement explicit Ocean window selector**

```python
def _select_ocean_hashrate_for_window(
    stats: AccountStats,
    window: OceanTimeWindow,
) -> Decimal | None:
    for item in stats.windows:
        if item.window is window:
            return item.hashrate.to(HashUnit.PH, TimeUnit.SECOND).value
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_daemon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hashbidder/daemon.py tests/unit/test_daemon.py
git commit -m "test: add explicit Ocean window selectors"
```

---

### Task 2: Braiins Raw Metric Parsing (TDD)

**Files:**
- Modify: `hashbidder/client.py`
- Modify: `tests/unit/test_braiins_client.py`

- [ ] **Step 1: Write failing tests for current speed and delivered hashrate without fallback**

```python
def test_parse_user_bid_keeps_current_and_delivered_separate() -> None:
    item = {
        "bid": {...},
        "state_estimate": {"avg_speed_ph": "1.25"},
        "counters_committed": {"delivered_hr_ph": "1.10"},
    }
    bid = _parse_user_bid(item)
    assert bid.current_speed is not None
    assert bid.current_speed.value == Decimal("1.25")
    assert bid.delivered_hashrate is not None
    assert bid.delivered_hashrate.value == Decimal("1.10")


def test_parse_user_bid_does_not_fallback_delivered_to_current() -> None:
    item = {
        "bid": {...},
        "state_estimate": {"avg_speed_ph": "1.25"},
        "counters_committed": {},
    }
    bid = _parse_user_bid(item)
    assert bid.current_speed is not None
    assert bid.delivered_hashrate is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_braiins_client.py -v`
Expected: FAIL due to fallback behavior.

- [ ] **Step 3: Remove delivered fallback**

```python
current_speed = parse_phs(state.get("avg_speed_ph"))
delivered_hr = parse_phs(counters.get("delivered_hr_ph"))

return UserBid(
    ...,
    current_speed=current_speed,
    delivered_hashrate=delivered_hr,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_braiins_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hashbidder/client.py tests/unit/test_braiins_client.py
git commit -m "fix: separate Braiins current and delivered metrics"
```

---

### Task 3: Metrics Schema And Repo Migration (TDD)

**Files:**
- Modify: `hashbidder/metrics.py`
- Modify: `tests/unit/test_metrics.py`

- [ ] **Step 1: Write failing metrics repo tests for new nullable columns**

```python
row = MetricRow(
    timestamp=1000,
    braiins_connected=True,
    ocean_connected=True,
    mempool_connected=True,
    ocean_hashrate_60s_phs=Decimal("0.50"),
    ocean_hashrate_600s_phs=Decimal("0.45"),
    ocean_hashrate_86400s_phs=Decimal("0.40"),
    braiins_current_speed_phs=Decimal("0.47"),
    braiins_delivered_hashrate_phs=None,
)
await repo.insert(row)
history = await repo.get_history(1000)
assert history[0].ocean_hashrate_60s_phs == Decimal("0.50")
assert history[0].braiins_delivered_hashrate_phs is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_metrics.py -v`
Expected: FAIL with unknown fields or migration mismatch.

- [ ] **Step 3: Add raw nullable columns and migration support**

Add these fields to `MetricRow` and SQLite schema:

- `ocean_hashrate_60s_phs`
- `ocean_hashrate_600s_phs`
- `ocean_hashrate_86400s_phs`
- `braiins_current_speed_phs`
- `braiins_delivered_hashrate_phs`

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hashbidder/metrics.py tests/unit/test_metrics.py
git commit -m "feat: store raw Ocean and Braiins hashrate metrics"
```

---

### Task 4: Daemon Collection Of Raw Metrics (TDD)

**Files:**
- Modify: `hashbidder/daemon.py`
- Modify: `tests/unit/test_daemon.py`

- [ ] **Step 1: Write failing tests for raw metric collection**

Add assertions that a persisted `MetricRow` uses:

- Ocean 60s only for `ocean_hashrate_60s_phs`
- Ocean 10m only for `ocean_hashrate_600s_phs`
- Ocean 24h only for `ocean_hashrate_86400s_phs`
- Braiins current speed sum for `braiins_current_speed_phs`
- Braiins delivered sum for `braiins_delivered_hashrate_phs`

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_daemon.py -v`
Expected: FAIL

- [ ] **Step 3: Persist raw nullable hashrate metrics**

```python
ocean_hashrate_60s_phs = _select_ocean_hashrate_for_window(stats, OceanTimeWindow.SIXTY_SECONDS)
ocean_hashrate_600s_phs = _select_ocean_hashrate_for_window(stats, OceanTimeWindow.TEN_MINUTES)
ocean_hashrate_86400s_phs = _select_ocean_hashrate_for_window(stats, OceanTimeWindow.DAY)

braiins_current_speed_phs = Decimal(0)
braiins_delivered_hashrate_phs = Decimal(0)
seen_current = False
seen_delivered = False
for bid in current_bids:
    if bid.current_speed is not None:
        braiins_current_speed_phs += bid.current_speed.to(HashUnit.PH, TimeUnit.SECOND).value
        seen_current = True
    if bid.delivered_hashrate is not None:
        braiins_delivered_hashrate_phs += bid.delivered_hashrate.to(HashUnit.PH, TimeUnit.SECOND).value
        seen_delivered = True

row = MetricRow(
    ...,
    ocean_hashrate_60s_phs=ocean_hashrate_60s_phs,
    ocean_hashrate_600s_phs=ocean_hashrate_600s_phs,
    ocean_hashrate_86400s_phs=ocean_hashrate_86400s_phs,
    braiins_current_speed_phs=braiins_current_speed_phs if seen_current else None,
    braiins_delivered_hashrate_phs=braiins_delivered_hashrate_phs if seen_delivered else None,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_daemon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hashbidder/daemon.py tests/unit/test_daemon.py
git commit -m "feat: collect raw nullable hashrate comparison metrics"
```

---

### Task 5: SSE Serialization Of New Fields (TDD)

**Files:**
- Modify: `hashbidder/dashboard.py`
- Modify: `tests/unit/test_stream.py`

- [ ] **Step 1: Write failing stream tests for new payload fields**

Assert serialized SSE payload includes:

- `ocean_hashrate_60s_phs`
- `ocean_hashrate_600s_phs`
- `ocean_hashrate_86400s_phs`
- `braiins_current_speed_phs`
- `braiins_delivered_hashrate_phs`

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_stream.py -v`
Expected: FAIL

- [ ] **Step 3: Update dashboard serialization and history rendering context**

Ensure `serialize_metric_row()` includes the new fields and existing history rendering remains compatible with nullable values.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hashbidder/dashboard.py tests/unit/test_stream.py
git commit -m "feat: expose raw hashrate series in SSE payloads"
```

---

### Task 6: Template Refactor For Two Hashrate Charts (TDD)

**Files:**
- Modify: `hashbidder/templates/index.html`

- [ ] **Step 1: Add persistent chart containers for diagnostic and trend charts**

Replace the old single hashrate chart with:

- `hashrateDiagnosticChart`
- `hashrateTrendChart`

Keep existing price, quality, and reward charts.

- [ ] **Step 2: Map raw nullable fields into frontend history objects**

```javascript
function mapRow(row) {
    return {
        timestamp: new Date(row.timestamp * 1000),
        ocean60s: row.ocean_hashrate_60s_phs !== null ? parseFloat(row.ocean_hashrate_60s_phs) * 1000 : null,
        ocean10m: row.ocean_hashrate_600s_phs !== null ? parseFloat(row.ocean_hashrate_600s_phs) * 1000 : null,
        ocean24h: row.ocean_hashrate_86400s_phs !== null ? parseFloat(row.ocean_hashrate_86400s_phs) * 1000 : null,
        braiinsCurrent: row.braiins_current_speed_phs !== null ? parseFloat(row.braiins_current_speed_phs) * 1000 : null,
        braiinsDelivered: row.braiins_delivered_hashrate_phs !== null ? parseFloat(row.braiins_delivered_hashrate_phs) * 1000 : null,
        target: row.target_hashrate_phs !== null ? parseFloat(row.target_hashrate_phs) * 1000 : null,
        ...
    };
}
```

- [ ] **Step 3: Run browser/manual smoke check**

Run: `uv run pytest tests/unit/test_stream.py -v`
Expected: PASS before manual browser check.

- [ ] **Step 4: Commit**

```bash
git add hashbidder/templates/index.html
git commit -m "ui: split hashrate dashboard into diagnostic and trend charts"
```

---

### Task 7: Frontend Carry-Forward And Chart Logic

**Files:**
- Modify: `hashbidder/templates/index.html`

- [ ] **Step 1: Implement carry-forward helper for nullable raw series**

```javascript
function carryForward(values) {
    let last = null;
    return values.map((value) => {
        if (value !== null) last = value;
        return last;
    });
}
```

- [ ] **Step 2: Build diagnostic chart from carried-forward raw series**

Diagnostic chart series:

- `Ocean Actual (60s)`
- `Ocean 10m`
- `Braiins Current`
- `Braiins Delivered Avg`
- `Target`

- [ ] **Step 3: Build trend chart from Ocean 24h and long moving averages**

Trend chart series:

- `Ocean 24h`
- `MA 10d`
- `MA 30d`
- `Target`

Use `carryForward(historyData.map(d => d.ocean24h))` as the base series for both moving averages.

- [ ] **Step 4: Update live SSE path to preserve carry-forward behavior**

On each new point:

- append raw nullable values,
- rebuild carried-forward arrays,
- recalculate chart datasets,
- update both hashrate charts.

- [ ] **Step 5: Commit**

```bash
git add hashbidder/templates/index.html
git commit -m "ui: carry forward missing raw samples in hashrate charts"
```

---

### Task 8: Transmission Quality Ratio Auto-Scaling

**Files:**
- Modify: `hashbidder/templates/index.html`

- [ ] **Step 1: Replace fixed `y1.max = 100` with computed bound**

```javascript
const ratioData = historyData.map(d => {
    const total = d.accepted + d.rejected;
    return total > 0 ? (d.rejected / total) * 100 : 0;
});
const maxRatio = Math.max(...ratioData, 0);
charts.quality.options.scales.y1.max = Math.min(100, Math.max(5, Math.ceil(maxRatio * 1.1)));
```

- [ ] **Step 2: Apply the same logic during live updates**

- [ ] **Step 3: Manual visual verification**

Observe the Transmission Quality chart with low rejection ratios and confirm the ratio line uses the chart area meaningfully.

- [ ] **Step 4: Commit**

```bash
git add hashbidder/templates/index.html
git commit -m "ui: auto-scale transmission quality ratio axis"
```

---

### Task 9: End-To-End Verification

- [ ] **Step 1: Run unit tests for changed areas**

Run: `pytest tests/unit/test_daemon.py tests/unit/test_metrics.py tests/unit/test_braiins_client.py tests/unit/test_stream.py -v`
Expected: PASS

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 3: Verify no HTMX polling remains on dashboard**

Run: `grep -r "hx-get" hashbidder/templates`
Expected: no matches in `hashbidder/templates/index.html`

- [ ] **Step 4: Build package**

Run: `make hashbidder9.s9pk`
Expected: successful build

- [ ] **Step 5: Commit final integration**

```bash
git commit -am "feat: add diagnostic and trend hashrate charts"
```
