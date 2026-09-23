"""SQLite database setup for structured scheme/partner/application data.

Kept separate from rag_core.py's ChromaDB store: this is for computable,
structured records (schemes, partners); ChromaDB stays scoped to full-text
RAG chat retrieval only.
"""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vittsetu.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables if they don't exist yet."""
    import models  # noqa: F401 (registers models on Base.metadata)
    Base.metadata.create_all(bind=engine)
