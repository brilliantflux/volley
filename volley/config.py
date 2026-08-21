"""Настройки: расписание дня и пути. Секрет — только из окружения."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Sofia")

POLL_TIME = time(9, 0)  # когда бот постит опрос
CLOSE_TIME = time(17, 0)  # когда закрывает, если состав не набрался раньше
CATCHUP_UNTIL = time(16, 0)  # позже этого времени пропущенный опрос уже не создаём
GAME_TIME = "18-00"

# Третий вариант опроса обещает ответ к этому времени; напоминание считается от
# него, чтобы правка дедлайна двигала и текст варианта, и время напоминания.
LATER_DEADLINE = time(16, 0)
REMINDER_LEAD = timedelta(minutes=15)
REMINDER_TIME = (datetime.combine(date(2000, 1, 1), LATER_DEADLINE) - REMINDER_LEAD).time()

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
