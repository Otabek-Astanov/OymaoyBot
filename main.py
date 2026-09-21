import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart

import config

# Logging sozlash
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

dp = Dispatcher()


@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    """/start buyrug'i uchun handler."""
    user_name = message.from_user.full_name if message.from_user else "Foydalanuvchi"
    await message.answer(
        f"Assalomu alaykum, <b>{user_name}</b>!\n\n"
        "Oymaoy do'kon botining ulanishi muvaffaqiyatli o'rnatildi va tizim ishlamoqda. 🚀",
    )


@dp.message()
async def echo_handler(message: types.Message) -> None:
    """Test xabarlarga javob qaytarish."""
    await message.reply("Xabar qabul qilindi. Bot muvaffaqiyatli ishlamoqda!")


async def main() -> None:
    if not config.BOT_TOKEN or config.BOT_TOKEN == "your_bot_token_here":
        logger.error(
            "XATOLIK: BOT_TOKEN aniqlanmadi!\n"
            "Iltimos, loyiha papkasidagi .env fayliga Telegram @BotFather'dan olgan tokeningizni kiriting:\n"
            "BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
        )
        sys.exit(1)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        # Connection test: bot ma'lumotlarini olish
        bot_user = await bot.get_me()
        logger.info(
            f"Telegram bilan aloqa o'rnatildi! Bot: @{bot_user.username} (ID: {bot_user.id}, Ismi: {bot_user.first_name})"
        )

        # Eski kutilayotgan update'larni tozalash
        await bot.delete_webhook(drop_pending_updates=True)

        logger.info("Bot polling rejimida ishga tushmoqda...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
