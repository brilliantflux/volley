"""SC-3: ровно один опрос в день, catch-up после падения, закрытие зависших опросов.

Решения здесь чистые: время приходит аргументом, а не читается из базы, — поэтому
тесты задают его явно и не зависят от того, что админ поменял в настройках.
"""

from datetime import datetime, time

from volley.domain import Poll
from volley.schedule import should_close_now, should_create_poll

POLL_AT = time(9, 0)
CLOSE_AT = time(16, 30)


def at(hour: int, minute: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 8, day, hour, minute)


def poll(day: str = "2026-08-21", **kw) -> Poll:
    return Poll(day=day, poll_id="p", message_id=1, **kw)


def test_creates_poll_at_nine():
    assert should_create_poll(at(9, 0), None, POLL_AT, CLOSE_AT) is True


def test_does_not_create_before_nine():
    assert should_create_poll(at(8, 59), None, POLL_AT, CLOSE_AT) is False


def test_catches_up_after_downtime():
    """Процесс лежал в 09:00 и поднялся в 11:00 — опрос всё равно нужен."""
    assert should_create_poll(at(11, 0), None, POLL_AT, CLOSE_AT) is True


def test_no_catch_up_too_late():
    """Опрос, который пора закрывать, создавать незачем: граница — время закрытия."""
    assert should_create_poll(at(16, 29), None, POLL_AT, CLOSE_AT) is True
    assert should_create_poll(at(16, 30), None, POLL_AT, CLOSE_AT) is False


def test_no_second_poll_when_today_already_has_one():
    assert should_create_poll(at(11, 0), poll(), POLL_AT, CLOSE_AT) is False
    assert should_create_poll(at(11, 0), poll(closed=True), POLL_AT, CLOSE_AT) is False


def test_closes_open_poll_at_close_time():
    assert should_close_now(at(16, 30), poll(), CLOSE_AT) is True


def test_does_not_close_before_close_time():
    assert should_close_now(at(16, 29), poll(), CLOSE_AT) is False


def test_closes_yesterdays_forgotten_poll():
    """Бот лежал сутки: вчерашний опрос надо закрыть, не дожидаясь его времени."""
    assert should_close_now(at(10, 0, day=22), poll(day="2026-08-21"), CLOSE_AT) is True


def test_already_closed_poll_is_left_alone():
    assert should_close_now(at(16, 30), poll(closed=True), CLOSE_AT) is False
    assert (
        should_close_now(at(10, 0, day=22), poll(day="2026-08-21", closed=True), CLOSE_AT)
        is False
    )
