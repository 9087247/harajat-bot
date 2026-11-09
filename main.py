import asyncio
import logging

from aiogram import Bot, Dispatcher

import db
from ai import GeminiReader
from config import BASE_DIR, load_config
from handlers import owner_router, setup_router
from worker import Worker


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(BASE_DIR / "bot.log", encoding="utf-8")],
    )
    # httpx INFO darajasida so'rov manzillarini yozadi, ularda Telegram tokeni bo'lishi mumkin
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_config()
    pool = await db.connect(config.database_url)
    bot = Bot(config.telegram_token)
    dispatcher = Dispatcher()

    worker_task = None
    if config.owner_id is None:
        logging.warning("OWNER_TELEGRAM_ID yozilmagan: bot faqat ID raqamni aytadi")
        dispatcher.include_router(setup_router())
    else:
        reader = GeminiReader(config.gemini_api_key, config.gemini_model)
        worker = Worker(bot, pool, reader, config)
        dispatcher["pool"] = pool
        dispatcher["config"] = config
        dispatcher["worker"] = worker
        dispatcher.include_router(owner_router(config.owner_id))
        worker_task = asyncio.create_task(worker.run())

    try:
        await dispatcher.start_polling(bot, allowed_updates=["message"])
    finally:
        if worker_task:
            worker_task.cancel()
        await pool.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

