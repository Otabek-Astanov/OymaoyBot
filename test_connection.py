import asyncio
import sys
from aiogram import Bot
import config


async def test_bot_connection():
    token = config.BOT_TOKEN
    if not token or token == "your_bot_token_here":
        print("\n❌ XATOLIK: .env faylida BOT_TOKEN topilmadi yoki to'ldirilmagan!")
        print("Loyiha papkasida .env faylini ochib, quyidagicha token yozing:")
        print("BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz\n")
        return False

    print("📡 Telegram serveriga so'rov yuborilmoqda...")
    bot = Bot(token=token)

    try:
        me = await bot.get_me()
        print("\n" + "=" * 45)
        print("✅ ALOQA MUVAFFAQIYATLI O'RNATILDI!")
        print(f"🤖 Bot nomi: {me.first_name}")
        print(f"🔗 Bot username: @{me.username}")
        print(f"🆔 Bot ID: {me.id}")
        print(f"👥 Guruhlarga qo'shilish: {'Ruxsat berilgan' if me.can_join_groups else 'Cheklangan'}")
        print("=" * 45 + "\n")
        return True
    except Exception as e:
        print("\n" + "=" * 45)
        print(f"❌ Telegram API bilan ulanishda xatolik yuz berdi:")
        print(f"{type(e).__name__}: {e}")
        print("=" * 45 + "\n")
        return False
    finally:
        await bot.session.close()


if __name__ == "__main__":
    success = asyncio.run(test_bot_connection())
    sys.exit(0 if success else 1)
