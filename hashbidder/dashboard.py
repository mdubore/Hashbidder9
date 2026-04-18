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
    return templates.TemplateResponse(
        request=request, name="index.html", context={"history": history}
    )

@app.get("/settings", response_class=HTMLResponse)
async def get_settings(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html", context={})
