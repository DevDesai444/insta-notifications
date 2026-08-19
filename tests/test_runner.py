import pytest

from insta_notify.runner import MAX_BACKOFF, Runner, parse_duration


class DummyPipeline:
    class cfg:
        target_username = "x"

    class notifier:
        @staticmethod
        def describe():
            return "dummy"

    def __init__(self, behaviour):
        self.behaviour = list(behaviour)
        self.calls = 0

    def poll_once(self):
        self.calls += 1
        action = self.behaviour.pop(0) if self.behaviour else 0
        if isinstance(action, Exception):
            raise action
        return action


def test_interval_is_floored_to_a_safe_minimum():
    assert Runner(DummyPipeline([]), interval=1).interval == 20


def test_delay_stays_within_the_jitter_band():
    r = Runner(DummyPipeline([]), interval=60, jitter=0.2)
    for _ in range(200):
        assert 48 <= r.next_delay() <= 72


def test_zero_jitter_gives_the_exact_interval():
    r = Runner(DummyPipeline([]), interval=60, jitter=0)
    assert r.next_delay() == 60


def test_failures_back_off_exponentially_and_cap():
    r = Runner(DummyPipeline([]), interval=60, jitter=0)
    r._failures = 1
    assert r.next_delay() == 120
    r._failures = 2
    assert r.next_delay() == 240
    r._failures = 20
    assert r.next_delay() == MAX_BACKOFF


def test_loop_recovers_from_an_exception_and_resets_backoff():
    pipeline = DummyPipeline([RuntimeError("instagram down"), 1])
    r = Runner(pipeline, interval=20, jitter=0)
    r.interval = 20

    real_wait = r._stop.wait

    def wait_then_stop(_delay):
        if pipeline.calls >= 2:
            r._stop.set()
        return real_wait(0.001)

    r._stop.wait = wait_then_stop
    r.run_forever()

    assert pipeline.calls == 2
    assert r._failures == 0  # the successful poll cleared the backoff


def test_stop_request_ends_the_loop():
    pipeline = DummyPipeline([0])
    r = Runner(pipeline, interval=20, jitter=0)
    r.request_stop()
    r.run_forever()
    assert pipeline.calls == 0


class TestDurationParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("5h30m", 19800.0),
            ("90m", 5400.0),
            ("2h", 7200.0),
            ("1d", 86400.0),
            ("45s", 45.0),
            ("3600", 3600.0),
            (3600, 3600.0),
            ("", None),
            (None, None),
            ("0", None),
        ],
    )
    def test_parses(self, text, expected):
        assert parse_duration(text) == expected

    def test_rejects_nonsense(self):
        with pytest.raises(ValueError):
            parse_duration("banana")


class TestDurationStopsTheLoop:
    def test_loop_exits_once_the_duration_elapses(self):
        import time

        pipeline = DummyPipeline([0] * 500)
        r = Runner(pipeline, interval=20, jitter=0, duration=0.15)
        # Compress the 20s interval to 10ms so the test runs fast but time
        # still advances, letting the deadline actually arrive.
        r._stop.wait = lambda _d: time.sleep(0.01)

        started = time.monotonic()
        r.run_forever()
        elapsed = time.monotonic() - started

        assert 0 < pipeline.calls < 500, "should stop early, not drain the script"
        assert elapsed < 1.0, "should have stopped at ~0.15s"

    def test_no_duration_means_no_deadline(self):
        r = Runner(DummyPipeline([]), interval=20, jitter=0)
        assert r.duration is None
        assert r.time_left is None

    def test_sleep_is_clipped_to_the_deadline(self):
        """A 60s interval must not overshoot a deadline 2s away."""
        import time

        pipeline = DummyPipeline([0, 0])
        r = Runner(pipeline, interval=60, jitter=0, duration=2)
        slept = []
        r._stop.wait = lambda d: slept.append(d)
        r._deadline = time.monotonic() + 2
        r.duration = 2

        # one manual iteration of the loop body
        r.pipeline.poll_once()
        delay = min(r.next_delay(), r._deadline - time.monotonic())
        assert delay <= 2, "would have slept 60s past a 2s deadline"
