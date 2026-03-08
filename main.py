"""
Brasil24 — Aggregador de Noticias + Canal YouTube 24/7
Entrypoint: FastAPI app + APScheduler
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from database.db import init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    init_db()

    logger.info("Starting scheduler...")
    from aggregator.scheduler import start_scheduler, _run_fetch_pipeline
    start_scheduler()

    # Run first fetch immediately in background
    import asyncio
    asyncio.create_task(_run_fetch_pipeline())

    yield

    # Shutdown
    from aggregator.scheduler import stop_scheduler
    stop_scheduler()
    logger.info("Brasil24 shutdown complete")


app = FastAPI(
    title="Brasil24 - Agregador de Noticias",
    description="Canal de noticias 24/7 com IA",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Static files ──────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend" / "static"), name="static")

# ── API Routes ────────────────────────────────────────────────
from api.routes.news import router as news_router
from api.routes.stream import router as stream_router
from api.routes.health import router as health_router
from api.routes.admin import router as admin_router

app.include_router(news_router)
app.include_router(stream_router)
app.include_router(health_router)
app.include_router(admin_router)

# ── WebSocket ─────────────────────────────────────────────────
from api.websocket import websocket_endpoint
from api.admin_ws import admin_websocket_endpoint

@app.websocket("/ws/news")
async def ws_news(websocket: WebSocket):
    await websocket_endpoint(websocket)

@app.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket):
    await admin_websocket_endpoint(websocket)

# ── Frontend ──────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "frontend" / "index.html"
    return html_path.read_text(encoding="utf-8")

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    html_path = BASE_DIR / "frontend" / "admin.html"
    return html_path.read_text(encoding="utf-8")


# ── Run directly ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
