"""Тексты для группы. Теги — только там, где пинг уместен.

Времена и варианты ответа приходят аргументами: их значение живёт в базе и
меняется админом на ходу, поэтому собственных копий здесь нет.
"""

from __future__ import annotations

import html
from datetime import date

from .domain import FULL_SQUAD, QUORUM, Outcome, Poll, Voter

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def dashed(clock: str) -> str:
    """«17:30» → «17-30»: так время игры пишут в самой группе."""
    return clock.replace(":", "-")


def poll_question(day: date, game_time: str) -> str:
    return f"{day:%d.%m} ({WEEKDAYS[day.weekday()]}) Игра {dashed(game_time)}"


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


def squad_full_text(plus: list[Voter], game_time: str) -> str:
    return (
        f"Набор окончен: {len(plus)} человек, играем в {dashed(game_time)} 🏐\n"
        f"{_mentions(plus)}\n"
        f"Замен нет, не опаздываем."
    )


def closing_text(outcome: Outcome, game_time: str) -> str:
    if outcome.playing:
        return (
            f"Опрос закрыт. Играем в {dashed(game_time)}, {outcome.total} человек 🏐\n"
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


def status_text(poll: Poll, later_option: str) -> str:
    head = (
        f"Опрос на {date.fromisoformat(poll.day):%d.%m}: "
        f"плюсов {len(poll.plus)} из {FULL_SQUAD}, "
        f"«{later_option}» — {len(poll.later)}."
    )
    return f"{head}\n{_names(poll.plus)}" if poll.plus else head


def later_reminder_text(later: list[Voter], close_time: str) -> str:
    """Напоминание считает от закрытия опроса: это единственный настоящий дедлайн."""
    return f"{_mentions(later)} — опрос закроется в {close_time}. Плюс или минус?"


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


def greeting_text(poll_time: str, close_time: str) -> str:
    return (
        "Привет! Теперь опрос на игру буду ставить я.\n"
        f"Каждый день в {poll_time} — новый опрос, закрою его при "
        f"{FULL_SQUAD} плюсах или в {close_time}.\n"
        f"При {QUORUM} плюсах напишу, что игра состоится.\n\n"
        "Чтобы это работало, мне нужны права администратора: отправлять опросы "
        "и закреплять сообщения.\n"
        "Команды для админов: /poll — опрос вне расписания, /close — закрыть "
        "досрочно, /status — сколько плюсов сейчас, /skip N — не ставить опрос N дней, /settings — что можно менять."
    )


def start_text() -> str:
    """Что это за бот — первому встречному в личке, одним экраном."""
    return (
        "Я веду опрос на волейбол: утром ставлю его в группе, днём закрываю и "
        "объявляю состав.\n\n"
        "Админам группы: /settings — что сейчас настроено, "
        "<code>/set ключ значение</code> — поменять время или вариант ответа, "
        "/status — сколько плюсов, /poll и /close — опрос вне расписания, <code>/skip N</code> — пауза в опросах на N дней."
    )


def not_admin_text() -> str:
    return "Эта команда только для админов группы."


def admin_check_failed_text() -> str:
    return "Не смог проверить права — Telegram не ответил. Попробуй ещё раз."


def no_group_yet_text() -> str:
    return "Меня ещё не добавили в группу — сначала туда, потом настройки."


# --- настройки --------------------------------------------------------------


def settings_text(rows: list[tuple]) -> str:
    """Что можно менять и что стоит сейчас. Ключ показываем: им же и задают."""
    lines = [f"<code>{setting.key}</code> — {setting.title}: {value}" for setting, value in rows]
    return "Настройки:\n" + "\n".join(lines) + "\n\n" + setting_usage_text()


def setting_usage_text() -> str:
    return (
        "Меняется по одной: <code>/set ключ значение</code>\n"
        "Например: <code>/set close_time 18:00</code> или "
        "<code>/set option_later Отвечу к обеду</code>"
    )


def setting_saved_text(title: str, value: str) -> str:
    """Про момент вступления в силу — честно: у времён он один, у текстов другой."""
    return (
        f"Готово, {title}: {value}.\n"
        f"Времена работают со следующей минуты, тексты — со следующего опроса: "
        f"уже висящий опрос Telegram переписать не даёт."
    )


def setting_unknown_text(key: str, known: list[str]) -> str:
    return f"Не знаю настройки «{html.escape(key)}». Есть: {', '.join(known)}."


def setting_rejected_text(reason: str) -> str:
    return f"Не принял: {reason}."


# --- пауза опросов ----------------------------------------------------------


def skip_usage_text() -> str:
    return (
        "Сколько дней не ставить опрос: <code>/skip 3</code>. "
        "<code>/skip 0</code> снимает паузу."
    )


def skip_saved_text(resume) -> str:
    return f"Ок. Следующий опрос - {resume:%d.%m}. Вручную можно в любой момент: /poll."


def skip_cancelled_text() -> str:
    return "Пауза снята, опросы идут по расписанию."
