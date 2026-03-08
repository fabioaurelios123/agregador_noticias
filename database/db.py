from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.models import Base
from config.settings import settings

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            settings.db_url,
            connect_args={"check_same_thread": False},
            echo=False,
        )
        Base.metadata.create_all(_engine)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


def get_db() -> Session:
    """FastAPI dependency that yields a database session."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize the database, create all tables, and apply incremental migrations."""
    engine = get_engine()
    # Incremental migrations for columns added after initial schema
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    with engine.connect() as conn:
        existing_cols = [c["name"] for c in insp.get_columns("episodes")]
        if "batch_run_id" not in existing_cols:
            conn.execute(text("ALTER TABLE episodes ADD COLUMN batch_run_id INTEGER REFERENCES batch_runs(id)"))
            conn.commit()
