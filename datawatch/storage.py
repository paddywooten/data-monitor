"""SQLite persistence for per-minute usage samples.

One row per (minute, interface).  At the default 2 second poll interval the
database grows by roughly 700 KB / year per interface, so it stays tiny.
"""

from __future__ import annotations

import os
import sqlite3
import threading

from . import config as config_mod
from . import util

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    minute INTEGER NOT NULL,
    iface  TEXT    NOT NULL,
    rx     INTEGER NOT NULL DEFAULT 0,
    tx     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (minute, iface)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS totals (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    rx INTEGER NOT NULL DEFAULT 0,
    tx INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO totals (id, rx, tx) VALUES (1, 0, 0);

CREATE TABLE IF NOT EXISTS iface_totals (
    iface TEXT PRIMARY KEY,
    rx    INTEGER NOT NULL DEFAULT 0,
    tx    INTEGER NOT NULL DEFAULT 0
);
"""


class Storage:
    """Thread safe (single connection guarded by a lock) SQLite wrapper."""

    def __init__(self, path: str | None = None):
        self.path = path or config_mod.database_path()
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self.conn.executescript(_SCHEMA)

    # -- writes -----------------------------------------------------------
    def add_usage(self, minute: int, iface: str, rx: int, tx: int) -> None:
        """Record bytes transferred during ``minute`` (epoch, minute aligned)."""
        if rx <= 0 and tx <= 0:
            return
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                cur.execute(
                    "INSERT INTO usage (minute, iface, rx, tx) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (minute, iface) DO UPDATE SET "
                    "  rx = usage.rx + excluded.rx, tx = usage.tx + excluded.tx",
                    (int(minute), iface, int(rx), int(tx)),
                )
                cur.execute(
                    "UPDATE totals SET rx = rx + ?, tx = tx + ? WHERE id = 1",
                    (int(rx), int(tx)),
                )
                cur.execute(
                    "INSERT INTO iface_totals (iface, rx, tx) VALUES (?, ?, ?) "
                    "ON CONFLICT (iface) DO UPDATE SET "
                    "  rx = iface_totals.rx + excluded.rx, tx = iface_totals.tx + excluded.tx",
                    (iface, int(rx), int(tx)),
                )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise

    def state_set(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO state (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def state_get(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def state_set_float(self, key: str, value: float) -> None:
        self.state_set(key, repr(float(value)))

    def clear_notified(self) -> None:
        """Forget sent alerts (used when limits change)."""
        with self._lock:
            self.conn.execute("DELETE FROM state WHERE key LIKE 'notified:%'")

    def state_get_float(self, key: str, default: float = 0.0) -> float:
        raw = self.state_get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    # -- reads ------------------------------------------------------------
    def _iface_clause(self, ifaces: list[str] | None) -> tuple[str, list]:
        if ifaces is None:
            return "", []
        if not ifaces:
            return " AND 0", []
        marks = ",".join("?" for _ in ifaces)
        return f" AND iface IN ({marks})", list(ifaces)

    def totals(
        self, start: int, end: int, ifaces: list[str] | None = None
    ) -> tuple[int, int]:
        """Sum of (downloaded, uploaded) bytes in ``[start, end)``."""
        extra, params = self._iface_clause(ifaces)
        sql = (
            "SELECT COALESCE(SUM(rx), 0), COALESCE(SUM(tx), 0) FROM usage "
            "WHERE minute >= ? AND minute < ?" + extra
        )
        with self._lock:
            row = self.conn.execute(sql, [int(start), int(end)] + params).fetchone()
        return int(row[0]), int(row[1])

    def all_time(self) -> tuple[int, int]:
        """Lifetime totals (kept in a separate row so pruning never shrinks it)."""
        with self._lock:
            row = self.conn.execute("SELECT rx, tx FROM totals WHERE id = 1").fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def daily_series(
        self, start: int, end: int, ifaces: list[str] | None = None
    ) -> list[tuple[int, int, int]]:
        """``[(day_start, rx, tx), ...]`` for every local day in the range."""
        series: list[tuple[int, int, int]] = []
        day = util.start_of_day(start)
        end = int(end)
        safety = 0
        while day < end and safety < 5000:
            nxt = util.add_days(day, 1)
            rx, tx = self.totals(day, min(nxt, end), ifaces)
            series.append((day, rx, tx))
            day = nxt
            safety += 1
        return series

    def per_interface(
        self, start: int, end: int, ifaces: list[str] | None = None
    ) -> list[tuple[str, int, int]]:
        extra, params = self._iface_clause(ifaces)
        sql = (
            "SELECT iface, COALESCE(SUM(rx), 0), COALESCE(SUM(tx), 0) FROM usage "
            "WHERE minute >= ? AND minute < ?" + extra
            + " GROUP BY iface ORDER BY SUM(rx) + SUM(tx) DESC"
        )
        with self._lock:
            rows = self.conn.execute(sql, [int(start), int(end)] + params).fetchall()
        return [(r[0], int(r[1]), int(r[2])) for r in rows]

    def all_time_per_interface(self) -> dict[str, tuple[int, int]]:
        """Lifetime totals per interface (O(1) lookup, never pruned)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT iface, rx, tx FROM iface_totals ORDER BY rx + tx DESC"
            ).fetchall()
        return {r[0]: (int(r[1]), int(r[2])) for r in rows}

    def sample_count(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM usage").fetchone()
        return int(row[0]) if row else 0

    def first_sample(self) -> int | None:
        with self._lock:
            row = self.conn.execute("SELECT MIN(minute) FROM usage").fetchone()
        return int(row[0]) if row and row[0] is not None else None

    # -- maintenance ------------------------------------------------------
    def prune(self, before: int) -> int:
        """Drop samples older than ``before`` (epoch seconds)."""
        oldest_day = util.day_key(before)
        with self._lock:
            cur = self.conn.execute("DELETE FROM usage WHERE minute < ?", (int(before),))
            deleted = max(0, int(cur.rowcount or 0))
            # Peak records are keyed by day; forget anything before the cutoff.
            self.conn.execute(
                "DELETE FROM state WHERE (key LIKE 'peak_down:%' OR key LIKE 'peak_up:%') "
                "AND substr(key, instr(key, ':') + 1) < ?",
                (oldest_day,),
            )
        return deleted

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self.conn.close()
