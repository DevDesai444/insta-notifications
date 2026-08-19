from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Item


class Source(ABC):
    """Something that can be polled for a user's latest posts and stories."""

    @abstractmethod
    def fetch_posts(self, limit: int = 5) -> list[Item]: ...

    @abstractmethod
    def fetch_stories(self) -> list[Item]: ...

    def connect(self) -> None:
        """Log in / warm up. Safe to call more than once."""
