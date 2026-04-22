# Dashboard SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace HTMX whole-fragment polling with a Server-Sent Events (SSE) pipeline for zero-flicker dashboard updates, featuring replay-on-connect, surgical DOM manipulation, and robust overflow recovery.

**Architecture:** 
- **Backend:** Internal bounded-queue Pub/Sub (`BroadcastHub`). `/stream` endpoint seeds initial state using `since` parameter and handles reconnections via `Last-Event-ID`. **Replay is loss-tolerant with client-side dedupe by timestamp.**
- **Frontend:** Persistent Vanilla JS state (`historyData`, `charts`). SSE events trigger targeted DOM updates and incremental `Chart.update()` calls.

**Tech Stack:** FastAPI, SSE (StreamingResponse), Chart.js, Vanilla JS.

---

### Task 1: Broadcast Hub (TDD)

**Files:**
- Create: `hashbidder/broadcast_hub.py`
- Create: `tests/unit/test_broadcast_hub.py`

- [ ] **Step 1: Write tests for hub lifecycle, overflow, and disconnect cleanup**

```python
# tests/unit/test_broadcast_hub.py
import asyncio
import pytest
from hashbidder.broadcast_hub import BroadcastHub, OVERFLOW_SIGNAL

@pytest.mark.asyncio
async def test_broadcast_hub_lifecycle():
    hub = BroadcastHub()
    q = await hub.subscribe()
    hub.publish({"tick": 1})
    assert await q.get() == {"tick": 1}
    hub.unsubscribe(q)
    assert len(hub._subscribers) == 0

@pytest.mark.asyncio
async def test_broadcast_hub_overflow():
    hub = BroadcastHub()
    q = await hub.subscribe()
    for i in range(50): hub.publish(i)
    hub.publish("overflow_trigger")
    assert q.get_nowait() == OVERFLOW_SIGNAL
    assert q.empty()

@pytest.mark.asyncio
async def test_broadcast_hub_disconnect_cleanup():
    hub = BroadcastHub()
    q = await hub.subscribe()
    assert len(hub._subscribers) == 1
    hub.unsubscribe(q)
    assert len(hub._subscribers) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_broadcast_hub.py`
Expected: FAIL (Module not found)

- [ ] **Step 3: Implement `BroadcastHub`**

```python
# hashbidder/broadcast_hub.py
import asyncio
from typing import Any, Final

OVERFLOW_SIGNAL: Final = "OVERFLOW"

class BroadcastHub:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    async def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=50)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    def publish(self, data: Any):
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                while not q.empty():
                    q.get_nowait()
                q.put_nowait(OVERFLOW_SIGNAL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_broadcast_hub.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hashbidder/broadcast_hub.py tests/unit/test_broadcast_hub.py
git commit -m "feat: implement BroadcastHub with overflow and cleanup tests"
```

---

### Task 2: Backend Publication & Dependency Wiring

**Files:**
- Modify: `hashbidder/daemon.py`
- Modify: `hashbidder/dashboard.py`

- [ ] **Step 1: Refactor `_tick` and loop to publish committed row**

```python
# hashbidder/daemon.py
# 1. Update _tick signature to return MetricRow
async def _tick(..., metrics_repo: MetricsRepo) -> MetricRow:
    # ... logic ...
    await metrics_repo.insert(row)
    return row

# 2. Update daemon_loop to take optional hub and publish
async def daemon_loop(..., hub: BroadcastHub | None = None):
    # ... inside while True:
    row = await _tick(...)
    if hub:
        hub.publish(row)
```

- [ ] **Step 2: Wire dependencies into app.state in lifespan**

```python
# hashbidder/dashboard.py
from hashbidder.broadcast_hub import BroadcastHub

# Initialize hub globally
broadcast_hub = BroadcastHub()

# Update lifespan to wire app state and pass hub to daemon
async def lifespan(app: FastAPI):
    # ... (existing client setup)
    
    # 1. Map existing repo and hub into app state
    app.state.metrics_repo = repo
    app.state.broadcast_hub = broadcast_hub

    # 2. Pass broadcast_hub directly to daemon_loop
    daemon_task = asyncio.create_task(
        daemon_loop(
            config_path=BIDS_CONFIG_PATH,
            braiins_client=braiins_client,
            ocean_client=ocean_client,
            mempool_client=mempool_client,
            metrics_repo=repo,
            ocean_address=ocean_address,
            interval_seconds=interval_seconds,
            hub=broadcast_hub
        )
    )
    # ... yield and cleanup
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat: publish committed metrics and wire dependencies into app.state"
```

