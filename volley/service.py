"""Действия бота: создать опрос, обработать голос, закрыть с итогом.

Два свойства, за которые здесь заплачено:

* **Один замок на все три входа.** aiogram обрабатывает апдейты конкурентными
  задачами (`handle_as_tasks=True`), поэтому без сериализации два почти
  одновременных голоса дают два «кворума», два `stopPoll` и два опроса за день.
* **Провал закрытия не выдаётся за успех.** Если `stopPoll` не прошёл, опрос в
  группе открыт и в нём голосуют — сказать «Опрос закрыт» значит соврать.
  Группа получает только предупреждение, один раз на опрос.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from . import texts
from .domain import PLUS, Poll, Voter, daily_outcome, decide_after_vote
from .store import Store

log = logging.getLogger(__name__)


ALREADY_CLOSED_MARKER = "already been closed"


class AlreadyClosed:
    """Опрос был закрыт до нас — счётчиков у Telegram уже не спросить."""

    options: tuple = ()


def telegram_plus_count(stopped_poll) -> int | None:
    """Сколько плюсов насчитал Telegram в момент закрытия.

    Свои данные могли отстать: голоса, поданные пока бот лежал или
    перезапускался, до него не дошли и восстановить их API не даёт. Ответ
    `stopPoll` — единственный авторитетный счётчик, что видела группа.
    """
    options = getattr(stopped_poll, "options", None) or []
    if len(options) <= PLUS:
        return None
    return getattr(options[PLUS], "voter_count", None)


class VolleyService:
    def __init__(self, bot, store: Store) -> None:
        self.bot = bot
        self.store = store
        self._lock = asyncio.Lock()

    # --- FR-1: опрос дня ---------------------------------------------------

    async def open_poll(self, day: date) -> bool:
        async with self._lock:
            return await self._open_poll(day)

    async def _open_poll(self, day: date) -> bool:
        chat_id = self.store.chat_id()
        if chat_id is None:
            log.warning("chat_id неизвестен: бота ещё не добавили в группу")
            return False
        if self.store.poll_for_day(day.isoformat()) is not None:
            log.info("опрос на %s уже есть, второй не создаём", day)
            return False
        try:
            message = await self.bot.send_poll(
                chat_id=chat_id,
                question=texts.poll_question(day),
                options=list(texts.POLL_OPTIONS),
                is_anonymous=False,
                allows_multiple_answers=False,
            )
        except Exception:  # noqa: BLE001 — любой сбой API не должен ронять бота
            # В группу об этом не пишем: отсутствие опроса заметно само,
            # а рестарты и нехватка прав — забота админа, не чата.
            log.exception("не смог создать опрос на %s", day)
            return False

        if self.store.add_poll(
            day=day.isoformat(), poll_id=message.poll.id, message_id=message.message_id
        ) is None:
            log.error("опрос на %s уже был записан — этот остался в группе бесхозным", day)
            return False
        await self._repin(chat_id, message.message_id)
        return True

    async def _repin(self, chat_id: int, message_id: int) -> None:
        previous = self.store.pinned_message_id()
        if previous is not None:
            try:
                await self.bot.unpin_chat_message(chat_id=chat_id, message_id=previous)
            except Exception:  # noqa: BLE001
                log.warning("не смог снять прошлый пин %s", previous)
        try:
            await self.bot.pin_chat_message(
                chat_id=chat_id, message_id=message_id, disable_notification=True
            )
        except Exception:  # noqa: BLE001
            log.warning("не смог закрепить опрос: нет права на пин")
            return
        self.store.set_pinned_message_id(message_id)

    # --- FR-2, FR-3: реакция на голоса -------------------------------------

    async def handle_vote(self, poll_id: str, voter: Voter, option_ids: list[int]) -> None:
        async with self._lock:
            poll = self.store.poll_by_id(poll_id)
            if poll is None or poll.closed:
                return
            self.store.record_vote(poll_id, voter, option_ids)
            poll = self.store.poll_by_id(poll_id)
            for action in decide_after_vote(poll):
                if action == "quorum":
                    await self._announce_quorum(poll)
                elif action == "close_full":
                    await self._close_full(poll)

    async def _announce_quorum(self, poll: Poll) -> None:
        chat_id = self.store.chat_id()
        if await self._say(chat_id, texts.quorum_text(poll.plus)):
            self.store.mark_quorum_announced(poll.poll_id)

    async def _close_full(self, poll: Poll) -> None:
        chat_id = self.store.chat_id()
        if await self._stop_poll(chat_id, poll) is None:
            return
        # Закрытым считаем только после того, как состав объявлен: иначе
        # непрошедшее сообщение потеряет состав навсегда.
        if await self._say(chat_id, texts.squad_full_text(poll.plus)):
            self.store.mark_closed(poll.poll_id)

    async def remind_later(self, poll: Poll | None) -> None:
        """Пинг тем, кто выбрал «Ответ до 16-00»: без тегов напоминание не работает."""
        if poll is None or poll.closed or not poll.later:
            return
        chat_id = self.store.chat_id()
        if chat_id is None:
            return
        async with self._lock:
            await self._say(chat_id, texts.later_reminder_text(poll.later))

    # --- FR-4: закрытие с итогом -------------------------------------------

    async def close_poll(self, poll: Poll | None) -> None:
        """Закрытие в 17:00 и по команде /close."""
        if poll is None:
            return
        async with self._lock:
            fresh = self.store.poll_by_id(poll.poll_id)
            if fresh is None or fresh.closed:
                return
            chat_id = self.store.chat_id()
            if chat_id is None:
                return
            stopped = await self._stop_poll(chat_id, fresh)
            if stopped is None:
                return  # опрос остался открытым — про закрытие молчим
            count = telegram_plus_count(stopped)
            if count is not None:
                # Повторная попытка получит от Telegram «уже закрыт» без счётчиков,
                # а свой счёт мог отстать — сохраняем истину сразу.
                self.store.save_telegram_plus_count(fresh.poll_id, count)
            fresh = self.store.poll_by_id(fresh.poll_id)
            outcome = daily_outcome(fresh, plus_count=fresh.telegram_plus_count)
            if await self._say(chat_id, texts.closing_text(outcome)):
                self.store.mark_closed(fresh.poll_id)

    async def _stop_poll(self, chat_id: int, poll: Poll):
        """Возвращает закрытый опрос от Telegram либо None, если закрыть не вышло."""
        try:
            return await self.bot.stop_poll(chat_id=chat_id, message_id=poll.message_id)
        except Exception as error:  # noqa: BLE001
            if ALREADY_CLOSED_MARKER in str(error):
                # Опрос закрыли до нас: руками или прошлой попыткой, чьё
                # сообщение не дошло. Это успех, а не отсутствие прав.
                log.info("опрос %s уже закрыт, публикуем итог", poll.poll_id)
                return AlreadyClosed()
            log.exception("не смог закрыть опрос %s", poll.poll_id)
            # Флаг ставим только когда предупреждение реально доставлено,
            # иначе двойной сбой оставит группу в тишине навсегда.
            if not poll.close_error_notified and await self._say(
                chat_id, texts.error_text("закрыть опрос", str(error))
            ):
                self.store.mark_close_error_notified(poll.poll_id)
            return None

    # --- /status ------------------------------------------------------------

    async def status_text(self) -> str:
        polls = self.store.open_polls()
        return texts.status_text(polls[-1]) if polls else texts.no_poll_text()

    async def _say(self, chat_id: int, text: str) -> bool:
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception:  # noqa: BLE001
            log.exception("не смог написать в чат")
            return False
        return True
