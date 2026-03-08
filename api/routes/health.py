from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Article, Episode

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    total_articles = db.query(Article).count()
    total_episodes = db.query(Episode).count()
    from ai.client import provider_info
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "total_articles": total_articles,
        "total_episodes": total_episodes,
        "ai": provider_info(),
    }
