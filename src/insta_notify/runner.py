"""The long-running loop.

Instagram gives no webhook for someone else's account, so "real time" here
means a tight polling loop. Two things keep that from getting the account
banned: a small random jitter on every interval (so the request pattern isn't
a metronome), and exponential backoff when Instagram starts erroring.
"""

from __future__ import annotations

import logging
import random
import re
import signal
import threading
import time

from .pipeline import Pipeline

log = logging.getLogger(__name__)

MAX_BACKOFF = 900  # 15 minutes

_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([smhd])", re.IGNORECASE)
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str | int | float | None) -> float | None:
    """'5h30m' -> 19800.0. A bare number is seconds. None/'' -> None (forever)."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    text = str(text).strip().lower()
    if not text:
        return None
    if text.isdigit():
        return float(text) or None
    total = 0.0
    matched = False
    for value, unit in _DURATION_RE.findall(text):
        total += float(value) * _UNITS[unit]
        matched = True
    if not matched:
        raise ValueError(f"could not read duration {text!r} (try '90m' or '5h30m')")
    return total or None


class Runner:
    def __init__(
        self,
        pipeline: Pipeline,
        interval: int,
        jitter: float = 0.2,
        duration: float | None = None,
    ):
        self.pipeline = pipeline
        self.interval = max(20, interval)
        self.jitter = max(0.0, min(jitter, 0.9))
        # Stop cleanly after this many seconds. Used by the GitHub Actions
        # watcher, which must exit before the runner's 6-hour job limit so it
        # can hand off to the next run instead of being killed mid-poll.
        self.duration = duration
        self._deadline: float | None = None
        self._stop = threading.Event()
        self._failures = 0

    @property
    def time_left(self) -> float | None:
        if self._deadline is None:
            return None
        return self._deadline - time.monotonic()

    def request_stop(self, *_args) -> None:
        log.info("stop requested; finishing current cycle")
        self._stop.set()

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self.request_stop)
            except (ValueError, OSError):  # not on the main thread
                pass

    def next_delay(self) -> float:
        if self._failures:
            backoff = min(self.interval * (2 ** self._failures), MAX_BACKOFF)
        else:
            backoff = self.interval
        spread = backoff * self.jitter
        return max(5.0, backoff + random.uniform(-spread, spread))

    def run_forever(self) -> None:
        if self.duration:
            self._deadline = time.monotonic() + self.duration
        log.info(
            "watching @%s every ~%ds via %s%s",
            self.pipeline.cfg.target_username,
            self.interval,
            self.pipeline.notifier.describe(),
            f" for {self.duration / 3600:.1f}h" if self.duration else "",
        )
        while not self._stop.is_set():
            if self._deadline is not None and time.monotonic() >= self._deadline:
                log.info("duration reached; exiting cleanly")
                break
            started = time.monotonic()
            try:
                sent = self.pipeline.poll_once()
                self._failures = 0
                if sent:
                    log.info("sent %d notification(s)", sent)
            except KeyboardInterrupt:
                self.request_stop()
                break
            except Exception as exc:
                self._failures += 1
                log.error(
                    "poll failed (%d in a row): %s", self._failures, exc, exc_info=True
                )

            elapsed = time.monotonic() - started
            delay = max(1.0, self.next_delay() - elapsed)
            # Never sleep past the deadline — exit on time, not one poll late.
            if self._deadline is not None:
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    log.info("duration reached; exiting cleanly")
                    break
                delay = min(delay, remaining)
            log.debug("next poll in %.0fs", delay)
            self._stop.wait(delay)
        log.info("stopped")
