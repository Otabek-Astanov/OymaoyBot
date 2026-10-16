"""Bounded, read-only readiness checks; never render raw provider errors."""

import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ChatMemberStatus

import config
from services.io_worker import io_worker

logger = logging.getLogger(__name__)


class SystemHealthChecker:
    def __init__(
        self,
        *,
        sheets=None,
        drive=None,
        worker=None,
        cache_seconds=30,
        timeout_seconds=20,
    ):
        self.sheets = sheets
        self.drive = drive
        self.worker = worker or io_worker
        self.cache_seconds = cache_seconds
        self.timeout_seconds = timeout_seconds
        self._cache = {}
        self._bots_by_id = {}

    def configure(self, *, bots_by_id):
        self._bots_by_id = dict(bots_by_id)
        self._cache.clear()

    async def _google_ready(self, service) -> bool:
        try:
            result = await asyncio.wait_for(
                self.worker.call(service.readiness), self.timeout_seconds
            )
            return result is not False
        except Exception as exc:
            logger.warning("Readiness check failed: %s", type(exc).__name__)
            return False

    async def _chat_ready(
        self, current_bot, token, destination, *, channel=False, require_post=True
    ) -> bool:
        if not token or not destination:
            return False
        selected = (
            current_bot
            if current_bot.token == token
            else next(
                (bot for bot in self._bots_by_id.values() if bot.token == token),
                None,
            )
        )
        temporary = selected is None
        selected = selected or Bot(token=token)
        try:
            await asyncio.wait_for(selected.get_chat(destination), self.timeout_seconds)
            if channel:
                member = await asyncio.wait_for(
                    selected.get_chat_member(destination, selected.id),
                    self.timeout_seconds,
                )
                if member.status == ChatMemberStatus.CREATOR:
                    return True
                return (
                    member.status == ChatMemberStatus.ADMINISTRATOR
                    and bool(member.can_edit_messages)
                    and (not require_post or bool(member.can_post_messages))
                )
            member = await asyncio.wait_for(
                selected.get_chat_member(destination, selected.id), self.timeout_seconds
            )
            if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
                return False
            return member.status != ChatMemberStatus.RESTRICTED or bool(
                member.can_send_messages
            )
        except Exception as exc:
            logger.warning("Telegram readiness check failed: %s", type(exc).__name__)
            return False
        finally:
            if temporary:
                await selected.session.close()

    async def run_diagnostics(self, bot, *, features=None, caller_id=None):
        # Navigation verifies sheet-based Admin roles. An explicitly supplied
        # caller ID is restricted to bootstrap ADMIN_IDS for standalone usage.
        if caller_id is not None and caller_id not in config.ADMIN_IDS:
            return False, "Diagnostikani ko'rish uchun admin ruxsati kerak.", {}
        features = tuple(
            features
            or (
                feature
                for feature in config.ENABLED_FEATURES
                if getattr(config, feature.upper() + "_BOT_TOKEN") == bot.token
            )
        )
        key = (bot.id, features)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        if self.sheets is None:
            from services.google_sheets import sheets_service

            self.sheets = sheets_service
        if self.drive is None:
            from services.google_drive import drive_service

            self.drive = drive_service
        results = {
            "creds_file": Path(config.GOOGLE_SERVICE_ACCOUNT_FILE).is_file(),
            "sheets_connected": await self._google_ready(self.sheets),
            "drive_connected": True,
            "has_admins": bool(config.ADMIN_IDS),
        }
        lines = ["<b>Tizim holati</b>"]
        lines.append(
            "✅ Google Sheets schema o'qildi."
            if results["sheets_connected"]
            else "❌ Google Sheets schema yoki ulanish tekshiruvi o'tmadi."
        )
        if config.DRIVE_FOLDER_ID:
            results["drive_connected"] = await self._google_ready(self.drive)
            lines.append(
                "✅ Drive papkasi ochildi."
                if results["drive_connected"]
                else "❌ Drive papkasi yoki ruxsati tekshirilmadi."
            )
        else:
            lines.append("Drive papkasi sozlanmagan; Drive yuklash o'chirilgan.")
        destinations = []
        if "harid" in features:
            destinations.extend(
                [
                    (
                        "channel_ok",
                        "Kanal",
                        config.HARID_BOT_TOKEN,
                        config.CHANNEL_ID,
                        True,
                        True,
                    ),
                    (
                        "harid_group_ok",
                        "Xarid guruhi",
                        config.HARID_BOT_TOKEN,
                        config.GROUP_HARID_ID,
                        False,
                        False,
                    ),
                ]
            )
        if "sotuv" in features:
            destinations.append(
                (
                    "sotuv_group_ok",
                    "Sotuv guruhi",
                    config.SOTUV_BOT_TOKEN,
                    config.GROUP_SOTUV_ID,
                    False,
                    False,
                )
            )
            if "harid" not in features:
                # Sold edits use the original purchase bot where available.
                destinations.append(
                    (
                        "channel_ok",
                        "Kanal tahriri",
                        config.HARID_BOT_TOKEN or config.SOTUV_BOT_TOKEN,
                        config.CHANNEL_ID,
                        True,
                        False,
                    )
                )
        for flag, name, token, destination, is_channel, require_post in destinations:
            if destination:
                results[flag] = await self._chat_ready(
                    bot,
                    token,
                    destination,
                    channel=is_channel,
                    require_post=require_post,
                )
                lines.append(
                    ("✅ " if results[flag] else "❌ ") + name + " ruxsati tekshirildi."
                )
            else:
                results[flag] = True
                lines.append(name + " sozlanmagan; ushbu bildirish o'chirilgan.")
        critical = (
            results["creds_file"]
            and results["sheets_connected"]
            and results["drive_connected"]
        )
        ready = critical and all(results[flag] for flag, *_ in destinations)
        lines.append(
            "Tizim tayyor."
            if ready
            else "Tizim tekshiruvlari to'liq o'tmadi; yozuvlar tayyorlik talabiga bo'ysunadi."
        )
        result = (ready, "\n".join(lines), results)
        self._cache[key] = (time.monotonic(), result)
        return result


health_checker = SystemHealthChecker()
