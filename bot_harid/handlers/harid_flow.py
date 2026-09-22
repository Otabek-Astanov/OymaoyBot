import os
import re
import uuid
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
    brand_kb,
    memory_kb,
    box_kb,
    payment_type_kb,
    yes_no_kb,
)
from services.google_sheets import sheets_service
from services.google_drive import drive_service
from services.telegram_poster import poster_service

logger = logging.getLogger(__name__)
router = Router()


def clean_currency(text: str) -> str:
    """Valyuta kiritilganda faqat raqamlarni oladi va dubl $ larni oldini oladi."""
    cleaned = re.sub(r"[^\d.]", "", text.strip())
    return cleaned if cleaned else "0"


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    is_active, role, name = sheets_service.check_member(user_id)

    if not is_active:
        await message.answer(
            "⛔ <b>Kechirasiz, sizga botdan foydalanish uchun ruxsat berilmagan!</b>\n\n"
            f"Sizning Telegram ID: <code>{user_id}</code>\n"
            "Iltimos, do'kon ma'muriyatiga murojaat qiling.",
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
    await message.answer("Jarayon bekor qilindi.", reply_markup=main_menu_kb())


# ==========================================
# 1. HARID QILISH OQIMI (FSM)
# ==========================================

@router.message(F.text == "📥 Harid qilish")
async def start_purchase(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, _, _ = sheets_service.check_member(user_id)
    if not is_active:
        await message.answer("Sizga ruxsat berilmagan.")
        return

    await state.clear()
    await state.set_state(HaridStates.choosing_brand)
    await message.answer(
        "📱 <b>Qanday rusumdagi telefon harid qilinmoqda?</b>",
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
    else:
        await state.set_state(HaridStates.input_custom_model)
        await call.message.answer(
            f"✍️ <b>{brand} modelining to'liq nomini yozing:</b>\n<i>(Masalan: Samsung S24 Ultra)</i>",
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
        if str(m.get("Versiya", "")).strip() == version:
            t = str(m.get("Turi", "")).strip()
            if t and t not in types_list:
                types_list.append(t)

    if not types_list:
        types_list = ["Oddiy", "Pro", "Pro Max", "Plus"]

    kb_rows = [
        [InlineKeyboardButton(text=f"{version} {t}", callback_data=f"type:{t}")]
        for t in types_list
    ]

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
    full_model = f"iPhone {version} {phone_type}".strip()
    await state.update_data(type=phone_type, model=full_model)
    await call.message.delete()

    await state.set_state(HaridStates.waiting_imei_photo)
    await call.message.answer(
        f"✅ Tanlandi: <b>{full_model}</b>\n\n"
        "📸 Endi telefonning <b>IMEI rasmini</b> yuboring:\n"
        "<i>(Faqat 1 ta rasm qabul qilinadi)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.input_custom_model)
async def custom_model_entered(message: types.Message, state: FSMContext):
    model_name = message.text.strip()
    await state.update_data(model=model_name, version=model_name, type="Boshqa")

    await state.set_state(HaridStates.waiting_imei_photo)
    await message.answer(
        f"✅ Model: <b>{model_name}</b>\n\n"
        "📸 Telefonning <b>IMEI rasmini</b> yuboring:\n"
        "<i>(Faqat 1 ta rasm qabul qilinadi)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_imei_photo, F.photo)
async def imei_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    file_id = photo.file_id

    # Rasmni yuklab olish
    os.makedirs("media", exist_ok=True)
    temp_filename = f"imei_{uuid.uuid4().hex[:8]}.jpg"
    local_path = os.path.join("media", temp_filename)
    await bot.download(photo, destination=local_path)

    await state.update_data(imei_photo_path=local_path, imei_photo_file_id=file_id)

    await state.set_state(HaridStates.choosing_memory)
    await message.answer(
        "💾 <b>Telefon xotirasini tanlang:</b>",
        reply_markup=memory_kb(),
    )


@router.callback_query(HaridStates.choosing_memory, F.data.startswith("mem:"))
async def memory_chosen(call: types.CallbackQuery, state: FSMContext):
    mem = call.data.split(":")[1]
    await state.update_data(memory=mem)
    await call.message.delete()

    await state.set_state(HaridStates.waiting_battery)
    await call.message.answer(
        "🔋 <b>Batareya foizini (%) kiriting:</b>\n<i>(Masalan: 88 yoki 100)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_battery)
async def battery_entered(message: types.Message, state: FSMContext):
    text = clean_currency(message.text)
    if not text.isdigit() or not (1 <= int(text) <= 100):
        await message.answer("Iltimos, batareya foizini 1 dan 100 gacha raqamda kiriting:")
        return

    await state.update_data(battery=text)
    await state.set_state(HaridStates.waiting_color)
    await message.answer(
        "🎨 <b>Telefon rangini kiriting:</b>\n<i>(Masalan: Qora, Moviy, Gold)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_color)
async def color_entered(message: types.Message, state: FSMContext):
    color = message.text.strip()
    await state.update_data(color=color)

    await state.set_state(HaridStates.waiting_imei_6)
    await message.answer(
        "🔢 <b>Telefon IMEI kodini (oxirgi 6 ta raqamini) kiriting:</b>\n<i>(Faqat 6 ta raqam)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_imei_6)
async def imei_6_entered(message: types.Message, state: FSMContext):
    digits = re.sub(r"\D", "", message.text.strip())
    if len(digits) < 6:
        await message.answer("Iltimos, IMEI ning kamida 6 ta raqamini kiriting:")
        return

    imei_6 = digits[-6:]
    await state.update_data(imei_6=imei_6)

    await state.set_state(HaridStates.waiting_box)
    await message.answer(
        f"IMEI qabul qilindi: <code>{imei_6}</code>\n\n📦 <b>Karobka-hujjati bormi?</b>",
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
        "👤 <b>Telefon egasining (sotuvchining) ismini kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_seller_name)
async def seller_name_entered(message: types.Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(seller_name=name)

    await state.set_state(HaridStates.waiting_seller_phone)
    await message.answer(
        "📞 <b>Telefon egasining telefon raqamini kiriting:</b>\n<i>(Masalan: +998901234567)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_seller_phone)
async def seller_phone_entered(message: types.Message, state: FSMContext):
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
    summary = (
        "📋 <b>HARID MA'LUMOTLARINI TASDIQLANG:</b>\n\n"
        f"📱 Model: <b>{data.get('model')}</b>\n"
        f"💾 Xotira: <b>{data.get('memory')}</b>\n"
        f"🔋 Batareya: <b>{data.get('battery')}%</b>\n"
        f"🎨 Rang: <b>{data.get('color')}</b>\n"
        f"📦 Karobka: <b>{data.get('has_box')}</b>\n"
        f"🔍 IMEI (oxirgi 6): <code>{data.get('imei_6')}</code>\n\n"
        f"💵 Harid narxi: <b>{data.get('buy_price')}$</b>\n"
        f"💳 To'lov turi: <b>{data.get('payment_type')}</b>\n"
        f"👤 Sotuvchi: <b>{data.get('seller_name')}</b> ({data.get('seller_phone')})\n\n"
        "<b>Ma'lumotlar to'g'rimi?</b>"
    )

    await state.set_state(HaridStates.confirm_purchase)
    await message.answer(summary, reply_markup=yes_no_kb())


@router.message(HaridStates.confirm_purchase, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def confirm_purchase_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("Harid bekor qilindi.", reply_markup=main_menu_kb())
        return

    data = await state.get_data()
    await message.answer("⏳ Ma'lumotlar saqlanmoqda, iltimos kuting...")

    # 1. Rasmni Drive ga yuklash
    local_photo = data.get("imei_photo_path")
    filename = f"imei_{data.get('imei_6')}.jpg"
    view_link, _, formula = drive_service.upload_photo(local_photo, filename)
    data["imei_photo_url"] = formula

    # 2. Google Sheets ga yozish
    sheets_service.add_phone(data)

    # 3. Sotib oldi guruhiga rasm bilan xabar yuborish
    if local_photo and os.path.exists(local_photo):
        await poster_service.post_to_buy_group(bot, data, local_photo)

    await message.answer(
        "✅ <b>Yangi telefon muvaffaqiyatli qabul qilindi va bazaga saqlandi!</b>\n\n"
        "📢 <b>Ushbu telefon uchun Telegram kanalga e'lon joylansinmi?</b>",
        reply_markup=yes_no_kb(),
    )
    await state.set_state(HaridStates.ask_post_channel)


@router.message(HaridStates.ask_post_channel, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def ask_post_channel_handler(message: types.Message, state: FSMContext):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("Tushunarli. Jarayon yakunlandi.", reply_markup=main_menu_kb())
        return

    await state.set_state(HaridStates.waiting_channel_photo)
    await message.answer(
        "📸 <b>Kanalga joylash uchun telefonning o'zini rasmini yuboring:</b>\n"
        "<i>(Faqat 1 ta sifatli rasm)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_channel_photo, F.photo)
async def channel_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    temp_filename = f"phone_{uuid.uuid4().hex[:8]}.jpg"
    local_path = os.path.join("media", temp_filename)
    await bot.download(photo, destination=local_path)

    await state.update_data(phone_photo_path=local_path)
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

    photo_path = data.get("phone_photo_path")
    imei_6 = data.get("imei_6")

    # Rasmni Drive ga yuklash
    filename = f"phone_{imei_6}.jpg"
    view_link, _, formula = drive_service.upload_photo(photo_path, filename)
    data["phone_photo_url"] = formula

    # Kanalga post qilish
    post_id = await poster_service.post_to_channel(bot, data, photo_path)

    # Google Sheets dagi telefon qatorini yangilash
    phone_rec = sheets_service.get_phone_by_imei(imei_6)
    if phone_rec and "_row_index" in phone_rec:
        sheets_service.update_phone(
            phone_rec["_row_index"],
            {
                "Telefon rasmi": formula,
                "Sotuv narxi ($)": price,
                "Holati": "Kanallangan",
                "Kanal post ID": str(post_id or ""),
            },
        )

    await state.clear()
    await message.answer(
        "🚀 <b>E'lon Telegram kanalga muvaffaqiyatli joylandi!</b>",
        reply_markup=main_menu_kb(),
    )


# ==========================================
# 2. ALOHIDA KANALGA E'LON BERISH OQIMI
# ==========================================

@router.message(F.text == "📢 Telegram kanalga e'lon berish")
async def start_channel_post(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, _, _ = sheets_service.check_member(user_id)
    if not is_active:
        await message.answer("Sizga ruxsat berilmagan.")
        return

    await state.clear()
    await state.set_state(ChannelPostStates.waiting_imei_search)
    await message.answer(
        "🔍 <b>E'lon bermoqchi bo'lgan telefonning IMEI kodini (oxirgi 6 ta raqamini) kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(ChannelPostStates.waiting_imei_search)
async def imei_searched(message: types.Message, state: FSMContext):
    digits = re.sub(r"\D", "", message.text.strip())
    if len(digits) < 6:
        await message.answer("Iltimos, kamida 6 ta raqam kiriting:")
        return

    imei_6 = digits[-6:]
    phone = sheets_service.get_phone_by_imei(imei_6)

    if not phone:
        await message.answer(
            f"❌ Bazadan <code>{imei_6}</code> raqamli telefon topilmadi!\n"
            "Iltimos, IMEI raqamni tekshirib qaytadan kiriting:",
            reply_markup=cancel_kb(),
        )
        return

    # Telefon ma'lumotlarini state ga saqlash
    await state.update_data(
        imei_6=imei_6,
        model=phone.get("Model", "iPhone"),
        memory=phone.get("Xotira", "128 GB"),
        battery=phone.get("Batareya %", "100"),
        color=phone.get("Rang", "-"),
        has_box=phone.get("Karobka", "Ha"),
        row_index=phone.get("_row_index"),
    )

    info = (
        f"📱 Telefon topildi: <b>{phone.get('Model')}</b>\n"
        f"💾 Xotira: {phone.get('Xotira')} | 🔋 {phone.get('Batareya %')}%\n"
        f"🎨 Rang: {phone.get('Rang')} | 📦 {phone.get('Karobka')}\n"
        f"🔍 IMEI: <code>{imei_6}</code>\n\n"
        "📸 <b>Endi ushbu telefonning kanalga chiqariladigan rasmini yuboring:</b>\n"
        "<i>(Faqat 1 ta rasm)</i>"
    )

    await state.set_state(ChannelPostStates.waiting_channel_photo)
    await message.answer(info, reply_markup=cancel_kb())


@router.message(ChannelPostStates.waiting_channel_photo, F.photo)
async def post_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    temp_filename = f"phone_{uuid.uuid4().hex[:8]}.jpg"
    local_path = os.path.join("media", temp_filename)
    await bot.download(photo, destination=local_path)

    await state.update_data(phone_photo_path=local_path)
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

    photo_path = data.get("phone_photo_path")
    imei_6 = data.get("imei_6")

    # Rasmni Drive ga yuklash
    filename = f"phone_{imei_6}.jpg"
    view_link, _, formula = drive_service.upload_photo(photo_path, filename)

    # Kanalga post qilish
    post_id = await poster_service.post_to_channel(bot, data, photo_path)

    # Google Sheets ni yangilash
    row_idx = data.get("row_index")
    if row_idx:
        sheets_service.update_phone(
            row_idx,
            {
                "Telefon rasmi": formula,
                "Sotuv narxi ($)": price,
                "Holati": "Kanallangan",
                "Kanal post ID": str(post_id or ""),
            },
        )

    await state.clear()
    await message.answer(
        "🚀 <b>E'lon Telegram kanalga muvaffaqiyatli joylandi!</b>",
        reply_markup=main_menu_kb(),
    )
