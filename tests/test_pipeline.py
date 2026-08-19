from datetime import datetime, timedelta, timezone

import pytest

from conftest import RecordingNotifier, make_item
from insta_notify.models import Extraction
from insta_notify.pipeline import Pipeline
from insta_notify.sources.fake import FakeSource
from insta_notify.state import StateStore


def build(cfg, notifier, posts=(), stories=(), vision=None):
    state = StateStore(cfg.data_dir / "state.db")
    source = FakeSource(posts=list(posts), stories=list(stories))
    return Pipeline(cfg, source, notifier, state, vision=vision), state


class TestDeduplication:
    def test_same_item_notifies_only_once(self, cfg, notifier):
        item = make_item(caption="new grad role https://acme.com/jobs")
        pipe, state = build(cfg, notifier, posts=[item])
        assert pipe.poll_once() == 1
        assert pipe.poll_once() == 0
        assert len(notifier.sent) == 1
        state.close()

    def test_dedup_persists_across_restart(self, cfg, notifier):
        item = make_item()
        pipe, state = build(cfg, notifier, posts=[item])
        pipe.poll_once()
        state.close()

        pipe2, state2 = build(cfg, notifier, posts=[item])
        assert pipe2.poll_once() == 0
        state2.close()

    def test_a_new_item_still_gets_through(self, cfg, notifier):
        first = make_item(item_id="post:1")
        pipe, state = build(cfg, notifier, posts=[first])
        pipe.poll_once()
        pipe.source.posts.append(make_item(item_id="post:2"))
        assert pipe.poll_once() == 1
        state.close()


class TestFirstRunSeeding:
    def test_seeding_records_without_notifying(self, cfg, notifier):
        cfg.seed_on_first_run = True
        pipe, state = build(cfg, notifier, posts=[make_item(), make_item(item_id="post:2")])
        assert pipe.poll_once() == 0
        assert notifier.sent == []
        state.close()

    def test_content_after_seeding_does_notify(self, cfg, notifier):
        cfg.seed_on_first_run = True
        pipe, state = build(cfg, notifier, posts=[make_item()])
        pipe.poll_once()
        pipe.source.posts.append(make_item(item_id="post:new"))
        assert pipe.poll_once() == 1
        state.close()


class TestLinkHandling:
    def test_tap_target_is_the_job_link_not_instagram(self, cfg, notifier):
        item = make_item(caption="apply https://boards.greenhouse.io/stripe/jobs/9")
        pipe, state = build(cfg, notifier, posts=[item])
        pipe.poll_once()
        note = notifier.sent[0]
        assert note.click_url == "https://boards.greenhouse.io/stripe/jobs/9"
        assert "Stripe" in note.title
        state.close()

    def test_story_sticker_link_is_unwrapped_from_instagram_redirect(self, cfg, notifier):
        story = make_item(
            kind="story",
            item_id="story:1",
            sticker_links=[
                "https://l.instagram.com/?u=https%3A%2F%2Facme.wd5.myworkdayjobs.com"
                "%2Fen-US%2FSite%2Fjob%2FSWE_JR1&e=AT"
            ],
        )
        pipe, state = build(cfg, notifier, stories=[story])
        pipe.poll_once()
        note = notifier.sent[0]
        assert note.click_url == (
            "https://acme.wd5.myworkdayjobs.com/en-US/Site/job/SWE_JR1"
        )
        assert "Workday" in note.title
        state.close()

    def test_ats_link_ranks_above_an_incidental_link(self, cfg, notifier):
        item = make_item(
            caption="see https://linktr.ee/me and https://jobs.lever.co/figma/a"
        )
        pipe, state = build(cfg, notifier, posts=[item])
        pipe.poll_once()
        assert notifier.sent[0].click_url == "https://jobs.lever.co/figma/a"
        state.close()

    def test_no_link_falls_back_to_the_instagram_permalink(self, cfg, notifier):
        item = make_item(caption="just some advice about interviews")
        pipe, state = build(cfg, notifier, posts=[item])
        pipe.poll_once()
        note = notifier.sent[0]
        assert note.click_url == "https://www.instagram.com/p/ABC/"
        assert note.links == []
        state.close()

    def test_at_most_three_links_are_carried(self, cfg, notifier):
        caption = " ".join(f"https://site{i}.com/x" for i in range(6))
        pipe, state = build(cfg, notifier, posts=[make_item(caption=caption)])
        pipe.poll_once()
        assert len(notifier.sent[0].links) == 3
        state.close()


