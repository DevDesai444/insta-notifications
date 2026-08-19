from insta_notify.state import StateStore


def test_marks_and_recalls(tmp_path):
    with StateStore(tmp_path / "s.db") as s:
        assert not s.has_seen("a")
        s.mark_seen("a", "post")
        assert s.has_seen("a")


def test_survives_reopen(tmp_path):
    path = tmp_path / "s.db"
    with StateStore(path) as s:
        s.mark_seen("a", "story")
    with StateStore(path) as s:
        assert s.has_seen("a")


def test_mark_seen_is_idempotent(tmp_path):
    with StateStore(tmp_path / "s.db") as s:
        s.mark_seen("a", "post")
        s.mark_seen("a", "post")
        assert s.count() == 1


def test_mark_many(tmp_path):
    with StateStore(tmp_path / "s.db") as s:
        s.mark_many([("a", "post"), ("b", "story")])
        assert s.has_seen("a") and s.has_seen("b")
        assert s.count() == 2


def test_meta_roundtrip_and_default(tmp_path):
    with StateStore(tmp_path / "s.db") as s:
        assert s.get_meta("missing", "fallback") == "fallback"
        s.set_meta("k", "v1")
        s.set_meta("k", "v2")  # upsert, not a duplicate-key error
        assert s.get_meta("k") == "v2"


def test_prune_removes_only_old_rows(tmp_path):
    import time

    path = tmp_path / "s.db"
    with StateStore(path) as s:
        s.mark_seen("old", "story")
        s._conn.execute(
            "UPDATE seen SET notified_at = ? WHERE item_id = 'old'",
            (time.time() - 40 * 86400,),
        )
        s._conn.commit()
        s.mark_seen("new", "story")
        assert s.prune(older_than_days=30) == 1
        assert not s.has_seen("old")
        assert s.has_seen("new")


def test_creates_parent_directory(tmp_path):
    with StateStore(tmp_path / "nested" / "deep" / "s.db") as s:
        s.mark_seen("a")
        assert s.has_seen("a")
