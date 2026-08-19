from insta_notify.runner import MAX_BACKOFF, Runner


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
