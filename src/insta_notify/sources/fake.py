from __future__ import annotations

from ..models import Item
from .base import Source


class FakeSource(Source):
    """Scripted source used by the tests and by ``--demo``."""

    def __init__(self, posts: list[Item] | None = None, stories: list[Item] | None = None):
        self.posts = posts or []
        self.stories = stories or []
        self.connect_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1

    def fetch_posts(self, limit: int = 5) -> list[Item]:
        return self.posts[:limit]

    def fetch_stories(self) -> list[Item]:
        return list(self.stories)
