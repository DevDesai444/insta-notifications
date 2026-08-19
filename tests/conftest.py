import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from insta_notify.config import Config          # noqa: E402
from insta_notify.models import Item, Notification  # noqa: E402
from insta_notify.notify.base import Notifier   # noqa: E402


class RecordingNotifier(Notifier):
    name = "recording"

    def __init__(self, succeed: bool = True):
        self.sent: list[Notification] = []
        self.succeed = succeed

    def send(self, note: Notification) -> bool:
        if self.succeed:
            self.sent.append(note)
        return self.succeed


@pytest.fixture
def notifier():
    return RecordingNotifier()


@pytest.fixture
def cfg(tmp_path):
    return Config(
        target_username="zero2sudo",
        backend="console",
        data_dir=tmp_path,
        seed_on_first_run=False,
        notify_all=True,
        vision_enabled=False,
        attach_images=False,
    )


def make_item(**kwargs) -> Item:
    defaults = dict(
        kind="post",
        item_id="post:1",
        username="zero2sudo",
        taken_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        permalink="https://www.instagram.com/p/ABC/",
        caption="",
    )
    defaults.update(kwargs)
    return Item(**defaults)
