"""Когда создавать, когда напоминать, когда закрывать.

Планировщика с расписанием здесь нет намеренно. Один цикл раз в минуту зовёт
идемпотентный `tick`, а тот каждый раз перечитывает времена из базы: поэтому
смена настройки админом применяется со следующей минуты, без перепланирования
джобов и без перезапуска процесса. Решения остаются чистыми функциями, время
приходит в них аргументом.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta

from . import config, settings
from .domain import Poll

log = logging.getLogger(__name__)

TICK_SECONDS = 60  # мельче не имеет смысла: настройки задаются с точностью до минуты


SKIP_KEY = "skip_until"  # не в settings.SETTINGS: через /set его менять нельзя


def skip_until(store) -> date | None:
    """Первый день, когда авто-опрос снова разрешён. Пусто и мусор — без паузы."""
    try:
        return date.fromisoformat(store.setting(SKIP_KEY) or "")
    except ValueError:
        return None


def skip_resume_day(now: datetime, today_poll: Poll | None, close_time: time, days: int) -> date:
    """Окно паузы начинается сегодня, если сегодняшний опрос ещё может появиться."""
    start = now.date()
    if today_poll is not None or now.time() >= close_time:
        start += timedelta(days=1)
    return start + timedelta(days=days)


def should_create_poll(
    now: datetime,
    today_poll: Poll | None,
    poll_time: time,
    close_time: time,
    skip_until: date | None = None,
) -> bool:
    """Опрос на сегодня нужен, если его ещё нет и день не прошёл.

    Catch-up после простоя: бот, поднявшийся в 11:00, всё равно создаёт опрос.
    Верхняя граница — время закрытия: опрос, который пора закрывать, создавать
    незачем. Отдельной константы на это больше нет, чтобы правка времени
    закрытия не оставляла рядом устаревшее число.
    """
    if today_poll is not None:
        return False
    if skip_until is not None and now.date() < skip_until:
        return False
    return poll_time <= now.time() < close_time


def should_close_now(now: datetime, poll: Poll, close_time: time) -> bool:
    """Закрываем открытый опрос в его время, а забытый с прошлых дней — сразу."""
    if poll.closed:
        return False
    if poll.day < now.date().isoformat():
        return True
    return now.time() >= close_time


def should_remind(now: datetime, poll: Poll | None, reminder_time: time) -> bool:
    """Напоминание уходит один раз за день и только тем, кто обещал ответить."""
    if poll is None or poll.closed or poll.reminded or not poll.later:
        return False
    return now.time() >= reminder_time


async def tick(service, store, now: datetime) -> None:
    """Один проход расписания. Идемпотентен: лишний вызов ничего не дублирует.

    Порядок важен: сначала закрываем, потом напоминаем. Иначе в тике, попавшем
    на время закрытия, группа получила бы и напоминание, и итог сразу за ним.
    """
    close_time = settings.time_value(store, "close_time")
    for poll in store.open_polls():
        if should_close_now(now, poll, close_time):
            await service.close_poll(poll)

    today = now.date().isoformat()
    poll = store.poll_for_day(today)
    if should_remind(now, poll, settings.time_value(store, "reminder_time")):
        await service.remind_later(poll)

    poll_time = settings.time_value(store, "poll_time")
    if should_create_poll(now, poll, poll_time, close_time, skip_until(store)):
        await service.open_poll(now.date())


async def run_loop(service, store, interval: float = TICK_SECONDS) -> None:
    """Единственный будильник бота.

    Исключение внутри тика гасится здесь: в отличие от планировщика, у своего
    цикла необработанная ошибка убила бы расписание навсегда и молча.
    """
    while True:
        try:
            await tick(service, store, datetime.now(config.TZ))
        except Exception:  # noqa: BLE001 — тик падает, расписание продолжает жить
            log.exception("тик расписания не прошёл, следующий будет через %s с", interval)
        await asyncio.sleep(interval)
