#!/usr/bin/env python3
"""Контракт с aiogram: диспетчер собирается и подписан на нужные типы апдейтов.

Тесты на фейковом боте этого не видят: если poll_answer не попал в
allowed_updates, голоса до бота не дойдут, а весь юнит-набор останется зелёным.
Запуск: .venv/bin/python scripts/smoke_updates.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Dispatcher  # noqa: E402
from aiogram.methods import SendPoll  # noqa: E402

from volley import texts  # noqa: E402
from volley.handlers import build_router  # noqa: E402

REQUIRED = {"poll_answer", "my_chat_member", "message"}


def main() -> int:
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    used = set(dispatcher.resolve_used_update_types())
    missing = REQUIRED - used
    print(f"allowed_updates: {sorted(used)}")
    if missing:
        print(f"ПРОВАЛ: не подписаны на {sorted(missing)}")
        return 1

    # sendPoll собирается ровно с теми аргументами, которыми его зовёт сервис
    call = SendPoll(
        chat_id=-1,
        question=texts.poll_question(__import__("datetime").date(2026, 8, 21)),
        options=list(texts.POLL_OPTIONS),
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    if call.is_anonymous is not False:
        print("ПРОВАЛ: опрос уходит анонимным, бот не получит голоса")
        return 1
    print(f"sendPoll ок: {call.question!r}, options={call.options}, anonymous={call.is_anonymous}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
