# Dashboard SSE Transition Design (Definitive v5)

**Date:** 2026-04-20
**Topic:** Real-time Dashboard Updates
**Issue:** #1 (Flicker on refresh)

## Goal
Replace HTMX whole-fragment polling with Server-Sent Events (SSE) to achieve "zero-flicker" dashboard updates. The UI will surgically update status chips, balance, and animate new data points into the graphs.

## Architecture
This design relies on a single app process (FastAPI + Daemon). Multi-worker deployments are not supported.

### 1. Backend Components (`hashbidder/dashboard.py` & `hashbidder/daemon.py`)
- **`BroadcastHub`**: A management object on the FastAPI event loop. It maintains a set of `asyncio.Queue` objects.
- **Queue Policy**: Queues are bounded (max size 50). Overflow triggers an `overflow` event, instructing the UI to perform a full page reload to resync state.
- **Publish Ordering**:
  1. `_tick()` performs metrics collection and returns a `MetricRow`.
  2. `metrics_repo.insert(row)` commits the row to SQLite.
  3. `daemon_loop()` publishes the committed row to the `BroadcastHub`.
- **`/stream` Endpoint**: 
  - **Replay Logic**: Accepts a `since` query parameter (on first connect) and the `Last-Event-ID` header (on reconnect).
  - **Cursor Seeding**: The client seeds the `since` parameter using the timestamp of the latest row rendered by the server.
  - **Sequence**: 
    1. Register queue with the hub.
    2. Query SQLite for all rows where `timestamp > MAX(since, Last-Event-ID)`.
    3. Yield historical replay events.
    4. Yield live events from the queue.
  - **Headers**: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` (disables buffering in reverse proxies like Nginx).
  - **Heartbeats**: Sends `: heartbeat\n\n` every 15 seconds.
  - **Cleanup**: `finally` block removes the queue from the hub.
- **Serialization**: `serialize_metric_row(row)` converts all `Decimal` fields to **strings**.

### 2. Frontend Components (`hashbidder/templates/index.html`)
- **State Management**:
  - `historyData`: Persistent array of normalized data points.
  - `retentionLimit`: 2,016 points (exactly 1 week at 5-minute intervals). Trims old points on every update.
- **Normalizer**: `mapMetricRowToPoint(row)` converts string Decimals to floats and handles hashrate unit conversion (PH to TH).
- **Surgical Updates**: 
  - Assign IDs: `status-braiins`, `status-ocean`, `status-mempool`, `balance-value`, `last-updated-time`.
  - Update DOM directly on event reception.
- **Chart.js Lifecycle**:
  - **Persistent Shells**: The HTML template always renders the dashboard grid and chart canvases.
  - **Initial Load**: Charts are initialized with the server-rendered `historyData` (which may be empty).
  - **SSE Update**: New points are appended; `chart.update()` is called with a 250ms duration.
- **Error Handling**:
  - `onerror`: Standard `EventSource` logic handles retries.
  - `overflow` event: Triggers `window.location.reload()` to resync full state.
- **Deduplication**: The UI ignores any incoming row with a `timestamp <= lastSeenTimestamp`.

### 3. Migration Checklist
- [ ] Remove `hx-get`, `hx-trigger`, and `hx-swap` from `#dashboard-root`.
- [ ] Remove `htmx:afterSettle` listener and the recursive `initCharts()` calls.
- [ ] Refactor `index.html` to always render chart containers (removing `{% if not history %}`).

## Data Schema (SSE Event)
- **Event Name**: `metric_row`
- **ID**: `timestamp`
- **Data**:
```json
{
  "timestamp": 1713634000,
  "braiins_hashrate_phs": "1.84",
  "ocean_hashrate_phs": "1.85",
  "braiins_connected": true,
  "ocean_connected": true,
  "mempool_connected": true,
  "target_hashrate_phs": "1.00",
  "needed_hashrate_phs": "0.15",
  "market_price_sat": 46627,
  "bids_active": 1,
  "balance_sat": 185577,
  "braiins_shares_accepted": 979894272,
  "braiins_shares_rejected": 1310720,
  "ocean_shares_window": 12730000000,
  "ocean_estimated_rewards_sat": 29344,
  "ocean_next_block_earnings_sat": 3644,
  "hashvalue_sat": 45500,
  "active_bid_price_sat": 46627
}
```

## Verification Plan
- **Backend Tests**:
  - `test_replay_logic`: Verify missing ticks are yielded after a reconnect using `Last-Event-ID`.
  - `test_cold_start_catchup`: Verify `since` parameter correctly fetches history on first load.
  - `test_subscription_ordering`: Confirm no events are lost or stuck during the transition from replay to live.
  - `test_disconnect_cleanup`: Verify hub queue count decrements after connection close.
  - `test_overflow_trigger`: Confirm full reload event on full queue.
- **Frontend Verification**:
  - **Initial Load Race**: Confirm that events arriving while the page is still loading (after server render but before stream connect) are handled gracefully via the `since` cursor.
  - **Gap Recovery**: Simulate connection drop for >5 minutes; verify chart "fills in" the missing points automatically using `Last-Event-ID`.
  - **Deduplication**: Verify that replayed events overlapping with live events are suppressed by the UI.
  - **Paint Flashing**: Inspect DOM via DevTools to confirm zero full-fragment swaps occur during updates.

## Self-Review
- **Reconnect**: Handled via `since` cursor (first connect) and `Last-Event-ID` (reconnect).
- **Races**: Resolved via registration-then-replay sequence.
- **Retention**: Trims to 1 week (2,016 points).
- **DOM**: Used pre-rendered shells for visual stability.
- **Ops**: Included required headers and proxy buffering notes.
