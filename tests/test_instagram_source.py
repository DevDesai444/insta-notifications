"""Mapping tests against real instagrapi model objects.

These guard the field names this project reads out of instagrapi — the most
likely thing to silently break when that library is upgraded.
"""

from datetime import datetime, timezone

import pytest

instagrapi_types = pytest.importorskip("instagrapi.types")

from instagrapi.types import Media, Story, StoryLink, UserShort  # noqa: E402

from insta_notify.sources.instagram import InstagramSource  # noqa: E402

MEDIA_REQUIRED = dict(like_count=0, usertags=[], sponsor_tags=[])
STORY_REQUIRED = dict(
    sponsor_tags=[], mentions=[], hashtags=[], locations=[], stickers=[],
    medias=[], polls=[], links=[],
)


@pytest.fixture
def source():
    return InstagramSource("u", "p", "zero2sudo", "/tmp/session.json")


@pytest.fixture
def user():
    return UserShort(pk="1", username="zero2sudo")


def make_media(**kw):
    defaults = dict(
        pk="123", id="123_1", code="CxYz", taken_at=datetime.now(timezone.utc),
        media_type=1, product_type="feed", caption_text="", **MEDIA_REQUIRED,
    )
    defaults.update(kw)
    return Media(**defaults)


def make_story(**kw):
    defaults = dict(
        pk="555", id="555_1", code="S1", taken_at=datetime.now(timezone.utc),
        media_type=1, **STORY_REQUIRED,
    )
    defaults.update(kw)
    return Story(**defaults)


class TestPostMapping:
    def test_feed_post(self, source, user):
        item = source._media_to_item(
            make_media(user=user, caption_text="hi", thumbnail_url="https://cdn/t.jpg")
        )
        assert item.kind == "post"
        assert item.item_id == "post:123"
        assert item.permalink == "https://www.instagram.com/p/CxYz/"
        assert item.image_url == "https://cdn/t.jpg"
        assert item.is_video is False

    def test_reel_gets_the_reel_permalink(self, source, user):
        item = source._media_to_item(
            make_media(user=user, code="R1", media_type=2, product_type="clips")
        )
        assert item.kind == "reel"
        assert item.permalink == "https://www.instagram.com/reel/R1/"
        assert item.is_video is True

    def test_taken_at_is_timezone_aware(self, source, user):
        item = source._media_to_item(make_media(user=user))
        assert item.taken_at.tzinfo is not None
        assert item.age_seconds >= 0


class TestStoryMapping:
    def test_story_basics(self, source, user):
        item = source._story_to_item(
            make_story(user=user, thumbnail_url="https://cdn/s.jpg")
        )
        assert item.kind == "story"
        assert item.item_id == "story:555"
        assert item.permalink == "https://www.instagram.com/stories/zero2sudo/555/"
        assert item.image_url == "https://cdn/s.jpg"

    def test_link_sticker_is_read_from_webUri(self, source, user):
        item = source._story_to_item(
            make_story(user=user, links=[StoryLink(webUri="https://acme.com/apply")])
        )
        assert item.sticker_links == ["https://acme.com/apply"]

    def test_story_with_no_links(self, source, user):
        assert source._story_to_item(make_story(user=user)).sticker_links == []

    def test_stories_have_no_caption_field_and_that_is_handled(self, source, user):
        """Story carries no caption_text — the text lives in the image."""
        assert "caption_text" not in Story.model_fields
        assert source._story_to_item(make_story(user=user)).caption == ""


class TestPostIdsAreStableAndDistinct:
    def test_post_and_story_ids_never_collide(self, source, user):
        post = source._media_to_item(make_media(user=user, pk="777"))
        story = source._story_to_item(make_story(user=user, pk="777"))
        assert post.item_id != story.item_id


class TestDeviceProfile:
    """Regression guard for the login-blocking bug this project hit.

    Pinning a stale ``app_version`` that isn't in instagrapi's APP_SETTINGS
    table leaves ``bloks_versioning_id`` unset, and login then dies with
    "Client.bloks_versioning_id is empty (hash is expected)". The device dict
    must therefore carry hardware fields only.
    """

    def test_device_dict_carries_no_app_profile_fields(self):
        from insta_notify.sources.instagram import DEVICE

        for key in ("app_version", "version_code", "bloks_versioning_id"):
            assert key not in DEVICE, (
                f"{key} must not be pinned — instagrapi keeps the app profile "
                "trio consistent on its own"
            )

    def test_applying_the_device_yields_a_usable_login_profile(self):
        from instagrapi import Client

        from insta_notify.sources.instagram import DEVICE, _apply_device

        client = Client()
        _apply_device(client, DEVICE)

        assert client.bloks_versioning_id, "login would fail without this"
        assert client.device_settings.get("app_version")
        assert client.device_settings.get("version_code")
        # our hardware choices survived
        assert client.device_settings["model"] == DEVICE["model"]

    def test_a_stale_app_version_would_have_broken_login(self):
        """Proves the guard above is testing something real.

        This is the exact device dict this project shipped with first: a full
        but stale app_version/version_code pair. It gets far enough to build a
        user agent, then leaves bloks_versioning_id empty and login dies.
        """
        from instagrapi import Client

        from insta_notify.sources.instagram import DEVICE, _apply_device

        client = Client()
        _apply_device(
            client,
            {**DEVICE, "app_version": "269.0.0.18.75", "version_code": "314665256"},
        )
        assert not client.bloks_versioning_id
