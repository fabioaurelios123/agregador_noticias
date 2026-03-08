"""
Fetches RSS feeds from Brazilian news sources and stores articles in the database.
"""
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import feedparser
import yaml
from sqlalchemy.orm import Session

from config.settings import settings
from database.db import get_session_factory
from database.models import Article

logger = logging.getLogger(__name__)


def _load_sources() -> list[dict]:
    with open(settings.sources_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("feeds", [])


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published", "updated"):
        value = getattr(entry, attr, None)
        if value:
            try:
                dt = parsedate_to_datetime(value)
                return dt.replace(tzinfo=None) if dt.tzinfo else dt
            except Exception:
                pass
    return None


def _extract_image(entry) -> Optional[str]:
    # Try media:thumbnail
    media_thumbnail = getattr(entry, "media_thumbnail", None)
    if media_thumbnail:
        return media_thumbnail[0].get("url")

    # Try enclosures
    enclosures = getattr(entry, "enclosures", [])
    for enc in enclosures:
        if enc.get("type", "").startswith("image/"):
            return enc.get("href") or enc.get("url")

    # Try links
    links = getattr(entry, "links", [])
    for link in links:
        if link.get("type", "").startswith("image/"):
            return link.get("href")

    return None


def _categorize(title: str, summary: str, source_config: dict, keywords: dict) -> str:
    text = (title + " " + summary).lower()
    for category, words in keywords.items():
        if any(w in text for w in words):
            return category
    return source_config.get("category_default", "geral")


def fetch_all_feeds() -> int:
    """Fetch all RSS feeds and persist new articles. Returns count of new articles."""
    with open(settings.sources_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    feeds = config.get("feeds", [])
    keywords = config.get("keywords", {})

    SessionLocal = get_session_factory()
    db: Session = SessionLocal()
    new_count = 0

    try:
        for source_cfg in feeds:
            name = source_cfg["name"]
            url = source_cfg["url"]
            weight = source_cfg.get("weight", 1.0)

            logger.info(f"Fetching feed: {name} ({url})")
            try:
                feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
            except Exception as e:
                logger.warning(f"Failed to fetch {name}: {e}")
                continue

            for entry in feed.entries:
                article_url = getattr(entry, "link", None)
                if not article_url:
                    continue

                # Skip if already in DB
                exists = db.query(Article).filter_by(url=article_url).first()
                if exists:
                    continue

                title = getattr(entry, "title", "").strip()
                raw_summary = getattr(entry, "summary", "") or ""
                image_url = _extract_image(entry)
                published_at = _parse_date(entry)
                category = _categorize(title, raw_summary, source_cfg, keywords)

                article = Article(
                    source=name,
                    title=title,
                    url=article_url,
                    content=None,       # filled by scraper
                    summary=None,       # filled by AI
                    image_url=image_url,
                    category=category,
                    score=weight,       # initial score = source weight
                    fetched_at=datetime.utcnow(),
                    published_at=published_at,
                    processed=False,
                )
                db.add(article)
                try:
                    db.flush()
                    new_count += 1
                except Exception:
                    db.rollback()
                    # URL already exists from another feed — skip
                    continue

        db.commit()
        logger.info(f"Feed fetch complete. New articles: {new_count}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return new_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = fetch_all_feeds()
    print(f"Fetched {count} new articles.")
