from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings


_engine = None
_SessionFactory = None


def get_engine():
    """Return the SQLAlchemy engine, creating it lazily if needed."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_size=5,
            echo=False,
        )
    return _engine


def create_session_factory() -> sessionmaker[Session]:
    """Return a sessionmaker bound to the engine."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionFactory


def ensure_runtime_schema() -> None:
    """补齐无迁移环境下运行期需要的新列。"""
    engine = get_engine()
    inspector = inspect(engine)
    if "knowledge_chunks" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
    dialect = engine.dialect.name
    indexed_at_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
    ddl_by_column = {
        "index_status": "ALTER TABLE knowledge_chunks ADD COLUMN index_status VARCHAR(32) DEFAULT 'pending'",
        "indexed_at": f"ALTER TABLE knowledge_chunks ADD COLUMN indexed_at {indexed_at_type}",
        "index_error": "ALTER TABLE knowledge_chunks ADD COLUMN index_error TEXT",
    }

    with engine.begin() as conn:
        for column, ddl in ddl_by_column.items():
            if column not in existing:
                conn.execute(text(ddl))
