# Configurable Reconciliation Interval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to configure the bid reconciliation interval (tick time) via the StartOS UI, enabling more aggressive 1-minute updates to handle market volatility.

**Architecture:** We will add a `reconciliationInterval` field to the StartOS configuration spec. This value will be passed to the Python process via a new `HASHBIDDER_INTERVAL_SECONDS` environment variable. The FastAPI lifespan handler will read this variable and pass it to the `daemon_loop`.

**Tech Stack:** TypeScript (StartOS SDK), Python 3.13, FastAPI

---

### Task 1: Update StartOS Configuration Spec

**Files:**
- Modify: `startos/config/spec.ts`

- [ ] **Step 1: Add reconciliationInterval to configSpec and configSchema**

```typescript
export const configSpec = InputSpec.of({
  // ... existing ...
  reconciliationInterval: Value.number({
    name: 'Reconciliation Interval (minutes)',
    description: 'How often the daemon checks the market and updates bids. 1 minute is recommended for volatile markets.',
    required: true,
    default: 5,
    range: '[1, 60]',
    integral: true,
  }),
})

// ... update configSchema ...
```

- [ ] **Step 2: Commit**

```bash
git add startos/config/spec.ts
git commit -m "feat: add reconciliationInterval to StartOS config spec"
```

### Task 2: Pass Interval to Daemon

**Files:**
- Modify: `startos/main.ts`

- [ ] **Step 1: Map config to HASHBIDDER_INTERVAL_SECONDS**

```typescript
  if (config.reconciliationInterval) {
    env.HASHBIDDER_INTERVAL_SECONDS = String(config.reconciliationInterval * 60)
  }
```

- [ ] **Step 2: Commit**

```bash
git add startos/main.ts
git commit -m "feat: pass reconciliation interval to daemon via env var"
```

### Task 3: Update Python Dashboard to use Configurable Interval

**Files:**
- Modify: `hashbidder/dashboard.py`

- [ ] **Step 1: Read env var and pass to daemon_loop**

```python
    interval_seconds = int(os.environ.get("HASHBIDDER_INTERVAL_SECONDS", "300"))
    
    daemon_task = asyncio.create_task(
        daemon_loop(
            # ... other args ...
            interval_seconds=interval_seconds,
        )
    )
```

- [ ] **Step 2: Commit**

```bash
git add hashbidder/dashboard.py
git commit -m "feat: use configurable reconciliation interval in daemon loop"
```

### Task 4: Rebuild and Final Verification

**Files:**
- [ ] **Step 1: Rebuild StartOS package**

Run: `make clean && make`
Expected: `hashbidder9.s9pk` built successfully.

- [ ] **Step 2: Commit**

```bash
git add .
git commit -m "build: finalize configurable reconciliation interval"
```
