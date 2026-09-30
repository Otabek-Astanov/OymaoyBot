import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
from bot_harid.handlers.harid_flow import router as harid_router
from bot_sotuv.handlers.sotuv_flow import router as sotuv_router
from bot_harajat.handlers.harajat_flow import router as harajat_router
from services.google_sheets import sheets_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("OymaoySystem")


async def run_single_bot(token: str, router, bot_name: str):
    """Alohida bitta botni ishga tushiruvchi funksiya."""
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    for attempt in range(5):
        try:
            me = await bot.get_me()
            logger.info(f"✅ {bot_name} ishga tushdi: @{me.username} (ID: {me.id})")
            break
        except Exception as e:
            if attempt == 4:
                raise
            logger.warning(f"⚠️ {bot_name} ulanishda xatolik: {e}. 2 soniyadan so'ng qayta uriniladi...")
            await asyncio.sleep(2)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


async def run_unified_bot(token: str):
    """
    Agar barcha 3 ta bot uchun 1 ta umumiy token berilgan bo'lsa (masalan test jarayonida),
    barcha oqimlarni bitta botga birlashtirib ishga tushiradi.
    """
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Barcha routerlarni birlashtirish
    dp.include_router(harid_router)
    dp.include_router(sotuv_router)
    dp.include_router(harajat_router)

    me = await bot.get_me()
    logger.info(f"🚀 Birlashgan OymaOy Boti ishga tushdi: @{me.username} (ID: {me.id})")
    logger.info("Ushbu bot ichida Harid, Sotuv va Harajat funksiyalari to'liq mujassamlashgan.")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


async def main():
    sheets_service.ensure_worksheets()

    tokens = {
        "harid": config.HARID_BOT_TOKEN,
        "sotuv": config.SOTUV_BOT_TOKEN,
        "harajat": config.HARAJAT_BOT_TOKEN,
    }

    # Tokenlar borligini tekshirish
    valid_tokens = {k: v for k, v in tokens.items() if v}
    if not valid_tokens:
        logger.error("Hech qanday bot tokeni (.env faylida) topilmadi!")
        return

    # Agar tokenlar har xil bo'lsa, parallel ravishda alohida botlarni ishga tushiramiz
    unique_tokens = set(valid_tokens.values())

    if len(unique_tokens) == 1:
        # Hozircha bitta token bor bo'lsa (birlashgan rejim)
        logger.info("Yagona token aniqlandi. Tizim Birlashgan (All-in-One) rejimida ishga tushmoqda...")
        single_token = list(unique_tokens)[0]
        await run_unified_bot(single_token)
    else:
        # Har bir bot alohida token bilan ishlaganda
        logger.info("Bir nechta bot tokeni aniqlandi. Har bir bot mustaqil ishga tushirilmoqda...")
        tasks = []
        if config.HARID_BOT_TOKEN:
            tasks.append(run_single_bot(config.HARID_BOT_TOKEN, harid_router, "Harid Bot"))
        if config.SOTUV_BOT_TOKEN:
            tasks.append(run_single_bot(config.SOTUV_BOT_TOKEN, sotuv_router, "Sotuv Bot"))
        if config.HARAJAT_BOT_TOKEN:
            tasks.append(run_single_bot(config.HARAJAT_BOT_TOKEN, harajat_router, "Harajat Bot"))

        await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Barcha botlar to'xtatildi.")
