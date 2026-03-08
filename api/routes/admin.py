"""
Rotas de administração do Brasil24.
Todas as operações de gerenciamento do canal.
"""
import asyncio
import json
import logging
import os
import re
import shutil
import signal

logger = logging.getLogger(__name__)
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config.settings import settings
from database.db import get_session_factory
from database.models import Article, BatchRun, Episode, StreamQueue

router = APIRouter(prefix="/api/admin", tags=["admin"])

BASE_DIR = Path(__file__).parent.parent.parent

# ── Stream queue manager ──────────────────────────────────────────────────────
import threading as _threading

_stream_stop_event: _threading.Event = _threading.Event()
_stream_thread: Optional[_threading.Thread] = None

# Fila e estado de reprodução
_stream_queue: list[dict] = []       # próximos vídeos (em ordem IA)
_stream_current: dict = {}           # vídeo em reprodução agora
_stream_played: list[dict] = []      # histórico transmitidos
_stream_queue_lock = _threading.Lock()

# Estado do batch automático (exibido no frontend)
_auto_batch_running: bool = False
_auto_batch_status: dict = {}        # {phase, progress, batch_run_id}


def _stream_is_live() -> bool:
    return _stream_thread is not None and _stream_thread.is_alive()


def _ep_to_dict(ep, article, mode: str = "live") -> dict:
    """Converte Episode + Article em dict serializable para a fila."""
    return {
        "ep_id":      ep.id,
        "article_id": ep.article_id,
        "title":      (article.title if article else "") or f"Episódio {ep.id}",
        "category":   (article.category if article else "geral") or "geral",
        "source":     (article.source if article else "") or "",
        "duration_s": ep.duration_s or 0,
        "video_path": ep.video_path or "",
        "mode":       mode,
    }


def _build_ai_queue(db) -> list[dict]:
    """
    Monta a fila de reprodução com sequência definida pela IA.
    1. Coleta episódios não transmitidos (LIVE) com video_path válido.
    2. Sequencia por IA (ai_sequence_articles).
    3. Se fila LIVE vazia, usa os já transmitidos (REPLAY) também sequenciados.
    """
    from aggregator.smart_fetcher import ai_sequence_articles

    def _load_episodes(streamed_filter: bool, mode: str) -> list[dict]:
        eps = (
            db.query(Episode)
            .filter(Episode.streamed == streamed_filter, Episode.video_path != None)
            .order_by(Episode.created_at.desc())
            .limit(50)
            .all()
        )
        valid = [e for e in eps if e.video_path and Path(e.video_path).exists()]
        if not valid:
            return []
        article_ids = [e.article_id for e in valid]
        ep_by_article = {e.article_id: e for e in valid}

        ordered_ids = ai_sequence_articles(article_ids)
        result = []
        for aid in ordered_ids:
            ep = ep_by_article.get(aid)
            if ep:
                art = db.query(Article).filter(Article.id == aid).first()
                result.append(_ep_to_dict(ep, art, mode))
        return result

    live_queue = _load_episodes(False, "live")
    if live_queue:
        return live_queue
    # Sem episódios novos → replay
    return _load_episodes(True, "replay")


def get_db():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    today_dt = datetime(today.year, today.month, today.day)

    articles_today = db.query(Article).filter(Article.fetched_at >= today_dt).count()
    articles_total = db.query(Article).count()
    episodes_today = db.query(Episode).filter(Episode.created_at >= today_dt).count()
    episodes_total = db.query(Episode).count()
    queue_depth = db.query(Episode).filter(
        Episode.streamed == False, Episode.video_path != None
    ).count()

    last_batch = db.query(BatchRun).order_by(BatchRun.started_at.desc()).first()
    last_batch_data = None
    if last_batch:
        last_batch_data = {
            "id": last_batch.id,
            "status": last_batch.status,
            "started_at": last_batch.started_at.isoformat() if last_batch.started_at else None,
            "episodes_generated": last_batch.episodes_generated,
        }

    from ai.client import is_available, provider_info
    ai_info = provider_info()

    is_live = _stream_is_live()

    return {
        "articles_today": articles_today,
        "articles_total": articles_total,
        "episodes_today": episodes_today,
        "episodes_total": episodes_total,
        "queue_depth": queue_depth,
        "stream_is_live": is_live,
        "last_batch": last_batch_data,
        "ai_status": ai_info,
    }


