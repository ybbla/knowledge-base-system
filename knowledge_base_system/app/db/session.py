from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.engine import create_session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    factory = create_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
