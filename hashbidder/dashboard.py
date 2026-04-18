"""Web dashboard for Hashbidder."""

import logging
import time
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from hashbidder.config import ExplicitBidsModel, TargetHashrateModel
from hashbidder.metrics import MetricsRepo

logger = logging.getLogger(__name__)

app = FastAPI(title="Hashbidder Dashboard")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
repo = MetricsRepo()

BIDS_CONFIG_PATH = Path("bids.toml")


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


@app.on_event("startup")
async def startup() -> None:
    """Initialize database on startup."""
    await repo.init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render main dashboard with metrics history."""
    # Fetch last 30 days
    thirty_days_ago = int(time.time()) - (30 * 24 * 60 * 60)
    history = await repo.get_history(thirty_days_ago)
    return templates.TemplateResponse(
        request=request, name="index.html", context={"history": history}
    )


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
    target_hashrate_ph_s: Annotated[Decimal | None, Form()] = None,
    max_bids_count: Annotated[int | None, Form()] = None,
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
            data["target_hashrate_ph_s"] = target_hashrate_ph_s
            data["max_bids_count"] = max_bids_count
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
