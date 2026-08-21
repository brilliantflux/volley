"""SC-3: ровно один опрос в день, catch-up после падения, закрытие зависших опросов."""

from datetime import datetime

from volley.domain import Poll
from volley.schedule import should_close_now, should_create_poll

TZ_NAIVE = None  # локальное время уже приведено к Europe/Sofia вызывающим кодом


def at(hour: int, minute: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 8, day, hour, minute)


def poll(day: str = "2026-08-21", **kw) -> Poll:
    return Poll(day=day, poll_id="p", message_id=1, **kw)


def test_creates_poll_at_nine():
    assert should_create_poll(at(9, 0), None) is True


def test_does_not_create_before_nine():
    assert should_create_poll(at(8, 59), None) is False


def test_catches_up_after_downtime():
    """Процесс лежал в 09:00 и поднялся в 11:00 — опрос всё равно нужен."""
    assert should_create_poll(at(11, 0), None) is True


def test_no_catch_up_too_late():
    """В 16:00 создавать опрос уже бессмысленно: игра в 18-00, закрытие в 17:00."""
    assert should_create_poll(at(16, 0), None) is False


def test_no_second_poll_when_today_already_has_one():
    assert should_create_poll(at(11, 0), poll()) is False
    assert should_create_poll(at(11, 0), poll(closed=True)) is False


def test_closes_open_poll_at_seventeen():
    assert should_close_now(at(17, 0), poll()) is True


def test_does_not_close_before_seventeen():
    assert should_close_now(at(16, 59), poll()) is False


def test_closes_yesterdays_forgotten_poll():
    """Бот лежал сутки: вчерашний опрос надо закрыть, не дожидаясь 17:00."""
    assert should_close_now(at(10, 0, day=22), poll(day="2026-08-21")) is True


def test_already_closed_poll_is_left_alone():
    assert should_close_now(at(17, 0), poll(closed=True)) is False
    assert should_close_now(at(10, 0, day=22), poll(day="2026-08-21", closed=True)) is False
