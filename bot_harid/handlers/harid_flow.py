import os
import re
import uuid
import tempfile
import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

import config
from bot_harid.states import HaridStates, ChannelPostStates
from bot_harid.keyboards import (
    main_menu_kb,
    cancel_kb,
    skip_or_cancel_kb,
    skip_inline_kb,
    brand_kb,
    memory_kb,
    box_kb,
    payment_type_kb,
    yes_no_kb,
    post_channel_kb,
)
from services.google_sheets import sheets_service
from services.google_drive import drive_service
from services.telegram_poster import poster_service
from services.health_check import health_checker
from utils.formatters import build_purchase_summary, extract_drive_file_id

logger = logging.getLogger(__name__)
router = Router()


def clean_currency(text: str) -> str:
    """Valyuta kiritilganda faqat raqamlarni oladi va dubl $ larni oldini oladi."""
    cleaned = re.sub(r"[^\d.]", "", text.strip())
    return cleaned if cleaned else "0"


@router.message(Command("status"))
@router.message(Command("check"))
async def cmd_check_status(message: types.Message, bot: Bot):
    """Admin uchun tizim konfiguratsiyasi diagnostikasini chiqaradi."""
    user_id = message.from_user.id
    if not config.ADMIN_IDS or user_id not in config.ADMIN_IDS:
        await message.answer("Ushbu buyruq faqat bot adminlari uchun!")
        return

    msg = await message.answer("🔍 Diagnostika o'tkazilmoqda...")
    is_ready, report, _ = await health_checker.run_diagnostics(bot)
    await msg.edit_text(report)


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    user_id = message.from_user.id

    # 1. Tizim to'liq sozlanganmi tekshirish
    is_ready, report, _ = await health_checker.run_diagnostics(bot)
    if not is_ready:
        # Agar admin bo'lsa (yoki admin hali belgilanmagan bo'lsa) adminga to'liq kamchiliklar ro'yxatini ko'rsatadi
        if not config.ADMIN_IDS or user_id in config.ADMIN_IDS:
            await message.answer(
                f"{report}\n\n"
                "💡 <i>Iltimos, yuqoridagi ❌ belgilangan konfiguratsiyalarni .env faylida to'ldiring.</i>"
            )
        else:
            await message.answer(
                "⚠️ <b>Bot hozirda sozlanish bosqichida!</b>\n\n"
                "Barcha tizim sozlamalari yakunlangach bot to'liq ishga tushadi. "
                "Iltimos, do'kon ma'muriyatiga murojaat qiling.",
                reply_markup=types.ReplyKeyboardRemove(),
            )
        return

    # 2. Foydalanuvchini Google Sheets dan tekshirish
    is_active, role, name = sheets_service.check_member(user_id, force_refresh=True)

    if not is_active:
        await message.answer(
            "⛔ <b>Kechirasiz, sizga botdan foydalanish uchun ruxsat berilmagan!</b>\n\n"
            f"Sizning Telegram ID: <code>{user_id}</code>\n"
            "Iltimos, do'kon ma'muriyatiga murojaat qiling.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return

    if role == "Investor":
        await message.answer(
            f"⛔ <b>Kechirasiz, {name}!</b>\n\n"
            "Investorlar uchun ushbu botda amallar bajarish ko'zda tutilmagan.\n"
            "Moliyaviy ko'rsatkichlarni ko'rish uchun <b>Harajat Boti</b>dan foydalaning.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return

    await message.answer(
        f"Assalomu alaykum, <b>{name}</b>!\n"
        f"Sizning rolingiz: <b>{role}</b>\n\n"
        "OymaOy Harid botiga xush kelibsiz. Quyidagi menyudan kerakli bo'limni tanlang:",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "🚫 Bekor qilish")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active or role == "Investor":
        await message.answer("Jarayon bekor qilindi.", reply_markup=types.ReplyKeyboardRemove())
    else:
        await message.answer("Jarayon bekor qilindi.", reply_markup=main_menu_kb())


@router.channel_post(Command("id"))
async def channel_post_id(message: types.Message):
    """Kanalning o'zida /id yozilganda ishlaydi."""
    chat = message.chat
    await message.reply(
        f"📢 <b>Kanal ma'lumotlari:</b>\n\n"
        f"🏷 Nomi: <b>{chat.title}</b>\n"
        f"🔗 Username: @{chat.username or 'mavjud emas'}\n"
        f"🆔 <b>Kanal ID:</b> <code>{chat.id}</code>\n\n"
        f"<i>(Ushbu ID ni nusxalab .env fayliga qo'yishingiz mumkin)</i>"
    )


@router.message(F.forward_from_chat)
async def forward_from_chat_handler(message: types.Message):
    """Kanaldan botga xabar forward qilinganda uning ID sini chiqaradi."""
    f_chat = message.forward_from_chat
    await message.reply(
        f"📢 <b>Forward qilingan kanal/guruh:</b>\n\n"
        f"🏷 Nomi: <b>{f_chat.title or 'Noma\'lum'}</b>\n"
        f"📁 Turi: <code>{f_chat.type}</code>\n"
        f"🔗 Username: @{f_chat.username or 'mavjud emas'}\n"
        f"🆔 <b>Kanal ID:</b> <code>{f_chat.id}</code>\n\n"
        f"<i>(Ushbu ID ni nusxalab .env fayliga qo'yishingiz mumkin)</i>"
    )


@router.message(F.forward_from)
async def forward_from_user_handler(message: types.Message):
    """Foydalanuvchining xabari botga forward qilinganda uning ID sini chiqaradi."""
    f_user = message.forward_from
    await message.reply(
        f"👤 <b>Forward qilingan foydalanuvchi:</b>\n\n"
        f"🏷 Ismi: <b>{f_user.full_name}</b>\n"
        f"🔗 Username: @{f_user.username or 'mavjud emas'}\n"
        f"🆔 <b>Telegram ID:</b> <code>{f_user.id}</code>\n\n"
        f"<i>(Ushbu ID ni nusxalab Xodimlar bazasiga yoki adminlar ro'yxatiga qo'yishingiz mumkin)</i>"
    )


@router.message(Command("id"))
async def get_chat_id(message: types.Message, bot: Bot):
    # 1. Agar birorta odamning xabariga REPLY qilib /id yozilgan bo'lsa
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        if target_user:
            await message.reply(
                f"👤 <b>Foydalanuvchi ma'lumotlari:</b>\n\n"
                f"🏷 Ismi: <b>{target_user.full_name}</b>\n"
                f"🔗 Username: @{target_user.username or 'mavjud emas'}\n"
                f"🆔 <b>Telegram ID:</b> <code>{target_user.id}</code>\n\n"
                f"<i>(Ushbu ID ni nusxalab olishingiz mumkin)</i>"
            )
            return

    # 2. Agar /id @username yoki /id -100... deb yozilgan bo'lsa
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and (args[1].startswith("@") or args[1].startswith("-100")):
        target = args[1].strip()
        try:
            target_chat = await bot.get_chat(target)
            await message.reply(
                f"📢 <b>Qidirilgan chat/kanal ma'lumotlari:</b>\n\n"
                f"🏷 Nomi: <b>{target_chat.title or target_chat.full_name}</b>\n"
                f"📁 Turi: <code>{target_chat.type}</code>\n"
                f"🔗 Username: @{target_chat.username or 'mavjud emas'}\n"
                f"🆔 <b>ID:</b> <code>{target_chat.id}</code>\n\n"
                f"<i>(Ushbu ID ni nusxalab olishingiz mumkin)</i>"
            )
            return
        except Exception:
            await message.reply(
                f"ℹ️ <b>'{target}' topilmadi!</b>\n\n"
                "💡 <i>Eslatma: Telegram qoidasiga ko'ra botlar odamlarni username orqali to'g'ridan-to'g'ri qidira olmaydi (faqat kanallar va ommaviy guruhlarni topa oladi).\n\n"
                "Odamning ID sini olish uchun:\n"
                "1. O'sha odam yozgan biron bir xabarni botga <b>Forward</b> (Переслать) qiling\n"
                "2. Yoki guruhda uning xabariga <b>Reply</b> (Javob) qilib <code>/id</code> deb yozing!</i>"
            )
            return

    # 3. Joriy chat yoki shaxsiy chat ma'lumoti
    chat = message.chat
    chat_type = chat.type
    chat_title = chat.title or chat.full_name or "Noma'lum"
    chat_id = chat.id

    text = (
        f"📋 <b>Chat ma'lumotlari:</b>\n\n"
        f"🏷 Nomi: <b>{chat_title}</b>\n"
        f"📁 Turi: <code>{chat_type}</code>\n"
        f"🆔 <b>Chat ID:</b> <code>{chat_id}</code>\n"
    )
    if message.from_user and chat_type in ["group", "supergroup"]:
        text += f"\n👤 <b>Sizning shaxsiy ID:</b> <code>{message.from_user.id}</code>\n"

    text += "\n<i>(Ushbu ID ni nusxalab olishingiz mumkin)</i>"
    await message.reply(text)


# ==========================================
# 1. HARID QILISH OQIMI (FSM)
# ==========================================

@router.message(F.text == "📥 Harid qilish")
async def start_purchase(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, role, name = sheets_service.check_member(user_id)
    if not is_active or role == "Investor":
        await message.answer("Sizga ruxsat berilmagan.")
        return

    # Xodimlar jadvalidan oluvchining F.I.Sh sini olish
    buyer_name = sheets_service.get_staff_name_by_tg_id(user_id) or (name if name != "Bosh Admin" else "") or message.from_user.full_name

    await state.clear()
    await state.update_data(buyer_staff_name=buyer_name, buyer_staff_id=user_id)
    await state.set_state(HaridStates.choosing_brand)
    await message.answer("📱 Qurilma haridi boshlandi.", reply_markup=cancel_kb())
    await message.answer(
        "<b>Qanday rusumdagi qurilma harid qilinmoqda?</b>",
        reply_markup=brand_kb(),
    )


@router.callback_query(HaridStates.choosing_brand, F.data.startswith("brand:"))
async def brand_chosen(call: types.CallbackQuery, state: FSMContext):
    brand = call.data.split(":")[1]
    await state.update_data(brand=brand)
    await call.message.delete()

    if brand == "iPhone":
        # Google sheets dan modellar olinadi
        models = sheets_service.get_models()
        # Versiyalarni ajratib olish (X dan boshlab)
        versions = []
        for m in models:
            v = str(m.get("Versiya", "")).strip()
            if v and v not in versions:
                versions.append(v)

        if not versions:
            versions = ["X", "XS", "XR", "11", "12", "13", "14", "15", "16"]

        # Klaviaturani 3 qatordan tuzish
        kb_rows = []
        row = []
        for v in versions:
            row.append(InlineKeyboardButton(text=f"iPhone {v}", callback_data=f"ver:{v}"))
            if len(row) == 3:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)

        await state.set_state(HaridStates.choosing_version)
        await call.message.answer(
            "🍏 <b>iPhone versiyasini tanlang:</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        )
    elif brand == "Android":
        await state.set_state(HaridStates.input_custom_model)
        await call.message.answer(
            "✍️ <b>Android telefon modelining to'liq nomini yozing:</b>\n<i>(Masalan: Samsung S24 Ultra yoki Xiaomi 14)</i>",
            reply_markup=cancel_kb(),
        )
    else:
        await state.set_state(HaridStates.input_custom_model)
        await call.message.answer(
            "✍️ <b>Qurilma modelining to'liq nomini yozing:</b>\n<i>(Masalan: iPad Air 5, Apple Watch yoki AirPods Pro)</i>",
            reply_markup=cancel_kb(),
        )


@router.callback_query(HaridStates.choosing_version, F.data.startswith("ver:"))
async def version_chosen(call: types.CallbackQuery, state: FSMContext):
    version = call.data.split(":")[1]
    await state.update_data(version=version)
    await call.message.delete()

    # Shu versiyaga mos turlarni olish
    models = sheets_service.get_models()
    types_list = []
    for m in models:
        if str(m.get("Versiya", "")).strip().lower() == version.strip().lower():
            raw_types = str(m.get("Turlari", m.get("Turi", "")))
            for t in raw_types.split(","):
                t_clean = t.strip()
                if t_clean and t_clean.lower() not in ["-", "yo'q", "yoq", "none"]:
                    if t_clean not in types_list:
                        types_list.append(t_clean)

    # 1. AGAR TUR UMUMAN YO'Q BO'LSA (masalan: iPhone X, XR):
    if len(types_list) == 0:
        full_model = f"iPhone {version}".strip()
        await state.update_data(type="", model=full_model)
        await state.set_state(HaridStates.waiting_imei_photo)
        await call.message.answer(
            f"✅ Tanlandi: <b>{full_model}</b>\n\n"
            "📸 <b>IMEI rasmini</b> yuboring:\n"
            "<i>(Faqat 1 ta rasm qabul qilinadi yoki '⏭ Tashlab ketish'ni bosing)</i>",
            reply_markup=skip_inline_kb("skip_imei_photo"),
        )
        return

    # 2. AGAR FAQAT 1 TA TUR BO'LSA (avtomatik o'sha tur tanlanib ketadi):
    if len(types_list) == 1:
        single_t = types_list[0]
        if single_t.lower() in [version.lower(), "oddiy", "standart"]:
            full_model = f"iPhone {version}".strip()
            type_val = ""
        elif version.lower() in single_t.lower():
            full_model = f"iPhone {single_t}".strip()
            type_val = single_t
        else:
            full_model = f"iPhone {version} {single_t}".strip()
            type_val = single_t

        await state.update_data(type=type_val, model=full_model)
        await state.set_state(HaridStates.waiting_imei_photo)
        await call.message.answer(
            f"✅ Tanlandi: <b>{full_model}</b>\n\n"
            "📸 <b>IMEI rasmini</b> yuboring:\n"
            "<i>(Faqat 1 ta rasm qabul qilinadi yoki '⏭ Tashlab ketish'ni bosing)</i>",
            reply_markup=skip_inline_kb("skip_imei_photo"),
        )
        return

    # 3. AGAR TURLAR 1 TADAN KO'P BO'LSA — TANLASH TUGMALARI CHIQADI:
    kb_rows = []
    row = []
    for t in types_list:
        if t.lower() in [version.lower(), "oddiy", "standart"]:
            btn_text = f"{version}"
        elif version.lower() in t.lower():
            btn_text = f"{t}"
        else:
            btn_text = f"{version} {t}"

        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"type:{t}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)

    await state.set_state(HaridStates.choosing_type)
    await call.message.answer(
        f"🍏 <b>iPhone {version} turini tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.callback_query(HaridStates.choosing_type, F.data.startswith("type:"))
async def type_chosen(call: types.CallbackQuery, state: FSMContext):
    phone_type = call.data.split(":")[1]
    data = await state.get_data()
    version = data.get("version", "")

    if phone_type.lower() in [version.lower(), "oddiy", "standart"]:
        full_model = f"iPhone {version}".strip()
        type_val = ""
    elif version.lower() in phone_type.lower():
        full_model = f"iPhone {phone_type}".strip()
        type_val = phone_type
    else:
        full_model = f"iPhone {version} {phone_type}".strip()
        type_val = phone_type

    await state.update_data(type=type_val, model=full_model)
    await call.message.delete()

    await state.set_state(HaridStates.waiting_imei_photo)
    await call.message.answer(
        f"✅ Tanlandi: <b>{full_model}</b>\n\n"
        "📸 <b>IMEI rasmini</b> yuboring:\n"
        "<i>(Faqat 1 ta rasm qabul qilinadi yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_imei_photo"),
    )


@router.message(HaridStates.input_custom_model)
async def custom_model_entered(message: types.Message, state: FSMContext):
    model_name = message.text.strip()
    data = await state.get_data()
    brand = data.get("brand", "Boshqa")
    await state.update_data(model=model_name, version=model_name, type="Boshqa")

    await state.set_state(HaridStates.waiting_imei_photo)
    await message.answer(
        f"✅ Model: <b>{model_name}</b>\n\n"
        "📸 <b>IMEI / Seriya raqami rasmini</b> yuboring:\n"
        "<i>(Faqat 1 ta rasm qabul qilinadi yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_imei_photo"),
    )


@router.callback_query(HaridStates.waiting_imei_photo, F.data == "skip_imei_photo")
async def imei_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(imei_photo_file_id=None)
    await state.set_state(HaridStates.choosing_memory)
    await call.message.answer(
        "💾 <b>Xotirasini tanlang:</b>\n<i>(Tugmalardan tanlang, yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=memory_kb(),
    )


@router.message(HaridStates.waiting_imei_photo, F.photo)
async def imei_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    file_id = photo.file_id

    await state.update_data(imei_photo_file_id=file_id)
    await state.set_state(HaridStates.choosing_memory)
    await message.answer(
        "💾 <b>Xotirasini tanlang:</b>\n<i>(Tugmalardan tanlang, yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=memory_kb(),
    )


@router.message(HaridStates.waiting_imei_photo, F.text.in_(["⏭ Tashlab ketish", "Tashlab ketish"]))
async def imei_photo_skipped(message: types.Message, state: FSMContext):
    await state.update_data(imei_photo_file_id=None)
    await state.set_state(HaridStates.choosing_memory)
    await message.answer(
        "💾 <b>Xotirasini tanlang:</b>\n<i>(Tugmalardan tanlang, yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=memory_kb(),
    )


@router.callback_query(HaridStates.choosing_memory, F.data.startswith("mem:"))
async def memory_chosen(call: types.CallbackQuery, state: FSMContext):
    mem = call.data.split(":")[1]
    await state.update_data(memory=mem)
    try:
        await call.message.delete()
    except Exception:
        pass

    await state.set_state(HaridStates.waiting_battery)
    mem_text = "" if mem == "-" else f"Tanlandi: <b>{mem}</b>\n\n"
    await call.message.answer(
        f"{mem_text}🔋 <b>Batareya foizini (%) kiriting:</b>\n<i>(Masalan: 88 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_battery"),
    )


@router.message(HaridStates.choosing_memory)
async def memory_message_handler(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        mem = "-"
    else:
        mem = message.text.strip()

    await state.update_data(memory=mem)
    await state.set_state(HaridStates.waiting_battery)
    mem_text = "" if mem == "-" else f"Xotira: <b>{mem}</b>\n\n"
    await message.answer(
        f"{mem_text}🔋 <b>Batareya foizini (%) kiriting:</b>\n<i>(Masalan: 88 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_battery"),
    )


@router.callback_query(HaridStates.waiting_battery, F.data == "skip_battery")
async def battery_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(battery="-")
    await state.set_state(HaridStates.waiting_color)
    await call.message.answer(
        "🎨 <b>Rangini kiriting:</b>\n<i>(Masalan: Qora, Moviy yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_color"),
    )