# ══════════════════════════════════════════════════════════════════════════════
# JOBS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/jobs/fetch")
async def start_fetch(background_tasks: BackgroundTasks):
    from api.job_manager import create_job, append_log, finish_job
    job_id = create_job("fetch", "Buscar notícias dos feeds RSS")

    async def _run():
        try:
            from aggregator.feed_fetcher import fetch_all_feeds
            count = fetch_all_feeds()
            append_log(job_id, f"Concluído: {count} novos artigos")
            finish_job(job_id, "done", {"articles": count})
        except Exception as e:
            append_log(job_id, f"ERRO: {e}")
            finish_job(job_id, "failed")

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "started"}


@router.post("/jobs/batch")
async def start_batch(
    background_tasks: BackgroundTasks,
    top_n: int = Query(5, ge=1, le=20),
    min_videos: int = Query(3, ge=1, le=20),
    stream_after: bool = Query(True),
    category: Optional[str] = Query(None),
):
    from api.job_manager import create_job, append_log, finish_job

    job_id = create_job("batch", f"Pipeline batch (top_n={top_n}, min_videos={min_videos})")

    async def _run():
        from aggregator.batch_pipeline import run_batch_pipeline

        def log_cb(line: str):
            append_log(job_id, line)

        try:
            batch_run_id = await run_batch_pipeline(
                top_n_per_source=top_n,
                min_videos_before_stream=min_videos,
                stream_after=stream_after,
                category_filter=category,
                log_callback=log_cb,
            )
            from api.job_manager import _JOBS
            if job_id in _JOBS:
                _JOBS[job_id]["batch_run_id"] = batch_run_id
            finish_job(job_id, "done", {"batch_run_id": batch_run_id})
        except Exception as e:
            append_log(job_id, f"ERRO: {e}")
            finish_job(job_id, "failed")

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "started"}


@router.post("/jobs/process-top")
async def process_top(
    background_tasks: BackgroundTasks,
    n: int = Query(3, ge=1, le=10),
):
    from api.job_manager import create_job, append_log, finish_job
    job_id = create_job("process-top", f"Gerar top {n} episódios")

    async def _run():
        from video.pipeline import process_top_articles
        try:
            await process_top_articles(n=n)
            append_log(job_id, f"Concluído: {n} episódios gerados")
            finish_job(job_id, "done")
        except Exception as e:
            append_log(job_id, f"ERRO: {e}")
            finish_job(job_id, "failed")

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "started"}


@router.get("/jobs")
async def list_jobs():
    from api.job_manager import list_jobs as _list
    return {"jobs": _list()}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    from api.job_manager import get_job as _get
    job = _get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return job


@router.get("/jobs/batch/runs")
async def list_batch_runs(limit: int = 20, db: Session = Depends(get_db)):
    runs = db.query(BatchRun).order_by(BatchRun.started_at.desc()).limit(limit).all()
    return {"runs": [
        {
            "id": r.id,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "articles_fetched": r.articles_fetched,
            "events_found": r.events_found,
            "episodes_generated": r.episodes_generated,
            "has_master": bool(r.master_video_path),
            "stream_started": r.stream_started,
            "category_filter": r.category_filter,
        }
        for r in runs
    ]}


