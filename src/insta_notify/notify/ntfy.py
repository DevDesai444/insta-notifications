"""ntfy.sh backend — the default.

Why ntfy for this job:
  * The iOS app receives over APNs, so delivery is effectively instant.
  * The ``click`` field makes tapping the notification open a URL in the
    phone's default browser — exactly the "tap it and land on the Workday
    page" behaviour that was asked for.
  * ``actions`` adds up to three labelled buttons, so a post carrying several
    links gives one button per link.
  * It's free and needs no account, so it keeps working after Instagram is
    deleted from the phone.

We publish with the JSON endpoint rather than the header-based one: headers
must be latin-1, and Instagram captions are full of emoji.
"""

from __future__ import annotations

import logging

import requests

from ..models import Notification
from .base import Notifier

log = logging.getLogger(__name__)

MAX_ACTIONS = 3  # ntfy's hard limit


class NtfyNotifier(Notifier):
    name = "ntfy"

    def __init__(
        self,
        server: str = "https://ntfy.sh",
        topic: str = "",
        token: str = "",
        default_priority: int = 5,
        attach_images: bool = True,
        timeout: int = 15,
    ):
        self.server = server.rstrip("/")
        self.topic = topic
        self.token = token
        self.default_priority = default_priority
        self.attach_images = attach_images
        self.timeout = timeout

    def describe(self) -> str:
        return f"ntfy ({self.server}/{self.topic})"

    def _payload(self, note: Notification) -> dict:
        payload: dict = {
            "topic": self.topic,
            "title": note.title[:250],
            "message": note.body[:3800],
            "priority": note.priority or self.default_priority,
        }
        if note.tags:
            payload["tags"] = note.tags
        if note.click_url:
            payload["click"] = note.click_url

        actions = []
        for i, link in enumerate(note.links[:MAX_ACTIONS]):
            explicit = note.link_labels[i] if i < len(note.link_labels) else ""
            actions.append(
                {
                    "action": "view",
                    "label": (explicit or _button_label(link))[:28],
                    "url": link,
                    "clear": False,
                }
            )
        if actions:
            payload["actions"] = actions

        if self.attach_images and note.image_url.startswith(("http://", "https://")):
            payload["attach"] = note.image_url

        return payload

    def send(self, note: Notification) -> bool:
        if not self.topic:
            log.error("NTFY_TOPIC is not set; cannot send")
            return False

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            resp = requests.post(
                self.server,
                json=self._payload(note),
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            log.error("ntfy publish failed: %s", exc)
            return False


def _button_label(url: str) -> str:
    """Short, human label for an action button (ntfy shows very little text)."""
    from urllib.parse import urlparse

    from ..extract.urls import guess_company, job_platform

    platform = job_platform(url)
    company = guess_company(url)
    if company and platform:
        return f"{company} ({platform})"[:28]
    if platform:
        return f"Open {platform}"[:28]

    # Two links on the same host would otherwise get identical captions, so
    # fall back to the last meaningful path segment to tell them apart.
    try:
        segments = [s for s in urlparse(url).path.split("/") if s]
    except ValueError:
        segments = []
    if segments:
        tail = segments[-1].rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
        if tail and not tail.isdigit():
            return tail.title()[:28]
    if company:
        return f"Open {company}"[:28]
    return "Open link"
