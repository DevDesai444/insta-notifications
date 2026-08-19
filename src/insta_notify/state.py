"""SQLite-backed 'have I already sent this?' store.

Instagram hands us the same posts and stories on every poll, so the only thing
standing between the user and a notification every 60 seconds is this table.
It is deliberately durable (a file, not memory) so restarts don't re-notify.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    item_id    TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    notified_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS seen_notified_at ON seen (notified_at);
"""


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def has_seen(self, item_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen WHERE item_id = ? LIMIT 1", (item_id,)
        )
        return cur.fetchone() is not None

    def mark_seen(self, item_id: str, kind: str = "unknown") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen (item_id, kind, notified_at) VALUES (?, ?, ?)",
            (item_id, kind, time.time()),
        )
        self._conn.commit()

    def mark_many(self, pairs: list[tuple[str, str]]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO seen (item_id, kind, notified_at) VALUES (?, ?, ?)",
            [(item_id, kind, time.time()) for item_id, kind in pairs],
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]

    def get_meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self._conn.commit()

    def prune(self, older_than_days: int = 30) -> int:
        """Stories vanish after 24h; there is no point remembering them forever."""
        cutoff = time.time() - older_than_days * 86400
        cur = self._conn.execute("DELETE FROM seen WHERE notified_at < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
