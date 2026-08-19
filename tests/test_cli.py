import argparse

import pytest

from insta_notify import cli
from insta_notify.config import Config


class Args(argparse.Namespace):
    def __init__(self, **kw):
        super().__init__(**{"quiet": False, **kw})


def cfg_with(**kw):
    defaults = dict(
        target_username="zero2sudo",
        backend="ntfy",
        ntfy_topic="topic",
        check_stories=True,
    )
    defaults.update(kw)
    return Config(**defaults)


class TestPreflight:
    def test_ready_when_a_session_cookie_is_present(self, monkeypatch):
        sent = []
        monkeypatch.setattr(cli, "build_notifier", lambda c: _Recorder(sent))
        assert cli.cmd_preflight(cfg_with(ig_sessionid="x" * 40), Args()) == 0
        assert sent == [], "no nudge needed when it's ready to go"

    def test_ready_when_a_password_is_present(self, monkeypatch):
        sent = []
        monkeypatch.setattr(cli, "build_notifier", lambda c: _Recorder(sent))
        cfg = cfg_with(ig_username="u", ig_password="p")
        assert cli.cmd_preflight(cfg, Args()) == 0

    def test_missing_instagram_auth_pushes_the_next_step(self, monkeypatch):
        sent = []
        monkeypatch.setattr(cli, "build_notifier", lambda c: _Recorder(sent))

        assert cli.cmd_preflight(cfg_with(), Args()) == 2, "2 = waiting on the user"

        assert len(sent) == 1
        note = sent[0]
        assert "IG_SESSIONID" in note.body
        assert note.click_url.endswith("/settings/secrets/actions/new")
        assert "sessionid" in note.body

    def test_quiet_skips_the_notification_but_keeps_the_code(self, monkeypatch):
        sent = []
        monkeypatch.setattr(cli, "build_notifier", lambda c: _Recorder(sent))
        assert cli.cmd_preflight(cfg_with(), Args(quiet=True)) == 2
        assert sent == [], "quiet runs must not spam the phone every 5 minutes"

    def test_broken_notification_config_is_a_hard_error(self, monkeypatch):
        sent = []
        monkeypatch.setattr(cli, "build_notifier", lambda c: _Recorder(sent))
        cfg = cfg_with(ntfy_topic="", ig_sessionid="x" * 40)
        assert cli.cmd_preflight(cfg, Args()) == 1, "1 = misconfigured, not just waiting"
        assert sent == []


class TestParser:
    @pytest.mark.parametrize(
        "argv",
        [
            ["run"],
            ["run", "--duration", "5h30m"],
            ["once"],
            ["doctor"],
            ["login"],
            ["selftest"],
            ["demo"],
            ["quickstart"],
            ["quickstart", "--force", "--no-test"],
            ["preflight"],
            ["preflight", "--quiet"],
        ],
    )
    def test_every_command_parses(self, argv):
        args = cli.build_parser().parse_args(argv)
        assert callable(args.func)

    def test_run_duration_defaults_to_none(self):
        assert cli.build_parser().parse_args(["run"]).duration is None


class _Recorder:
    def __init__(self, sink):
        self.sink = sink

    def send(self, note):
        self.sink.append(note)
        return True

    def describe(self):
        return "recorder"


class TestAuthFailureAlert:
    """A silent watcher is worse than a broken one — expiry must be audible."""

    def test_alert_names_the_cookie_when_using_a_session(self, monkeypatch):
        sent = []
        monkeypatch.setattr(cli, "build_notifier", lambda c: _Recorder(sent))
        cli._alert_auth_failure(
            cfg_with(ig_sessionid="x" * 40), RuntimeError("login_required")
        )
        assert len(sent) == 1
        note = sent[0]
        assert "sessionid" in note.body
        assert note.priority == 5, "this is urgent — nothing is being watched"
        assert note.link_labels[0] == "Update the secret"
        assert "login_required" in note.body, "the real cause should be visible"

    def test_alert_points_at_credentials_when_using_a_password(self, monkeypatch):
        sent = []
        monkeypatch.setattr(cli, "build_notifier", lambda c: _Recorder(sent))
        cli._alert_auth_failure(
            cfg_with(ig_username="u", ig_password="p"), RuntimeError("challenge")
        )
        assert "IG_USERNAME" in sent[0].body

    def test_a_broken_notifier_does_not_raise(self, monkeypatch):
        class Exploding:
            def send(self, note):
                raise RuntimeError("ntfy is down too")

            def describe(self):
                return "exploding"

        monkeypatch.setattr(cli, "build_notifier", lambda c: Exploding())
        # Must not raise: the caller is already handling a failure.
        cli._alert_auth_failure(cfg_with(ig_sessionid="x" * 40), RuntimeError("boom"))

    def test_long_error_text_is_truncated(self, monkeypatch):
        sent = []
        monkeypatch.setattr(cli, "build_notifier", lambda c: _Recorder(sent))
        cli._alert_auth_failure(cfg_with(ig_sessionid="x" * 40), RuntimeError("e" * 5000))
        assert len(sent[0].body) < 1000
