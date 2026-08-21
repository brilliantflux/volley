"""Когда создавать и когда закрывать опрос. Чистые решения по локальному времени."""

from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config
from .config import CATCHUP_UNTIL, CLOSE_TIME, POLL_TIME, REMINDER_TIME
from .domain import Poll

# Пропущенный джоб APScheduler по умолчанию просто не выполняется (грация 1 с):
# заминка event loop в 09:00 стоила бы группе дня без опроса.
MISFIRE_GRACE = 3600


def should_create_poll(now: datetime, today_poll: Poll | None) -> bool:
    """Опрос на сегодня нужен, если его ещё нет и день не прошёл.

    Catch-up после простоя: бот, поднявшийся в 11:00, всё равно создаёт опрос.
    После CATCHUP_UNTIL смысла нет — закрытие в 17:00, игра в 18-00.
    """
    if today_poll is not None:
        return False
    return POLL_TIME <= now.time() < CATCHUP_UNTIL


def should_close_now(now: datetime, poll: Poll) -> bool:
    """Закрываем открытый опрос в 17:00, а забытый с прошлых дней — сразу."""
    if poll.closed:
        return False
    if poll.day < now.date().isoformat():
        return True
    return now.time() >= CLOSE_TIME


async def tick(service, store, now: datetime) -> None:
    """Один проход расписания: закрыть что пора, создать опрос если нужно.

    Одна и та же функция работает и как cron в 09:00, и как cron в 17:00,
    и как catch-up при старте — решения живут в should_* и не расходятся.
    """
    for poll in store.open_polls():
        if should_close_now(now, poll):
            await service.close_poll(poll)
    if should_create_poll(now, store.poll_for_day(now.date().isoformat())):
        await service.open_poll(now.date())


def build_scheduler(service, store) -> AsyncIOScheduler:
    """Три будильника: поставить опрос, напомнить обещавшим ответ, закрыть с итогом."""
    scheduler = AsyncIOScheduler(timezone=config.TZ)
    jobs = ((POLL_TIME, run_tick), (REMINDER_TIME, remind_tick), (CLOSE_TIME, run_tick))
    for moment, job in jobs:
        scheduler.add_job(
            job,
            CronTrigger(hour=moment.hour, minute=moment.minute, timezone=config.TZ),
            args=[service, store],
            name=f"tick-{moment:%H:%M}",
            misfire_grace_time=MISFIRE_GRACE,
        )
    return scheduler


async def remind_tick(service, store) -> None:
    """Напомнить тем, кто обещал ответить к дедлайну. Простой таймер, без catch-up."""
    today = datetime.now(config.TZ).date().isoformat()
    await service.remind_later(store.poll_for_day(today) if store else None)


async def run_tick(service, store) -> None:
    await tick(service, store, datetime.now(config.TZ))
