from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    url = Column(Text, unique=True, nullable=False)
    content = Column(Text)
    summary = Column(Text)
    image_url = Column(Text)
    category = Column(Text, default="geral")
    score = Column(Float, default=0.0)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)
    processed = Column(Boolean, default=False)

    episodes = relationship("Episode", back_populates="article")

    def __repr__(self):
        return f"<Article id={self.id} source={self.source!r} title={self.title[:50]!r}>"


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    script = Column(Text)
    audio_path = Column(Text)
    video_path = Column(Text)
    duration_s = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    streamed = Column(Boolean, default=False)
    batch_run_id = Column(Integer, ForeignKey("batch_runs.id"), nullable=True)

    article = relationship("Article", back_populates="episodes")
    queue_entries = relationship("StreamQueue", back_populates="episode")

    def __repr__(self):
        return f"<Episode id={self.id} article_id={self.article_id} streamed={self.streamed}>"


class StreamQueue(Base):
    __tablename__ = "stream_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=False)
    scheduled_at = Column(DateTime)
    played_at = Column(DateTime)
    mode = Column(Text, default="live")

    episode = relationship("Episode", back_populates="queue_entries")

    def __repr__(self):
        return f"<StreamQueue id={self.id} episode_id={self.episode_id} mode={self.mode!r}>"


class BatchRun(Base):
    """Tracks a full production run: fetch → dedup → generate → concat → stream."""
    __tablename__ = "batch_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(Text, default="running")   # running | done | failed | cancelled
    category_filter = Column(Text, nullable=True)
    articles_fetched = Column(Integer, default=0)
    events_found = Column(Integer, default=0)
    episodes_generated = Column(Integer, default=0)
    master_video_path = Column(Text, nullable=True)
    stream_started = Column(Boolean, default=False)
    log = Column(Text, default="")

    def __repr__(self):
        return f"<BatchRun id={self.id} status={self.status!r} episodes={self.episodes_generated}>"