class TestReliability:
    def test_failed_send_is_retried_on_the_next_poll(self, cfg):
        failing = RecordingNotifier(succeed=False)
        item = make_item()
        pipe, state = build(cfg, failing, posts=[item])
        assert pipe.poll_once() == 0

        pipe.notifier = RecordingNotifier(succeed=True)
        assert pipe.poll_once() == 1
        state.close()

    def test_one_bad_item_does_not_stop_the_others(self, cfg, notifier, monkeypatch):
        good = make_item(item_id="post:good")
        bad = make_item(item_id="post:bad")
        pipe, state = build(cfg, notifier, posts=[bad, good])

        original = pipe.build_notification

        def explode(item, extraction):
            if item.item_id == "post:bad":
                raise RuntimeError("boom")
            return original(item, extraction)

        monkeypatch.setattr(pipe, "build_notification", explode)
        assert pipe.poll_once() == 1
        assert "@zero2sudo" in notifier.sent[0].body
        assert state.has_seen("post:good")
        # the broken one is left unmarked so the next poll retries it
        assert not state.has_seen("post:bad")
        state.close()

    def test_source_failure_does_not_raise(self, cfg, notifier):
        pipe, state = build(cfg, notifier, posts=[make_item()])

        def boom(*_a, **_k):
            raise RuntimeError("instagram is down")

        pipe.source.fetch_posts = boom
        assert pipe.poll_once() == 0
        state.close()

    def test_items_older_than_the_cutoff_are_skipped_and_remembered(self, cfg, notifier):
        cfg.max_item_age_hours = 24
        old = make_item(
            item_id="post:old",
            taken_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        pipe, state = build(cfg, notifier, posts=[old])
        assert pipe.poll_once() == 0
        assert state.has_seen("post:old")
        state.close()


class TestFiltering:
    def test_notify_all_lets_everything_through(self, cfg, notifier):
        cfg.notify_all = True
        cfg.keywords = ("new grad",)
        pipe, state = build(cfg, notifier, posts=[make_item(caption="cat picture")])
        assert pipe.poll_once() == 1
        state.close()

    def test_keyword_filter_drops_unrelated_content(self, cfg, notifier):
        cfg.notify_all = False
        cfg.keywords = ("new grad",)
        pipe, state = build(cfg, notifier, posts=[make_item(caption="cat picture")])
        assert pipe.poll_once() == 0
        assert state.has_seen("post:1")  # dropped for good, not retried forever
        state.close()

    def test_keyword_filter_keeps_matching_content(self, cfg, notifier):
        cfg.notify_all = False
        cfg.keywords = ("new grad",)
        pipe, state = build(
            cfg, notifier, posts=[make_item(caption="New Grad roles open")]
        )
        assert pipe.poll_once() == 1
        state.close()

    def test_any_link_survives_the_filter(self, cfg, notifier):
        cfg.notify_all = False
        cfg.keywords = ("new grad",)
        pipe, state = build(
            cfg, notifier, posts=[make_item(caption="https://jobs.lever.co/figma/a")]
        )
        assert pipe.poll_once() == 1
        state.close()


class TestVisionIntegration:
    def test_vision_links_are_merged_with_caption_links(self, cfg, notifier, monkeypatch):
        """The headline case: a Workday URL that exists only inside the image."""

        class StubVision:
            available = True

            def analyze(self, *_a, **_k):
                return Extraction(
                    links=["https://acme.wd5.myworkdayjobs.com/en-US/S/job/SWE_JR7"],
                    summary="Screenshot of an Acme new grad posting.",
                    image_text="Acme — New Grad Software Engineer",
                    is_job_related=True,
                    company="Acme",
                    role="New Grad SWE",
                    source="vision",
                )

        monkeypatch.setattr(
            "insta_notify.pipeline.media_utils.download", lambda *a, **k: "/tmp/x.jpg"
        )
        monkeypatch.setattr(
            "insta_notify.pipeline.media_utils.prepare_for_vision",
            lambda *a, **k: (b"fake", "image/jpeg"),
        )

        item = make_item(
            kind="story",
            item_id="story:img",
            caption="",
            image_url="https://cdn.example/story.jpg",
        )
        pipe, state = build(cfg, notifier, stories=[item], vision=StubVision())
        assert pipe.poll_once() == 1

        note = notifier.sent[0]
        assert note.click_url == (
            "https://acme.wd5.myworkdayjobs.com/en-US/S/job/SWE_JR7"
        )
        assert "Acme" in note.title and "New Grad SWE" in note.title
        assert "New Grad Software Engineer" in note.body
        state.close()

    def test_vision_budget_limits_calls_per_poll(self, cfg, notifier, monkeypatch):
        calls = {"n": 0}

        class CountingVision:
            available = True

            def analyze(self, *_a, **_k):
                calls["n"] += 1
                return Extraction(source="vision")

        monkeypatch.setattr(
            "insta_notify.pipeline.media_utils.download", lambda *a, **k: "/tmp/x.jpg"
        )
        monkeypatch.setattr(
            "insta_notify.pipeline.media_utils.prepare_for_vision",
            lambda *a, **k: (b"f", "image/jpeg"),
        )
        cfg.vision_max_per_poll = 2
        stories = [
            make_item(kind="story", item_id=f"story:{i}", image_url="https://cdn/x.jpg")
            for i in range(5)
        ]
        pipe, state = build(cfg, notifier, stories=stories, vision=CountingVision())
        pipe.poll_once()
        assert calls["n"] == 2
        assert len(notifier.sent) == 5  # all still notified, just without vision
        state.close()

    def test_vision_failure_falls_back_to_caption_links(self, cfg, notifier, monkeypatch):
        class BrokenVision:
            available = True

            def analyze(self, *_a, **_k):
                return None

        monkeypatch.setattr(
            "insta_notify.pipeline.media_utils.download", lambda *a, **k: "/tmp/x.jpg"
        )
        monkeypatch.setattr(
            "insta_notify.pipeline.media_utils.prepare_for_vision",
            lambda *a, **k: (b"f", "image/jpeg"),
        )
        item = make_item(
            caption="apply https://jobs.lever.co/figma/a",
            image_url="https://cdn/x.jpg",
        )
        pipe, state = build(cfg, notifier, posts=[item], vision=BrokenVision())
        assert pipe.poll_once() == 1
        assert notifier.sent[0].click_url == "https://jobs.lever.co/figma/a"
        state.close()


class TestFirstRunSeedingEdgeCases:
    """Regression guards for a bug that made the watcher look dead.

    The seed flag used to be set only when the first poll actually found
    something. An account with no story currently up gives an empty first
    poll, so the flag stayed unset — and the next genuinely new post was then
    treated as first-run content and silently swallowed.
    """

    def test_empty_first_poll_still_arms_the_seed(self, cfg, notifier):
        cfg.seed_on_first_run = True
        pipe, state = build(cfg, notifier, posts=[], stories=[])

        assert pipe.poll_once() == 0          # nothing up yet

        pipe.source.posts.append(make_item(item_id="post:the-first-real-one"))
        assert pipe.poll_once() == 1, "the first real post must be pushed, not seeded"
        assert len(notifier.sent) == 1
        state.close()

    def test_a_totally_failed_first_poll_does_not_arm_the_seed(self, cfg, notifier):
        """Otherwise a network blip at startup eats the next real post."""
        cfg.seed_on_first_run = True
        pipe, state = build(cfg, notifier, posts=[], stories=[])

        def boom(*_a, **_k):
            raise RuntimeError("instagram unreachable")

        pipe.source.fetch_posts = boom
        pipe.source.fetch_stories = boom
        assert pipe.poll_once() == 0

        # Instagram comes back, and there is already a post up.
        pipe.source = FakeSource(posts=[make_item(item_id="post:existing")])
        assert pipe.poll_once() == 0, "this poll is the real first one — it seeds"

        pipe.source.posts.append(make_item(item_id="post:brand-new"))
        assert pipe.poll_once() == 1
        state.close()

    def test_partial_failure_still_counts_as_reaching_instagram(self, cfg, notifier):
        cfg.seed_on_first_run = True
        pipe, state = build(cfg, notifier, posts=[make_item()], stories=[])

        def boom(*_a, **_k):
            raise RuntimeError("stories endpoint flaked")

        pipe.source.fetch_stories = boom
        assert pipe.poll_once() == 0          # seeds off the posts it did get
        pipe.source.posts.append(make_item(item_id="post:after"))
        assert pipe.poll_once() == 1
        state.close()

    def test_seeding_disabled_notifies_from_the_very_first_poll(self, cfg, notifier):
        cfg.seed_on_first_run = False
        pipe, state = build(cfg, notifier, posts=[make_item()])
        assert pipe.poll_once() == 1
        state.close()


class TestCollect:
    def test_reports_success_when_a_source_returns_nothing(self, cfg, notifier):
        pipe, state = build(cfg, notifier, posts=[], stories=[])
        items, ok = pipe._collect()
        assert items == [] and ok is True
        state.close()

    def test_reports_failure_when_every_source_raises(self, cfg, notifier):
        pipe, state = build(cfg, notifier)

        def boom(*_a, **_k):
            raise RuntimeError("down")

        pipe.source.fetch_posts = boom
        pipe.source.fetch_stories = boom
        items, ok = pipe._collect()
        assert items == [] and ok is False
        state.close()

    def test_reports_success_when_both_sources_are_switched_off(self, cfg, notifier):
        cfg.check_posts = False
        cfg.check_stories = False
        pipe, state = build(cfg, notifier, posts=[make_item()])
        items, ok = pipe._collect()
        assert items == [] and ok is True
        state.close()


class TestHeartbeat:
    """Without this, a dead watcher and a quiet account look identical."""

    def test_first_poll_records_the_baseline_without_pinging(self, cfg, notifier):
        cfg.heartbeat_hours = 24
        pipe, state = build(cfg, notifier, posts=[])
        pipe.poll_once()
        assert notifier.sent == [], "don't ping the moment it starts"
        assert state.get_meta("last_heartbeat") != ""
        state.close()

    def test_pings_once_the_interval_has_elapsed(self, cfg, notifier):
        import time

        cfg.heartbeat_hours = 24
        pipe, state = build(cfg, notifier, posts=[])
        pipe.poll_once()
        state.set_meta("last_heartbeat", str(time.time() - 25 * 3600))

        pipe.poll_once()
        assert len(notifier.sent) == 1
        note = notifier.sent[0]
        assert "Still watching" in note.title
        assert note.priority == 1, "a heartbeat must not buzz the phone"
        state.close()

    def test_does_not_ping_again_until_the_next_interval(self, cfg, notifier):
        import time

        cfg.heartbeat_hours = 24
        pipe, state = build(cfg, notifier, posts=[])
        pipe.poll_once()
        state.set_meta("last_heartbeat", str(time.time() - 25 * 3600))
        pipe.poll_once()
        pipe.poll_once()
        pipe.poll_once()
        assert len(notifier.sent) == 1
        state.close()

    def test_zero_disables_it(self, cfg, notifier):
        import time

        cfg.heartbeat_hours = 0
        pipe, state = build(cfg, notifier, posts=[])
        pipe.poll_once()
        state.set_meta("last_heartbeat", str(time.time() - 1000 * 3600))
        pipe.poll_once()
        assert notifier.sent == []
        state.close()

    def test_a_failed_heartbeat_send_is_retried(self, cfg):
        import time

        from conftest import RecordingNotifier

        cfg.heartbeat_hours = 24
        failing = RecordingNotifier(succeed=False)
        pipe, state = build(cfg, failing, posts=[])
        pipe.poll_once()
        stale = str(time.time() - 25 * 3600)
        state.set_meta("last_heartbeat", stale)

        pipe.poll_once()
        assert state.get_meta("last_heartbeat") == stale, "unsent means not recorded"

        pipe.notifier = RecordingNotifier(succeed=True)
        pipe.poll_once()
        assert len(pipe.notifier.sent) == 1
        state.close()

    def test_a_real_post_still_gets_through_alongside_a_heartbeat(self, cfg, notifier):
        import time

        cfg.heartbeat_hours = 24
        pipe, state = build(cfg, notifier, posts=[])
        pipe.poll_once()
        state.set_meta("last_heartbeat", str(time.time() - 25 * 3600))

        pipe.source.posts.append(make_item(caption="https://jobs.lever.co/figma/a"))
        assert pipe.poll_once() == 1
        titles = [n.title for n in notifier.sent]
        assert any("Still watching" in t for t in titles)
        assert any("Figma" in t for t in titles)
        state.close()
