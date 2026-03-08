"""
APScheduler jobs: periodically fetch feeds, scrape content, deduplicate and rank.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_fetch_pipeline():
    """Full pipeline: fetch → scrape → deduplicate → rank."""
    logger.info("Starting scheduled news fetch pipeline...")
    try:
        from aggregator.feed_fetcher import fetch_all_feeds
        from aggregator.scraper import scrape_pending
        from aggregator.deduplicator import deduplicate_recent
        from aggregator.ranker import rank_articles

        new = fetch_all_feeds()
        logger.info(f"Fetched {new} new articles")

        scraped = scrape_pending(limit=30)
        logger.info(f"Scraped content for {scraped} articles")

        dupes = deduplicate_recent()
        logger.info(f"Removed {dupes} duplicate articles")

        ranked = rank_articles()
        logger.info(f"Ranked {ranked} articles")

        # Notify WebSocket clients of new articles
        try:
            from api.websocket import broadcast_new_articles
            await broadcast_new_articles()
        except Exception as e:
            logger.debug(f"WebSocket broadcast skipped: {e}")

    except Exception as e:
        logger.error(f"Error in fetch pipeline: {e}", exc_info=True)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            _run_fetch_pipeline,
            trigger=IntervalTrigger(minutes=settings.fetch_interval_minutes),
            id="fetch_pipeline",
            name="News fetch pipeline",
            replace_existing=True,
            max_instances=1,
        )
    return _scheduler


def start_scheduler():
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info(
            f"Scheduler started — fetch every {settings.fetch_interval_minutes} minutes"
        )


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
