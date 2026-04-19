# Dashboard Troubleshooting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose and fix the "Internal Server Error" on the dashboard GET route by adding detailed exception logging and defensive template rendering.

**Architecture:** We will wrap the `index` route in a try-except block to capture and log the specific traceback. We will also make the template rendering more defensive by checking for data presence.

**Tech Stack:** Python, FastAPI, Jinja2

---

### Task 1: Add Exception Logging to Dashboard

**Files:**
- Modify: `hashbidder/dashboard.py`

- [ ] **Step 1: Wrap index route in try-except**

Modify the `index` route to log any exceptions before they cause a 500.

```python
import traceback

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render main dashboard with metrics history."""
    try:
        # Fetch last 30 days
        thirty_days_ago = int(time.time()) - (30 * 24 * 60 * 60)
        history = await repo.get_history(thirty_days_ago)
        
        # Extract current status (latest metric row)
        current_status = history[-1] if history else None
        
        return templates.TemplateResponse(
            request=request, 
            name="index.html", 
            context={"history": history, "current_status": current_status}
        )
    except Exception as e:
        logger.error("Error rendering dashboard: %s", e)
        logger.error(traceback.format_exc())
        return HTMLResponse(content=f"Internal Server Error: {e}", status_code=500)
```

- [ ] **Step 2: Commit**

```bash
git add hashbidder/dashboard.py
git commit -m "debug: add detailed exception logging to dashboard index route"
```

### Task 2: Defensive Template Rendering

**Files:**
- Modify: `hashbidder/templates/index.html`

- [ ] **Step 1: Make balance display more defensive**

Update the balance chip to use a simpler check.

```html
<span class="status-chip status-blue">
    Balance: 
    {% if current_status and current_status.balance_sat is not None %}
        {{ current_status.balance_sat }} sats
    {% else %}
        N/A
    {% endif %}
</span>
```

- [ ] **Step 2: Rebuild StartOS package**

Run: `make clean && make`
Expected: `hashbidder9.s9pk` built successfully.

- [ ] **Step 3: Commit**

```bash
git add hashbidder/templates/index.html
git commit -m "fix: make dashboard template more defensive"
```
