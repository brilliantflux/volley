"""Один «тик» расписания: он же старт после простоя, он же 09:00, он же 17:00."""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime

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


def test_tick_at_seventeen_closes_todays_poll(tmp_path):
    store, service = Store(tmp_path / "s.db"), FakeService()
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=1)
    run(tick(service, store, at(17)))
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


def test_scheduler_has_both_daily_jobs_and_forgives_a_late_start():
    """Пропущенный джоб с грацией в секунду стоил бы группе целого дня без опроса."""
    from volley.schedule import build_scheduler

    scheduler = build_scheduler(service=FakeService(), store=None)
    jobs = scheduler.get_jobs()

    assert all(job.misfire_grace_time >= 3600 for job in jobs)
    assert any("hour='9'" in str(job.trigger) for job in jobs)
    assert any("hour='17'" in str(job.trigger) for job in jobs)


def test_reminder_tick_takes_todays_poll(tmp_path):
    """Таймер в 15:45: взять сегодняшний опрос и напомнить обещавшим ответ."""
    from volley.schedule import remind_tick

    store, service = Store(tmp_path / "s.db"), FakeService()
    store.add_poll(day=date.today().isoformat(), poll_id="pid1", message_id=1)
    run(remind_tick(service, store))

    assert service.calls == [("remind_later", "pid1")]


def test_reminder_tick_without_a_poll_today_does_nothing(tmp_path):
    from volley.schedule import remind_tick

    store, service = Store(tmp_path / "s.db"), FakeService()
    run(remind_tick(service, store))
    assert service.calls == [("remind_later", None)]


def test_scheduler_also_wakes_up_for_the_reminder():
    from volley.schedule import build_scheduler

    jobs = build_scheduler(service=FakeService(), store=None).get_jobs()
    assert {job.name for job in jobs} == {"tick-09:00", "tick-15:45", "tick-17:00"}
