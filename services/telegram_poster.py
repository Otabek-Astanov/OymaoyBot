import logging
from typing import Optional, Dict, Any
from aiogram import Bot
from aiogram.types import FSInputFile

import config
from services.google_sheets import sheets_service

logger = logging.getLogger(__name__)


class TelegramPosterService:
    @staticmethod
    async def post_to_channel(bot: Bot, phone_data: Dict[str, Any], photo_path: str) -> Optional[int]:
        """
        Telegram kanaliga e'lon joylaydi va message_id qaytaradi.
        """
        if not config.CHANNEL_ID:
            logger.warning("CHANNEL_ID sozlanmagan, e'lon kanalga yuborilmadi.")
            return None

        template = sheets_service.get_template("Elon")
        caption = template.format(
            model=phone_data.get("model", ""),
            memory=phone_data.get("memory", ""),
            battery=phone_data.get("battery", ""),
            color=phone_data.get("color", ""),
            box=phone_data.get("has_box", ""),
            imei_6=phone_data.get("imei_6", ""),
            price=phone_data.get("sell_price", phone_data.get("buy_price", "")),
        )

        try:
            photo = FSInputFile(photo_path)
            sent_msg = await bot.send_photo(
                chat_id=config.CHANNEL_ID,
                photo=photo,
                caption=caption,
            )
            logger.info(f"Kanalga post joylandi! Message ID: {sent_msg.message_id}")
            return sent_msg.message_id
        except Exception as e:
            logger.error(f"Kanalga post joylashda xatolik: {e}")
            return None

    @staticmethod
    async def post_to_buy_group(bot: Bot, phone_data: Dict[str, Any], imei_photo_path: str) -> Optional[int]:
        """
        'Sotib oldi' guruhiga harid hisobotini rasm bilan yuboradi.
        """
        if not config.GROUP_HARID_ID:
            logger.warning("GROUP_HARID_ID sozlanmagan.")
            return None

        caption = (
            "📥 <b>YANGI TELEFON HARID QILINDI!</b>\n\n"
            f"📱 Model: <b>{phone_data.get('model')}</b>\n"
            f"💾 Xotira: <b>{phone_data.get('memory')}</b>\n"
            f"🔋 Batareya: <b>{phone_data.get('battery')}%</b>\n"
            f"🎨 Rang: <b>{phone_data.get('color')}</b>\n"
            f"📦 Karobka: <b>{phone_data.get('has_box')}</b>\n"
            f"🔍 IMEI (oxirgi 6): <code>{phone_data.get('imei_6')}</code>\n\n"
            f"💵 Harid narxi: <b>{phone_data.get('buy_price')}$</b>\n"
            f"💳 To'lov turi: <b>{phone_data.get('payment_type')}</b>\n"
        )
        if phone_data.get("payment_type") == "Qarz":
            caption += f"⚠️ Qarz summasi: <b>{phone_data.get('debt_amount')}$</b>\n"

        caption += (
            f"\n👤 Sotuvchi: <b>{phone_data.get('seller_name')}</b>\n"
            f"📞 Tel: <b>{phone_data.get('seller_phone')}</b>"
        )

        try:
            photo = FSInputFile(imei_photo_path)
            sent_msg = await bot.send_photo(
                chat_id=config.GROUP_HARID_ID,
                photo=photo,
                caption=caption,
            )
            return sent_msg.message_id
        except Exception as e:
            logger.error(f"Harid guruhiga yuborishda xatolik: {e}")
            return None

    @staticmethod
    async def post_to_sell_group(bot: Bot, sale_data: Dict[str, Any]) -> Optional[int]:
        """
        'Sotuv' guruhiga sotilgan telefon hisobotini yuboradi.
        """
        if not config.GROUP_SOTUV_ID:
            logger.warning("GROUP_SOTUV_ID sozlanmagan.")
            return None

        text = (
            "🎉 <b>YANGI SOTUV AMALGA OSHIRILDI!</b>\n\n"
            f"📱 Telefon: <b>{sale_data.get('model', 'Telefon')}</b>\n"
            f"🔍 IMEI (oxirgi 6): <code>{sale_data.get('imei_6')}</code>\n"
            f"💰 Sotuv narxi: <b>{sale_data.get('sell_price')}$</b>\n\n"
            f"👤 Xaridor: <b>{sale_data.get('buyer_name')}</b>\n"
            f"📞 Xaridor tel: <b>{sale_data.get('buyer_phone')}</b>\n"
            f"💳 To'lov turi: <b>{sale_data.get('payment_type')}</b>\n"
        )
        if sale_data.get("payment_type") == "Qarz":
            text += (
                f"🤝 Hamkor: <b>{sale_data.get('partner_name')}</b>\n"
                f"💵 Boshlang'ich to'lov: <b>{sale_data.get('initial_payment')}$</b>\n"
                f"📉 Hamkor qarzi: <b>{sale_data.get('partner_debt')}$</b>\n"
            )

        text += (
            f"\n🎁 Sotuvchi KPI: <b>{sale_data.get('seller_kpi')}$</b>\n"
            f"👨‍💼 Sotuvchi: <b>{sale_data.get('seller_name')}</b>"
        )

        try:
            sent_msg = await bot.send_message(
                chat_id=config.GROUP_SOTUV_ID,
                text=text,
            )
            return sent_msg.message_id
        except Exception as e:
            logger.error(f"Sotuv guruhiga yuborishda xatolik: {e}")
            return None

    @staticmethod
    async def mark_as_sold_on_channel(bot: Bot, channel_post_id: int) -> bool:
        """
        Kanaldagi eski postni '🔴 SOTILDI ❌' deb edit qiladi.
        """
        if not config.CHANNEL_ID or not channel_post_id:
            return False

        try:
            new_caption = (
                "🔴 <b>SOTILDI ❌</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "<i>Ushbu telefon muvaffaqiyatli sotildi! Boshqa e'lonlar bilan kanalda tanishishingiz mumkin.</i>"
            )
            await bot.edit_message_caption(
                chat_id=config.CHANNEL_ID,
                message_id=channel_post_id,
                caption=new_caption,
            )
            logger.info(f"Kanaldagi post (ID: {channel_post_id}) 'SOTILDI' holatiga o'tkazildi.")
            return True
        except Exception as e:
            logger.error(f"Kanaldagi postni tahrirlashda xatolik: {e}")
            return False


poster_service = TelegramPosterService()
