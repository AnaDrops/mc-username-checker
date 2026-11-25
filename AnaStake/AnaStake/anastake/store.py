"""SQLite history and resume positions."""
from __future__ import annotations

import sqlite3
import time


class Store:
    def __init__(self, path: str = "anastake.db"):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS results(
                name TEXT PRIMARY KEY, status TEXT, checked_at REAL, mode TEXT);
            CREATE TABLE IF NOT EXISTS positions(key TEXT PRIMARY KEY, position INTEGER);
        """)

    def record(self, name: str, status: str, mode: str, when: float | None = None) -> None:
        self.db.execute("INSERT OR REPLACE INTO results VALUES(?,?,?,?)",
                        (name, status, time.time() if when is None else when, mode))
        self.db.commit()

    def fresh(self, name: str, max_age_hours: float) -> bool:
        row = self.db.execute("SELECT status, checked_at FROM results WHERE name=?",
                              (name,)).fetchone()
        return bool(row) and row[0] != "ERROR" and time.time() - row[1] < max_age_hours * 3600

    def errors(self, mode: str) -> list[str]:
        rows = self.db.execute("SELECT name FROM results WHERE status='ERROR' AND mode=?", (mode,))
        return [r[0] for r in rows]

    def position(self, key: str) -> int:
        row = self.db.execute("SELECT position FROM positions WHERE key=?", (key,)).fetchone()
        return int(row[0]) if row else 0

    def save_position(self, key: str, position: int) -> None:
        # stored as text so very large indices do not overflow SQLite integers
        self.db.execute("INSERT OR REPLACE INTO positions VALUES(?,?)", (key, str(position)))
        self.db.commit()

    def recent(self, limit: int = 200) -> list[tuple]:
        return self.db.execute("SELECT name,status,checked_at,mode FROM results "
                               "ORDER BY checked_at DESC LIMIT ?", (limit,)).fetchall()

    def close(self) -> None:
        self.db.close()