---

### Task 3: /stream Endpoint & Serialization (TDD)

**Files:**
- Create: `tests/unit/test_stream.py`
- Modify: `hashbidder/dashboard.py`

- [ ] **Step 1: Write integration tests for /stream endpoint**

```python
# tests/unit/test_stream.py
import pytest
import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path
from httpx import ASGITransport, AsyncClient
from hashbidder.dashboard import app, broadcast_hub
from hashbidder.metrics import MetricRow, MetricsRepo

@pytest.fixture
async def metrics_repo(tmp_path: Path):
    db_path = tmp_path / "test.sqlite"
    repo = MetricsRepo(str(db_path))
    await repo.init_db()
    return repo

@pytest.fixture
async def sse_client(metrics_repo):
    app.state.metrics_repo = metrics_repo
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_stream_replay_sequencing(sse_client, metrics_repo):
    # 1. Add row to repo
    row = MetricRow(timestamp=1713634000, braiins_hashrate_phs=Decimal("1.0"), ocean_hashrate_phs=Decimal("1.1"), 
                    braiins_connected=True, ocean_connected=True, mempool_connected=True)
    await metrics_repo.insert(row)
    
    # 2. Test replay via 'since' param and read full frame
    async with sse_client.stream("GET", "/stream?since=1713633000") as resp:
        buffer = ""
        async for line in resp.aiter_lines():
            buffer += line + "\n"
            if not line: # End of frame
                break
        assert "id: 1713634000" in buffer
        assert "event: metric_row" in buffer
        assert '"braiins_hashrate_phs": "1.0"' in buffer

@pytest.mark.asyncio
async def test_stream_unsubscribe_on_exit(sse_client):
    initial_count = len(broadcast_hub._subscribers)
    async with sse_client.stream("GET", "/stream"):
        assert len(broadcast_hub._subscribers) == initial_count + 1
    assert len(broadcast_hub._subscribers) == initial_count
```

- [ ] **Step 2: Implement serialization and endpoint**

```python
# hashbidder/dashboard.py
from decimal import Decimal
import json
from fastapi.responses import StreamingResponse
from hashbidder.broadcast_hub import OVERFLOW_SIGNAL

def serialize_metric_row(row: MetricRow) -> dict:
    """JSON-safe metric row serialization."""
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in vars(row).items()}

@app.get("/stream")
async def stream(request: Request, since: int | None = None):
    hub = request.app.state.broadcast_hub
    repo = request.app.state.metrics_repo
    
    async def event_generator():
        q = await hub.subscribe()
        last_id = request.headers.get("Last-Event-ID")
        cursor = max(int(last_id) if last_id else 0, since or 0)
        
        try:
            # 1. Replay historical ticks
            if cursor > 0:
                for row in await repo.get_history(cursor + 1):
                    yield f"id: {row.timestamp}\nevent: metric_row\ndata: {json.dumps(serialize_metric_row(row))}\n\n"
            
            # 2. Live bridge
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    if msg == OVERFLOW_SIGNAL:
                        yield "event: overflow\ndata: reset\n\n"
                        continue
                    yield f"id: {msg.timestamp}\nevent: metric_row\ndata: {json.dumps(serialize_metric_row(msg))}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            hub.unsubscribe(q)

    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/unit/test_stream.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_stream.py
git commit -am "feat: implement SSE stream with replay sequencing and heartbeat"
```

---

### Task 4: UI Shell & Mapping Refactor

**Files:**
- Modify: `hashbidder/templates/index.html`

- [ ] **Step 1: Simplify template and assign IDs**
- [ ] **Step 2: Implement JS normalization and dedupe**

