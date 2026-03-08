"""
WebSocket endpoint for real-time admin log streaming.
Clients connect to /ws/admin and receive JSON log events.
"""
import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket, WebSocketDisconnect

from api.job_manager import add_log_subscriber, remove_log_subscriber

logger = logging.getLogger(__name__)

_admin_clients: Set[WebSocket] = set()


async def broadcast_admin(message: dict):
    """Broadcast a message to all connected admin WebSocket clients."""
    if not _admin_clients:
        return
    data = json.dumps(message, ensure_ascii=False, default=str)
    dead = set()
    for ws in list(_admin_clients):
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _admin_clients.difference_update(dead)


async def admin_websocket_endpoint(websocket: WebSocket):
    """Handle admin WebSocket connection — streams live job logs."""
    await websocket.accept()
    _admin_clients.add(websocket)

    # Register subscriber so job_manager broadcasts to this WS
    async def _on_event(event: dict):
        try:
            await websocket.send_text(json.dumps(event, ensure_ascii=False, default=str))
        except Exception:
            pass

    add_log_subscriber(_on_event)
    logger.info(f"Admin WS connected (total={len(_admin_clients)})")

    try:
        # Keep connection alive; client sends pings
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # echo ping back
                if msg == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_text(json.dumps({"type": "heartbeat"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"Admin WS error: {e}")
    finally:
        remove_log_subscriber(_on_event)
        _admin_clients.discard(websocket)
        logger.info(f"Admin WS disconnected (remaining={len(_admin_clients)})")
