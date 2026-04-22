# Hashrate Diagnostic Chart Design

**Date:** 2026-04-21

**Goal:** Make the dashboard's hashrate comparison more useful for spotting delivery and routing issues by separating short-window operational signals from long-window trend signals.

## Problem

The current `Hashrate Performance (TH/s)` graph mixes unlike series:

- Ocean "actual" currently uses fallback selection across multiple Ocean windows.
- Braiins "reported" currently uses delivered hashrate with fallback to current speed.
- Long-window moving averages are plotted on the same chart as short-window operational series.

This makes the gap between Ocean and Braiins harder to interpret. A noisy Braiins line can reflect fallback behavior rather than a real delivery mismatch, and long-window averages obscure short-window divergence.

## Approved Design

### 1. Persist Raw Metrics Only

The database should store only values actually returned by the upstream APIs. If a specific metric is missing for a given daemon tick, store `NULL` for that metric rather than `0` or a carried-forward synthetic value.

This preserves historical truth and keeps the database usable for diagnostics.

### 2. Remove Cross-Metric Fallbacks

Each plotted metric should map to one upstream field only:

- `Ocean Actual (60s)` uses Ocean `hashrate_60s` only.
- `Ocean 10m` uses Ocean `hashrate_600s` only.
- `Ocean 24h` uses Ocean `hashrate_86400s` only.
- `Braiins Current` uses Braiins `state_estimate.avg_speed_ph` only.
- `Braiins Delivered Avg` uses Braiins `counters_committed.delivered_hr_ph` only.

If an upstream field is missing, store `NULL`. Do not substitute another window or another Braiins field.

### 3. Carry Forward Only In The Chart Layer

The frontend should carry forward the last non-null plotted value per series when rendering history and when applying live SSE updates.

That means:

- the DB remains truthful,
- the charts remain visually continuous,
- and missing upstream samples do not render as false zeros.

Carry-forward is a display concern only.

## Chart Layout

### Diagnostic Chart

Replace the current `Hashrate Performance (TH/s)` graph with a diagnostic comparison chart containing:

1. `Ocean Actual (60s)`
2. `Ocean 10m`
3. `Braiins Current`
4. `Braiins Delivered Avg`
5. `Target`

Purpose:

- Compare short-window Ocean and Braiins behavior directly.
- Surface routing, delivery, and stability issues.
- Keep `Target` visible so deficit conditions remain obvious.

### Trend Chart

Add a separate trend chart containing:

1. `Ocean 24h`
2. `MA 10d`
3. `MA 30d`
4. `Target`

Trend calculations should use the Ocean `24h` series as the source. The previous `MA 1d` line should be removed, because the raw `Ocean 24h` line already represents the 1-day average.

Purpose:

- Preserve longer-term trend visibility.
- Keep the diagnostic chart focused on operational comparison.

## Transmission Quality Graph Change

The `Ratio (%)` right-side axis on `Transmission Quality (Shares/min)` should auto-scale instead of staying fixed at 100.

Behavior:

- compute the maximum visible rejection ratio from the current data,
- apply a small padding factor,
- clamp to a sensible ceiling where needed,
- and update the `y1` axis max dynamically.

This makes the ratio line more useful when the actual values are small.

## Data Model Changes

The metrics row should be extended with raw nullable fields for:

- `ocean_hashrate_60s_phs`
- `ocean_hashrate_600s_phs`
- `ocean_hashrate_86400s_phs`
- `braiins_current_speed_phs`
- `braiins_delivered_hashrate_phs`

Existing `ocean_hashrate_phs` and `braiins_hashrate_phs` should be retired from charting once the new fields are in place. They may be removed from persistence entirely if no other view depends on them.

## Testing Strategy

Testing should cover:

- Ocean window extraction with no fallback.
- Braiins current vs delivered parsing with no fallback.
- Metrics repo migration for new nullable columns.
- Dashboard rendering with nullable historical samples.
- SSE serialization of new fields.
- Frontend carry-forward behavior for missing samples.
- Trend chart moving averages based on Ocean 24h only.
- Auto-scaling of the Transmission Quality ratio axis.

## Recommendation

Proceed with a focused implementation that:

1. adds the raw metrics and migrations,
2. updates daemon collection and SSE payloads,
3. refactors the dashboard into diagnostic and trend charts,
4. then verifies carry-forward and ratio auto-scaling behavior.
