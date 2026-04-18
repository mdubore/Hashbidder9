# Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a FastAPI dashboard that serves historical metrics from SQLite, visualizes them with Chart.js via HTMX templates, and provides a web form to edit `bids.toml`.

**Architecture:** A new `dashboard.py` running FastAPI will be integrated. The `hashbidder/metrics.py` module will handle reading/writing to `hashbidder.sqlite` using `aiosqlite`. A `templates` directory will hold Jinja2 HTML files. The daemon loop will be extracted into an `async def run_daemon()` function.

**Tech Stack:** Python 3.13, `fastapi`, `uvicorn`, `jinja2`, `aiosqlite`, `htmx` (via CDN), `chart.js` (via CDN)

---

### Task 1: Add Web Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add FastAPI and aiosqlite**

```bash
uv add "fastapi[standard]>=0.115.0" aiosqlite>=0.20.0 jinja2>=3.1.4
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add web dashboard dependencies"
```

### Task 2: Create Metrics Repository

**Files:**
- Create: `hashbidder/metrics.py`
- Create: `tests/unit/test_metrics.py`

- [ ] **Step 1: Create `hashbidder/metrics.py`**

Define the schema and `aiosqlite` abstraction:

```python
import aiosqlite
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class MetricRow:
    timestamp: int
    braiins_hashrate_phs: Decimal
    ocean_hashrate_phs: Decimal
    braiins_connected: bool
    ocean_connected: bool
    mempool_connected: bool

class MetricsRepo:
    def __init__(self, db_path: str = "hashbidder.sqlite") -> None:
        self.db_path = db_path

    async def init_db(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    timestamp INTEGER PRIMARY KEY,
                    braiins_hashrate_phs TEXT,
                    ocean_hashrate_phs TEXT,
                    braiins_connected INTEGER,
                    ocean_connected INTEGER,
                    mempool_connected INTEGER
                )
            """)
            await db.commit()

    async def insert(self, row: MetricRow) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO metrics VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row.timestamp,
                    str(row.braiins_hashrate_phs),
                    str(row.ocean_hashrate_phs),
                    int(row.braiins_connected),
                    int(row.ocean_connected),
                    int(row.mempool_connected),
                ),
            )
            await db.commit()

    async def get_history(self, since_timestamp: int) -> list[MetricRow]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM metrics WHERE timestamp >= ? ORDER BY timestamp ASC",
                (since_timestamp,)
            )
            rows = await cursor.fetchall()
            return [
                MetricRow(
                    timestamp=r["timestamp"],
                    braiins_hashrate_phs=Decimal(r["braiins_hashrate_phs"]),
                    ocean_hashrate_phs=Decimal(r["ocean_hashrate_phs"]),
                    braiins_connected=bool(r["braiins_connected"]),
                    ocean_connected=bool(r["ocean_connected"]),
                    mempool_connected=bool(r["mempool_connected"])
                ) for r in rows
            ]
```

- [ ] **Step 2: Add test in `test_metrics.py`**

Write a test using a temporary in-memory database (`:memory:`) to verify `init_db`, `insert`, and `get_history` work.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/unit/test_metrics.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add hashbidder/metrics.py tests/unit/test_metrics.py
git commit -m "feat: add SQLite metrics repository"
```

### Task 3: Create FastAPI Dashboard

**Files:**
- Create: `hashbidder/dashboard.py`
- Create: `hashbidder/templates/index.html`
- Create: `hashbidder/templates/settings.html`

- [ ] **Step 1: Implement `hashbidder/dashboard.py`**

```python
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import time
from hashbidder.metrics import MetricsRepo

app = FastAPI(title="Hashbidder Dashboard")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
repo = MetricsRepo()

@app.on_event("startup")
async def startup():
    await repo.init_db()

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Fetch last 30 days
    thirty_days_ago = int(time.time()) - (30 * 24 * 60 * 60)
    history = await repo.get_history(thirty_days_ago)
    return templates.TemplateResponse("index.html", {"request": request, "history": history})

@app.get("/settings", response_class=HTMLResponse)
async def get_settings(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})
```

- [ ] **Step 2: Implement Jinja2 Templates**

Create `hashbidder/templates/index.html` displaying an empty dashboard layout and including HTMX/Chart.js CDNs. Create `hashbidder/templates/settings.html`. 

- [ ] **Step 3: Commit**

```bash
git add hashbidder/dashboard.py hashbidder/templates/
git commit -m "feat: bootstrap FastAPI web dashboard and templates"
```

### Task 4: Connect Config Editing to UI

**Files:**
- Modify: `hashbidder/dashboard.py`
- Modify: `hashbidder/templates/settings.html`

- [ ] **Step 1: Read/Write config endpoints**

In `hashbidder/dashboard.py`, implement `POST /settings` to receive form data, validate it with Pydantic, write back to `bids.toml`, and return a success or error snippet.

- [ ] **Step 2: Update HTML**

Use HTMX to POST the form data without a page reload and display the returned message.

- [ ] **Step 3: Commit**

```bash
git add hashbidder/dashboard.py hashbidder/templates/settings.html
git commit -m "feat: connect bids.toml editing to dashboard"
```

### Task 5: Add Web Command to CLI

**Files:**
- Modify: `hashbidder/main.py`

- [ ] **Step 1: Add `web` command**

In `hashbidder/main.py`, add a `web` command using `uvicorn.run()`:

```python
import uvicorn

@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
def web(host: str, port: int) -> None:
    """Start the Hashbidder Web Dashboard."""
    uvicorn.run("hashbidder.dashboard:app", host=host, port=port)
```

- [ ] **Step 2: Run all checks**

Run: `make check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add hashbidder/main.py
git commit -m "feat: add web command to start dashboard"
```
