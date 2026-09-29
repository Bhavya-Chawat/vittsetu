"""SQLite database setup for structured scheme/partner/application data.

Kept separate from rag_core.py's ChromaDB store: this is for computable,
structured records (schemes, partners); ChromaDB stays scoped to full-text
RAG chat retrieval only.
"""

import logging
import os
from pathlib import Path
from sqlalchemy import bindparam, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = Path(__file__).resolve().parent
# VITTSETU_DB_PATH lets tests (and alternative deployments) point at another file.
DB_PATH = Path(os.environ.get("VITTSETU_DB_PATH", BASE_DIR / "vittsetu.db"))

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

logger = logging.getLogger(__name__)


def get_db():
    """FastAPI dependency: yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create missing tables, then add any columns missing from existing tables."""
    import models  # noqa: F401 (registers models on Base.metadata)
    Base.metadata.create_all(bind=engine)
    migrate()


def migrate(bind=None) -> list[str]:
    """Lightweight, additive-only schema migration (no Alembic).

    create_all() creates missing tables but never touches existing ones, so a
    vittsetu.db created before a model gained a column would otherwise break.
    For every model column absent from its table, this runs
    ``ALTER TABLE ... ADD COLUMN``. Scalar defaults become the column's SQL
    DEFAULT; callable defaults (e.g. ``default=list``) are backfilled into
    existing rows. SQLite can't add PRIMARY KEY/UNIQUE columns or NOT NULL
    ones without a default, so those constraints are dropped (and logged) —
    except that model indexes (including ``unique=True, index=True`` columns,
    which SQLAlchemy expresses as a UNIQUE INDEX) are created afterwards if
    missing, so uniqueness declared that way is still enforced.

    Never drops or alters existing columns. Returns the "table.column" names
    and "index:<name>" entries added.
    """
    bind = bind or engine
    added: list[str] = []
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                enforced_by_index = any(
                    index.unique and list(index.columns) == [column] for index in table.indexes
                )
                if column.primary_key or (column.unique and not enforced_by_index):
                    logger.warning(
                        "migrate: adding %s.%s without its PRIMARY KEY/UNIQUE constraint (unsupported by SQLite ALTER)",
                        table.name, column.name,
                    )
                col_type = column.type.compile(dialect=bind.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'

                default = column.default
                if default is not None and default.is_scalar:
                    literal = column.type.literal_processor(dialect=bind.dialect)
                    value = literal(default.arg) if literal else repr(default.arg)
                    ddl += f" DEFAULT {value}"
                    if not column.nullable:
                        ddl += " NOT NULL"
                elif not column.nullable:
                    logger.warning(
                        "migrate: adding %s.%s as nullable (SQLite can't add NOT NULL without a default)",
                        table.name, column.name,
                    )

                conn.execute(text(ddl))

                if default is not None and default.is_callable:
                    # SQLAlchemy wraps zero-arg callables to accept an execution context.
                    # Raw single-column UPDATE: table.update() would also set onupdate
                    # columns (e.g. updated_at) that may not have been added yet.
                    value = bindparam("value", default.arg(None), type_=column.type)
                    conn.execute(
                        text(f'UPDATE "{table.name}" SET "{column.name}" = :value WHERE "{column.name}" IS NULL')
                        .bindparams(value)
                    )

                added.append(f"{table.name}.{column.name}")
                logger.info("migrate: added column %s.%s", table.name, column.name)

            existing_indexes = {ix["name"] for ix in inspector.get_indexes(table.name)}
            for index in table.indexes:
                if index.name not in existing_indexes:
                    index.create(conn)
                    added.append(f"index:{index.name}")
                    logger.info("migrate: created index %s", index.name)

    return added
