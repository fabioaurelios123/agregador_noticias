"""
Ranks articles by importance: recency + source weight + category boost.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database.db import get_session_factory
from database.models import Article

logger = logging.getLogger(__name__)

# Category importance multipliers
CATEGORY_BOOST = {
    "politica": 1.3,
    "economia": 1.2,
    "saude": 1.1,
    "tech": 1.0,
    "esporte": 0.9,
    "geral": 1.0,
}


def _recency_score(published_at: datetime | None, fetched_at: datetime) -> float:
    """Score 1.0 (just published) → 0.0 (24h ago)."""
    ref = published_at or fetched_at
    age_hours = max(0, (datetime.utcnow() - ref).total_seconds() / 3600)
    return max(0.0, 1.0 - age_hours / 24.0)


def rank_articles(limit: int = 200) -> int:
    """Recalculate scores for recent unprocessed articles. Returns count updated."""
    SessionLocal = get_session_factory()
    db: Session = SessionLocal()
    updated = 0

    try:
        articles = (
            db.query(Article)
            .filter(Article.processed == False)
            .order_by(Article.fetched_at.desc())
            .limit(limit)
            .all()
        )

        for article in articles:
            recency = _recency_score(article.published_at, article.fetched_at)
            category_boost = CATEGORY_BOOST.get(article.category or "geral", 1.0)
            # score already carries source weight from feed_fetcher
            article.score = article.score * recency * category_boost
            updated += 1

        db.commit()
        logger.info(f"Ranked {updated} articles")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return updated


def get_top_articles(n: int = 10, category: str | None = None) -> list[Article]:
    """Return the top N articles by score."""
    SessionLocal = get_session_factory()
    db: Session = SessionLocal()
    try:
        q = db.query(Article).filter(Article.processed == False)
        if category:
            q = q.filter(Article.category == category)
        articles = q.order_by(Article.score.desc()).limit(n).all()
        # Detach from session so caller can use outside session
        db.expunge_all()
        return articles
    finally:
        db.close()
