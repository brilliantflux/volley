"""Один «тик» расписания: он же старт после простоя, он же опрос, он же закрытие."""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time

from volley.schedule import tick
from volley.store import Store


@dataclass
class FakeService:
    calls: list[tuple] = field(default_factory=list)

    async def open_poll(self, day, announce_errors=True):
        self.calls.append(("open_poll", day.isoformat()))
        return True

    async def close_poll(self, poll):
        self.calls.append(("close_poll", poll.poll_id))

    async def remind_later(self, poll):
        self.calls.append(("remind_later", poll.poll_id if poll else None))


def at(hour, minute=0, day=21):
    return datetime(2026, 8, day, hour, minute)


def run(coro):
    return asyncio.run(coro)


def test_tick_at_nine_creates_poll(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    run(tick(service, store, at(9)))
    assert service.calls == [("open_poll", "2026-08-21")]


def test_tick_at_closing_time_closes_todays_poll(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=1)
    run(tick(service, store, at(16, 30)))
    assert service.calls == [("close_poll", "pid1")]


def test_tick_at_noon_does_nothing_when_poll_is_open(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=1)
    run(tick(service, store, at(12)))
    assert service.calls == []


def test_tick_on_startup_after_downtime_creates_missed_poll(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    run(tick(service, store, at(11)))
    assert service.calls == [("open_poll", "2026-08-21")]


def test_tick_late_at_night_creates_nothing(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    run(tick(service, store, at(23)))
    assert service.calls == []


def test_tick_closes_yesterdays_poll_and_opens_todays(tmp_path):
    """Бот лежал сутки: вчерашний опрос закрыть, сегодняшний открыть."""
    store, service = Store(tmp_path / "s.db"), FakeService()
    store.add_poll(day="2026-08-20", poll_id="old", message_id=1)
    run(tick(service, store, at(10, 0, day=21)))

    assert service.calls == [("close_poll", "old"), ("open_poll", "2026-08-21")]



# --- /skip: отложенные опросы ----------------------------------------------


def test_skip_blocks_the_poll_until_the_resume_day(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    store.set_setting("skip_until", "2026-08-23")
    run(tick(service, store, at(9, day=21)))
    run(tick(service, store, at(9, day=22)))
    assert service.calls == []


def test_poll_resumes_on_the_first_allowed_day(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    store.set_setting("skip_until", "2026-08-23")
    run(tick(service, store, at(9, day=23)))
    assert service.calls == [("open_poll", "2026-08-23")]


def test_corrupt_skip_value_means_no_skip(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    store.set_setting("skip_until", "завтра")
    run(tick(service, store, at(9)))
    assert service.calls == [("open_poll", "2026-08-21")]


def test_skip_does_not_stop_closing_an_open_poll(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=1)
    store.set_setting("skip_until", "2026-08-25")
    run(tick(service, store, at(16, 30)))
    assert service.calls == [("close_poll", "pid1")]


def test_skip_window_starts_today_while_a_poll_can_still_be_made():
    from volley.schedule import skip_resume_day

    close = time(16, 30)
    assert skip_resume_day(at(8), None, close, 3) == date(2026, 8, 24)


def test_skip_window_starts_tomorrow_when_today_has_a_poll_or_is_over():
    from volley.schedule import skip_resume_day

    close = time(16, 30)
    poll = object()
    assert skip_resume_day(at(8), poll, close, 3) == date(2026, 8, 25)
    assert skip_resume_day(at(16, 30), None, close, 3) == date(2026, 8, 25)
