from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Episode, StreamQueue

router = APIRouter(prefix="/api/stream", tags=["stream"])


@router.get("/status")
def stream_status(db: Session = Depends(get_db)):
    hour = datetime.now().hour
    mode = "live" if 6 <= hour < 23 else "replay"

    # Next episode in queue
    next_entry = (
        db.query(StreamQueue)
        .filter(StreamQueue.played_at == None)
        .order_by(StreamQueue.scheduled_at.asc())
        .first()
    )

    # Total episodes generated
    total_episodes = db.query(Episode).count()
    unstreamed = db.query(Episode).filter(Episode.streamed == False).count()

    return {
        "mode": mode,
        "is_live": True,
        "total_episodes": total_episodes,
        "unstreamed_episodes": unstreamed,
        "next_episode_id": next_entry.episode_id if next_entry else None,
        "timestamp": datetime.utcnow().isoformat(),
    }
