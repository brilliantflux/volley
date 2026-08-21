"""Запуск бота: long polling плюс два тика расписания в день."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from . import config
from .handlers import build_router
from .schedule import build_scheduler, run_tick
from .service import VolleyService
from .store import Store

log = logging.getLogger("volley")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    store = Store(config.db_path())
    bot = Bot(token=config.token(), default=DefaultBotProperties(parse_mode="HTML"))
    service = VolleyService(bot=bot, store=store)

    dispatcher = Dispatcher(service=service, store=store)
    dispatcher.include_router(build_router())

    build_scheduler(service, store).start()
    await run_tick(service, store)  # catch-up после простоя или рестарта
    log.info("бот запущен, база %s", config.db_path())
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
