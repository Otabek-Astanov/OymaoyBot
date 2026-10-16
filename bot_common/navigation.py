"""One navigation router per token; feature routers contain business flows only."""

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

import config
from bot_common.handler_support import safe_handler
from services.errors import BusinessRuleError, ServiceError
from services.google_sheets import sheets_service
from services.health_check import health_checker
from services.io_worker import io_worker
from utils.formatters import safe_html


def menu_for(role, features):
    features = set(features)
    rows = []
    if role in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        if "harid" in features:
            rows += [
                [KeyboardButton(text="📥 Harid qilish")],
                [
                    KeyboardButton(text="📢 Telegram kanalga e'lon berish"),
                    KeyboardButton(text="📦 Karobka"),
                ],
            ]
        if "sotuv" in features:
            rows.append([KeyboardButton(text="📱 Yangi sotuvni rasmiylashtirish")])
    # Balance is part of the finance (Harajat) bot only, as in the original spec.
    if "harajat" in features:
        if role in {"Admin", "Hisobchi"}:
            rows.append(
                [KeyboardButton(text="📈 Kirim"), KeyboardButton(text="📉 Chiqim")]
            )
        if role in {"Admin", "Hisobchi", "Rahbariyat", "Investor"}:
            rows.append([KeyboardButton(text="💰 Balance")])
    return (
        ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
        if rows
        else ReplyKeyboardRemove()
    )


async def member(user_id):
    active, role, name = await io_worker.call(
        sheets_service.check_member, user_id, force_refresh=False
    )
    if not active:
        raise BusinessRuleError(f"Ruxsat berilmagan. Telegram ID: {user_id}")
    return role, name


