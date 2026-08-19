from __future__ import annotations

from ..models import Notification
from .base import Notifier


class ConsoleNotifier(Notifier):
    """Prints instead of pushing — for dry runs and debugging."""

    name = "console"

    def send(self, note: Notification) -> bool:
        print("\n" + "=" * 64)
        print(f"  {note.title}")
        print("=" * 64)
        print(note.body)
        if note.click_url:
            print(f"\n  TAP -> {note.click_url}")
        for i, link in enumerate(note.links, 1):
            print(f"  [{i}] {link}")
        if note.image_url:
            print(f"  image url: {note.image_url}")
        if note.image_path:
            print(f"  image file: {note.image_path}")
        print("=" * 64 + "\n")
        return True
