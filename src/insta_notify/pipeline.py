"""Poll -> extract -> notify.

One pass over the watched account: pull the latest posts and story frames,
drop anything already sent, pull links out of the caption and out of the image
itself, and push a notification whose tap target is the job link.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .config import Config
from .extract import media as media_utils
from .extract.urls import (
    clean_url,
    extract_urls,
    guess_company,
    is_job_link,
    job_platform,
    rank_links,
    stitch_broken_urls,
)
from .extract.vision import VisionExtractor
from .models import Extraction, Item, Notification
from .notify.base import Notifier
from .sources.base import Source
from .state import StateStore

log = logging.getLogger(__name__)

_SEEDED_KEY = "seeded"
_HEARTBEAT_KEY = "last_heartbeat"
_TARGET_ID_KEY = "target_user_id"


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        source: Source,
        notifier: Notifier,
        state: StateStore,
        vision: VisionExtractor | None = None,
    ):
        self.cfg = cfg
        self.source = source
        self.notifier = notifier
        self.state = state
        self.vision = vision
        self._vision_budget = cfg.vision_max_per_poll

    # ------------------------------------------------------------------ poll

    def poll_once(self) -> int:
        """Run one full cycle. Returns the number of notifications sent."""
        self._vision_budget = self.cfg.vision_max_per_poll
        items, reached_instagram = self._collect()

        # A poll where every fetch errored tells us nothing. Returning here
        # keeps a failed first poll from being mistaken for "nothing is
        # posted", which would arm the seed below against real content.
        if not reached_instagram:
            return 0

        cutoff = self.cfg.max_item_age_hours * 3600
        unseen = [i for i in items if not self.state.has_seen(i.item_id)]
        fresh = [i for i in unseen if i.age_seconds <= cutoff]

        # Mark items that are too old anyway, so we never look at them again.
        stale = [(i.item_id, i.kind) for i in unseen if i.age_seconds > cutoff]
        if stale:
            self.state.mark_many(stale)

        # First successful poll: remember what's already up rather than firing
        # a burst of notifications for content the user has likely seen.
        #
        # This has to run even when `fresh` is empty. An account with no story
        # currently up gives a first poll with nothing in it; if the flag
        # weren't set here, the next genuinely new post would be treated as
        # first-run content and silently swallowed instead of pushed — which
        # looks exactly like the watcher never starting.
        if self.cfg.seed_on_first_run and self.state.get_meta(_SEEDED_KEY) != "1":
            if fresh:
                self.state.mark_many([(i.item_id, i.kind) for i in fresh])
            self.state.set_meta(_SEEDED_KEY, "1")
            log.info(
                "first run: recorded %d existing item(s) without notifying. "
                "Anything posted from now on gets pushed.",
                len(fresh),
            )
            return 0

        self._maybe_heartbeat()

        if not fresh:
            return 0

        fresh.sort(key=lambda i: i.taken_at)

        sent = 0
        for item in fresh:
            try:
                if self._handle(item):
                    sent += 1
            except Exception as exc:
                log.exception("failed to handle %s: %s", item.item_id, exc)
                # Do not mark as seen — retry it on the next poll.
                continue
        media_utils.cleanup(self.cfg.media_dir)
        return sent

    def _maybe_heartbeat(self) -> None:
        """Prove the watcher is alive, so silence means 'he hasn't posted'."""
        if not self.cfg.heartbeat_hours:
            return

        now = time.time()
        try:
            last = float(self.state.get_meta(_HEARTBEAT_KEY, "0") or 0)
        except ValueError:
            last = 0.0

        if last == 0.0:
            # Don't ping the instant it starts; wait out a full interval first.
            self.state.set_meta(_HEARTBEAT_KEY, str(now))
            return

        if now - last < self.cfg.heartbeat_hours * 3600:
            return

        hours = (now - last) / 3600
        note = Notification(
            title=f"💚 Still watching @{self.cfg.target_username}",
            body=(
                f"No new posts in the last {hours:.0f}h — that's him being "
                f"quiet, not this being broken.\n\n"
                f"{self.state.count()} item(s) seen since setup."
            ),
            links=[],
            click_url=f"https://www.instagram.com/{self.cfg.target_username}/",
            tags=["green_heart"],
            priority=1,  # min: shows in the app, no sound, no banner
        )
        if self.notifier.send(note):
            self.state.set_meta(_HEARTBEAT_KEY, str(now))

    def _collect(self) -> tuple[list[Item], bool]:
        """Everything currently visible, plus whether we heard from Instagram.

        The flag distinguishes "he has posted nothing" from "the fetch blew
        up", which are the same empty list but must not be treated alike.
        """
        items: list[Item] = []
        attempted = 0
        succeeded = 0

        if self.cfg.check_stories:
            attempted += 1
            try:
                items.extend(self.source.fetch_stories())
                succeeded += 1
            except Exception as exc:
                log.error("could not fetch stories: %s", exc)

        if self.cfg.check_posts:
            attempted += 1
            try:
                items.extend(self.source.fetch_posts(limit=self.cfg.posts_per_poll))
                succeeded += 1
            except Exception as exc:
                log.error("could not fetch posts: %s", exc)

        return items, (succeeded > 0 or attempted == 0)

    # --------------------------------------------------------------- process

    def _handle(self, item: Item) -> bool:
        extraction = self.extract(item)

        if not self._should_notify(item, extraction):
            log.info("filtered out %s (not job related)", item.item_id)
            self.state.mark_seen(item.item_id, item.kind)
            return False

        note = self.build_notification(item, extraction)
        ok = self.notifier.send(note)
        if ok:
            self.state.mark_seen(item.item_id, item.kind)
            log.info(
                "notified: %s [%s] links=%d",
                note.title,
                extraction.source,
                len(note.links),
            )
        else:
            log.error("send failed for %s; will retry next poll", item.item_id)
        return ok

    def extract(self, item: Item) -> Extraction:
        """Links and context from the caption, the stickers, and the image."""
        text = stitch_broken_urls(item.caption)
        links = extract_urls(text)
        for raw in item.sticker_links:
            cleaned = clean_url(raw)
            if cleaned and cleaned not in links:
                links.append(cleaned)

        base = Extraction(
            links=rank_links(links),
            summary=item.caption.strip(),
            is_job_related=self._keyword_hit(item.caption),
            source="regex",
        )

        if not self._vision_wanted(item):
            return base

        local = media_utils.download(item.image_url, self.cfg.media_dir)
        if not local:
            return base
        prepared = media_utils.prepare_for_vision(local)
        if not prepared:
            return base

        self._vision_budget -= 1
        image_bytes, media_type = prepared
        result = self.vision.analyze(image_bytes, media_type, caption=item.caption)
        if result is None:
            return base

        merged = base.merged_with(result)
        merged.links = rank_links(merged.links)
        return merged

    def _vision_wanted(self, item: Item) -> bool:
        return bool(
            self.vision
            and self.vision.available
            and item.image_url
            and self._vision_budget > 0
        )

    def _keyword_hit(self, text: str) -> bool:
        if not self.cfg.keywords:
            return True
        lowered = (text or "").lower()
        return any(k in lowered for k in self.cfg.keywords)

    def _should_notify(self, item: Item, extraction: Extraction) -> bool:
        if self.cfg.notify_all:
            return True
        if extraction.links:
            return True
        return extraction.is_job_related or self._keyword_hit(
            f"{item.caption}\n{extraction.image_text}\n{extraction.summary}"
        )

    # ------------------------------------------------------------ formatting

    def build_notification(self, item: Item, extraction: Extraction) -> Notification:
        links = extraction.links
        job_links = [u for u in links if is_job_link(u)]
        primary = (job_links or links or [item.permalink])[0]

        title = self._title(item, extraction, job_links, links)
        body = self._body(item, extraction, links)

        tags = ["rotating_light"] if job_links else ["camera"]
        if item.kind == "story":
            tags.append("hourglass_flowing_sand")

        return Notification(
            title=title,
            body=body,
            links=links[:3],
            click_url=primary or item.permalink,
            image_url=item.image_url,
            image_path=str(self._local_image(item) or ""),
            tags=tags,
            priority=self.cfg.ntfy_priority,
        )

    def _title(
        self,
        item: Item,
        extraction: Extraction,
        job_links: list[str],
        links: list[str],
    ) -> str:
        company = extraction.company or (
            guess_company(job_links[0]) if job_links else ""
        )
        platform = job_platform(job_links[0]) if job_links else ""
        role = extraction.role

        if job_links:
            head = " · ".join(p for p in (company, role or "New grad role") if p)
            suffix = f" ({platform})" if platform else ""
            return f"🔗 {head}{suffix}"[:240]

        if links:
            return f"🔗 @{item.username} {item.label.lower()} with a link"[:240]

        return f"📣 @{item.username} posted a new {item.label.lower()}"[:240]

    def _body(self, item: Item, extraction: Extraction, links: list[str]) -> str:
        parts: list[str] = []

        text = extraction.summary or item.caption
        if extraction.image_text and extraction.image_text not in text:
            text = f"{text}\n\n{extraction.image_text}" if text else extraction.image_text
        if text:
            parts.append(_truncate(text.strip(), 700))

        if links:
            parts.append("")
            for url in links[:3]:
                platform = job_platform(url)
                marker = f"[{platform}] " if platform else ""
                parts.append(f"{marker}{url}")
        else:
            parts.append("")
            parts.append("(no link found — tap to open on Instagram)")

        parts.append("")
        parts.append(f"— {item.label} by @{item.username}")
        return "\n".join(parts).strip()

    def _local_image(self, item: Item) -> Path | None:
        if self.cfg.backend != "pushover" or not self.cfg.attach_images:
            return None
        return media_utils.download(item.image_url, self.cfg.media_dir)


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split()) if "\n" not in text else text
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
