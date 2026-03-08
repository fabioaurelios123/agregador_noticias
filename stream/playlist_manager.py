"""
Manages the streaming playlist — queues episodes for live or replay.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from database.db import get_session_factory
from database.models import Episode, StreamQueue

logger = logging.getLogger(__name__)


def get_next_episode(mode: str = "live") -> Optional[Path]:
    """
    Return the path to the next video file to stream.
    Mode "live": unstreamed episodes.
    Mode "replay": re-streams today's episodes in order.
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        if mode == "live":
            episode = (
                db.query(Episode)
                .filter(Episode.streamed == False, Episode.video_path != None)
                .order_by(Episode.created_at.asc())
                .first()
            )
            if episode:
                episode.streamed = True
                db.commit()
                return Path(episode.video_path)
        else:
            # Replay: cycle through today's episodes
            today = datetime.utcnow().date()
            episodes = (
                db.query(Episode)
                .filter(
                    Episode.video_path != None,
                    Episode.created_at >= datetime(today.year, today.month, today.day),
                )
                .order_by(Episode.created_at.asc())
                .all()
            )
            if episodes:
                # Round-robin: return first unplayed or restart
                return Path(episodes[0].video_path)
        return None
    finally:
        db.close()


def queue_episode(episode_id: int, mode: str = "live"):
    """Add an episode to the stream queue."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        entry = StreamQueue(
            episode_id=episode_id,
            scheduled_at=datetime.utcnow(),
            mode=mode,
        )
        db.add(entry)
        db.commit()
    finally:
        db.close()


def get_queue_length() -> int:
    """Return number of episodes waiting to be streamed."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        return db.query(Episode).filter(Episode.streamed == False, Episode.video_path != None).count()
    finally:
        db.close()
