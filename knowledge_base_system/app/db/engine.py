from sqlalchemy import create_engine
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
