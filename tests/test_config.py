import pytest

from insta_notify.config import Config


def base(**kw):
    defaults = dict(
        target_username="zero2sudo",
        ig_username="u",
        ig_password="p",
        backend="ntfy",
        ntfy_topic="t",
    )
    defaults.update(kw)
    return Config(**defaults)


def test_a_complete_config_has_no_problems():
    assert base().validate() == []


def test_missing_ntfy_topic_is_reported():
    assert any("NTFY_TOPIC" in p for p in base(ntfy_topic="").validate())


def test_missing_instagram_credentials_reported_when_stories_are_on():
    problems = base(ig_username="", ig_password="").validate()
    assert any("IG_USERNAME" in p for p in problems)


def test_credentials_not_required_when_stories_are_off():
    cfg = base(ig_username="", ig_password="", check_stories=False)
    assert not any("IG_USERNAME" in p for p in cfg.validate())


def test_pushover_requires_both_keys():
    problems = base(backend="pushover", pushover_token="x").validate()
    assert any("PUSHOVER" in p for p in problems)


def test_unknown_backend_is_reported():
    assert any("Unknown NOTIFY_BACKEND" in p for p in base(backend="carrier-pigeon").validate())


def test_dangerously_fast_polling_is_reported():
    assert any("POLL_INTERVAL" in p for p in base(poll_interval=5).validate())


def test_vision_requires_a_key():
    assert base(vision_enabled=True, anthropic_api_key="").use_vision is False
    assert base(vision_enabled=True, anthropic_api_key="sk-x").use_vision is True
    assert base(vision_enabled=False, anthropic_api_key="sk-x").use_vision is False


def test_paths_derive_from_the_data_dir(tmp_path):
    cfg = base(data_dir=tmp_path)
    assert cfg.state_db == tmp_path / "state.db"
    assert cfg.session_file == tmp_path / "ig_session.json"
    assert cfg.media_dir == tmp_path / "media"


def test_from_env_reads_and_coerces(monkeypatch):
    monkeypatch.setenv("IG_TARGET_USERNAME", "@someone")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "45")
    monkeypatch.setenv("NOTIFY_ALL", "false")
    monkeypatch.setenv("KEYWORDS", "new grad, workday ,")
    cfg = Config.from_env(env_file=None)
    assert cfg.target_username == "someone"      # leading @ stripped
    assert cfg.poll_interval == 45
    assert cfg.notify_all is False
    assert cfg.keywords == ("new grad", "workday")


def test_from_env_survives_garbage_numbers(monkeypatch):
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "not-a-number")
    assert Config.from_env(env_file=None).poll_interval == 60