@router.get("/jobs/batch/runs/{batch_run_id}")
async def get_batch_run(batch_run_id: int, db: Session = Depends(get_db)):
    run = db.query(BatchRun).filter(BatchRun.id == batch_run_id).first()
    if not run:
        raise HTTPException(404, "BatchRun não encontrado")
    return {
        "id": run.id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "articles_fetched": run.articles_fetched,
        "events_found": run.events_found,
        "episodes_generated": run.episodes_generated,
        "master_video_path": run.master_video_path,
        "stream_started": run.stream_started,
        "category_filter": run.category_filter,
        "log": (run.log or "").split("\n")[-100:],  # últimas 100 linhas
    }


# ══════════════════════════════════════════════════════════════════════════════
# STREAM CONTROLLER
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/stream/status")
async def stream_status(db: Session = Depends(get_db)):
    is_live = _stream_is_live()
    with _stream_queue_lock:
        current       = dict(_stream_current)
        queue_snapshot = list(_stream_queue)[:12]
        played_count  = len(_stream_played)

    live_count = db.query(Episode).filter(
        Episode.streamed == False, Episode.video_path != None
    ).count()

    return {
        "is_live":        is_live,
        "key_configured": bool(settings.youtube_stream_key),
        "current":        current if current else None,
        "queue":          queue_snapshot,
        "queue_depth":    len(queue_snapshot),
        "live_available": live_count,
        "played_count":   played_count,
        "mode":           current.get("mode", "idle") if is_live else "idle",
        "auto_batch":     dict(_auto_batch_status) if _auto_batch_running else None,
    }


@router.get("/stream/queue")
async def stream_queue_full():
    with _stream_queue_lock:
        return {
            "current": dict(_stream_current) if _stream_current else None,
            "queue":   list(_stream_queue),
            "played":  list(_stream_played)[-20:],
        }


