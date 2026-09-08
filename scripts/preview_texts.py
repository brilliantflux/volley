#!/usr/bin/env python3
"""Показать все сообщения, которые бот может отправить в группу.

Тексты читают люди, поэтому их удобно вычитывать целиком, а не по одному в
тестах. Значения берутся из настроек на чистой базе — то есть ровно те, что
увидит группа сразу после установки. Запуск: .venv/bin/python scripts/preview_texts.py
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from volley import settings, texts  # noqa: E402
from volley.domain import LATER, PLUS, Outcome, Poll, Voter  # noqa: E402
from volley.store import Store  # noqa: E402

SQUAD = [Voter(n, f"Игрок {n}", f"player{n}" if n % 3 else None) for n in range(1, 9)]
FULL = SQUAD + [Voter(n, f"Игрок {n}", f"player{n}" if n % 3 else None) for n in range(9, 13)]


def show(title: str, body: str) -> None:
    print(f"\n\033[1m── {title}\033[0m\n{body}")


def main() -> None:
    store = Store(Path(tempfile.mkdtemp()) / "preview.db")
    game = settings.value(store, "game_time")
    close = settings.value(store, "close_time")
    poll_at = settings.value(store, "poll_time")
    later_option = settings.value(store, "option_later")

    poll = Poll(day="2026-08-21", poll_id="p", message_id=1)
    for voter in SQUAD[:5]:
        poll.apply(voter, [PLUS])
    poll.apply(Voter(20, "Игрок 20", "player20"), [LATER])

    print(
        "Опрос:",
        texts.poll_question(date(2026, 8, 21), game),
        "|",
        " / ".join(settings.options(store)),
    )
    show("приветствие при добавлении в группу", texts.greeting_text(poll_at, close))
    show("8-й плюс: кворум, без тегов", texts.quorum_text(SQUAD))
    show("12-й плюс: набор окончен, с тегами", texts.squad_full_text(FULL, game))
    show("закрытие, играем", texts.closing_text(Outcome(playing=True, plus=SQUAD, count=9), game))
    show(
        "закрытие, не собрались",
        texts.closing_text(Outcome(playing=False, plus=SQUAD[:3], count=3), game),
    )
    show(
        "закрытие, счёта от Telegram нет (бот лежал, админ закрыл сам)",
        texts.closing_text(Outcome(playing=False, plus=SQUAD[:3], count=None), game),
    )
    show("напоминание обещавшим ответить", texts.later_reminder_text(poll.later, close))
    show("/status", texts.status_text(poll, later_option))
    show("/status без опроса", texts.no_poll_text())
    show("/poll не сработал", texts.poll_not_created_text())
    show("команда не от админа", texts.not_admin_text())
    show("/settings", texts.settings_text(settings.current(store)))
    show("/set принял значение", texts.setting_saved_text("когда закрывать опрос", "18:00"))
    show("/set не понял значение", texts.setting_rejected_text("на часах не больше 23:59"))
    show(
        "/set не знает такой настройки",
        texts.setting_unknown_text("кворум", list(settings.BY_KEY)),
    )
    show("настройки до добавления в группу", texts.no_group_yet_text())
    show(
        "не смог закрыть опрос",
        texts.error_text("закрыть опрос", "Forbidden: not enough rights to manage poll"),
    )


if __name__ == "__main__":
    main()
