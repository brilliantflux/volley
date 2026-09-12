"""Хендлеры Telegram: привязка к группе, голоса, команды админов."""

from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command

from . import config, settings, texts
from .domain import Voter
from .store import Store

log = logging.getLogger(__name__)

GROUP_TYPES = ("group", "supergroup")
PRIVATE = "private"
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
    await bot.send_message(
        chat_id=event.chat.id,
        text=texts.greeting_text(
            settings.value(store, "poll_time"), settings.value(store, "close_time")
        ),
    )


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
    """Команду выполняет админ ПРИВЯЗАННОЙ группы — хоть из неё, хоть из лички.

    Личка не заводит второй источник прав: список админов всё равно берётся у
    группы. Чужой групповой чат по-прежнему игнорируется молча, а вот админу в
    личке молчать нельзя — тишина в ответ на команду читается как поломка.

    Владелец бота из `VOLLEY_OWNER_ID` — единственное исключение: он ставил
    бота, но админом группы быть не обязан, а повысить его там может только
    создатель. Чужой чат это исключение своим не делает.
    """
    private = message.chat.type == PRIVATE
    chat_id = store.chat_id()
    if chat_id is None:
        if private:
            await message.reply(texts.no_group_yet_text())
        return False
    if not private and message.chat.id != chat_id:
        return False
    if message.from_user.id == config.owner_id():
        return True
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


async def cmd_start(message) -> None:
    """Ответ на «Запустить» в личке — единственная команда без проверки прав.

    Telegram показывает эту кнопку любому, кто открыл бота, и тишина в ответ на
    первое же сообщение читается как поломка. Скрывать тут нечего: имена команд
    не секрет, а выполнить их всё равно даст только гейт. В группе /start —
    чужой шум, поэтому там молчим.
    """
    if message.chat.type != PRIVATE:
        return
    await message.reply(texts.start_text())


async def cmd_poll(message, service, store: Store, bot) -> None:
    if not await _allowed(message, store, bot):
        return
    # Проверку «а нет ли уже опроса» делает сам сервис под своим замком:
    # здесь она была бы гонкой с тиком расписания, а молчание в ответ на
    # команду читается как «бот сломался».
    if not await service.open_poll(datetime.now(config.TZ).date()):
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


async def cmd_settings(message, store: Store, bot) -> None:
    if not await _allowed(message, store, bot):
        return
    await message.reply(texts.settings_text(settings.current(store)))


async def cmd_set(message, command, store: Store, bot) -> None:
    """Одна команда — одна настройка: пачкой их менять некому и незачем."""
    if not await _allowed(message, store, bot):
        return
    key, _, raw = (command.args or "").strip().partition(" ")
    if not key or not raw.strip():
        await message.reply(texts.setting_usage_text())
        return
    try:
        value = settings.set_value(store, key, raw)
    except KeyError:
        await message.reply(texts.setting_unknown_text(key, list(settings.BY_KEY)))
    except ValueError as error:
        await message.reply(texts.setting_rejected_text(str(error)))
    else:
        log.info("админ %s сменил %s на %r", message.from_user.id, key, value)
        await message.reply(texts.setting_saved_text(settings.BY_KEY[key].title, value))


def build_router() -> Router:
    router = Router(name="volley")
    router.my_chat_member.register(on_my_chat_member)
    router.poll_answer.register(on_poll_answer)
    router.message.register(on_migrate, F.migrate_to_chat_id)
    router.message.register(cmd_start, Command("start"))
    router.message.register(cmd_poll, Command("poll"))
    router.message.register(cmd_close, Command("close"))
    router.message.register(cmd_status, Command("status"))
    router.message.register(cmd_settings, Command("settings"))
    router.message.register(cmd_set, Command("set"))
    return router