@router.post("/stream/start")
async def stream_start(background_tasks: BackgroundTasks):
    global _stream_thread, _stream_stop_event
    if _stream_is_live():
        return {"status": "already_running"}
    if not settings.youtube_stream_key:
        raise HTTPException(400, "YOUTUBE_STREAM_KEY não configurada")

    _stream_stop_event.clear()

    def _run_stream():
        global _stream_queue, _stream_current, _stream_played
        global _auto_batch_running, _auto_batch_status
        import asyncio
        from stream.streamer import stream_video

        vignette = (settings.video_output_path / ".." / "assets" / "vignette.mp4").resolve()

        # ── helpers ────────────────────────────────────────────────────────────

        def _refresh_queue():
            """Reconstrói fila com sequência IA a partir dos episódios disponíveis."""
            from database.db import get_session_factory
            db2 = get_session_factory()()
            try:
                q = _build_ai_queue(db2)
                with _stream_queue_lock:
                    _stream_queue[:] = q
            finally:
                db2.close()

        def _mark_streamed(ep_id: int, mode: str):
            if mode != "live":
                return
            try:
                from database.db import get_session_factory
                db3 = get_session_factory()()
                ep = db3.query(Episode).filter(Episode.id == ep_id).first()
                if ep:
                    ep.streamed = True
                    db3.commit()
                db3.close()
            except Exception:
                pass

        def _trigger_auto_batch():
            """
            Lança uma nova rodada completa do pipeline:
            fetch → dedup → sequência IA → gera episódios → adiciona à fila.
            Roda em thread separada para não bloquear o stream.
            """
            global _auto_batch_running, _auto_batch_status
            if _auto_batch_running:
                return
            _auto_batch_running = True
            _auto_batch_status = {"phase": "iniciando", "progress": "—", "batch_run_id": None}

            def _batch_worker():
                global _auto_batch_running, _auto_batch_status
                try:
                    def _log(line: str):
                        # Extrai fase do log para exibir no frontend
                        phase = _auto_batch_status.get("phase", "")
                        if "Buscando" in line:
                            phase = "buscando notícias"
                        elif "Agrupando" in line or "MinHash" in line:
                            phase = "deduplicando com IA"
                        elif "Ordenando" in line:
                            phase = "sequenciando com IA"
                        elif "Gerando" in line and "episódio" in line.lower():
                            phase = "gerando episódios"
                        elif "Episódios gerados" in line:
                            prog = line.split("Episódios gerados:")[-1].strip()
                            phase = f"gerados {prog}"
                        _auto_batch_status["phase"] = phase
                        _auto_batch_status["progress"] = line.split("] ", 1)[-1][:80]
                        logger.info(f"[auto-batch] {line}")

                    from aggregator.batch_pipeline import run_batch_pipeline
                    batch_run_id = asyncio.run(run_batch_pipeline(
                        top_n_per_source=settings.batch_top_n_per_source,
                        min_videos_before_stream=settings.batch_min_videos_before_stream,
                        stream_after=False,   # stream já está rodando
                        log_callback=_log,
                    ))
                    _auto_batch_status["batch_run_id"] = batch_run_id
                    _auto_batch_status["phase"] = "concluído"
                    logger.info(f"[auto-batch] Batch #{batch_run_id} concluído — resequenciando fila")
                    # Recarrega fila com os novos episódios, em nova ordem IA
                    _refresh_queue()
                except Exception as e:
                    logger.error(f"[auto-batch] Falhou: {e}", exc_info=True)
                    _auto_batch_status["phase"] = f"erro: {e}"
                finally:
                    _auto_batch_running = False

            _threading.Thread(target=_batch_worker, daemon=True, name="auto-batch").start()

        # ── fila inicial ───────────────────────────────────────────────────────
        _refresh_queue()

        # Se não há nada, começa gerando imediatamente
        with _stream_queue_lock:
            queue_empty = len(_stream_queue) == 0
        if queue_empty:
            logger.info("[stream] Fila vazia — iniciando geração automática de conteúdo")
            _trigger_auto_batch()

        # ── loop principal de transmissão ──────────────────────────────────────
        while not _stream_stop_event.is_set():

            with _stream_queue_lock:
                queue_size = len(_stream_queue)

            # Dispara novo batch proativamente quando fila estiver no último episódio
            if queue_size <= 1 and not _auto_batch_running and not _stream_stop_event.is_set():
                logger.info(f"[stream] Fila com {queue_size} item(s) — gerando próxima sequência")
                _trigger_auto_batch()

            # Sem vídeos: aguarda batch terminar e recarregar
            if queue_size == 0:
                with _stream_queue_lock:
                    _stream_current = {
                        "mode":  "generating",
                        "title": f"Gerando novo conteúdo… ({_auto_batch_status.get('phase','—')})",
                        "started_at": datetime.utcnow().isoformat(),
                    }
                _stream_stop_event.wait(timeout=20)
                _refresh_queue()
                continue

            # Pega próximo da fila
            with _stream_queue_lock:
                if not _stream_queue:
                    continue
                item = _stream_queue.pop(0)
                _stream_current = {**item, "started_at": datetime.utcnow().isoformat()}

            video_path = Path(item["video_path"])
            if not video_path.exists():
                logger.warning(f"[stream] Vídeo não encontrado: {video_path}")
                continue

            # Vinheta de transição
            if vignette.exists() and not _stream_stop_event.is_set():
                stream_video(vignette)

            # Transmite episódio
            if not _stream_stop_event.is_set():
                stream_video(video_path)

            # Pós-transmissão
            if not _stream_stop_event.is_set():
                _mark_streamed(item["ep_id"], item["mode"])
                with _stream_queue_lock:
                    _stream_played.append(item)
                    if len(_stream_played) > 200:
                        _stream_played.pop(0)

        # Limpeza ao parar
        with _stream_queue_lock:
            _stream_current = {}
        _auto_batch_status = {}

    _stream_thread = _threading.Thread(target=_run_stream, daemon=True, name="admin-stream")
    _stream_thread.start()
    with _stream_queue_lock:
        _stream_current = {
            "mode": "starting",
            "title": "Iniciando — sequenciando episódios por IA…",
            "started_at": datetime.utcnow().isoformat(),
        }
    return {"status": "started"}


