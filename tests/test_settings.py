"""Настройки, которые админ меняет на ходу, и цикл расписания, читающий их из базы."""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pytest

from volley import settings
from volley.domain import Voter
from volley.schedule import run_loop, should_create_poll, tick
from volley.store import Store

TODAY = date(2026, 8, 21)


def at(hour: int, minute: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 8, day, hour, minute)


@dataclass
class FakeService:
    """Фейк ставит те же отметки, что настоящий сервис после удачной отправки.

    Без этого идемпотентность тика непроверяема: закрытие и напоминание
    защищены именно отметками в базе, а не памятью процесса.
    """

    store: Store | None = None
    calls: list[tuple] = field(default_factory=list)
    fail: bool = False

    async def open_poll(self, day):
        self.calls.append(("open_poll", day.isoformat()))
        if self.fail:
            raise RuntimeError("Telegram молчит")
        return True

    async def close_poll(self, poll):
        self.calls.append(("close_poll", poll.poll_id))
        if self.fail:
            raise RuntimeError("Telegram молчит")
        self.store.mark_closed(poll.poll_id)

    async def remind_later(self, poll):
        self.calls.append(("remind_later", poll.poll_id))
        self.store.mark_reminded(poll.poll_id)


def store_with_poll(tmp_path, votes: dict[int, int] | None = None) -> tuple[Store, str]:
    store = Store(tmp_path / "s.db")
    store.add_poll(day=TODAY.isoformat(), poll_id="pid", message_id=1)
    for user_id, option in (votes or {}).items():
        store.record_vote("pid", Voter(user_id=user_id, first_name=f"Игрок {user_id}"), [option])
    return store, "pid"


def run(coro):
    return asyncio.run(coro)


# --- значения: дефолт из кода, переопределение из базы ----------------------


def test_default_comes_from_config(tmp_path):
    store = Store(tmp_path / "s.db")
    assert settings.value(store, "close_time") == "16:30"
    assert settings.value(store, "game_time") == "17:30"


def test_default_options_match_the_group_habit(tmp_path):
    store = Store(tmp_path / "s.db")
    assert settings.options(store) == ("Плюс", "Минус", "Ответ до 16-00")


def test_saved_value_wins_and_survives_reopen(tmp_path):
    store = Store(tmp_path / "s.db")
    settings.set_value(store, "close_time", "18-00")
    assert settings.value(store, "close_time") == "18:00"

    again = Store(tmp_path / "s.db")
    assert settings.value(again, "close_time") == "18:00"


def test_time_is_normalized_whatever_the_admin_typed(tmp_path):
    store = Store(tmp_path / "s.db")
    for typed in ("17-30", "17:30", " 17.30 "):
        settings.set_value(store, "close_time", typed)
        assert settings.value(store, "close_time") == "17:30"


def test_garbage_is_refused_and_nothing_is_written(tmp_path):
    store = Store(tmp_path / "s.db")
    with pytest.raises(ValueError):
        settings.set_value(store, "close_time", "вечером")
    assert settings.value(store, "close_time") == "16:30"


def test_impossible_clock_time_is_refused(tmp_path):
    store = Store(tmp_path / "s.db")
    with pytest.raises(ValueError):
        settings.set_value(store, "close_time", "25:00")
    with pytest.raises(ValueError):
        settings.set_value(store, "close_time", "12:60")


def test_unknown_key_is_refused(tmp_path):
    store = Store(tmp_path / "s.db")
    with pytest.raises(KeyError):
        settings.set_value(store, "кворум", "5")


def test_option_longer_than_telegram_allows_is_refused(tmp_path):
    """Вариант ответа длиннее 100 символов Telegram не примет — ловим до отправки."""
    store = Store(tmp_path / "s.db")
    with pytest.raises(ValueError):
        settings.set_value(store, "option_later", "я" * 101)
    settings.set_value(store, "option_later", "я" * 100)


def test_empty_option_is_refused(tmp_path):
    store = Store(tmp_path / "s.db")
    with pytest.raises(ValueError):
        settings.set_value(store, "option_plus", "   ")


def test_option_text_is_free_form(tmp_path):
    store = Store(tmp_path / "s.db")
    settings.set_value(store, "option_plus", "Буду 🏐")
    assert settings.value(store, "option_plus") == "Буду 🏐"


# --- расписание читает базу, а не константы --------------------------------


def test_tick_closes_by_the_stored_time(tmp_path):
    store, pid = store_with_poll(tmp_path)
    settings.set_value(store, "close_time", "12:00")
    service = FakeService(store=store)

    run(tick(service, store, at(12, 0)))
    assert service.calls == [("close_poll", pid)]


