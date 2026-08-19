from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Notification


class Notifier(ABC):
    name: str = "notifier"

    @abstractmethod
    def send(self, note: Notification) -> bool:
        """Deliver one notification. Returns True on success."""

    def describe(self) -> str:
        return self.name
