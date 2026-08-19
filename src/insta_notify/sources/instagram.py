"""Instagram source built on instagrapi (the private mobile API).

A note on why this needs a login: Instagram has no public API for reading a
third party's content, and **stories in particular are only visible to an
authenticated account**. So this needs an Instagram account of its own — use a
throwaway one that follows the target, never your main account, because
automated polling is against Instagram's terms of service and can get an
account restricted.

The session is saved to disk and reused. Logging in on every poll is the
fastest way to get an account flagged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from ..models import Item
from .base import Source

log = logging.getLogger(__name__)

# Hardware fingerprint only.
#
# Deliberately NO app_version / version_code / bloks_versioning_id here:
# instagrapi keeps those three in a matched set, and pinning a stale
# app_version that isn't in its table leaves bloks_versioning_id unset, which
# makes login fail with "Client.bloks_versioning_id is empty". Letting
# instagrapi fill the app profile keeps the trio self-consistent and current.
#
# Consistency across runs comes from the saved session file, which stores the
# whole device profile — a fingerprint that changes between runs looks like a
# hijacked account and triggers challenges.
DEVICE = {
    "android_version": 34,
    "android_release": "14",
    "dpi": "480dpi",
    "resolution": "1080x2400",
    "manufacturer": "Google/google",
    "device": "husky",
    "model": "Pixel 8 Pro",
    "cpu": "husky",
}


def _apply_device(client, device: dict) -> None:
    """set_device across instagrapi versions with and without the hydrate flag."""
    try:
        client.set_device(device, hydrate_app_profile=True)
    except TypeError:  # older instagrapi
        client.set_device(device)


class InstagramSource(Source):
    def __init__(
        self,
        username: str = "",
        password: str = "",
        target: str = "",
        session_file: Path | str = "session.json",
        totp_seed: str = "",
        sessionid: str = "",
        request_delay: tuple[int, int] = (1, 3),
    ):
        self.username = username
        self.password = password
        self.target = target.lstrip("@")
        self.session_file = Path(session_file)
        self.totp_seed = totp_seed
        self.sessionid = sessionid
        self.request_delay = request_delay
        self._client = None
        self._target_id: str | None = None

    @property
    def auth_mode(self) -> str:
        if self.sessionid:
            return "sessionid"
        if self.username and self.password:
            return "password"
        return "none"

    # ------------------------------------------------------------------ auth

    def connect(self) -> None:
        if self._client is not None:
            return

        from instagrapi import Client
        from instagrapi.exceptions import LoginRequired

        cl = Client()
        cl.delay_range = list(self.request_delay)

        loaded = False
        if self.session_file.exists():
            try:
                # Restores the saved device profile and uuids along with auth,
                # so don't call set_device after this and stomp them.
                cl.load_settings(self.session_file)
                loaded = True
            except Exception as exc:
                log.warning("could not load saved session (%s); logging in fresh", exc)

        if not loaded:
            _apply_device(cl, DEVICE)

        if self.auth_mode == "none":
            raise RuntimeError(
                "No Instagram credentials. Set IG_SESSIONID (recommended) or "
                "IG_USERNAME + IG_PASSWORD."
            )

        if loaded:
            try:
                self._resume(cl)
                cl.get_timeline_feed()  # proves the session is actually alive
                log.info("reused saved Instagram session (%s)", self.auth_mode)
            except LoginRequired:
                log.info("saved session expired; signing in again")
                self._fresh_login(cl)
            except Exception as exc:
                log.warning("session check failed (%s); signing in again", exc)
                self._fresh_login(cl)
        else:
            self._fresh_login(cl)

        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        cl.dump_settings(self.session_file)
        self._client = cl

    def _resume(self, client) -> None:
        """Re-assert credentials over a restored session file."""
        if self.auth_mode == "sessionid":
            # The cookie in the session file may be stale; the configured one
            # is the source of truth.
            client.login_by_sessionid(self.sessionid)
        else:
            client.login(
                self.username, self.password, verification_code=self._totp(client)
            )

    def _fresh_login(self, client) -> None:
        """Drop stale auth but keep the device and uuids we registered with."""
        old = client.get_settings() or {}
        device = old.get("device_settings") or DEVICE
        client.set_settings({})
        client.set_uuids(old.get("uuids", {}))
        _apply_device(client, device)

        if self.auth_mode == "sessionid":
            client.login_by_sessionid(self.sessionid)
            log.info("signed in as @%s via session cookie", client.username)
        else:
            client.login(
                self.username, self.password, verification_code=self._totp(client)
            )

    def _totp(self, client) -> str:
        if not self.totp_seed:
            return ""
        try:
            return client.totp_generate_code(self.totp_seed)
        except Exception as exc:
            log.warning("could not generate 2FA code: %s", exc)
            return ""

    @property
    def target_id(self) -> str:
        if self._target_id is None:
            self.connect()
            self._target_id = str(self._client.user_id_from_username(self.target))
            log.info("resolved @%s -> user id %s", self.target, self._target_id)
        return self._target_id

    def set_target_id(self, user_id: str) -> None:
        """Skip a lookup request by supplying a previously cached id."""
        if user_id:
            self._target_id = str(user_id)

    # ----------------------------------------------------------------- fetch

    def fetch_posts(self, limit: int = 5) -> list[Item]:
        self.connect()
        medias = self._client.user_medias(self.target_id, amount=limit)
        items = []
        for media in medias:
            try:
                items.append(self._media_to_item(media))
            except Exception as exc:
                log.warning("skipping unparseable post: %s", exc)
        return items

    def fetch_stories(self) -> list[Item]:
        self.connect()
        stories = self._client.user_stories(self.target_id)
        items = []
        for story in stories:
            try:
                items.append(self._story_to_item(story))
            except Exception as exc:
                log.warning("skipping unparseable story: %s", exc)
        return items

    # ---------------------------------------------------------------- mapping

    def _media_to_item(self, media) -> Item:
        code = _s(getattr(media, "code", ""))
        product = _s(getattr(media, "product_type", ""))
        media_type = getattr(media, "media_type", 1)
        is_reel = product == "clips"
        kind = "reel" if is_reel else "post"

        image_url = _s(getattr(media, "thumbnail_url", ""))
        if not image_url:
            resources = getattr(media, "resources", None) or []
            for res in resources:
                candidate = _s(getattr(res, "thumbnail_url", ""))
                if candidate:
                    image_url = candidate
                    break

        base = "reel" if is_reel else "p"
        return Item(
            kind=kind,
            item_id=f"post:{_s(getattr(media, 'pk', '')) or code}",
            username=self.target,
            taken_at=_dt(getattr(media, "taken_at", None)),
            permalink=f"https://www.instagram.com/{base}/{code}/" if code else "",
            caption=_s(getattr(media, "caption_text", "")),
            image_url=image_url,
            video_url=_s(getattr(media, "video_url", "")),
            is_video=media_type == 2,
            sticker_links=[],
        )

    def _story_to_item(self, story) -> Item:
        pk = _s(getattr(story, "pk", "")) or _s(getattr(story, "id", ""))
        media_type = getattr(story, "media_type", 1)
        return Item(
            kind="story",
            item_id=f"story:{pk}",
            username=self.target,
            taken_at=_dt(getattr(story, "taken_at", None)),
            permalink=f"https://www.instagram.com/stories/{self.target}/{pk}/",
            caption=_s(getattr(story, "caption_text", "")),
            image_url=_s(getattr(story, "thumbnail_url", "")),
            video_url=_s(getattr(story, "video_url", "")),
            is_video=media_type == 2,
            sticker_links=_story_links(story),
        )


# ------------------------------------------------------------------ helpers


def _s(value) -> str:
    """instagrapi mixes str, HttpUrl, and None across versions and fields."""
    if value is None:
        return ""
    return str(value)


def _dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _story_links(story) -> list[str]:
    """Pull swipe-up / link-sticker URLs out of a story object.

    instagrapi has moved this field around between versions, so try every
    shape rather than pinning to one.
    """
    urls: list[str] = []

    for link in getattr(story, "links", None) or []:
        for attr in ("webUri", "web_uri", "url"):
            value = _s(getattr(link, attr, ""))
            if value:
                urls.append(value)
                break
        else:
            if isinstance(link, str):
                urls.append(link)
            elif isinstance(link, dict):
                for key in ("webUri", "web_uri", "url"):
                    if link.get(key):
                        urls.append(_s(link[key]))
                        break

    for attr in ("story_cta_url", "link", "swipe_up_url"):
        value = _s(getattr(story, attr, ""))
        if value:
            urls.append(value)

    for cta in getattr(story, "story_cta", None) or []:
        links = cta.get("links") if isinstance(cta, dict) else None
        for link in links or []:
            if isinstance(link, dict) and link.get("webUri"):
                urls.append(_s(link["webUri"]))

    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique
