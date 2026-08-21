"""Тексты для группы. Теги — только там, где пинг уместен."""

from __future__ import annotations

import html
from datetime import date

from .config import CLOSE_TIME, GAME_TIME, LATER_DEADLINE, POLL_TIME, REMINDER_LEAD
from .domain import FULL_SQUAD, QUORUM, Outcome, Poll, Voter

POLL_OPTIONS = ("Плюс", "Минус", f"Ответ до {LATER_DEADLINE:%H-%M}")
WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def poll_question(day: date) -> str:
    return f"{day:%d.%m} ({WEEKDAYS[day.weekday()]}) Игра {GAME_TIME}"


def plain_name(voter: Voter) -> str:
    """Имя без пинга: сообщения о кворуме не должны будить пол-группы."""
    return html.escape(voter.first_name)


def mention(voter: Voter) -> str:
    if voter.username:
        return f"@{voter.username}"
    return f'<a href="tg://user?id={voter.user_id}">{plain_name(voter)}</a>'


def _names(voters: list[Voter]) -> str:
    return ", ".join(plain_name(v) for v in voters)


def _mentions(voters: list[Voter]) -> str:
    return ", ".join(mention(v) for v in voters)


def quorum_text(plus: list[Voter]) -> str:
    return (
        f"Кворум есть — игра состоится 🏐\n"
        f"Плюсов: {len(plus)} из {FULL_SQUAD}\n"
        f"{_names(plus)}"
    )


def squad_full_text(plus: list[Voter]) -> str:
    return (
        f"Набор окончен: {len(plus)} человек, играем в {GAME_TIME} 🏐\n"
        f"{_mentions(plus)}\n"
        f"Замен нет, не опаздываем."
    )


def closing_text(outcome: Outcome) -> str:
    if outcome.playing:
        return (
            f"Опрос закрыт. Играем в {GAME_TIME}, {outcome.total} человек 🏐\n"
            f"{_mentions(outcome.plus)}"
        )
    if outcome.count is None:
        # Счёт только свой: часть голосов могла не дойти, пока бот был недоступен.
        # «Играем» из неполных данных сказать можно — своих плюсов не больше, чем
        # настоящих. «Игры нет» — нельзя, это может оказаться неправдой.
        return (
            f"Опрос закрыт. У меня отмечено плюсов: {outcome.total} из {QUORUM} — "
            f"на игру не хватает. Если голосовали, пока я был недоступен, "
            f"посмотрите сам опрос."
        )
    return f"Опрос закрыт. Плюсов {outcome.total} из {QUORUM} — игры сегодня нет."


def status_text(poll: Poll) -> str:
    head = (
        f"Опрос на {date.fromisoformat(poll.day):%d.%m}: "
        f"плюсов {len(poll.plus)} из {FULL_SQUAD}, "
        f"«ответ до 16-00» — {len(poll.later)}."
    )
    return f"{head}\n{_names(poll.plus)}" if poll.plus else head


def later_reminder_text(later: list[Voter]) -> str:
    minutes = int(REMINDER_LEAD.total_seconds() // 60)
    return (
        f"{_mentions(later)} — до {LATER_DEADLINE:%H-%M} осталось {minutes} минут. "
        f"Плюс или минус?"
    )


def no_poll_text() -> str:
    return "Открытого опроса нет."


def poll_not_created_text() -> str:
    return (
        "Опрос не создан: либо он на сегодня уже есть, либо мне не хватило прав. "
        "Посмотри /status."
    )


def error_text(action: str, error: str) -> str:
    return (
        f"⚠️ Не смог {action}: {html.escape(error)}\n"
        f"Сделайте это вручную — похоже, у бота не хватает прав администратора."
    )


def greeting_text() -> str:
    return (
        "Привет! Теперь опрос на игру буду ставить я.\n"
        f"Каждый день в {POLL_TIME:%H:%M} — новый опрос, закрою его при "
        f"{FULL_SQUAD} плюсах или в {CLOSE_TIME:%H:%M}.\n"
        f"При {QUORUM} плюсах напишу, что игра состоится.\n\n"
        "Чтобы это работало, мне нужны права администратора: отправлять опросы "
        "и закреплять сообщения.\n"
        "Команды для админов: /poll — опрос вне расписания, /close — закрыть "
        "досрочно, /status — сколько плюсов сейчас."
    )


def not_admin_text() -> str:
    return "Эта команда только для админов группы."


def admin_check_failed_text() -> str:
    return "Не смог проверить права — Telegram не ответил. Попробуй ещё раз."
