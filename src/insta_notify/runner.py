"""The long-running loop.

Instagram gives no webhook for someone else's account, so "real time" here
means a tight polling loop. Two things keep that from getting the account
banned: a small random jitter on every interval (so the request pattern isn't
a metronome), and exponential backoff when Instagram starts erroring.
"""

from __future__ import annotations

import logging
import random
import signal
import threading
import time

from .pipeline import Pipeline

log = logging.getLogger(__name__)

MAX_BACKOFF = 900  # 15 minutes


class Runner:
    def __init__(self, pipeline: Pipeline, interval: int, jitter: float = 0.2):
        self.pipeline = pipeline
        self.interval = max(20, interval)
        self.jitter = max(0.0, min(jitter, 0.9))
        self._stop = threading.Event()
        self._failures = 0

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
        log.info(
            "watching @%s every ~%ds via %s",
            self.pipeline.cfg.target_username,
            self.interval,
            self.pipeline.notifier.describe(),
        )
        while not self._stop.is_set():
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
            log.debug("next poll in %.0fs", delay)
            self._stop.wait(delay)
        log.info("stopped")
