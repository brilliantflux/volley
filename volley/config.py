"""Настройки процесса: часовой пояс, пути, секрет из окружения.

Времена и тексты вариантов здесь — только ДЕФОЛТЫ, с которых бот начинает на
чистой базе. Живое значение админ меняет командой, и читать его надо через
`settings.py`, а не отсюда: иначе одна и та же величина окажется в двух местах.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Sofia")

GAME_TIME = "17-30"  # во сколько игра — попадает только в текст опроса
POLL_TIME = "09:00"  # когда бот постит опрос
REMINDER_TIME = "15:45"  # когда тегает обещавших ответить
CLOSE_TIME = "16:30"  # когда закрывает, если состав не набрался раньше

OPTION_PLUS = "Плюс"
OPTION_MINUS = "Минус"
OPTION_LATER = "Ответ до 16-00"

DEFAULT_DB = Path.home() / ".local" / "share" / "volley" / "state.db"


def token() -> str:
    value = os.environ.get("VOLLEY_BOT_TOKEN", "").strip()
    if not value:
        raise SystemExit(
            "VOLLEY_BOT_TOKEN не задан. Токен от @BotFather кладётся в .env "
            "(локально) или в EnvironmentFile юнита (на сервере)."
        )
    return value


def db_path() -> Path:
    value = os.environ.get("VOLLEY_DB", "").strip()
    return Path(value).expanduser() if value else DEFAULT_DB