@router.post("/stream/stop")
async def stream_stop():
    global _auto_batch_running, _auto_batch_status
    _stream_stop_event.set()
    try:
        subprocess.run(["pkill", "-f", "rtmp://"], capture_output=True)
    except Exception:
        pass
    with _stream_queue_lock:
        _stream_current.clear()
    _auto_batch_status = {}
    return {"status": "stopped"}


@router.post("/stream/rebuild-queue")
async def stream_rebuild_queue():
    """Força resequenciamento IA da fila atual sem parar o stream."""
    if not _stream_is_live():
        raise HTTPException(400, "Stream não está rodando")
    from database.db import get_session_factory
    db2 = get_session_factory()()
    try:
        q = _build_ai_queue(db2)
        with _stream_queue_lock:
            _stream_queue[:] = q
        return {"status": "rebuilt", "queue_size": len(q)}
    finally:
        db2.close()


class StreamConfigBody(BaseModel):
    youtube_key: Optional[str] = None
    bitrate: Optional[str] = None


@router.patch("/stream/config")
async def stream_config(body: StreamConfigBody):
    updates = {}
    if body.youtube_key:
        updates["YOUTUBE_STREAM_KEY"] = body.youtube_key
    if body.bitrate:
        updates["STREAM_BITRATE"] = body.bitrate
    if updates:
        _write_env(updates)
    return {"status": "updated", "fields": list(updates.keys())}


# ══════════════════════════════════════════════════════════════════════════════
# RSS SOURCES MANAGER
# ══════════════════════════════════════════════════════════════════════════════

