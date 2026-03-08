from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Article, Episode

router = APIRouter(prefix="/api/news", tags=["news"])


def _article_to_dict(a: Article) -> dict:
    return {
        "id": a.id,
        "source": a.source,
        "title": a.title,
        "url": a.url,
        "summary": a.summary,
        "image_url": a.image_url,
        "category": a.category,
        "score": round(a.score or 0, 4),
        "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "processed": a.processed,
        "has_episode": len(a.episodes) > 0,
    }


@router.get("/top")
def get_top_news(
    n: int = Query(10, ge=1, le=50),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Article).filter(Article.processed == False)
    if category:
        q = q.filter(Article.category == category)
    articles = q.order_by(Article.score.desc()).limit(n).all()
    return {"articles": [_article_to_dict(a) for a in articles]}


@router.get("")
def list_news(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Article).filter(Article.processed == False)
    if category:
        q = q.filter(Article.category == category)
    if source:
        q = q.filter(Article.source == source)
    total = q.count()
    articles = (
        q.order_by(Article.score.desc(), Article.fetched_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "articles": [_article_to_dict(a) for a in articles],
    }


@router.get("/{article_id}")
def get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    data = _article_to_dict(article)
    data["content"] = article.content
    return data
