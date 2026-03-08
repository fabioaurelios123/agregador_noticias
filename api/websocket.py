"""
WebSocket endpoint for real-time news push to frontend clients.
"""
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

_active_connections: list[WebSocket] = []


async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _active_connections.append(websocket)
    logger.info(f"WebSocket client connected. Total: {len(_active_connections)}")
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        _active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(_active_connections)}")
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
        if websocket in _active_connections:
            _active_connections.remove(websocket)


async def broadcast(message: dict[str, Any]):
    """Send a JSON message to all connected clients."""
    if not _active_connections:
        return
    text = json.dumps(message, ensure_ascii=False, default=str)
    dead = []
    for ws in _active_connections:
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _active_connections.remove(ws)


async def broadcast_new_articles():
    """Fetch latest top articles and broadcast to all clients."""
    from aggregator.ranker import get_top_articles

    articles = get_top_articles(n=10)
    if not articles:
        return

    payload = {
        "type": "news_update",
        "timestamp": datetime.utcnow().isoformat(),
        "articles": [
            {
                "id": a.id,
                "title": a.title,
                "source": a.source,
                "category": a.category,
                "image_url": a.image_url,
                "url": a.url,
                "score": a.score,
                "published_at": a.published_at.isoformat() if a.published_at else None,
            }
            for a in articles
        ],
    }
    await broadcast(payload)
