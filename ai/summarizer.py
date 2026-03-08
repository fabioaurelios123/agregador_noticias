"""
Summarizes news articles in PT-BR using the configured AI provider
(Anthropic Claude or Ollama).
"""
import logging

from config.settings import settings
from ai.prompts import SUMMARY_SYSTEM, SUMMARY_USER

logger = logging.getLogger(__name__)


def summarize_article(title: str, content: str, source: str = "") -> str:
    """Return a PT-BR summary of the article. Falls back to truncated content on error."""
    if not content or len(content.strip()) < 100:
        return content or title

    from ai.client import chat, is_available

    if not is_available():
        logger.warning(
            f"AI provider '{settings.ai_provider}' not available — using truncated content"
        )
        return content[:500]

    prompt = SUMMARY_USER.format(
        title=title,
        source=source,
        content=content[:4000],
    )

    try:
        return chat(system=SUMMARY_SYSTEM, user=prompt, max_tokens=512)
    except Exception as e:
        logger.error(f"Summarization failed ({settings.ai_provider}): {e}")
        return content[:500]


def summarize_pending(limit: int = 10) -> int:
    """Summarize articles that have content but no summary yet."""
    from database.db import get_session_factory
    from database.models import Article

    SessionLocal = get_session_factory()
    db = SessionLocal()
    updated = 0

    try:
        pending = (
            db.query(Article)
            .filter(
                Article.content != None,
                Article.summary == None,
                Article.processed == False,
            )
            .order_by(Article.score.desc())
            .limit(limit)
            .all()
        )

        for article in pending:
            summary = summarize_article(article.title, article.content or "", article.source)
            article.summary = summary
            updated += 1
            logger.info(f"Summarized article {article.id}: {article.title[:60]}")

        db.commit()
        logger.info(f"Summarized {updated} articles")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return updated
