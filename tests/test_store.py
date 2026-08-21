"""SC-2: состояние переживает рестарт процесса, один опрос на день."""

from volley.domain import MINUS, PLUS, Voter
from volley.store import Store


def voter(n: int) -> Voter:
    return Voter(user_id=n, first_name=f"Игрок{n}", username=f"user{n}")


def test_chat_id_roundtrip(tmp_path):
    path = tmp_path / "state.db"
    Store(path).set_chat_id(-100500)
    assert Store(path).chat_id() == -100500


def test_chat_id_absent_before_bot_added(tmp_path):
    assert Store(tmp_path / "state.db").chat_id() is None


def test_poll_and_votes_survive_restart(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=42)
    for n in range(1, 6):
        store.record_vote("pid1", voter(n), [PLUS])

    reopened = Store(path)
    poll = reopened.poll_for_day("2026-08-21")
    assert poll is not None
    assert poll.message_id == 42
    assert poll.poll_id == "pid1"
    assert len(poll.plus) == 5


def test_retracted_vote_is_deleted_not_kept(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=42)
    store.record_vote("pid1", voter(1), [PLUS])
    store.record_vote("pid1", voter(1), [])

    assert Store(path).poll_for_day("2026-08-21").plus == []


def test_revote_overwrites_previous_option(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=42)
    store.record_vote("pid1", voter(1), [MINUS])
    store.record_vote("pid1", voter(1), [PLUS])

    poll = Store(path).poll_for_day("2026-08-21")
    assert [v.user_id for v in poll.plus] == [1]
    assert poll.voters_for(MINUS) == []


def test_one_poll_per_day(tmp_path):
    store = Store(tmp_path / "state.db")
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=1)
    assert store.add_poll(day="2026-08-21", poll_id="pid2", message_id=2) is None
    assert store.poll_for_day("2026-08-21").poll_id == "pid1"


def test_lookup_by_poll_id(tmp_path):
    store = Store(tmp_path / "state.db")
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=1)
    assert store.poll_by_id("pid1").day == "2026-08-21"
    assert store.poll_by_id("nope") is None


def test_flags_persist(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=1)
    store.mark_quorum_announced("pid1")
    store.mark_close_error_notified("pid1")

    poll = Store(path).poll_for_day("2026-08-21")
    assert poll.quorum_announced is True
    assert poll.close_error_notified is True
    assert poll.closed is False


def test_open_polls_exclude_closed(tmp_path):
    store = Store(tmp_path / "state.db")
    store.add_poll(day="2026-08-20", poll_id="old", message_id=1)
    store.add_poll(day="2026-08-21", poll_id="new", message_id=2)
    store.mark_closed("old")

    assert [p.poll_id for p in store.open_polls()] == ["new"]


def test_votes_of_one_poll_do_not_leak_into_another(tmp_path):
    store = Store(tmp_path / "state.db")
    store.add_poll(day="2026-08-20", poll_id="old", message_id=1)
    store.add_poll(day="2026-08-21", poll_id="new", message_id=2)
    store.record_vote("old", voter(1), [PLUS])
    store.record_vote("new", voter(2), [PLUS])

    assert [v.user_id for v in store.poll_by_id("old").plus] == [1]
    assert [v.user_id for v in store.poll_by_id("new").plus] == [2]


def test_vote_for_unknown_poll_is_ignored(tmp_path):
    """Голос в старом опросе, о котором бот не знает, не должен ломать процесс."""
    store = Store(tmp_path / "state.db")
    store.record_vote("ghost", voter(1), [PLUS])
    assert store.poll_by_id("ghost") is None


def test_pinned_message_roundtrip(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    assert store.pinned_message_id() is None
    store.set_pinned_message_id(77)
    assert Store(path).pinned_message_id() == 77


def test_old_database_gets_the_new_column(tmp_path):
    """База уже живёт на сервере: новая колонка добавляется без потери данных."""
    import sqlite3

    path = tmp_path / "state.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE polls (
            poll_id TEXT PRIMARY KEY, day TEXT NOT NULL UNIQUE, message_id INTEGER NOT NULL,
            closed INTEGER NOT NULL DEFAULT 0, quorum_announced INTEGER NOT NULL DEFAULT 0,
            close_error_notified INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE votes (
            poll_id TEXT NOT NULL, user_id INTEGER NOT NULL, option INTEGER NOT NULL,
            first_name TEXT NOT NULL, username TEXT, PRIMARY KEY (poll_id, user_id));
        INSERT INTO settings VALUES ('chat_id', '-100777');
        INSERT INTO polls (poll_id, day, message_id) VALUES ('old', '2026-08-20', 5);
        INSERT INTO votes VALUES ('old', 1, 0, 'Первый', 'player1');
        """
    )
    old.commit()
    old.close()

    store = Store(path)
    assert store.chat_id() == -100777
    poll = store.poll_by_id("old")
    assert [v.first_name for v in poll.plus] == ["Первый"]
    assert poll.telegram_plus_count is None
    store.save_telegram_plus_count("old", 9)
    assert Store(path).poll_by_id("old").telegram_plus_count == 9
