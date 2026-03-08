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

app.include_router(news_router)
app.include_router(stream_router)
app.include_router(health_router)

# ── Admin Routes ──────────────────────────────────────────────
from fastapi import BackgroundTasks

@app.post("/api/admin/fetch", tags=["admin"])
async def admin_fetch(background_tasks: BackgroundTasks):
    from aggregator.scheduler import _run_fetch_pipeline
    background_tasks.add_task(_run_fetch_pipeline)
    return {"status": "fetch started"}


@app.post("/api/admin/generate/{article_id}", tags=["admin"])
async def admin_generate(article_id: int, background_tasks: BackgroundTasks):
    from video.pipeline import generate_episode_for_article
    background_tasks.add_task(generate_episode_for_article, article_id)
    return {"status": "generation started", "article_id": article_id}


@app.post("/api/admin/process-top", tags=["admin"])
async def admin_process_top(n: int = 3, background_tasks: BackgroundTasks = None):
    from video.pipeline import process_top_articles
    background_tasks.add_task(process_top_articles, n)
    return {"status": f"processing top {n} articles"}

# ── WebSocket ─────────────────────────────────────────────────
from api.websocket import websocket_endpoint

@app.websocket("/ws/news")
async def ws_news(websocket: WebSocket):
    await websocket_endpoint(websocket)

# ── Frontend ──────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "frontend" / "index.html"
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