```javascript
// in index.html script block
function mapRowToPoint(row) {
    return {
        timestamp: new Date(row.timestamp * 1000),
        ocean: parseFloat(row.ocean_hashrate_phs || 0) * 1000,
        target: row.target_hashrate_phs ? parseFloat(row.target_hashrate_phs) * 1000 : null,
        braiins: parseFloat(row.braiins_hashrate_phs || 0) * 1000,
        price: row.market_price_sat,
        accepted: row.braiins_shares_accepted || 0,
        rejected: row.braiins_shares_rejected || 0,
        ocean_shares: row.ocean_shares_window || 0,
        estimated_rewards: row.ocean_estimated_rewards_sat || 0,
        next_block_earnings: row.ocean_next_block_earnings_sat || 0,
        hashvalue: row.hashvalue_sat,
        active_bid: row.active_bid_price_sat
    };
}
```

- [ ] **Step 3: Commit**

```bash
git commit -am "ui: refactor template for persistent canvases and ID-based updates"
```

---

### Task 5: Live Updates & Scaling

**Files:**
- Modify: `hashbidder/templates/index.html`

- [ ] **Step 1: Implement `updateDashboard` for all 4 charts**

```javascript
function updateDashboard(point) {
    // 1. DOM Updates (Status Chips/Balance)
    document.getElementById('balance-value').textContent = point.balance_sat + ' sats';
    // ... update status chips text and className ...

    // 2. History Push & Trim (2016 = 1 week)
    historyData.push(point);
    if (historyData.length > 2016) historyData.shift();

    const labels = historyData.map(d => d.timestamp.toLocaleTimeString());

    // 3. Update datasets for all 4 charts
    // Hashrate Chart
    charts.hashrate.data.labels = labels;
    charts.hashrate.data.datasets[0].data = historyData.map(d => d.ocean);
    charts.hashrate.data.datasets[1].data = movingAverage(charts.hashrate.data.datasets[0].data, 288);
    // ... ma10d, ma30d, target, braiins ...

    // Price Chart
    charts.price.data.labels = labels;
    charts.price.data.datasets[0].data = historyData.map(d => d.price);
    // ... hashvalue, active_bid ...
    const allPrices = historyData.flatMap(d => [d.price, d.hashvalue, d.active_bid]).filter(v => v !== null);
    if (allPrices.length > 0) {
        const minP = Math.min(...allPrices);
        const maxP = Math.max(...allPrices);
        charts.price.options.scales.y.min = Math.floor(minP * 0.95);
        charts.price.options.scales.y.max = Math.ceil(maxP * 1.05);
    }

    // Quality Chart
    charts.quality.data.labels = labels;
    charts.quality.data.datasets[0].data = historyData.map((d, i) => {
        if (i === 0) return 0;
        const diff = d.accepted - historyData[i-1].accepted;
        const timeDiffMin = (d.timestamp - historyData[i-1].timestamp) / 60000;
        return timeDiffMin > 0 ? Math.max(0, diff / timeDiffMin) : 0;
    });
    // ... rejected/min, ratio ...

    // Rewards Chart
    charts.reward.data.labels = labels;
    charts.reward.data.datasets[0].data = historyData.map(d => d.estimated_rewards);
    // ... next_block, shares ...
    
    Object.values(charts).forEach(c => c.update({duration: 250}));
}
```

- [ ] **Step 2: Implement EventSource and recovery**
- [ ] **Step 3: Commit**

```bash
git commit -am "ui: implement SSE listener and surgical chart updates"
```

---

### Task 6: Final Release Verification

- [ ] **Step 1: Verify No Polling Remains**

Run: `grep -r "hx-get" hashbidder/templates`
Expected: 0 matches in dashboard section.

- [ ] **Step 2: Verify Disconnect Cleanup Test**

Run: `pytest tests/unit/test_broadcast_hub.py::test_broadcast_hub_disconnect_cleanup`
Expected: PASS

- [ ] **Step 3: Build package**

Run: `make hashbidder9.s9pk`
Expected: Successful build.

- [ ] **Step 4: Final Commit**

```bash
git commit -am "chore: finalize SSE transition and remove legacy polling"
```
