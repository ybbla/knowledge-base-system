"""数据库引擎模块 — SQLAlchemy 引擎与会话工厂的惰性初始化。

同时负责运行期 Schema 补齐（兼容无迁移环境的旧表结构）。
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings


_engine = None
_SessionFactory = None


def get_engine():
    """惰性获取 SQLAlchemy 引擎实例（首次调用时创建）。"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_size=5,
            echo=False,
        )
    return _engine


def create_session_factory() -> sessionmaker[Session]:
    """惰性创建绑定到引擎的 sessionmaker（autocommit=False, autoflush=False）。"""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionFactory


def ensure_runtime_schema() -> None:
    """运行期补齐缺失的列和索引，兼容无 Alembic 迁移环境的旧表结构。

    检测 knowledge_chunks 表中是否存在已废弃的旧列（index_status、
    indexed_at、index_error），按需补建。同时为 documents 表创建
    去重查询所需的部分唯一索引和 source_uri 索引。
    """
    engine = get_engine()
    inspector = inspect(engine)
    if "knowledge_chunks" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
    dialect = engine.dialect.name
    indexed_at_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
    ddl_by_column = {
        # 以下列已废弃 — 仅用于向后兼容的 DDL，代码层不再读写
        "index_status": "ALTER TABLE knowledge_chunks ADD COLUMN index_status VARCHAR(32) DEFAULT 'pending'",
        "indexed_at": f"ALTER TABLE knowledge_chunks ADD COLUMN indexed_at {indexed_at_type}",
        "index_error": "ALTER TABLE knowledge_chunks ADD COLUMN index_error TEXT",
    }

    # 去重与增量更新所需索引（仅 PostgreSQL）
    if dialect == "postgresql" and "documents" in inspector.get_table_names():
        doc_columns = {col["name"] for col in inspector.get_columns("documents")}
        if "source_hash" in doc_columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source_hash_active "
                    "ON documents (source_hash) WHERE status = 'active'"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_documents_source_uri "
                    "ON documents (source_uri)"
                ))

    with engine.begin() as conn:
        for column, ddl in ddl_by_column.items():
            if column not in existing:
                conn.execute(text(ddl))
