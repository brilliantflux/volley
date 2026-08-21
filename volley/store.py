"""Состояние бота в SQLite: опросы, голоса, chat_id. Переживает рестарт процесса."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .domain import Poll, Voter

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS polls (
    poll_id              TEXT PRIMARY KEY,
    day                  TEXT NOT NULL UNIQUE,
    message_id           INTEGER NOT NULL,
    closed               INTEGER NOT NULL DEFAULT 0,
    quorum_announced     INTEGER NOT NULL DEFAULT 0,
    close_error_notified INTEGER NOT NULL DEFAULT 0,
    telegram_plus_count  INTEGER
);
CREATE TABLE IF NOT EXISTS votes (
    poll_id    TEXT NOT NULL REFERENCES polls(poll_id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL,
    option     INTEGER NOT NULL,
    first_name TEXT NOT NULL,
    username   TEXT,
    PRIMARY KEY (poll_id, user_id)
);
"""


class Store:
    """Одна база на бота. UNIQUE(day) делает второй опрос за день невозможным."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """База уже работает на сервере: новые колонки досыпаем на месте.

        CREATE TABLE IF NOT EXISTS существующую таблицу не меняет, поэтому без
        этого шага живая база осталась бы со старой схемой.
        """
        self._ensure_column("polls", "telegram_plus_count", "telegram_plus_count INTEGER")

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        present = {row["name"] for row in self._db.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            self._db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    # --- настройки ---------------------------------------------------------

    def _setting(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_setting(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def chat_id(self) -> int | None:
        value = self._setting("chat_id")
        return int(value) if value is not None else None

    def set_chat_id(self, chat_id: int) -> None:
        self._set_setting("chat_id", str(chat_id))

    def pinned_message_id(self) -> int | None:
        value = self._setting("pinned_message_id")
        return int(value) if value is not None else None

    def set_pinned_message_id(self, message_id: int) -> None:
        self._set_setting("pinned_message_id", str(message_id))

    # --- опросы -----------------------------------------------------------

    def add_poll(self, day: str, poll_id: str, message_id: int) -> Poll | None:
        """Создаёт опрос дня. None, если опрос на этот день уже есть."""
        try:
            self._db.execute(
                "INSERT INTO polls (poll_id, day, message_id) VALUES (?, ?, ?)",
                (poll_id, day, message_id),
            )
        except sqlite3.IntegrityError:
            return None
        return self.poll_by_id(poll_id)

    def poll_for_day(self, day: str) -> Poll | None:
        return self._load("SELECT * FROM polls WHERE day = ?", (day,))

    def poll_by_id(self, poll_id: str) -> Poll | None:
        return self._load("SELECT * FROM polls WHERE poll_id = ?", (poll_id,))

    def open_polls(self) -> list[Poll]:
        rows = self._db.execute("SELECT * FROM polls WHERE closed = 0 ORDER BY day").fetchall()
        return [self._with_votes(row) for row in rows]

    def _load(self, sql: str, params: tuple) -> Poll | None:
        row = self._db.execute(sql, params).fetchone()
        return self._with_votes(row) if row else None

    def _with_votes(self, row: sqlite3.Row) -> Poll:
        poll = Poll(
            day=row["day"],
            poll_id=row["poll_id"],
            message_id=row["message_id"],
            closed=bool(row["closed"]),
            quorum_announced=bool(row["quorum_announced"]),
            close_error_notified=bool(row["close_error_notified"]),
            telegram_plus_count=row["telegram_plus_count"],
        )
        votes = self._db.execute(
            "SELECT user_id, option, first_name, username FROM votes "
            "WHERE poll_id = ? ORDER BY rowid",
            (poll.poll_id,),
        ).fetchall()
        for vote in votes:
            poll.votes[vote["user_id"]] = (
                vote["option"],
                Voter(
                    user_id=vote["user_id"],
                    first_name=vote["first_name"],
                    username=vote["username"],
                ),
            )
        return poll

    # --- голоса и флаги ---------------------------------------------------

    def record_vote(self, poll_id: str, voter: Voter, option_ids: list[int]) -> None:
        """Пустой option_ids — голос отозван, строка удаляется."""
        if self.poll_by_id(poll_id) is None:
            return
        if not option_ids:
            self._db.execute(
                "DELETE FROM votes WHERE poll_id = ? AND user_id = ?", (poll_id, voter.user_id)
            )
            return
        self._db.execute(
            "INSERT INTO votes (poll_id, user_id, option, first_name, username) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(poll_id, user_id) DO UPDATE SET "
            "option = excluded.option, first_name = excluded.first_name, "
            "username = excluded.username",
            (poll_id, voter.user_id, option_ids[0], voter.first_name, voter.username),
        )

    def _set_flag(self, poll_id: str, column: str) -> None:
        self._db.execute(f"UPDATE polls SET {column} = 1 WHERE poll_id = ?", (poll_id,))

    def save_telegram_plus_count(self, poll_id: str, count: int) -> None:
        self._db.execute(
            "UPDATE polls SET telegram_plus_count = ? WHERE poll_id = ?", (count, poll_id)
        )

    def mark_closed(self, poll_id: str) -> None:
        self._set_flag(poll_id, "closed")

    def mark_quorum_announced(self, poll_id: str) -> None:
        self._set_flag(poll_id, "quorum_announced")

    def mark_close_error_notified(self, poll_id: str) -> None:
        self._set_flag(poll_id, "close_error_notified")

