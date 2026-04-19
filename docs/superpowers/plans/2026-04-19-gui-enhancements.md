# GUI Polish & Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the web dashboard into a professional, dark-themed monitoring interface with real-time connectivity indicators and interactive Chart.js graphs visualizing actual vs. target hashrate and market price trends.

**Architecture:** We will update the Jinja2 templates (`index.html`, `settings.html`) with a consistent dark CSS theme. We will implement visual "Health" indicators (Green/Red) using the `braiins_connected`, `ocean_connected`, and `mempool_connected` metrics. Finally, we will add a JavaScript initialization block to `index.html` that uses Chart.js to render the historical `history` data passed from FastAPI.

**Tech Stack:** Jinja2, CSS (Dark Mode), Chart.js, HTMX

---

### Task 1: Dark Mode & Layout Foundations

**Files:**
- Modify: `hashbidder/templates/index.html`
- Modify: `hashbidder/templates/settings.html`

- [ ] **Step 1: Implement global dark theme CSS**

Update the `<style>` block in both files to a professional dark theme (background `#121212`, text `#e0e0e0`, cards `#1e1e1e`).

- [ ] **Step 2: Commit**

```bash
git add hashbidder/templates/
git commit -m "ui: implement dark mode theme for dashboard and settings"
```

### Task 2: Connectivity Status Indicators

**Files:**
- Modify: `hashbidder/templates/index.html`
- Modify: `hashbidder/dashboard.py` (to pass the latest row status)

- [ ] **Step 1: Update `dashboard.py` to pass current status**

Extract the most recent `MetricRow` to determine the "Current Status" of connections.

- [ ] **Step 2: Implement status chips in `index.html`**

Add a header row with chips for Braiins, Ocean, and Mempool that turn green/red based on the latest metrics.

- [ ] **Step 3: Commit**

```bash
git add hashbidder/dashboard.py hashbidder/templates/index.html
git commit -m "ui: add connectivity status indicators to dashboard"
```

### Task 3: Hashrate & Price Charts

**Files:**
- Modify: `hashbidder/templates/index.html`

- [ ] **Step 1: Implement Chart.js initialization**

Write the JavaScript code to transform the `history` list (passed as JSON-like data) into two Chart.js line charts:
1. **Hashrate Performance:** Ocean Actual, Target (if exists), and Braiins report.
2. **Market Price Trend:** Cheapest served bid price over time.

- [ ] **Step 2: Commit**

```bash
git add hashbidder/templates/index.html
git commit -m "ui: implement Chart.js visualization for hashrate and market price"
```

### Task 4: Final Verification & Rebuild

**Files:**
- [ ] **Step 1: Rebuild StartOS package**

Run: `make clean && make`
Expected: `hashbidder9.s9pk` built successfully.

- [ ] **Step 2: Commit**

```bash
git add .
git commit -m "build: finalize GUI enhancements for next StartOS release"
```
