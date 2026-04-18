# Hashbidder Web Dashboard Design Spec

## Goal
Add a web-based Graphical User Interface (GUI) to the `hashbidder` application. The GUI will serve as a monitoring dashboard to visualize historical hashrate data (actual vs. 1-day, 10-day, and 30-day rolling averages), display connectivity indicators for Braiins, Ocean, and Mempool, and provide a visual interface to modify the application's configuration (`bids.toml`).

## Target Environment
The application is intended to be packaged as a service for Start9's StartOS (v0.4.0). Therefore, the architecture must be self-contained, lightweight, and capable of serving a web UI over a local network.

## Architecture

The system will be expanded into three interacting components:

1. **The Hashbidder Daemon (Async Refactor):**
   - The existing Python CLI and API clients (`BraiinsClient`, `OceanClient`, `MempoolClient`) will be refactored to use `httpx.AsyncClient` and `asyncio` for concurrent, non-blocking I/O. This resolves the previous performance bottleneck of sequential API calls.
   - At periodic intervals (e.g., every 5 minutes), the daemon queries the APIs concurrently.
   - It executes the bid reconciliation logic.
   - *New:* It writes the fetched metrics (current actual hashrate, connectivity status) to a local database.

2. **The Database (SQLite):**
   - A local `hashbidder.sqlite` embedded database.
   - **Schema Design (High-Level):**
     - `metrics` table: `timestamp`, `braiins_hashrate_phs`, `ocean_hashrate_phs`, `braiins_connected` (boolean), `ocean_connected` (boolean), `mempool_connected` (boolean).
   - SQLite is lightweight, requires no external server process, and perfectly fits the StartOS self-hosted paradigm.

3. **The Web Dashboard (FastAPI + HTMX + Jinja2):**
   - A new, lightweight ASGI web server built with FastAPI.
   - **Frontend:** Server-side rendered HTML using Jinja2 templates, made interactive via HTMX. This avoids the complexity of a separate Node.js/React build pipeline while still providing a modern, SPA-like feel.
   - **Charting:** A lightweight, vanilla JavaScript charting library (e.g., Chart.js or uPlot) embedded in the templates to render the 1d/10d/30d moving averages of the hashrate based on JSON data endpoints provided by FastAPI.
   - **Configuration Editor:** A dedicated route that reads `bids.toml`, populates an HTML form, and writes the validated data back to the file (leveraging the newly added Pydantic models for safe validation).

## Data Flow

1. **Metrics Collection:** The background daemon writes a row to the SQLite database on every tick.
2. **Dashboard Viewing:** When a user opens the dashboard in their browser:
   - FastAPI queries SQLite for the last 30 days of metrics.
   - FastAPI computes the rolling averages (1d, 10d, 30d) in memory (or via SQL window functions) and passes the structured data to the Jinja2 template.
   - The template renders the HTML layout, embedding the data into a `<script>` block for the client-side charting library to draw.
3. **Config Editing:** 
   - User navigates to `/settings`.
   - FastAPI reads `bids.toml`, uses Pydantic to serialize it to a dictionary, and populates the form.
   - User submits the HTMX form (`POST /settings`). FastAPI validates the payload with Pydantic, writes back to `bids.toml`, and returns a success banner (or validation errors) via HTMX.

## Testing Strategy
- **SQLite Abstraction:** The database interaction will be abstracted behind a Repository pattern interface, allowing it to be easily mocked or swapped with an in-memory SQLite instance for fast unit tests.
- **FastAPI TestClient:** The `httpx` integration with FastAPI will be used to test the web routes, ensuring the `/settings` endpoints correctly serialize/deserialize the TOML configuration.