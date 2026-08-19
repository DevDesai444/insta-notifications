from insta_notify.models import Notification
from insta_notify.notify.ntfy import NtfyNotifier


def build(**kw):
    defaults = dict(title="T", body="B", priority=5)
    defaults.update(kw)
    return Notification(**defaults)


def test_payload_matches_documented_schema():
    p = NtfyNotifier(topic="mytopic")._payload(
        build(links=["https://a.com/1"], click_url="https://a.com/1", tags=["x"])
    )
    assert p["topic"] == "mytopic"
    assert p["title"] == "T"
    assert p["message"] == "B"
    assert p["priority"] == 5
    assert p["tags"] == ["x"]
    assert p["click"] == "https://a.com/1"
    assert p["actions"][0] == {
        "action": "view",
        "label": "Open A",
        "url": "https://a.com/1",
        "clear": False,
    }


def test_actions_capped_at_ntfy_limit_of_three():
    links = [f"https://a{i}.com/x" for i in range(6)]
    p = NtfyNotifier(topic="t")._payload(build(links=links))
    assert len(p["actions"]) == 3


def test_no_actions_key_when_no_links():
    p = NtfyNotifier(topic="t")._payload(build())
    assert "actions" not in p


def test_action_labels_name_the_company_and_ats():
    p = NtfyNotifier(topic="t")._payload(
        build(links=["https://nvidia.wd5.myworkdayjobs.com/en-US/x/job/y"])
    )
    assert p["actions"][0]["label"] == "Nvidia (Workday)"


def test_attaches_remote_image_only():
    n = NtfyNotifier(topic="t", attach_images=True)
    assert n._payload(build(image_url="https://cdn/x.jpg"))["attach"] == "https://cdn/x.jpg"
    assert "attach" not in n._payload(build(image_path="/local/x.jpg"))


def test_attachment_can_be_disabled():
    n = NtfyNotifier(topic="t", attach_images=False)
    assert "attach" not in n._payload(build(image_url="https://cdn/x.jpg"))


def test_unicode_survives_because_we_use_json_not_headers():
    p = NtfyNotifier(topic="t")._payload(build(title="🔗 Nvidia · SWE", body="— ✅"))
    assert p["title"] == "🔗 Nvidia · SWE"
    assert p["body" if "body" in p else "message"] == "— ✅"


def test_send_without_topic_fails_loudly():
    assert NtfyNotifier(topic="").send(build()) is False


def test_long_fields_are_truncated_not_rejected():
    p = NtfyNotifier(topic="t")._payload(build(title="x" * 500, body="y" * 9000))
    assert len(p["title"]) <= 250
    assert len(p["message"]) <= 3800
