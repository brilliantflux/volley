"""Настройки, которые админ меняет на ходу.

Дефолт живёт в `config`, изменённое значение — в таблице `settings` базы. Читают
всегда отсюда: расписание, тексты и команды не имеют своих копий этих чисел.
Хранится всё строками в каноническом виде, разбор — на входе, а не по месту
использования.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Callable

from . import config

TELEGRAM_OPTION_LIMIT = 100  # предел Telegram на длину варианта ответа


def _as_time(raw: str) -> str:
    """«17-30», «17:30», «17.30» → «17:30». Иначе ValueError с внятным текстом."""
    parts = raw.strip().replace("-", ":").replace(".", ":").split(":")
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        raise ValueError("время задаётся как ЧЧ:ММ, например 17:30")
    hour, minute = (int(part) for part in parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("на часах не больше 23:59")
    return f"{hour:02d}:{minute:02d}"


def _as_option(raw: str) -> str:
    text = " ".join(raw.split())
    if not text:
        raise ValueError("вариант ответа не может быть пустым")
    if len(text) > TELEGRAM_OPTION_LIMIT:
        raise ValueError(f"Telegram не примет вариант длиннее {TELEGRAM_OPTION_LIMIT} символов")
    return text


@dataclass(frozen=True)
class Setting:
    key: str
    title: str
    default: str
    normalize: Callable[[str], str]


SETTINGS: tuple[Setting, ...] = (
    Setting("game_time", "во сколько игра", config.GAME_TIME, _as_time),
    Setting("poll_time", "когда ставить опрос", config.POLL_TIME, _as_time),
    Setting("reminder_time", "когда напоминать", config.REMINDER_TIME, _as_time),
    Setting("close_time", "когда закрывать опрос", config.CLOSE_TIME, _as_time),
    Setting("option_plus", "вариант «за»", config.OPTION_PLUS, _as_option),
    Setting("option_minus", "вариант «против»", config.OPTION_MINUS, _as_option),
    Setting("option_later", "вариант «отвечу позже»", config.OPTION_LATER, _as_option),
)

BY_KEY = {setting.key: setting for setting in SETTINGS}


def value(store, key: str) -> str:
    setting = BY_KEY[key]
    saved = store.setting(key)
    return saved if saved is not None else setting.normalize(setting.default)


def time_value(store, key: str) -> time:
    hour, minute = (int(part) for part in value(store, key).split(":"))
    return time(hour, minute)


def set_value(store, key: str, raw: str) -> str:
    """Пишет одну настройку. KeyError — нет такой, ValueError — значение не годится."""
    if key not in BY_KEY:
        raise KeyError(key)
    normalized = BY_KEY[key].normalize(raw)
    store.set_setting(key, normalized)
    return normalized


def current(store) -> list[tuple[Setting, str]]:
    return [(setting, value(store, setting.key)) for setting in SETTINGS]


def options(store) -> tuple[str, str, str]:
    """Три варианта ответа в порядке, который домен понимает по позиции."""
    return (
        value(store, "option_plus"),
        value(store, "option_minus"),
        value(store, "option_later"),
    )
