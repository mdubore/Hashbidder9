# Total Evaluation Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a comprehensive 4-graph monitoring suite with dual-axis charting, official Ocean JSON API integration, and performance moving averages.

**Architecture:** We will replace the Ocean HTML scraping with the official `api.ocean.xyz` JSON API. The SQLite `metrics` schema will be expanded to store Braiins share counts and Ocean reward window data. The frontend will be updated with four distinct Chart.js visualizations.

**Tech Stack:** Python 3.13, `httpx`, `aiosqlite`, Chart.js, FastAPI, Jinja2

---

### Task 1: Migrate OceanClient to JSON API

**Files:**
- Modify: `hashbidder/ocean_client.py`
- Modify: `tests/unit/test_ocean_client.py`

- [ ] **Step 1: Update `OceanClient` and models**

Add new fields to `AccountStats` and refactor `get_account_stats` to use `https://api.ocean.xyz/v1/user_hashrate/`.

```python
@dataclass(frozen=True)
class AccountStats:
    windows: tuple[HashrateWindow, ...]
    shares_window: int | None = None
    estimated_rewards: int | None = None
    next_block_earnings: int | None = None

class OceanClient:
    _API_URL = "https://api.ocean.xyz/v1/user_hashrate/"
    # ... update get_account_stats to parse JSON
```

- [ ] **Step 2: Update tests**

Replace HTML-based tests with JSON-mock tests.

- [ ] **Step 3: Commit**

```bash
git add hashbidder/ocean_client.py tests/unit/test_ocean_client.py
git commit -m "refactor: migrate OceanClient to official JSON API"
```

### Task 2: Expand Metrics Schema (Revision 3)

**Files:**
- Modify: `hashbidder/metrics.py`

- [ ] **Step 1: Add share and reward fields to `MetricRow` and DB**

```python
@dataclass
class MetricRow:
    # ... existing ...
    # Braiins Shares
    braiins_shares_accepted: int | None = None
    braiins_shares_rejected: int | None = None
    # Ocean Rewards
    ocean_shares_window: int | None = None
    ocean_estimated_rewards_sat: int | None = None
    ocean_next_block_earnings_sat: int | None = None
```

- [ ] **Step 2: Update `init_db`, `insert`, and `get_history`**

- [ ] **Step 3: Commit**

```bash
git add hashbidder/metrics.py
git commit -m "feat: expand metrics schema for shares and rewards"
```

### Task 3: Update Daemon Data Collection

**Files:**
- Modify: `hashbidder/daemon.py`

- [ ] **Step 1: Capture shares and rewards in `_tick`**

Extract `accepted_shares` and `rejected_shares` from `braiins_client.get_current_bids()`. Extract reward fields from `ocean_client.get_account_stats()`.

- [ ] **Step 2: Commit**

```bash
git add hashbidder/daemon.py
git commit -m "feat: record share and reward metrics in daemon loop"
```

### Task 4: Implement Quad-Graph Dashboard

**Files:**
- Modify: `hashbidder/templates/index.html`

- [ ] **Step 1: Add Chart.js logic for Transmission Quality (Graph 3)**

Implement dual Y-axis: Left for Share counts, Right for Rejection %.

- [ ] **Step 2: Add Chart.js logic for Ocean Rewards (Graph 4)**

Implement dual Y-axis: Left for Sat rewards, Right for Share count.

- [ ] **Step 3: Add Moving Averages to Hashrate Chart (Graph 1)**

Implement client-side moving average calculation for 1d, 10d, and 30d trend lines.

- [ ] **Step 4: Commit**

```bash
git add hashbidder/templates/index.html
git commit -m "ui: implement quad-graph suite with dual-axis charts and moving averages"
```

### Task 5: Final Build

- [ ] **Step 1: Rebuild StartOS package**

```bash
make clean && make
```

- [ ] **Step 2: Commit**

```bash
git add .
git commit -m "build: finalized Hashbidder v1.1.0 with total evaluation suite"
```
