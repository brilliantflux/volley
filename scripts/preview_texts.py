#!/usr/bin/env python3
"""Показать все сообщения, которые бот может отправить в группу.

Тексты читают люди, поэтому их удобно вычитывать целиком, а не по одному в
тестах. Запуск: .venv/bin/python scripts/preview_texts.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from volley import texts  # noqa: E402
from volley.domain import LATER, PLUS, Outcome, Poll, Voter  # noqa: E402

SQUAD = [Voter(n, f"Игрок {n}", f"player{n}" if n % 3 else None) for n in range(1, 9)]
FULL = SQUAD + [Voter(n, f"Игрок {n}", f"player{n}" if n % 3 else None) for n in range(9, 13)]


def show(title: str, body: str) -> None:
    print(f"\n\033[1m── {title}\033[0m\n{body}")


def main() -> None:
    poll = Poll(day="2026-08-21", poll_id="p", message_id=1)
    for voter in SQUAD[:5]:
        poll.apply(voter, [PLUS])
    poll.apply(Voter(20, "Игрок 20", "player20"), [LATER])

    print("Опрос:", texts.poll_question(date(2026, 8, 21)), "|", " / ".join(texts.POLL_OPTIONS))
    show("приветствие при добавлении в группу", texts.greeting_text())
    show("8-й плюс: кворум, без тегов", texts.quorum_text(SQUAD))
    show("12-й плюс: набор окончен, с тегами", texts.squad_full_text(FULL))
    show("17:00, играем", texts.closing_text(Outcome(playing=True, plus=SQUAD, count=9)))
    show("17:00, не собрались", texts.closing_text(Outcome(playing=False, plus=SQUAD[:3], count=3)))
    show(
        "17:00, счёта от Telegram нет (бот лежал, админ закрыл сам)",
        texts.closing_text(Outcome(playing=False, plus=SQUAD[:3], count=None)),
    )
    show("/status", texts.status_text(poll))
    show("/status без опроса", texts.no_poll_text())
    show("/poll не сработал", texts.poll_not_created_text())
    show("команда не от админа", texts.not_admin_text())
    show(
        "не смог закрыть опрос",
        texts.error_text("закрыть опрос", "Forbidden: not enough rights to manage poll"),
    )


if __name__ == "__main__":
    main()
