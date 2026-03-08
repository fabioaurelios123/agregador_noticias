"""
Removes duplicate articles using MinHash LSH on title similarity.
"""
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from database.db import get_session_factory
from database.models import Article

logger = logging.getLogger(__name__)

try:
    from datasketch import MinHash, MinHashLSH
    MINHASH_AVAILABLE = True
except ImportError:
    MINHASH_AVAILABLE = False
    logger.warning("datasketch not installed — using simple title dedup")


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _shingles(text: str, k: int = 3) -> set:
    words = text.split()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)} or set(words)


def _make_minhash(text: str, num_perm: int = 64) -> "MinHash":
    m = MinHash(num_perm=num_perm)
    for s in _shingles(_normalize(text)):
        m.update(s.encode("utf-8"))
    return m


def deduplicate_recent(threshold: float = 0.7, limit: int = 200) -> int:
    """
    Mark near-duplicate articles as processed=True (suppressed).
    Returns count of duplicates removed.
    """
    SessionLocal = get_session_factory()
    db: Session = SessionLocal()
    removed = 0

    try:
        recent = (
            db.query(Article)
            .filter(Article.processed == False)
            .order_by(Article.score.desc(), Article.fetched_at.desc())
            .limit(limit)
            .all()
        )

        if MINHASH_AVAILABLE:
            removed = _dedup_minhash(db, recent, threshold)
        else:
            removed = _dedup_simple(db, recent)

        db.commit()
        logger.info(f"Deduplication removed {removed} duplicates")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return removed


def _dedup_minhash(db: Session, articles: list, threshold: float) -> int:
    lsh = MinHashLSH(threshold=threshold, num_perm=64)
    seen_ids = set()
    removed = 0

    for article in articles:
        key = str(article.id)
        m = _make_minhash(article.title)
        results = lsh.query(m)

        if results:
            # Duplicate found — keep the higher-scored one already in LSH
            article.processed = True
            removed += 1
        else:
            lsh.insert(key, m)
            seen_ids.add(article.id)

    return removed


def _dedup_simple(db: Session, articles: list) -> int:
    seen_titles: set[str] = set()
    removed = 0

    for article in articles:
        norm = _normalize(article.title)
        # Simple exact-normalized match
        if norm in seen_titles:
            article.processed = True
            removed += 1
        else:
            seen_titles.add(norm)

    return removed
