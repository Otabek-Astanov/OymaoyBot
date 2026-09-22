import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
from bot_harajat.handlers.harajat_flow import router as harajat_router
from services.google_sheets import sheets_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("HarajatBot")


async def main():
    token = config.HARAJAT_BOT_TOKEN
    if not token:
        logger.error("HARAJAT_BOT_TOKEN yoki BOT_TOKEN .env faylida topilmadi!")
        return

    sheets_service.ensure_worksheets()

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(harajat_router)

    me = await bot.get_me()
    logger.info(f"Harajat Bot ishga tushdi: @{me.username} (ID: {me.id})")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Harajat Bot to'xtatildi.")
