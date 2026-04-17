# Operational Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the operational resilience of the `hashbidder` CLI by adding configurable HTTP timeouts, network retries for idempotent reads, and graceful fallbacks in the `Makefile`.

**Architecture:** Introduce `tenacity` for exponential backoff retries on transient network and HTTP errors across all API clients. Expose an `HTTP_TIMEOUT` environment variable in the CLI entrypoint. Add a check in the `Makefile` to ensure `uv` is installed before running commands.

**Tech Stack:** Python 3.13, `httpx`, `tenacity`, GNU Make

---

### Task 1: Makefile Dependencies Check

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add a uv installation check to the Makefile**

Modify `Makefile` to include a `.check-uv` target that verifies `uv` is in the PATH. Make other targets depend on it.

```makefile
.PHONY: format lint typecheck imports test check .check-uv

.check-uv:
	@command -v uv >/dev/null 2>&1 || { echo >&2 "Error: 'uv' is not installed. Please install it from https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }

format: .check-uv
	uv run ruff format .
	uv run ruff check --select I --fix .

lint: .check-uv
	uv run ruff check .

typecheck: .check-uv
	uv run mypy .

imports: .check-uv
	uv run lint-imports

test: .check-uv
	uv run pytest -v

check: format lint typecheck imports test
```

- [ ] **Step 2: Commit**

```bash
git add Makefile
git commit -m "build: add uv installation check to Makefile"
```

### Task 2: Add `tenacity` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add tenacity to dependencies**

Run the `uv` command to add the dependency:

```bash
uv add tenacity>=8.2.3
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add tenacity dependency for network retries"
```

### Task 3: Configurable Timeout

**Files:**
- Modify: `hashbidder/main.py`
- Modify: `tests/unit/test_execute.py` (if necessary, though we just read env var)

- [ ] **Step 1: Modify `main.py` to read `HTTP_TIMEOUT`**

Update the client initializations in `hashbidder/main.py`.

```python
import os

def _get_http_timeout() -> float:
    """Read HTTP_TIMEOUT from env, defaulting to 10.0 seconds."""
    try:
        return float(os.environ.get("HTTP_TIMEOUT", "10.0"))
    except ValueError:
        return 10.0
```

Update the `cli` function in `hashbidder/main.py`:

```python
@cli.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Also log to this file.",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, log_file: Path | None) -> None:
    """Hashbidder CLI."""
    load_dotenv()
    _setup_logging(verbose, log_file)
    if ctx.obj is None:
        ctx.obj = Clients()
    app: Clients = ctx.obj
    timeout = _get_http_timeout()
    if app.braiins is None:
        api_key = os.environ.get("BRAIINS_API_KEY")
        http_client = httpx.Client(timeout=timeout)
        app.braiins = BraiinsClient(API_BASE, api_key=api_key, http_client=http_client)
    if app.mempool is None:
        app.mempool = MempoolClient(_resolve_mempool_url(), httpx.Client(timeout=timeout))
    if app.ocean is None:
        app.ocean = OceanClient(DEFAULT_OCEAN_URL, httpx.Client(timeout=timeout))
```

- [ ] **Step 2: Run tests**

Run: `make test`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add hashbidder/main.py
git commit -m "feat: make HTTP timeout configurable via HTTP_TIMEOUT env var"
```

### Task 4: Network Retries for BraiinsClient

**Files:**
- Modify: `hashbidder/client.py`

- [ ] **Step 1: Add retry logic**

Add `tenacity` imports at the top of `hashbidder/client.py`:

```python
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
```

Add a helper function to determine if an error is transient:

```python
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
```

Apply the `@braiins_retry` decorator to idempotent read methods in `BraiinsClient`:
- `get_orderbook(self) -> OrderBook`
- `get_current_bids(self) -> tuple[UserBid, ...]`
- `get_market_settings(self) -> MarketSettings`
- `get_account_balance(self) -> AccountBalance`

Example:
```python
    @braiins_retry
    def get_orderbook(self) -> OrderBook:
```

- [ ] **Step 2: Run tests**

Run: `make test`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add hashbidder/client.py
git commit -m "feat: add tenacity retries to BraiinsClient read operations"
```

### Task 5: Network Retries for OceanClient

**Files:**
- Modify: `hashbidder/ocean_client.py`

- [ ] **Step 1: Add retry logic**

Add imports and retry logic to `hashbidder/ocean_client.py`:

```python
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

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
```

Apply `@ocean_retry` to `get_account_stats(self, address: BtcAddress) -> AccountStats` in `OceanClient`.

- [ ] **Step 2: Run tests**

Run: `make test`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add hashbidder/ocean_client.py
git commit -m "feat: add tenacity retries to OceanClient"
```

### Task 6: Network Retries for MempoolClient

**Files:**
- Modify: `hashbidder/mempool_client.py`

- [ ] **Step 1: Add retry logic**

Add imports and retry logic to `hashbidder/mempool_client.py`:

```python
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

def _is_transient_mempool_error(e: BaseException) -> bool:
    if isinstance(e, (httpx.TimeoutException, httpx.RequestError)):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code == 429 or e.response.status_code >= 500
    if isinstance(e, MempoolError):
        return e.status_code == 429 or e.status_code >= 500
    return False

mempool_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_transient_mempool_error),
    reraise=True,
)
```

Apply `@mempool_retry` to `get_chain_stats(self, block_count: int) -> ChainStats` in `MempoolClient`.

- [ ] **Step 2: Run tests**

Run: `make test`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add hashbidder/mempool_client.py
git commit -m "feat: add tenacity retries to MempoolClient"
```
