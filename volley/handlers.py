"""Хендлеры Telegram: привязка к группе, голоса, команды админов."""

from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command

from . import texts
from .config import TZ
from .domain import Voter
from .store import Store

log = logging.getLogger(__name__)

GROUP_TYPES = ("group", "supergroup")
JOINED_STATUSES = ("member", "administrator", "creator")


async def on_my_chat_member(event, store: Store, bot) -> None:
    """Бота добавили в группу — запоминаем чат один раз и здороваемся.

    Юзернейм бота публичный, добавить его в свой чат может кто угодно. Первая
    привязка выигрывает: иначе посторонний чат перетянул бы опросы на себя.
    """
    if event.chat.type not in GROUP_TYPES:
        return
    if event.new_chat_member.status not in JOINED_STATUSES:
        return

    known = store.chat_id()
    if known is not None:
        if known != event.chat.id:
            log.warning(
                "бота добавили в чат %s, но привязка остаётся на %s", event.chat.id, known
            )
        return

    store.set_chat_id(event.chat.id)
    log.info("привязался к чату %s", event.chat.id)
    await bot.send_message(chat_id=event.chat.id, text=texts.greeting_text())


async def on_migrate(message, store: Store) -> None:
    """Обычная группа стала супергруппой: chat_id сменился, иначе бот замолчит.

    Переезд постороннего чата, куда бота тоже добавили, привязку не меняет.
    """
    new_chat_id = message.migrate_to_chat_id
    if new_chat_id is None:
        return
    known = store.chat_id()
    if known is not None and known != message.chat.id:
        log.warning("мигрировал чужой чат %s — привязка остаётся на %s", message.chat.id, known)
        return
    log.info("чат %s мигрировал в %s", message.chat.id, new_chat_id)
    store.set_chat_id(new_chat_id)


async def on_poll_answer(answer, service) -> None:
    if answer.user is None:  # голос от имени канала — считать некого
        return
    voter = Voter(
        user_id=answer.user.id,
        first_name=answer.user.first_name,
        username=answer.user.username,
    )
    await service.handle_vote(answer.poll_id, voter, list(answer.option_ids))


async def _allowed(message, store: Store, bot) -> bool:
    chat_id = store.chat_id()
    if chat_id is None or message.chat.id != chat_id:
        return False
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except Exception:  # noqa: BLE001 — сбой проверки не должен оставлять команду без ответа
        log.exception("не смог получить список админов чата %s", chat_id)
        await message.reply(texts.admin_check_failed_text())
        return False
    if message.from_user.id not in {admin.user.id for admin in admins}:
        await message.reply(texts.not_admin_text())
        return False
    return True


async def cmd_poll(message, service, store: Store, bot) -> None:
    if not await _allowed(message, store, bot):
        return
    # Проверку «а нет ли уже опроса» делает сам сервис под своим замком:
    # здесь она была бы гонкой с тиком расписания, а молчание в ответ на
    # команду читается как «бот сломался».
    if not await service.open_poll(datetime.now(TZ).date()):
        await message.reply(texts.poll_not_created_text())


async def cmd_close(message, service, store: Store, bot) -> None:
    if not await _allowed(message, store, bot):
        return
    polls = store.open_polls()
    if not polls:
        await message.reply(texts.no_poll_text())
        return
    await service.close_poll(polls[-1])


async def cmd_status(message, service, store: Store, bot) -> None:
    if not await _allowed(message, store, bot):
        return
    await message.reply(await service.status_text())


def build_router() -> Router:
    router = Router(name="volley")
    router.my_chat_member.register(on_my_chat_member)
    router.poll_answer.register(on_poll_answer)
    router.message.register(on_migrate, F.migrate_to_chat_id)
    router.message.register(cmd_poll, Command("poll"))
    router.message.register(cmd_close, Command("close"))
    router.message.register(cmd_status, Command("status"))
    return router
