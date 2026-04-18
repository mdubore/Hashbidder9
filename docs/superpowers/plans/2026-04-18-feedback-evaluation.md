# Feedback & Evaluation Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand metrics collection and logging to allow for "actual vs. desired" evaluation and feedback-loop fine-tuning.

**Architecture:** We will expand the SQLite `metrics` schema to include target hashrate, needed hashrate, market price, bid action counts, and account balance. The `daemon.py` tick logic will be updated to populate these new fields and emit a high-signal `INFO` summary log on every iteration.

**Tech Stack:** Python 3.13, `aiosqlite`, `asyncio`, `logging`

---

### Task 1: Expand Metrics Data Model

**Files:**
- Modify: `hashbidder/metrics.py`

- [ ] **Step 1: Update `MetricRow` dataclass and `MetricsRepo.init_db`**

Add the new fields to the dataclass and the SQL schema.

```python
@dataclass
class MetricRow:
    timestamp: int
    braiins_hashrate_phs: Decimal
    ocean_hashrate_phs: Decimal
    braiins_connected: bool
    ocean_connected: bool
    mempool_connected: bool
    # New Fields
    target_hashrate_phs: Decimal | None = None
    needed_hashrate_phs: Decimal | None = None
    market_price_sat: int | None = None
    bids_active: int | None = None
    bids_created: int | None = None
    bids_edited: int | None = None
    bids_cancelled: int | None = None
    balance_sat: int | None = None
```

Update `init_db` to include these columns in the `metrics` table. Note: Use `TEXT` for Decimals for consistency with existing pattern.

- [ ] **Step 2: Update `MetricsRepo.insert` and `get_history`**

Update the SQL queries to handle the new columns.

- [ ] **Step 3: Commit**

```bash
git add hashbidder/metrics.py
git commit -m "feat: expand metrics schema for feedback evaluation"
```

### Task 2: Update Tests for Metrics

**Files:**
- Modify: `tests/unit/test_metrics.py`

- [ ] **Step 1: Update existing test to use new fields**

Ensure the test verifies that the new optional fields are correctly persisted and retrieved.

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/unit/test_metrics.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_metrics.py
git commit -m "test: update metrics tests for new schema"
```

### Task 3: Enhance Daemon Data Collection & Logging

**Files:**
- Modify: `hashbidder/daemon.py`

- [ ] **Step 1: Update `_tick` to return results and record detailed metrics**

Refactor `_tick` to capture the results from `run_set_bids` and `run_set_bids_target`. Populate the expanded `MetricRow`.

```python
async def _tick(...) -> None:
    # ... existing collection ...
    
    # Track the decision inputs
    target_phs = None
    needed_phs = None
    market_price = None

    # Load config
    config = load_config(config_path)
    
    # Reconcile and capture results
    result: SetBidsResult | None = None
    if isinstance(config, TargetHashrateConfig):
        target_res = await use_cases.run_set_bids_target(...)
        target_phs = target_res.inputs.target.value
        needed_phs = target_res.inputs.needed.value
        market_price = int(target_res.inputs.price.sats)
        result = target_res.set_bids_result
    else:
        # Manual mode
        result = await use_cases.run_set_bids(...)

    # Extract outcome counts
    # ...
```

- [ ] **Step 2: Implement High-Signal Logging**

Add an `logger.info()` call at the end of every successful tick that prints the "Actual vs. Desired" summary.

- [ ] **Step 3: Commit**

```bash
git add hashbidder/daemon.py
git commit -m "feat: enhance daemon logging and data collection for evaluation"
```

### Task 4: Final Verification

**Files:**
- [ ] **Step 1: Run full check**

Run: `make check`
Expected: PASS

- [ ] **Step 2: Smoke test logs**

Run: `export OCEAN_ADDRESS=... && uv run hashbidder web`
Verify that `INFO` logs now show the detailed summary.
