"""
Uses Newspaper3K to extract full article content from URLs.
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from database.db import get_session_factory
from database.models import Article

logger = logging.getLogger(__name__)

try:
    from newspaper import Article as NewspaperArticle
    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False
    logger.warning("newspaper3k not installed — scraping disabled")


def scrape_article(url: str) -> dict:
    """Download and parse a single article URL. Returns dict with content and image."""
    if not NEWSPAPER_AVAILABLE:
        return {}

    try:
        paper = NewspaperArticle(url, language="pt")
        paper.download()
        paper.parse()
        return {
            "content": paper.text or "",
            "image_url": paper.top_image or None,
            "published_at": paper.publish_date,
        }
    except Exception as e:
        logger.warning(f"Failed to scrape {url}: {e}")
        return {}


def scrape_pending(limit: int = 20) -> int:
    """Scrape articles that have no content yet. Returns count updated."""
    SessionLocal = get_session_factory()
    db: Session = SessionLocal()
    updated = 0

    try:
        pending = (
            db.query(Article)
            .filter(Article.content == None, Article.processed == False)
            .order_by(Article.fetched_at.desc())
            .limit(limit)
            .all()
        )

        for article in pending:
            result = scrape_article(article.url)
            if result.get("content"):
                article.content = result["content"]
            if result.get("image_url") and not article.image_url:
                article.image_url = result["image_url"]
            if result.get("published_at") and not article.published_at:
                article.published_at = result["published_at"]
            updated += 1

        db.commit()
        logger.info(f"Scraped content for {updated} articles")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return updated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = scrape_pending(limit=5)
    print(f"Scraped {count} articles.")
