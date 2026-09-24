import os
import logging
from typing import Tuple, Dict, Any
from aiogram import Bot
from aiogram.enums import ChatMemberStatus

import config
from services.google_sheets import sheets_service
from services.google_drive import drive_service

logger = logging.getLogger(__name__)


class SystemHealthChecker:
    @staticmethod
    async def run_diagnostics(bot: Bot) -> Tuple[bool, str, Dict[str, bool]]:
        """
        Tizimning barcha kerakli konfiguratsiyalarini tekshiradi.
        Qaytaradi: (tayyormi: bool, hisobot_matni: str, statuslar_lugati)
        """
        results = {}
        report_lines = ["🛠 <b>TIZIM SOZLAMALARI VA ULANISHLAR DIAGNOSTIKASI:</b>\n"]

        # 1. Google Sheets Fayli
        creds_exists = os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_FILE)
        results["creds_file"] = creds_exists
        if creds_exists:
            report_lines.append("✅ <b>Google Kalit:</b> <code>credentials.json</code> mavjud")
        else:
            report_lines.append("❌ <b>Google Kalit:</b> <code>credentials.json</code> fayli topilmadi")

        # 2. Spreadsheet ID va ulanishi
        sheet_id_set = bool(config.SPREADSHEET_ID)
        sheets_connected = sheets_service.is_connected()
        results["sheets_connected"] = sheets_connected
        if sheet_id_set and sheets_connected:
            report_lines.append("✅ <b>Google Sheets Baza:</b> Ulangan va faol")
        elif not sheet_id_set:
            report_lines.append("❌ <b>Google Sheets Baza:</b> <code>SPREADSHEET_ID</code> kiritilmagan")
        else:
            report_lines.append("❌ <b>Google Sheets Baza:</b> Jadvalga ulanib bo'lmadi")

        # 3. Google Drive
        drive_connected = drive_service.is_connected()
        results["drive_connected"] = drive_connected
        if drive_connected:
            report_lines.append("✅ <b>Google Drive:</b> Rasmlar ombori faol")
        else:
            report_lines.append("❌ <b>Google Drive:</b> Ulanmagan (rasmlar lokal saqlanadi)")

        # 4. Telegram Kanal
        channel_set = bool(config.CHANNEL_ID)
        channel_ok = False
        if channel_set:
            try:
                chat = await bot.get_chat(config.CHANNEL_ID)
                # Bot adminmi tekshirish
                bot_member = await bot.get_chat_member(config.CHANNEL_ID, bot.id)
                if bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                    channel_ok = True
                    report_lines.append(f"✅ <b>Telegram Kanal:</b> @{chat.username or chat.title} (Bot admin)")
                else:
                    report_lines.append(f"⚠️ <b>Telegram Kanal:</b> Bot kanalda admin emas!")
            except Exception as e:
                report_lines.append(f"❌ <b>Telegram Kanal:</b> Ulanishda xato ({e})")
        else:
            report_lines.append("❌ <b>Telegram Kanal:</b> <code>CHANNEL_ID</code> kiritilmagan")
        results["channel_ok"] = channel_ok

        # 5. Harid Guruhi ("Sotib oldi")
        harid_group_set = bool(config.GROUP_HARID_ID)
        harid_group_ok = False
        if harid_group_set:
            try:
                chat = await bot.get_chat(config.GROUP_HARID_ID)
                harid_group_ok = True
                report_lines.append(f"✅ <b>Harid guruhi:</b> {chat.title}")
            except Exception as e:
                report_lines.append(f"❌ <b>Harid guruhi:</b> Ulanishda xato ({e})")
        else:
            report_lines.append("❌ <b>Harid guruhi:</b> <code>GROUP_HARID_ID</code> kiritilmagan")
        results["harid_group_ok"] = harid_group_ok

        # 6. Sotuv Guruhi
        sotuv_group_set = bool(config.GROUP_SOTUV_ID)
        sotuv_group_ok = False
        if sotuv_group_set:
            try:
                chat = await bot.get_chat(config.GROUP_SOTUV_ID)
                sotuv_group_ok = True
                report_lines.append(f"✅ <b>Sotuv guruhi:</b> {chat.title}")
            except Exception as e:
                report_lines.append(f"❌ <b>Sotuv guruhi:</b> Ulanishda xato ({e})")
        else:
            report_lines.append("❌ <b>Sotuv guruhi:</b> <code>GROUP_SOTUV_ID</code> kiritilmagan")
        results["sotuv_group_ok"] = sotuv_group_ok

        # 7. Adminlar ro'yxati
        has_admins = bool(config.ADMIN_IDS)
        results["has_admins"] = has_admins
        if has_admins:
            report_lines.append(f"✅ <b>Adminlar:</b> {len(config.ADMIN_IDS)} ta admin kiritilgan")
        else:
            report_lines.append("⚠️ <b>Adminlar:</b> <code>ADMIN_IDS</code> kiritilmagan")

        # Asosiy holat: Google Sheets va kalit bo'lsa bot to'liq ishlay oladi
        critical_passed = creds_exists and sheets_connected

        report_lines.append("\n━━━━━━━━━━━━━━━━━━━━")
        if critical_passed:
            report_lines.append("🎉 <b>XULOSA: Google Sheets bazasi muvaffaqiyatli ulangan! Bot ishchi holatda.</b>")
            if not (channel_ok and harid_group_ok and sotuv_group_ok):
                report_lines.append("<i>💡 Eslatma: Kanal yoki guruh sozlanmagan bo'lsa, ma'lumotlar to'g'ridan-to'g'ri Google Sheets'ga yoziladi.</i>")
        else:
            report_lines.append(
                "⚠️ <b>XULOSA: Google Sheets sozlanmagan!</b>\n"
                "<i>Iltimos, credentials.json va SPREADSHEET_ID ni to'ldiring.</i>"
            )

        full_report = "\n".join(report_lines)
        return critical_passed, full_report, results


health_checker = SystemHealthChecker()
