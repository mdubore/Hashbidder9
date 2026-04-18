# Async Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the existing synchronous HTTP clients and use cases to use `httpx.AsyncClient` and `asyncio` for concurrent, non-blocking I/O.

**Architecture:** We will replace `httpx.Client` with `httpx.AsyncClient` in `BraiinsClient`, `OceanClient`, and `MempoolClient`. All network-bound methods will become `async def`. We will update the `hashbidder/use_cases/` to await these methods, and finally, wrap the CLI entrypoints in `hashbidder/main.py` with `asyncio.run()`.

**Tech Stack:** Python 3.13, `httpx`, `asyncio`, `pytest-asyncio` (via `anyio`)

---

### Task 1: Add pytest-asyncio dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Add pytest-asyncio**

```bash
uv add --dev pytest-asyncio>=0.23.5
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pytest-asyncio for async testing"
```

### Task 2: Refactor OceanClient to Async

**Files:**
- Modify: `hashbidder/ocean_client.py`
- Modify: `tests/unit/test_ocean_client.py`

- [ ] **Step 1: Make OceanClient methods async**

In `hashbidder/ocean_client.py`, change the `OceanSource` protocol and `OceanClient` signature:

```python
class OceanSource(Protocol):
    """Protocol for Ocean data sources."""
    async def get_account_stats(self, address: BtcAddress) -> AccountStats: ...

class OceanClient:
    # ... init stays the same, but typehint http_client as httpx.AsyncClient
    def __init__(self, base_url: httpx.URL, http_client: httpx.AsyncClient) -> None:
        self._base_url = base_url
        self._http = http_client

    @ocean_retry
    async def get_account_stats(self, address: BtcAddress) -> AccountStats:
        url = f"{self._base_url}{self._HASHRATE_ROWS_PATH}"
        resp = await self._http.get(url, params={"user": address.value})
        # ... rest remains unchanged
```

- [ ] **Step 2: Update tests in `test_ocean_client.py`**

Add `@pytest.mark.asyncio` to the test class/methods, and use `httpx.AsyncClient` with an ASGI transport or mock. For simplicity, if using `respx` or mock clients, just `await client.get_account_stats(...)`. Change any `httpx.Client` in the tests to `httpx.AsyncClient`. Update fake clients to have `async def`.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/unit/test_ocean_client.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add hashbidder/ocean_client.py tests/unit/test_ocean_client.py
git commit -m "refactor: migrate OceanClient to async"
```

### Task 3: Refactor MempoolClient to Async

**Files:**
- Modify: `hashbidder/mempool_client.py`
- Modify: `tests/unit/test_mempool_client.py`

- [ ] **Step 1: Make MempoolClient async**

In `hashbidder/mempool_client.py`, change `MempoolSource` protocol and `MempoolClient`:

```python
class MempoolSource(Protocol):
    async def get_chain_stats(self, block_count: int) -> ChainStats: ...

class MempoolClient:
    def __init__(self, base_url: httpx.URL, http_client: httpx.AsyncClient) -> None:
        self._base_url = base_url
        self._http = http_client

    @mempool_retry
    async def get_chain_stats(self, block_count: int) -> ChainStats:
        # ... await self._http.get(...)
```

- [ ] **Step 2: Update tests**

Add `@pytest.mark.asyncio` and `await` the client methods in `tests/unit/test_mempool_client.py`.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/unit/test_mempool_client.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add hashbidder/mempool_client.py tests/unit/test_mempool_client.py
git commit -m "refactor: migrate MempoolClient to async"
```

### Task 4: Refactor BraiinsClient to Async

**Files:**
- Modify: `hashbidder/client.py`
- Modify: `tests/unit/test_braiins_client.py`
- Modify: `tests/unit/test_fake_client.py`

- [ ] **Step 1: Make BraiinsClient async**

In `hashbidder/client.py`, update `HashpowerClient` protocol and `BraiinsClient` methods (`get_orderbook`, `get_current_bids`, `create_bid`, `edit_bid`, `cancel_bid`, etc.) to `async def`. Update `_request` to `async def _request` and `await self._http.request(...)`. 

- [ ] **Step 2: Update FakeClient**

Update `FakeClient` in `tests/unit/test_fake_client.py` and `hashbidder/fake_client.py` (if it exists) to match the `async` protocol methods.

- [ ] **Step 3: Update tests**

Add `@pytest.mark.asyncio` and `await` calls in `test_braiins_client.py` and `test_fake_client.py`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_braiins_client.py tests/unit/test_fake_client.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hashbidder/client.py tests/unit/test_braiins_client.py tests/unit/test_fake_client.py
git commit -m "refactor: migrate BraiinsClient to async"
```

### Task 5: Refactor Use Cases and Bid Runner to Async

**Files:**
- Modify: `hashbidder/use_cases/*.py`
- Modify: `hashbidder/bid_runner.py`
- Modify: `tests/unit/test_use_cases_*.py`
- Modify: `tests/unit/test_execute.py`

- [ ] **Step 1: Make Use Cases async**

Update the use case functions to `async def`:
- `hashbidder/use_cases/ping.py`: `async def run_ping(...)`
- `hashbidder/use_cases/hashvalue.py`: `async def run_hashvalue(...)`
- `hashbidder/use_cases/ocean.py`: `async def run_ocean(...)`
- `hashbidder/use_cases/set_bids.py`: `async def run_set_bids(...)`
- `hashbidder/use_cases/set_bids_target.py`: `async def run_set_bids_target(...)`

In `hashbidder/bid_runner.py`, change `execute` to `async def execute(...)` and await the `client.create_bid`, `client.cancel_bid`, etc.

- [ ] **Step 2: Update tests**

Add `@pytest.mark.asyncio` and `await` to all related unit tests.

- [ ] **Step 3: Run tests**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add hashbidder/use_cases/ hashbidder/bid_runner.py tests/unit/
git commit -m "refactor: migrate use cases and bid runner to async"
```

### Task 6: Refactor CLI Entrypoints

**Files:**
- Modify: `hashbidder/main.py`
- Modify: `tests/cli/test_*.py`

- [ ] **Step 1: Wrap CLI commands in asyncio.run**

In `hashbidder/main.py`, the HTTP clients need to be initialized with `httpx.AsyncClient()`. However, `httpx.AsyncClient()` must be created *inside* an event loop. 

Update the CLI commands to use a helper or run `asyncio.run()`. For `click`, you can create an async decorator:

```python
import asyncio
from functools import wraps

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper
```

Apply `@coro` to all `@cli.command()` functions, make them `async def`, and initialize `app.braiins`, `app.mempool`, `app.ocean` with `httpx.AsyncClient` inside those async commands instead of globally in the group, or handle it via a factory.

- [ ] **Step 2: Update CLI tests**

Ensure `tests/cli/` tests pass with the new async CLI structure.

- [ ] **Step 3: Run all checks**

Run: `make check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add hashbidder/main.py tests/cli/
git commit -m "refactor: integrate async use cases into click CLI"
```
