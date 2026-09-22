import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
from bot_sotuv.handlers.sotuv_flow import router as sotuv_router
from services.google_sheets import sheets_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SotuvBot")


async def main():
    token = config.SOTUV_BOT_TOKEN
    if not token:
        logger.error("SOTUV_BOT_TOKEN yoki BOT_TOKEN .env faylida topilmadi!")
        return

    sheets_service.ensure_worksheets()

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(sotuv_router)

    me = await bot.get_me()
    logger.info(f"Sotuv Bot ishga tushdi: @{me.username} (ID: {me.id})")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Sotuv Bot to'xtatildi.")
