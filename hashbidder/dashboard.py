"""Web dashboard for Hashbidder."""

import asyncio
import contextlib
import logging
import os
import time
import tomllib
import traceback
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from hashbidder.client import API_BASE, BraiinsClient
from hashbidder.config import ExplicitBidsModel, TargetHashrateModel
from hashbidder.daemon import daemon_loop
from hashbidder.domain.btc_address import BtcAddress
from hashbidder.mempool_client import DEFAULT_MEMPOOL_URL, MempoolClient
from hashbidder.metrics import MetricsRepo
from hashbidder.ocean_client import DEFAULT_OCEAN_URL, OceanClient

logger = logging.getLogger(__name__)


def _get_http_timeout() -> float:
    """Read HTTP_TIMEOUT from env, defaulting to 10.0 seconds."""
    try:
        return float(os.environ.get("HTTP_TIMEOUT", "10.0"))
    except (TypeError, ValueError):
        return 10.0


def _resolve_mempool_url() -> httpx.URL:
    """Resolve the mempool URL from env, falling back to the default."""
    env_url = os.environ.get("MEMPOOL_URL")
    return httpx.URL(env_url) if env_url else DEFAULT_MEMPOOL_URL


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage lifecycle of the dashboard and its background tasks."""
    load_dotenv()
    await repo.init_db()

    # Resolve OCEAN_ADDRESS
    address_str = os.environ.get("OCEAN_ADDRESS")
    if not address_str:
        logger.error("OCEAN_ADDRESS environment variable is required for daemon.")
        yield
        return

    try:
        ocean_address = BtcAddress(address_str)
    except ValueError:
        logger.error("Invalid OCEAN_ADDRESS: %s", address_str)
        yield
        return

    timeout = _get_http_timeout()
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        api_key = os.environ.get("BRAIINS_API_KEY")
        braiins_client = BraiinsClient(
            API_BASE, api_key=api_key, http_client=http_client
        )
        mempool_client = MempoolClient(_resolve_mempool_url(), http_client)
        ocean_client = OceanClient(DEFAULT_OCEAN_URL, http_client)

        daemon_task = asyncio.create_task(
            daemon_loop(
                config_path=BIDS_CONFIG_PATH,
                braiins_client=braiins_client,
                ocean_client=ocean_client,
                mempool_client=mempool_client,
                metrics_repo=repo,
                ocean_address=ocean_address,
            )
        )

        yield

        daemon_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await daemon_task


app = FastAPI(title="Hashbidder Dashboard", lifespan=lifespan)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
repo = MetricsRepo()

BIDS_CONFIG_PATH = Path(os.environ.get("HASHBIDDER_CONFIG_PATH", "bids.toml"))


def save_config_to_toml(data: dict[str, Any], path: Path) -> None:
    """Write configuration data to TOML file."""
    lines = []
    if "mode" in data:
        lines.append(f'mode = "{data["mode"]}"')

    lines.append(f"default_amount_sat = {data['default_amount_sat']}")

    if data.get("mode") == "target-hashrate":
        lines.append(f"target_hashrate_ph_s = {data['target_hashrate_ph_s']}")
        lines.append(f"max_bids_count = {data['max_bids_count']}")

    lines.append("")
    lines.append("[upstream]")
    lines.append(f'url = "{data["upstream"]["url"]}"')
    lines.append(f'identity = "{data["upstream"]["identity"]}"')

    if data.get("mode") == "explicit-bids" and "bids" in data:
        for bid in data["bids"]:
            lines.append("")
            lines.append("[[bids]]")
            lines.append(f"price_sat_per_ph_day = {bid['price_sat_per_ph_day']}")
            lines.append(f"speed_limit_ph_s = {bid['speed_limit_ph_s']}")

    path.write_text("\n".join(lines) + "\n")


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


@app.get("/settings", response_class=HTMLResponse)
async def get_settings(request: Request) -> HTMLResponse:
    """Render settings page with current configuration."""
    config_data: dict[str, Any] = {}
    if BIDS_CONFIG_PATH.exists():
        try:
            with BIDS_CONFIG_PATH.open("rb") as f:
                config_data = tomllib.load(f)
        except Exception:
            logger.exception("Failed to load config from %s", BIDS_CONFIG_PATH)
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={"request": request, "config": config_data},
    )


@app.post("/settings", response_class=HTMLResponse)
async def post_settings(
    request: Request,
    mode: Annotated[str, Form()],
    default_amount_sat: Annotated[int, Form()],
    upstream_url: Annotated[str, Form()],
    upstream_identity: Annotated[str, Form()],
    target_hashrate_ph_s: Annotated[str | None, Form()] = None,
    max_bids_count: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """Save updated settings to config file."""
    try:
        data = {
            "mode": mode,
            "default_amount_sat": default_amount_sat,
            "upstream": {
                "url": upstream_url,
                "identity": upstream_identity,
            },
        }

        if mode == "target-hashrate":
            data["target_hashrate_ph_s"] = (
                Decimal(target_hashrate_ph_s) if target_hashrate_ph_s else None
            )
            data["max_bids_count"] = (
                int(max_bids_count) if max_bids_count else None
            )
            TargetHashrateModel.model_validate(data)
        else:
            # For now, explicit-bids with no bids from form
            data["bids"] = []
            ExplicitBidsModel.model_validate(data)

        save_config_to_toml(data, BIDS_CONFIG_PATH)
        success_msg = "Settings saved successfully!"
        return HTMLResponse(
            f'<div style="color: green; margin-top: 1rem;">{success_msg}</div>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<div style="color: red; margin-top: 1rem;">Error: {e!s}</div>'
        )
