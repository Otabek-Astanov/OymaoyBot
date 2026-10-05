import os
import re
import logging
from typing import Optional, Dict, Any
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

import config
from services.google_sheets import sheets_service
from utils.formatters import build_channel_caption, build_buy_group_caption

logger = logging.getLogger(__name__)


def extract_drive_file_id(photo_field: Any) -> str:
    """Google Sheets'dagi formula yoki URL ichidan Google Drive file_id ni ajratib oladi."""
    if not photo_field:
        return ""
    text = str(photo_field)
    match = re.search(r'/d/([a-zA-Z0-9_-]{25,})', text)
    if match:
        return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]{25,})', text)
    if match:
        return match.group(1)
    return ""


class TelegramPosterService:
    @staticmethod
    async def post_to_channel(bot: Bot, phone_data: Dict[str, Any], photo_path: Optional[str] = None) -> Optional[int]:
        """
        Telegram kanaliga e'lon joylaydi va message_id qaytaradi.
        """
        if not config.CHANNEL_ID:
            logger.warning("CHANNEL_ID sozlanmagan, e'lon kanalga yuborilmadi.")
            return None

        caption = build_channel_caption(phone_data, is_sold=False)

        try:
            if not photo_path:
                sent_msg = await bot.send_message(
                    chat_id=config.CHANNEL_ID,
                    text=caption,
                )
                logger.info(f"Kanalga matnli post joylandi! Message ID: {sent_msg.message_id}")
                return sent_msg.message_id

            if isinstance(photo_path, str) and len(photo_path) < 255 and os.path.exists(photo_path):
                photo = FSInputFile(photo_path)
            else:
                photo = photo_path

            sent_msg = await bot.send_photo(
                chat_id=config.CHANNEL_ID,
                photo=photo,
                caption=caption,
            )
            logger.info(f"Kanalga rasmli post joylandi! Message ID: {sent_msg.message_id}")
            return sent_msg.message_id
        except Exception as e:
            logger.error(f"Kanalga post joylashda xatolik: {e}")
            return None

    @staticmethod
    async def post_to_buy_group(bot: Bot, phone_data: Dict[str, Any], imei_photo_path: Optional[str] = None) -> Optional[int]:
        """
        'Sotib oldi' guruhiga harid hisobotini rasm bilan (yoki rasmsiz) yuboradi.
        """
        if not config.GROUP_HARID_ID:
            logger.warning("GROUP_HARID_ID sozlanmagan.")
            return None

        caption = build_buy_group_caption(phone_data)

        try:
            if not imei_photo_path:
                sent_msg = await bot.send_message(
                    chat_id=config.GROUP_HARID_ID,
                    text=caption,
                )
                return sent_msg.message_id

            if isinstance(imei_photo_path, str) and len(imei_photo_path) < 255 and os.path.exists(imei_photo_path):
                photo = FSInputFile(imei_photo_path)
            else:
                photo = imei_photo_path

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
            f"📱 Model: <b>{sale_data.get('model', 'Model')}</b>\n"
            f"🔍 IMEI / Seriya: <code>{sale_data.get('imei', sale_data.get('imei_6'))}</code>\n"
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

        sellers = sale_data.get("sellers")
        if sellers and isinstance(sellers, list) and len(sellers) > 1:
            seller_details = "\n".join([f"{s.get('name', 'Xodim')}: {s.get('kpi', 0)}$" for s in sellers])
            text += (
                f"\n🎁 Jami KPI: <b>{sale_data.get('seller_kpi')}$</b>\n"
                f"{seller_details}\n"
                f"👨‍💼 Sotuvchilar: <b>{sale_data.get('seller_name')}</b>"
            )
        else:
            text += (
                f"\n🎁 Sotuvchi KPI: <b>{sale_data.get('seller_kpi')}$</b>\n"
                f"👨‍💼 Sotuvchi: <b>{sale_data.get('seller_name')}</b>"
            )

        phone_data = sale_data.get("phone_data", {}) if isinstance(sale_data.get("phone_data"), dict) else {}
        photo_field = (
            sale_data.get("phone_photo_url")
            or phone_data.get("Telefon rasmi")
            or phone_data.get("phone_photo_url")
            or sale_data.get("imei_photo_url")
            or phone_data.get("IMEI rasmi")
            or phone_data.get("imei_photo_url")
        )
        drive_id = extract_drive_file_id(photo_field)

        try:
            if drive_id:
                try:
                    photo_url = f"https://lh3.googleusercontent.com/d/{drive_id}"
                    sent_msg = await bot.send_photo(
                        chat_id=config.GROUP_SOTUV_ID,
                        photo=photo_url,
                        caption=text,
                    )
                    logger.info(f"Sotuv guruhiga rasm bilan xabar yuborildi! Msg ID: {sent_msg.message_id}")
                    return sent_msg.message_id
                except Exception as pe:
                    logger.warning(f"Sotuv guruhiga rasm bilan yuborishda ogohlantirish ({pe}), matn shaklida yuboriladi.")

            sent_msg = await bot.send_message(
                chat_id=config.GROUP_SOTUV_ID,
                text=text,
            )
            return sent_msg.message_id
        except Exception as e:
            logger.error(f"Sotuv guruhiga yuborishda xatolik: {e}")
            return None

    @staticmethod
    async def mark_as_sold_on_channel(
        bot: Bot, channel_post_id: int, phone_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Kanaldagi eski postni '🔴 SOTILDI ❌' deb edit qiladi.
        E'lonning to'liq ma'lumotlarini saqlab qoladi.
        """
        if not config.CHANNEL_ID or not channel_post_id:
            return False

        if phone_data:
            new_caption = build_channel_caption(phone_data, is_sold=True)
        else:
            new_caption = (
                "🔴 <b>SOTILDI ❌</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "<i>Ushbu telefon muvaffaqiyatli sotildi! Boshqa e'lonlar bilan kanalda tanishishingiz mumkin.</i>"
            )

        async def _try_edit(target_bot: Bot) -> bool:
            try:
                await target_bot.edit_message_caption(
                    chat_id=config.CHANNEL_ID,
                    message_id=channel_post_id,
                    caption=new_caption,
                    parse_mode=ParseMode.HTML,
                )
                return True
            except Exception as ce:
                try:
                    await target_bot.edit_message_text(
                        chat_id=config.CHANNEL_ID,
                        message_id=channel_post_id,
                        text=new_caption,
                        parse_mode=ParseMode.HTML,
                    )
                    return True
                except Exception:
                    logger.warning(f"edit_message xatolik: {ce}")
                    return False

        # 1. Avval joriy bot orqali urinib ko'rish
        success = await _try_edit(bot)
        if success:
            logger.info(f"Kanaldagi post (ID: {channel_post_id}) 'SOTILDI' holatiga o'tkazildi.")
            return True

        # 2. Agar sotuv boti tahrir qilolmasa, Harid boti orqali urinib ko'rish
        if config.HARID_BOT_TOKEN and config.HARID_BOT_TOKEN != bot.token:
            temp_bot = Bot(
                token=config.HARID_BOT_TOKEN,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            try:
                success2 = await _try_edit(temp_bot)
                if success2:
                    logger.info(f"Kanaldagi post (ID: {channel_post_id}) Harid boti orqali 'SOTILDI' holatiga o'tkazildi.")
                    return True
            finally:
                await temp_bot.session.close()

        return False


poster_service = TelegramPosterService()