def test_tick_does_not_close_before_the_stored_time(tmp_path):
    store, _ = store_with_poll(tmp_path)
    settings.set_value(store, "close_time", "12:00")
    service = FakeService(store=store)

    run(tick(service, store, at(11, 59)))
    assert service.calls == []


def test_poll_time_change_moves_creation(tmp_path):
    store = Store(tmp_path / "s.db")
    settings.set_value(store, "poll_time", "11:00")
    service = FakeService(store=store)

    run(tick(service, store, at(10, 59)))
    assert service.calls == []

    run(tick(service, store, at(11, 0)))
    assert service.calls == [("open_poll", TODAY.isoformat())]


def test_catch_up_window_ends_at_closing(tmp_path):
    """Отдельной константы больше нет: опрос имеет смысл, пока его не пора закрывать."""
    store = Store(tmp_path / "s.db")
    poll_time = settings.time_value(store, "poll_time")
    close_time = settings.time_value(store, "close_time")

    assert should_create_poll(at(16, 29), None, poll_time, close_time) is True
    assert should_create_poll(at(16, 30), None, poll_time, close_time) is False


def test_change_applies_on_the_next_tick_without_a_restart(tmp_path):
    """Flow: админ сдвинул закрытие — ближайший тик уже работает по новому времени."""
    store, pid = store_with_poll(tmp_path)
    service = FakeService(store=store)
    now = at(13, 0)

    run(tick(service, store, now))
    assert service.calls == []

    settings.set_value(store, "close_time", "12:30")
    run(tick(service, store, now + timedelta(minutes=1)))
    assert service.calls == [("close_poll", pid)]


# --- напоминание: теперь идемпотентно --------------------------------------


def test_reminder_goes_out_once_even_if_the_tick_repeats(tmp_path):
    store, pid = store_with_poll(tmp_path, votes={5: 2})
    service = FakeService(store=store)

    run(tick(service, store, at(15, 45)))
    run(tick(service, store, at(15, 46)))

    assert service.calls == [("remind_later", pid)]


def test_reminder_waits_for_its_time(tmp_path):
    store, _ = store_with_poll(tmp_path, votes={5: 2})
    service = FakeService(store=store)

    run(tick(service, store, at(15, 44)))
    assert service.calls == []


def test_reminder_follows_the_stored_time(tmp_path):
    store, pid = store_with_poll(tmp_path, votes={5: 2})
    settings.set_value(store, "reminder_time", "10:00")
    service = FakeService(store=store)

    run(tick(service, store, at(10, 0)))
    assert service.calls == [("remind_later", pid)]


def test_no_one_promised_an_answer_no_reminder(tmp_path):
    store, _ = store_with_poll(tmp_path, votes={5: 0})
    service = FakeService(store=store)

    run(tick(service, store, at(15, 45)))
    assert service.calls == []


def test_closing_tick_does_not_also_remind(tmp_path):
    """В один тик опрос закрывается — напоминать в закрытом опросе уже некому."""
    store, pid = store_with_poll(tmp_path, votes={5: 2})
    service = FakeService(store=store)

    run(tick(service, store, at(16, 30)))
    assert service.calls == [("close_poll", pid)]


# --- цикл вместо cron ------------------------------------------------------


def test_loop_survives_a_failing_tick(tmp_path):
    """Своему циклу необработанное исключение стоило бы всего расписания навсегда."""
    store, _ = store_with_poll(tmp_path)
    settings.set_value(store, "close_time", "00:00")  # закрывать пора всегда
    service = FakeService(store=store, fail=True)

    async def scenario():
        task = asyncio.create_task(run_loop(service, store, interval=0))
        await asyncio.sleep(0.05)
        task.cancel()

    run(scenario())
    assert len(service.calls) > 1, "цикл остановился на первом же исключении"


def test_loop_sleeps_between_ticks(tmp_path):
    """Между тиками цикл спит: иначе он сожрёт процессор на пустом месте."""
    store = Store(tmp_path / "s.db")
    service = FakeService(store=store)
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *a, **kw):
        slept.append(delay)
        if len(slept) >= 2:
            raise asyncio.CancelledError
        await real_sleep(0)

    async def scenario():
        asyncio.sleep = fake_sleep
        try:
            with pytest.raises(asyncio.CancelledError):
                await run_loop(service, store)
        finally:
            asyncio.sleep = real_sleep

    run(scenario())
    assert slept and all(delay >= 30 for delay in slept)
