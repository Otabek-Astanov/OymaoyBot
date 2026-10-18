"""Check current membership on every update, including an existing FSM flow."""

import asyncio
import logging

from aiogram import BaseMiddleware, types

from services.errors import ServiceError
from services.google_sheets import sheets_service
from services.io_worker import WorkerBusyError, io_worker

logger = logging.getLogger(__name__)
WRITE_ROLES = {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}
FINANCE_ROLES = {"Admin", "Hisobchi"}
BALANCE_ROLES = {"Admin", "Hisobchi", "Rahbariyat", "Investor"}
NAVIGATION_COMMANDS = {"/start", "/id", "/status", "/check", "/amal", "/pending"}


def event_target(event):
    if isinstance(event, types.Update):
        return (
            event.callback_query
            or event.message
            or event.channel_post
            or event.edited_message
        )
    return event


class AccessMiddleware(BaseMiddleware):
    def __init__(self, features):
        self.features = set(features)

    async def __call__(self, handler, event, data):
        target = event_target(event)
        if target is None:
            return None
        user = getattr(target, "from_user", None)
        text = getattr(target, "text", None) or ""
        command = (
            text.split(maxsplit=1)[0].split("@")[0] if text.startswith("/") else ""
        )
        if (
            command in NAVIGATION_COMMANDS
            or text == "🚫 Bekor qilish"
            or getattr(target, "forward_origin", None)
        ):
            return await handler(event, data)
        if not user:
            return None
        message = target.message if isinstance(target, types.CallbackQuery) else target
        chat = getattr(message, "chat", None)
        if chat and chat.type != "private":
            return None
        state = data.get("state")
        state_name = (await state.get_state()) if state else ""
        state_name = state_name or ""
        finance = state_name.startswith(("ChiqimStates:", "KirimStates:")) or text in {
            "📉 Chiqim",
            "📈 Kirim",
        }
        purchase = state_name.startswith(
            ("HaridStates:", "ChannelPostStates:", "KarobkaStates:")
        ) or text in {
            "📥 Harid qilish",
            "📢 Telegram kanalga e'lon berish",
            "📦 Karobka",
            "Karobka",
        }
        sale = (
            state_name.startswith("SotuvStates:")
            or text == "📱 Yangi sotuvni rasmiylashtirish"
        )
        try:
            # Cached (cleared after every bot write); a revoked user is still
            # refused at commit, where _authorize reads Xodimlar fresh.
            active, role, name = await io_worker.call(
                sheets_service.check_member, user.id
            )
        except (ServiceError, WorkerBusyError, asyncio.TimeoutError) as exc:
            # check_member already applied its own fallbacks; anything left is closed.
            logger.warning("Access check unavailable: %s", type(exc).__name__)
            await message.answer(
                "⚠️ Google bilan aloqa sekin, ruxsatni tekshirib bo'lmadi. "
                "Hech narsa bajarilmadi — bir necha soniyadan keyin qayta bosing."
            )
            return None
        roles = (
            FINANCE_ROLES
            if finance
            else BALANCE_ROLES
            if text == "💰 Balance"
            else WRITE_ROLES
        )
        feature_allowed = not (
            ((finance or text == "💰 Balance") and "harajat" not in self.features)
            or (purchase and "harid" not in self.features)
            or (sale and "sotuv" not in self.features)
        )
        if not active or role not in roles or not feature_allowed:
            if isinstance(target, types.CallbackQuery):
                await target.answer("Bu amal uchun ruxsat berilmagan.", show_alert=True)
            else:
                await message.answer("⛔ Bu amal uchun ruxsat berilmagan.")
            return None
        data.update(staff_role=role, staff_name=name)
        return await handler(event, data)
