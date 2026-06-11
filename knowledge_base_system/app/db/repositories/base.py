from abc import ABC, abstractmethod


class BaseRepository(ABC):
    """Abstract base for repositories that need a session factory."""

    @abstractmethod
    def __init__(self, session_factory) -> None: ...