@router.message(HaridStates.waiting_battery)
async def battery_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        battery_val = "-"
    else:
        text = clean_currency(message.text)
        if not text.isdigit() or not (1 <= int(text) <= 100):
            await message.answer(
                "Iltimos, batareya foizini 1 dan 100 gacha raqamda kiriting yoki '⏭ Tashlab ketish'ni bosing:",
                reply_markup=skip_inline_kb("skip_battery"),
            )
            return
        battery_val = text

    await state.update_data(battery=battery_val)
    await state.set_state(HaridStates.waiting_color)
    await message.answer(
        "🎨 <b>Rangini kiriting:</b>\n<i>(Masalan: Qora, Moviy yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_color"),
    )


@router.callback_query(HaridStates.waiting_color, F.data == "skip_color")
async def color_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(color="-")
    await state.set_state(HaridStates.waiting_imei_6)
    await call.message.answer(
        "🔢 <b>IMEI yoki Seriya raqamini kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_color)
async def color_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        color = "-"
    else:
        color = message.text.strip()
    await state.update_data(color=color)

    await state.set_state(HaridStates.waiting_imei_6)
    await message.answer(
        "🔢 <b>IMEI yoki Seriya raqamini kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_imei_6)
async def imei_6_entered(message: types.Message, state: FSMContext):
    imei = message.text.strip()
    if len(imei) < 4:
        await message.answer("Iltimos, to'g'ri IMEI kodini kiriting:")
        return

    await state.update_data(imei=imei, imei_6=imei)

    await state.set_state(HaridStates.waiting_box)
    await message.answer(
        f"Qabul qilindi: <code>{imei}</code>\n\n📦 <b>Karobka-hujjati bormi?</b>",
        reply_markup=box_kb(),
    )


@router.message(HaridStates.waiting_box, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def box_chosen(message: types.Message, state: FSMContext):
    has_box = "Ha" if "Ha" in message.text else "Yo'q"
    await state.update_data(has_box=has_box)

    await state.set_state(HaridStates.waiting_buy_price)
    await message.answer(
        "💵 <b>Sotib olish narxini kiriting ($):</b>\n<i>(Masalan: 450 yoki $450)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_buy_price)
async def buy_price_entered(message: types.Message, state: FSMContext):
    price = clean_currency(message.text)
    if not price or float(price) <= 0:
        await message.answer("Iltimos, to'g'ri narx kiriting ($ da):")
        return

    await state.update_data(buy_price=price)
    await state.set_state(HaridStates.waiting_seller_name)
    await message.answer(
        "👤 <b>Egasining ismini kiriting:</b>\n<i>(Masalan: Akmal yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_seller_name"),
    )


@router.callback_query(HaridStates.waiting_seller_name, F.data == "skip_seller_name")
async def seller_name_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(seller_name="Mijoz")
    await state.set_state(HaridStates.waiting_seller_phone)
    await call.message.answer(
        "📞 <b>Egasining telefon raqamini kiriting:</b>\n<i>(Masalan: +998901234567 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_seller_phone"),
    )


@router.message(HaridStates.waiting_seller_name)
async def seller_name_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        name = "Mijoz"
    else:
        name = message.text.strip()
    await state.update_data(seller_name=name)

    await state.set_state(HaridStates.waiting_seller_phone)
    await message.answer(
        "📞 <b>Egasining telefon raqamini kiriting:</b>\n<i>(Masalan: +998901234567 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_seller_phone"),
    )


@router.callback_query(HaridStates.waiting_seller_phone, F.data == "skip_seller_phone")
async def seller_phone_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(seller_phone="-")
    await state.set_state(HaridStates.waiting_payment_type)
    await call.message.answer(
        "💳 <b>Puli qanday to'landi?</b>",
        reply_markup=payment_type_kb(),
    )


@router.message(HaridStates.waiting_seller_phone)
async def seller_phone_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        phone = "-"
    else:
        phone = message.text.strip()
    await state.update_data(seller_phone=phone)

    await state.set_state(HaridStates.waiting_payment_type)
    await message.answer(
        "💳 <b>Puli qanday to'landi?</b>",
        reply_markup=payment_type_kb(),
    )


@router.message(HaridStates.waiting_payment_type, F.text.in_(["💵 Naqd", "💳 Qarzga"]))
async def payment_type_chosen(message: types.Message, state: FSMContext):
    ptype = "Naqd" if "Naqd" in message.text else "Qarz"
    await state.update_data(payment_type=ptype)

    if ptype == "Qarz":
        data = await state.get_data()
        await state.update_data(debt_amount=data.get("buy_price", 0))
    else:
        await state.update_data(debt_amount="0")

    # Tasdiqlash xulosasini ko'rsatish
    data = await state.get_data()
    if not data.get("buyer_staff_name"):
        buyer_name = sheets_service.get_staff_name_by_tg_id(message.from_user.id) or message.from_user.full_name
        await state.update_data(buyer_staff_name=buyer_name)
        data["buyer_staff_name"] = buyer_name

    summary = build_purchase_summary(data)

    photo_file_id = data.get("imei_photo_file_id")
    await state.set_state(HaridStates.confirm_purchase)
    if photo_file_id:
        await message.answer_photo(
            photo=photo_file_id,
            caption=summary,
            reply_markup=yes_no_kb(),
        )
    else:
        await message.answer(summary, reply_markup=yes_no_kb())


@router.message(HaridStates.confirm_purchase, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def confirm_purchase_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("Harid bekor qilindi.", reply_markup=main_menu_kb())
        return

    data = await state.get_data()
    if not data.get("buyer_staff_name"):
        buyer_name = sheets_service.get_staff_name_by_tg_id(message.from_user.id) or message.from_user.full_name
        data["buyer_staff_name"] = buyer_name

    loading_msg = await message.answer("⏳ Ma'lumotlar saqlanmoqda, iltimos kuting...")

    file_id = data.get("imei_photo_file_id")
    formula = ""
    # 1. Agar Drive ulangan bo'lsa, rasmni vaqtincha olib Drive ga yuklaymiz va darhol o'chirib tashlaymiz
    if file_id and drive_service.is_connected() and config.DRIVE_FOLDER_ID:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            await bot.download(file_id, destination=tmp_path)
            imei_val = data.get("imei", data.get("imei_6", "unknown"))
            filename = f"imei_{imei_val}.jpg"
            view_link, _, formula = drive_service.upload_photo(tmp_path, filename)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    data["imei_photo_url"] = formula

    # 2. Google Sheets ga yozish
    sheets_service.add_phone(data)

    # 3. Sotib oldi guruhiga xabar yuborish
    group_msg_id = await poster_service.post_to_buy_group(bot, data, file_id)

    try:
        await loading_msg.delete()
    except Exception:
        pass

    group_status_note = ""
    if not group_msg_id:
        group_status_note = "\n⚠️ <i>(Eslatma: Harid guruhiga xabar yuborilmadi. Bot guruhda admin ekanini tekshiring)</i>"

    item_type = "qurilma" if data.get("brand") == "Boshqa" else "telefon"
    await message.answer(
        f"✅ <b>Yangi {item_type} muvaffaqiyatli qabul qilindi va bazaga saqlandi!</b>"
        f"{group_status_note}\n\n"
        f"📢 <b>Ushbu {item_type} uchun Telegram kanalga e'lon joylansinmi?</b>",
        reply_markup=post_channel_kb(),
    )
    await state.set_state(HaridStates.ask_post_channel)


@router.message(HaridStates.ask_post_channel, F.text.in_(["📢 Joylash", "Joylash", "✅ Ha", "Ha", "❌ Yo'q", "Yo'q"]))
async def ask_post_channel_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text in ["❌ Yo'q", "Yo'q"]:
        await state.clear()
        await message.answer("Tushunarli. Jarayon yakunlandi.", reply_markup=main_menu_kb())
        return

    data = await state.get_data()
    item_label = "qurilmaning" if data.get("brand") == "Boshqa" else "telefonning"

    await state.set_state(HaridStates.waiting_channel_photo)
    await message.answer(
        "📢 <b>Kanalga e'lon berish jarayoni:</b>",
        reply_markup=cancel_kb(),
    )
    await message.answer(
        f"📸 <b>{item_label.capitalize()} o'zini rasmini yuboring:</b>\n"
        "<i>(Faqat 1 ta sifatli rasm yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_channel_photo"),
    )


@router.callback_query(HaridStates.waiting_channel_photo, F.data == "skip_channel_photo")
async def channel_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    # Haridda olingan IMEI rasmi bo'lsa o'shani ishlatamiz
    imei_photo = data.get("imei_photo_file_id")
    await state.update_data(phone_photo_file_id=imei_photo)
    await state.set_state(HaridStates.waiting_sell_price)
    await call.message.answer(
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 550)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_channel_photo, F.text.in_(["⏭ Tashlab ketish", "Tashlab ketish"]))
async def channel_photo_skipped(message: types.Message, state: FSMContext):
    data = await state.get_data()
    # Haridda olingan IMEI rasmi bo'lsa o'shani ishlatamiz
    imei_photo = data.get("imei_photo_file_id")
    await state.update_data(phone_photo_file_id=imei_photo)
    await state.set_state(HaridStates.waiting_sell_price)
    await message.answer(
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 550)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_channel_photo, F.photo)
async def channel_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    await state.update_data(phone_photo_file_id=photo.file_id)
    await state.set_state(HaridStates.waiting_sell_price)
    await message.answer(
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 550)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_sell_price)
async def sell_price_received(message: types.Message, state: FSMContext, bot: Bot):
    price = clean_currency(message.text)
    if not price or float(price) <= 0:
        await message.answer("Iltimos, to'g'ri sotuv narxi kiriting ($ da):")
        return

    data = await state.get_data()
    data["sell_price"] = price

    loading_msg = await message.answer("⏳ <b>E'lon kanalga joylanmoqda, iltimos kuting...</b>")

    photo_file_id = data.get("phone_photo_file_id")
    imei_val = data.get("imei", data.get("imei_6", "phone"))

    # Rasmni Drive ga yuklash (agar Drive ulangan bo'lsa) va vaqtincha faylni darhol o'chirish
    formula = ""
    if photo_file_id and drive_service.is_connected() and config.DRIVE_FOLDER_ID:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            await bot.download(photo_file_id, destination=tmp_path)
            filename = f"phone_{imei_val}.jpg"
            view_link, _, formula = drive_service.upload_photo(tmp_path, filename)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    data["phone_photo_url"] = formula

    # Kanalga post qilish (Telegram file_id orqali)
    post_id = await poster_service.post_to_channel(bot, data, photo_file_id)

    # Google Sheets dagi telefon qatorini yangilash
    phone_rec = sheets_service.get_phone_by_imei(imei_val)
    if phone_rec and "_row_index" in phone_rec:
        sheets_service.update_phone(
            phone_rec["_row_index"],
            {
                "Telefon rasmi": formula,
                "Sotuv narxi ($)": price,
                "Holati": "Sotuvda",
                "Kanal post ID": str(post_id or ""),
            },
        )

    try:
        await loading_msg.delete()
    except Exception:
        pass

    await state.clear()
    if post_id:
        await message.answer(
            "🚀 <b>E'lon Telegram kanalga muvaffaqiyatli joylandi!</b>",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer(
            "⚠️ <b>Ma'lumotlar bazaga saqlandi, lekin Telegram kanalga e'lon joylanmadi!</b>\n\n"
            "<i>(Sabab: Bot kanalda admin emas yoki kanal ID si noto'g'ri sozlangan bo'lishi mumkin)</i>",
            reply_markup=main_menu_kb(),
        )


# ==========================================
# 2. ALOHIDA KANALGA E'LON BERISH OQIMI
# ==========================================

@router.message(F.text == "📢 Telegram kanalga e'lon berish")
async def start_channel_post(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active or role == "Investor":
        await message.answer("Sizga ruxsat berilmagan.")
        return

    await state.clear()
    await state.set_state(ChannelPostStates.waiting_imei_search)
    await message.answer(
        "🔍 <b>E'lon bermoqchi bo'lgan qurilmaning IMEI yoki Seriya raqamini kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(ChannelPostStates.waiting_imei_search)
async def imei_searched(message: types.Message, state: FSMContext):
    imei_input = message.text.strip()
    if len(imei_input) < 4:
        await message.answer("Iltimos, to'g'ri IMEI yoki seriya raqamini kiriting:")
        return

    phone = sheets_service.get_phone_by_imei(imei_input)

    if not phone:
        await message.answer(
            f"❌ Bazadan <code>{imei_input}</code> raqamli qurilma topilmadi!\n"
            "Iltimos, IMEI yoki seriya raqamini tekshirib qaytadan kiriting:",
            reply_markup=cancel_kb(),
        )
        return

    actual_imei = phone.get("IMEI", phone.get("IMEI (oxirgi 6)", imei_input))
    model = phone.get("Model", "Qurilma")
    memory = phone.get("Xotira")
    battery = phone.get("Batareya %")
    color = phone.get("Rang")
    box = phone.get("Karobka")
    buy_price = phone.get("Harid narxi ($)") or phone.get("Jami tannarx ($)") or "0"
    channel_post_id = str(phone.get("Kanal post ID", "")).strip()
    prev_sell_price = str(phone.get("Sotuv narxi ($)", "")).strip()
    status = str(phone.get("Holati", "")).strip()

    existing_photo_field = phone.get("Telefon rasmi") or phone.get("IMEI rasmi") or ""
    drive_id = extract_drive_file_id(existing_photo_field)

    # Qurilma ma'lumotlarini state ga saqlash
    await state.update_data(
        imei=actual_imei,
        imei_6=actual_imei,
        model=model,
        memory=memory or "-",
        battery=battery or "-",
        color=color or "-",
        has_box=box or "Ha",
        buy_price=buy_price,
        existing_photo_url=existing_photo_field,
        existing_drive_id=drive_id,
        phone_photo_url=existing_photo_field,
        row_index=phone.get("_row_index"),
        channel_post_id=channel_post_id,
    )

    info_lines = [
        f"📱 Qurilma topildi: <b>{model}</b>",
    ]
    specs = []
    if memory and memory != "-":
        specs.append(f"💾 Xotira: {memory}")
    if battery and battery != "-":
        battery_str = f"{battery}%" if "%" not in str(battery) else str(battery)
        specs.append(f"🔋 {battery_str}")
    if specs:
        info_lines.append(" | ".join(specs))

    extra_specs = []
    if color and color != "-":
        extra_specs.append(f"🎨 Rang: {color}")
    if box and box != "-":
        extra_specs.append(f"📦 {box}")
    if extra_specs:
        info_lines.append(" | ".join(extra_specs))

    if buy_price and buy_price != "0":
        info_lines.append(f"💵 Tannarxi (Harid): <b>{buy_price}$</b>")
    info_lines.append(f"🔍 IMEI / Seriya: <code>{actual_imei}</code>")

    # Oldin kanalga e'lon berilgan bo'lsa Note
    is_already_posted = bool(channel_post_id) or bool(prev_sell_price and prev_sell_price not in ["", "0", "-"])
    if is_already_posted:
        info_lines.append("")
        info_lines.append("📢 <b>Eslatma: Ushbu qurilma uchun avval ham kanalga e'lon berilgan!</b>")
        if prev_sell_price and prev_sell_price not in ["", "0", "-"]:
            info_lines.append(f"💰 <b>Oldingi sotuv narxi:</b> {prev_sell_price}$")
        if channel_post_id:
            info_lines.append(f"🔗 <b>Kanal post ID:</b> #{channel_post_id}")

    info_lines.append("")
    if drive_id:
        info_lines.append("📸 <b>Kanalga chiqariladigan rasmni yuboring:</b>")
        info_lines.append("<i>(Yangi rasm yuboring yoki avvalgi rasmni qoldirish uchun '⏭ Tashlab ketish'ni bosing)</i>")
    else:
        info_lines.append("📸 <b>Endi ushbu qurilmaning kanalga chiqariladigan rasmini yuboring:</b>")
        info_lines.append("<i>(Faqat 1 ta rasm yoki '⏭ Tashlab ketish'ni bosing)</i>")

    info_text = "\n".join(info_lines)

    await state.set_state(ChannelPostStates.waiting_channel_photo)

    photo_sent = False
    if drive_id:
        try:
            photo_url = f"https://lh3.googleusercontent.com/d/{drive_id}"
            await message.answer_photo(
                photo=photo_url,
                caption=info_text,
                reply_markup=skip_inline_kb("skip_post_photo"),
            )
            photo_sent = True
        except Exception as e:
            logger.warning(f"Avvalgi rasmni ko'rsatishda xatolik ({e}), matn ko'rinishida yuboriladi.")

    if not photo_sent:
        await message.answer(info_text, reply_markup=skip_inline_kb("skip_post_photo"))


@router.callback_query(ChannelPostStates.waiting_channel_photo, F.data == "skip_post_photo")
async def post_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(ChannelPostStates.waiting_sell_price)
    await call.message.answer(
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 600)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(ChannelPostStates.waiting_channel_photo, F.text.in_(["⏭ Tashlab ketish", "Tashlab ketish"]))
async def post_photo_skipped(message: types.Message, state: FSMContext):
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(ChannelPostStates.waiting_sell_price)
    await message.answer(
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 600)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(ChannelPostStates.waiting_channel_photo, F.photo)
async def post_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    await state.update_data(phone_photo_file_id=photo.file_id)
    await state.set_state(ChannelPostStates.waiting_sell_price)
    await message.answer(
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 600)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(ChannelPostStates.waiting_sell_price)
async def post_sell_price_received(message: types.Message, state: FSMContext, bot: Bot):
    price = clean_currency(message.text)
    if not price or float(price) <= 0:
        await message.answer("Iltimos, to'g'ri sotuv narxi kiriting ($ da):")
        return

    data = await state.get_data()
    data["sell_price"] = price

    loading_msg = await message.answer("⏳ <b>E'lon kanalga joylanmoqda, iltimos kuting...</b>")

    photo_file_id = data.get("phone_photo_file_id")
    existing_drive_id = data.get("existing_drive_id")
    existing_photo_url = data.get("existing_photo_url", "")
    imei_val = data.get("imei", data.get("imei_6", "phone"))

    formula = existing_photo_url or ""
    photo_to_post = None

    # 1. Agar yangi rasm yuklangan bo'lsa Drive ga yuklaymiz
    if photo_file_id:
        if drive_service.is_connected() and config.DRIVE_FOLDER_ID:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                await bot.download(photo_file_id, destination=tmp_path)
                filename = f"phone_{imei_val}.jpg"
                view_link, _, formula = drive_service.upload_photo(tmp_path, filename)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        photo_to_post = photo_file_id
    elif existing_drive_id:
        # Yangi rasm yuklanmagan, lekin mavjud rasm bor
        photo_to_post = f"https://lh3.googleusercontent.com/d/{existing_drive_id}"

    data["phone_photo_url"] = formula

    # 2. Kanalga post qilish (Telegram file_id yoki URL orqali)
    post_id = await poster_service.post_to_channel(bot, data, photo_to_post)

    # 3. Google Sheets ni yangilash
    row_idx = data.get("row_index")
    if row_idx:
        sheets_service.update_phone(
            row_idx,
            {
                "Telefon rasmi": formula,
                "Sotuv narxi ($)": price,
                "Holati": "Sotuvda",
                "Kanal post ID": str(post_id or ""),
            },
        )

    try:
        await loading_msg.delete()
    except Exception:
        pass

    await state.clear()
    if post_id:
        await message.answer(
            "🚀 <b>E'lon Telegram kanalga muvaffaqiyatli joylandi!</b>",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer(
            "⚠️ <b>Qurilma ma'lumotlari yangilandi, lekin Telegram kanalga e'lon joylanmadi!</b>\n\n"
            "<i>(Sabab: Bot kanalda admin emas yoki kanal ID si noto'g'ri sozlangan bo'lishi mumkin)</i>",
            reply_markup=main_menu_kb(),
        )