def _load_sources() -> dict:
    with open(settings.sources_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_sources(data: dict):
    with open(settings.sources_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


@router.get("/sources")
async def list_sources():
    data = _load_sources()
    feeds = data.get("feeds", [])
    # Garante campo enabled
    for feed in feeds:
        feed.setdefault("enabled", True)
    return {"feeds": feeds}


class SourceCreateBody(BaseModel):
    name: str
    url: str
    weight: float = 1.0
    category_default: str = "geral"
    enabled: bool = True


class SourceUpdateBody(BaseModel):
    weight: Optional[float] = None
    enabled: Optional[bool] = None
    category_default: Optional[str] = None


@router.post("/sources")
async def add_source(body: SourceCreateBody):
    data = _load_sources()
    feeds = data.get("feeds", [])
    if any(f["name"] == body.name for f in feeds):
        raise HTTPException(400, f"Fonte '{body.name}' já existe")
    feeds.append({
        "name": body.name,
        "url": body.url,
        "weight": body.weight,
        "category_default": body.category_default,
        "enabled": body.enabled,
    })
    data["feeds"] = feeds
    _save_sources(data)
    return {"status": "added", "feeds": feeds}


@router.patch("/sources/{name}")
async def update_source(name: str, body: SourceUpdateBody):
    data = _load_sources()
    feeds = data.get("feeds", [])
    feed = next((f for f in feeds if f["name"] == name), None)
    if not feed:
        raise HTTPException(404, f"Fonte '{name}' não encontrada")
    if body.weight is not None:
        feed["weight"] = body.weight
    if body.enabled is not None:
        feed["enabled"] = body.enabled
    if body.category_default is not None:
        feed["category_default"] = body.category_default
    data["feeds"] = feeds
    _save_sources(data)
    return {"status": "updated", "feed": feed}


@router.delete("/sources/{name}")
async def delete_source(name: str):
    data = _load_sources()
    feeds = data.get("feeds", [])
    new_feeds = [f for f in feeds if f["name"] != name]
    if len(new_feeds) == len(feeds):
        raise HTTPException(404, f"Fonte '{name}' não encontrada")
    data["feeds"] = new_feeds
    _save_sources(data)
    return {"status": "deleted"}


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS EDITOR
# ══════════════════════════════════════════════════════════════════════════════

EDITABLE_SETTINGS = {
    "AI_PROVIDER", "ANTHROPIC_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_MODEL",
    "YOUTUBE_STREAM_KEY", "FETCH_INTERVAL_MINUTES", "MAX_NEWS_PER_CYCLE",
    "LOG_LEVEL", "HOST", "PORT",
}

SENSITIVE = {"ANTHROPIC_API_KEY", "YOUTUBE_STREAM_KEY"}


def _read_env() -> dict:
    env_path = BASE_DIR / ".env"
    result = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    return result


def _write_env(updates: dict):
    env_path = BASE_DIR / ".env"
    current = _read_env()
    current.update(updates)
    lines = [f"{k}={v}" for k, v in current.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@router.get("/settings")
async def get_settings_api():
    env = _read_env()
    result = {}
    for k in EDITABLE_SETTINGS:
        v = env.get(k, "")
        if k in SENSITIVE and v:
            result[k] = v[:6] + "****" + v[-4:] if len(v) > 10 else "****"
        else:
            result[k] = v
    return {"settings": result, "requires_restart": False}


class SettingsUpdateBody(BaseModel):
    AI_PROVIDER: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: Optional[str] = None
    OLLAMA_MODEL: Optional[str] = None
    YOUTUBE_STREAM_KEY: Optional[str] = None
    FETCH_INTERVAL_MINUTES: Optional[str] = None
    MAX_NEWS_PER_CYCLE: Optional[str] = None
    LOG_LEVEL: Optional[str] = None


@router.patch("/settings")
async def update_settings(body: SettingsUpdateBody):
    updates = {k: str(v) for k, v in body.model_dump().items()
               if v is not None and k in EDITABLE_SETTINGS}
    if not updates:
        raise HTTPException(400, "Nenhum campo para atualizar")
    _write_env(updates)
    return {"status": "updated", "fields": list(updates.keys()),
            "requires_restart": True,
            "message": "Reinicie o servidor para aplicar as mudanças"}


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULE / AGENDA
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/schedule")
async def get_schedule():
    with open(settings.schedule_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {"schedule": data}


class ScheduleUpdateBody(BaseModel):
    daytime_start: Optional[int] = None
    daytime_end: Optional[int] = None
    category_schedules: Optional[dict] = None
    top_articles_per_cycle: Optional[int] = None
    min_videos_before_replay: Optional[int] = None


@router.patch("/schedule")
async def update_schedule(body: ScheduleUpdateBody):
    with open(settings.schedule_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if body.daytime_start is not None:
        data.setdefault("stream", {})["daytime_start"] = body.daytime_start
    if body.daytime_end is not None:
        data.setdefault("stream", {})["daytime_end"] = body.daytime_end
    if body.top_articles_per_cycle is not None:
        data.setdefault("stream", {})["top_articles_per_cycle"] = body.top_articles_per_cycle
    if body.min_videos_before_replay is not None:
        data.setdefault("stream", {})["min_videos_before_replay"] = body.min_videos_before_replay
    if body.category_schedules is not None:
        data["category_schedules"] = body.category_schedules

    with open(settings.schedule_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    return {"status": "updated", "schedule": data}


# ══════════════════════════════════════════════════════════════════════════════
# EPISODE LIBRARY
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/episodes")
async def list_episodes(
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    category: Optional[str] = None,
    streamed: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Episode, Article).join(Article, Episode.article_id == Article.id)
    if category:
        q = q.filter(Article.category == category)
    if streamed is not None:
        q = q.filter(Episode.streamed == streamed)

    total = q.count()
    items = q.order_by(Episode.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    episodes = []
    for ep, art in items:
        video_exists = bool(ep.video_path and Path(ep.video_path).exists())
        episodes.append({
            "id": ep.id,
            "article_id": ep.article_id,
            "title": art.title,
            "category": art.category,
            "source": art.source,
            "duration_s": ep.duration_s,
            "created_at": ep.created_at.isoformat() if ep.created_at else None,
            "streamed": ep.streamed,
            "has_video": video_exists,
            "video_path": ep.video_path if video_exists else None,
            "batch_run_id": ep.batch_run_id,
        })

    return {
        "episodes": episodes,
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/episodes/{episode_id}/video")
async def serve_video(episode_id: int, db: Session = Depends(get_db)):
    ep = db.query(Episode).filter(Episode.id == episode_id).first()
    if not ep or not ep.video_path:
        raise HTTPException(404, "Episódio não tem vídeo")
    p = Path(ep.video_path)
    if not p.exists():
        raise HTTPException(404, "Arquivo de vídeo não encontrado")
    # Segurança: validar que está dentro do output dir
    try:
        p.relative_to(settings.video_output_path)
    except ValueError:
        raise HTTPException(403, "Acesso negado")
    return FileResponse(str(p), media_type="video/mp4")


@router.delete("/episodes/{episode_id}")
async def delete_episode(episode_id: int, db: Session = Depends(get_db)):
    ep = db.query(Episode).filter(Episode.id == episode_id).first()
    if not ep:
        raise HTTPException(404, "Episódio não encontrado")
    # Remove arquivos
    if ep.video_path:
        ep_dir = Path(ep.video_path).parent
        if ep_dir.exists():
            shutil.rmtree(ep_dir, ignore_errors=True)
    # Atualiza artigo
    art = db.query(Article).filter(Article.id == ep.article_id).first()
    if art:
        art.processed = False
    db.delete(ep)
    db.commit()
    return {"status": "deleted"}


@router.post("/episodes/{episode_id}/requeue")
async def requeue_episode(episode_id: int, db: Session = Depends(get_db)):
    ep = db.query(Episode).filter(Episode.id == episode_id).first()
    if not ep:
        raise HTTPException(404, "Episódio não encontrado")
    ep.streamed = False
    db.commit()
    return {"status": "requeued"}


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE RESET
# ══════════════════════════════════════════════════════════════════════════════

class ResetBody(BaseModel):
    confirm: str   # deve ser "RESETAR" para confirmar

@router.post("/database/reset")
async def database_reset(body: ResetBody, db: Session = Depends(get_db)):
    """
    Apaga todos os artigos, episódios, batch_runs e stream_queue.
    Remove também os arquivos de vídeo/áudio gerados.
    Requer confirmação: {"confirm": "RESETAR"}.
    """
    if body.confirm != "RESETAR":
        raise HTTPException(400, "Confirmação inválida. Envie {\"confirm\": \"RESETAR\"}")

    if _stream_is_live():
        raise HTTPException(400, "Pare o stream antes de resetar a base")

    stats = {"articles": 0, "episodes": 0, "batch_runs": 0, "files_removed": 0}

    # Remove arquivos físicos dos episódios antes de apagar o banco
    episodes = db.query(Episode).all()
    stats["episodes"] = len(episodes)
    for ep in episodes:
        for path_field in [ep.video_path, ep.audio_path]:
            if path_field:
                p = Path(path_field)
                try:
                    if p.exists():
                        p.unlink()
                        stats["files_removed"] += 1
                    # Remove diretório do episódio se vazio
                    parent = p.parent
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                except Exception:
                    pass

    # Remove diretórios de batch vazios
    output_dir = settings.video_output_path
    if output_dir.exists():
        for d in output_dir.iterdir():
            if d.is_dir():
                try:
                    shutil.rmtree(d)
                    stats["files_removed"] += 1
                except Exception:
                    pass

    # Apaga registros do banco na ordem correta (FK)
    from database.models import StreamQueue
    db.query(StreamQueue).delete()
    db.query(Episode).delete()
    stats["batch_runs"] = db.query(BatchRun).count()
    db.query(BatchRun).delete()
    stats["articles"] = db.query(Article).count()
    db.query(Article).delete()
    db.commit()

    # Limpa estado do stream em memória
    with _stream_queue_lock:
        _stream_queue.clear()
        _stream_current.clear()
        _stream_played.clear()

    logger.warning(f"DATABASE RESET: {stats}")
    return {"status": "reset_complete", "removed": stats}
