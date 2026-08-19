"""Push notification backends."""

from ..config import Config
from .base import Notifier
from .console import ConsoleNotifier
from .ntfy import NtfyNotifier
from .pushover import PushoverNotifier


def build_notifier(cfg: Config) -> Notifier:
    if cfg.backend == "ntfy":
        return NtfyNotifier(
            server=cfg.ntfy_server,
            topic=cfg.ntfy_topic,
            token=cfg.ntfy_token,
            default_priority=cfg.ntfy_priority,
            attach_images=cfg.attach_images,
        )
    if cfg.backend == "pushover":
        return PushoverNotifier(
            token=cfg.pushover_token,
            user=cfg.pushover_user,
            attach_images=cfg.attach_images,
        )
    return ConsoleNotifier()


__all__ = [
    "Notifier",
    "NtfyNotifier",
    "PushoverNotifier",
    "ConsoleNotifier",
    "build_notifier",
]
