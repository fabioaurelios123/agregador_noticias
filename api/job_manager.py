"""
Gerenciador de jobs em memória para o painel admin.
Tracks background tasks com status, logs e resultados.
"""
import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

# job_id -> {id, type, status, started_at, finished_at, logs, result, batch_run_id}
_JOBS: dict[str, dict] = {}

# WebSocket callbacks para envio de logs ao vivo
_log_subscribers: list[Callable] = []


def create_job(job_type: str, description: str = "") -> str:
    job_id = str(uuid.uuid4())[:8]
    _JOBS[job_id] = {
        "id": job_id,
        "type": job_type,
        "description": description,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "logs": [],
        "result": None,
        "batch_run_id": None,
    }
    return job_id


def _broadcast(event: dict):
    """Send event to all log subscribers (handles both sync and async callbacks)."""
    for cb in list(_log_subscribers):
        try:
            import inspect
            result = cb(event)
            if inspect.iscoroutine(result):
                # Schedule async callback on the running event loop if available
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(result)
                except RuntimeError:
                    pass
        except Exception:
            pass


def append_log(job_id: str, line: str):
    if job_id in _JOBS:
        _JOBS[job_id]["logs"].append(line)
        _broadcast({"type": "log", "job_id": job_id, "line": line,
                    "batch_run_id": _JOBS[job_id].get("batch_run_id")})


def finish_job(job_id: str, status: str = "done", result: Any = None):
    if job_id in _JOBS:
        _JOBS[job_id]["status"] = status
        _JOBS[job_id]["finished_at"] = datetime.utcnow().isoformat()
        _JOBS[job_id]["result"] = result
        _broadcast({"type": "job_update", "job_id": job_id, "status": status})


def get_job(job_id: str) -> Optional[dict]:
    return _JOBS.get(job_id)


def list_jobs() -> list[dict]:
    return sorted(_JOBS.values(), key=lambda j: j["started_at"], reverse=True)


def add_log_subscriber(cb: Callable):
    _log_subscribers.append(cb)


def remove_log_subscriber(cb: Callable):
    _log_subscribers.discard(cb) if hasattr(_log_subscribers, 'discard') else None
    if cb in _log_subscribers:
        _log_subscribers.remove(cb)