def create_navigation_router(features):
    features = tuple(features)
    router = Router()

    @router.message(CommandStart())
    @safe_handler
    async def start(message: types.Message, state: FSMContext):
        role, name = await member(message.from_user.id)
        pending = await io_worker.call(
            sheets_service.get_actor_pending_operations, message.from_user.id
        )
        if pending:
            ids = "\n".join(
                f"<code>{safe_html(p['operation_id'])}</code> — {safe_html(p['state'])}"
                for p in pending
            )
            await message.answer(
                "⚠️ Yakunlanmagan amallar mavjud. Yangi amal boshlashdan oldin hisobchi bilan tekshiring:\n"
                + ids
            )
            return
        await state.clear()
        await message.answer(
            f"<b>{safe_html(name)}</b> · {safe_html(role)}\nAmalni tanlang:",
            reply_markup=menu_for(role, features),
        )

    @router.message(F.text == "🚫 Bekor qilish")
    @safe_handler
    async def cancel(message: types.Message, state: FSMContext):
        role, _ = await member(message.from_user.id)
        data = await state.get_data()
        identifier = data.get("operation_id")
        if identifier:
            status = await io_worker.call(
                sheets_service.get_operation_status, identifier
            )
            if status and status.get("state") in {"sending", "unknown"}:
                raise BusinessRuleError(
                    f"Amal natijasi noaniq. Avval /amal {identifier} orqali tekshiring."
                )
        await state.clear()
        await message.answer(
            "Jarayon bekor qilindi.", reply_markup=menu_for(role, features)
        )

    @router.message(Command("status", "check"))
    @safe_handler
    async def status(message: types.Message, bot):
        try:
            role, _ = await member(message.from_user.id)
        except ServiceError:
            role = "Admin" if message.from_user.id in config.ADMIN_IDS else ""
        if role != "Admin":
            raise BusinessRuleError("Diagnostika faqat admin uchun.")
        _, report, _ = await health_checker.run_diagnostics(bot, features=features)
        await message.answer(report)

    @router.message(Command("amal"))
    @safe_handler
    async def operation_status(message: types.Message):
        role, _ = await member(message.from_user.id)
        parts = message.text.split(maxsplit=1)
        if len(parts) != 2:
            raise BusinessRuleError("Amal ID ni kiriting: /amal UUID")
        operation = await io_worker.call(
            sheets_service.get_operation_status, parts[1].strip()
        )
        if not operation:
            raise BusinessRuleError("Bu ID mahalliy jurnalda topilmadi.")
        if role not in {"Admin", "Hisobchi"} and str(operation.get("actor_id")) != str(
            message.from_user.id
        ):
            raise BusinessRuleError("Bu amal holatini ko‘rishga ruxsat berilmagan.")
        await message.answer(
            f"Amal: <code>{safe_html(parts[1])}</code>\nHolat: <b>{safe_html(operation['state'])}</b>"
        )

    @router.message(Command("pending"))
    @safe_handler
    async def pending_operations(message: types.Message):
        await member(message.from_user.id)
        pending = await io_worker.call(
            sheets_service.get_actor_pending_operations, message.from_user.id
        )
        text = "\n".join(
            f"<code>{safe_html(p['operation_id'])}</code> — {safe_html(p['state'])}"
            for p in pending
        )
        await message.answer(text or "Yakunlanmagan amal yo‘q.")

    if "harajat" in features:

        @router.message(F.text == "💰 Balance")
        async def balance(message: types.Message):
            from bot_harajat.handlers.harajat_flow import view_balance

            await view_balance(message)

    @router.channel_post(Command("id"))
    @router.message(Command("id"))
    async def show_id(message: types.Message, bot):
        target = (
            message.reply_to_message.from_user
            if message.reply_to_message and message.reply_to_message.from_user
            else message.chat
        )
        args = (message.text or "").split(maxsplit=1)
        if len(args) == 2:
            query = args[1].strip()
            if not (query.startswith("@") or query.lstrip("-").isdigit()):
                await message.answer(
                    "Kanal username yoki chat ID kiriting; odam ID si uchun uning xabariga javob qilib /id yozing."
                )
                return
            try:
                target = await bot.get_chat(query)
            except Exception:
                await message.answer(
                    "Chat topilmadi. Botning shu chatga kirish huquqini tekshiring."
                )
                return
        name = getattr(target, "title", None) or getattr(target, "full_name", "")
        await message.answer(f"<b>{safe_html(name)}</b>\nID: <code>{target.id}</code>")

    @router.message(F.forward_origin)
    async def forwarded(message: types.Message):
        origin = message.forward_origin
        if isinstance(origin, types.MessageOriginHiddenUser):
            await message.answer(
                f"Yashirilgan foydalanuvchi: {safe_html(origin.sender_user_name)}. Telegram ID ni ko‘rsatmaydi."
            )
            return
        target = (
            origin.chat
            if isinstance(origin, types.MessageOriginChannel)
            else origin.sender_chat
            if isinstance(origin, types.MessageOriginChat)
            else origin.sender_user
        )
        name = getattr(target, "title", None) or getattr(target, "full_name", "")
        await message.answer(f"<b>{safe_html(name)}</b>\nID: <code>{target.id}</code>")

    @router.callback_query(F.data.startswith("phone:"))
    @safe_handler
    async def phone_selection(call: types.CallbackQuery, state: FSMContext):
        await call.answer()
        key = call.data.partition(":")[2]
        data = await state.get_data()
        if key not in data.get("phone_choices", {}):
            raise BusinessRuleError("Telefon tanlovi eskirgan yoki noto‘g‘ri.")
        phone_id = data["phone_choices"][key]
        phone = await io_worker.call(
            sheets_service.get_phone_by_id, phone_id, fresh=True
        )
        if not phone:
            raise BusinessRuleError("Telefon topilmadi.")
        current = await state.get_state()
        from bot_harid.handlers.harid_flow import imei_searched, process_karobka_imei
        from bot_sotuv.handlers.sotuv_flow import imei_entered
        from bot_harajat.handlers.harajat_flow import (
            remont_imei_entered,
            phone_debt_imei_entered,
        )

        handlers = {
            "SotuvStates:waiting_imei": imei_entered,
            "ChannelPostStates:waiting_imei_search": imei_searched,
            "KarobkaStates:waiting_imei": process_karobka_imei,
            "ChiqimStates:waiting_remont_imei": remont_imei_entered,
            "ChiqimStates:waiting_phone_debt_imei": phone_debt_imei_entered,
        }
        if current not in handlers:
            raise BusinessRuleError("Bu holatda telefon tanlab bo‘lmaydi.")
        await state.update_data(selected_phone_id=phone_id)
        selected_message = call.message.model_copy(
            update={"text": str(phone["IMEI"]), "from_user": call.from_user}
        )
        await handlers[current](selected_message, state)

    return router
