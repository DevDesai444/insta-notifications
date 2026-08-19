"""Core data structures passed between the source, extractor, and notifiers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Item:
    """One piece of Instagram content: a feed post, a reel, or a story frame."""

    kind: str                      # "post" | "reel" | "story"
    item_id: str                   # stable, unique per piece of content
    username: str
    taken_at: datetime
    permalink: str = ""
    caption: str = ""
    image_url: str = ""            # still image, or the cover frame of a video
    video_url: str = ""
    is_video: bool = False
    # URLs Instagram gives us directly (link stickers, swipe-ups, bio links)
    sticker_links: list[str] = field(default_factory=list)

    @property
    def age_seconds(self) -> float:
        now = datetime.now(timezone.utc)
        taken = self.taken_at
        if taken.tzinfo is None:
            taken = taken.replace(tzinfo=timezone.utc)
        return (now - taken).total_seconds()

    @property
    def label(self) -> str:
        return {"post": "Post", "reel": "Reel", "story": "Story"}.get(
            self.kind, self.kind.title()
        )


@dataclass
class Extraction:
    """What we managed to pull out of an item — links plus a readable summary."""

    links: list[str] = field(default_factory=list)
    summary: str = ""
    image_text: str = ""
    is_job_related: bool = True
    company: str = ""
    role: str = ""
    source: str = "regex"          # "regex" | "vision" | "vision+regex"

    def merged_with(self, other: "Extraction") -> "Extraction":
        seen: set[str] = set()
        links: list[str] = []
        for url in [*self.links, *other.links]:
            if url not in seen:
                seen.add(url)
                links.append(url)
        return Extraction(
            links=links,
            summary=other.summary or self.summary,
            image_text=other.image_text or self.image_text,
            is_job_related=self.is_job_related or other.is_job_related,
            company=other.company or self.company,
            role=other.role or self.role,
            source="+".join(
                dict.fromkeys(p for p in (self.source, other.source) if p)
            ),
        )


@dataclass
class Notification:
    """A backend-agnostic push notification."""

    title: str
    body: str
    links: list[str] = field(default_factory=list)
    # Optional button captions, positionally matched to `links`. Left empty,
    # each button is captioned from its own URL.
    link_labels: list[str] = field(default_factory=list)
    click_url: str = ""            # what opens when the notification is tapped
    image_url: str = ""            # remote image, attached by URL (ntfy)
    image_path: str = ""           # local file, uploaded as multipart (Pushover)
    tags: list[str] = field(default_factory=list)
    priority: int = 5
