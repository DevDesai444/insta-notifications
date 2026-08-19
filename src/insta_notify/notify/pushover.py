"""Pushover backend — alternative to ntfy.

Pushover's ``url`` field gives the notification a supplementary link that
opens in the default browser. It only carries one link, so extra links are
appended to the message body as plain text.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from ..models import Notification
from .base import Notifier

log = logging.getLogger(__name__)

API_URL = "https://api.pushover.net/1/messages.json"


class PushoverNotifier(Notifier):
    name = "pushover"

    def __init__(
        self,
        token: str,
        user: str,
        attach_images: bool = True,
        timeout: int = 15,
    ):
        self.token = token
        self.user = user
        self.attach_images = attach_images
        self.timeout = timeout

    def describe(self) -> str:
        return "pushover"

    def send(self, note: Notification) -> bool:
        if not (self.token and self.user):
            log.error("PUSHOVER_TOKEN/PUSHOVER_USER not set; cannot send")
            return False

        body = note.body
        extras = note.links[1:]
        if extras:
            body += "\n\nMore links:\n" + "\n".join(extras)

        data = {
            "token": self.token,
            "user": self.user,
            "title": note.title[:250],
            "message": body[:1024],
            # 1 = high priority: bypasses the user's quiet hours.
            "priority": 1 if note.priority >= 4 else 0,
        }
        if note.click_url:
            data["url"] = note.click_url
            data["url_title"] = "Open link"

        files = None
        local_image = Path(note.image_path) if note.image_path else None
        if self.attach_images and local_image and local_image.exists():
            try:
                files = {"attachment": (local_image.name, local_image.read_bytes(), "image/jpeg")}
            except OSError:
                files = None

        try:
            resp = requests.post(API_URL, data=data, files=files, timeout=self.timeout)
            resp.raise_for_status()
            return True
        except Exception as exc:
            log.error("pushover send failed: %s", exc)
            return False
