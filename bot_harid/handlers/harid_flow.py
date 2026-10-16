from bot_common.handler_support import begin_flow
from services.errors import AmbiguousPhone, StorageWriteError
from services.google_drive import DriveUnavailable
from bot_common.handler_support import (
    clean_currency,
    close_prompt,
    commit,
    find_phone,
    progress,
    safe_handler,
    operation_id,
    answer_preview,
    wait_for_delivery,
)
from services.io_worker import io_worker
from services.errors import BusinessRuleError
from utils.formatters import safe_html
from bot_common.callbacks import callback_key

import os
import uuid
import tempfile
import logging
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
from bot_harid.states import HaridStates, ChannelPostStates, KarobkaStates
from bot_harid.keyboards import (
    main_menu_kb,
    cancel_kb,
    skip_inline_kb,
    brand_kb,
    memory_kb,
    box_kb,
    payment_type_kb,
    yes_no_kb,
    post_channel_kb,
    condition_inline_kb,
)
from services.google_sheets import sheets_service
from services.google_drive import drive_service
from utils.formatters import build_purchase_summary

logger = logging.getLogger(__name__)
router = Router()

SKIPPED = "Tashlab ketildi"
SKIP_TEXTS = ["⏭ Tashlab ketish", "Tashlab ketish"]
MEMORY_PROMPT = (
    "💾 <b>Xotirasini tanlang:</b>\n"
    "<i>(Tugmadan tanlang yoki yozing)</i>"
)
BATTERY_PROMPT = (
    "🔋 <b>Batareya foizini kiriting:</b>\n<i>(Masalan: 88)</i>"
)
COLOR_PROMPT = "🎨 <b>Rangini kiriting:</b>\n<i>(Masalan: Qora, Moviy)</i>"
IMEI_PROMPT = (
    "🔢 <b>IMEI yoki seriya raqamini kiriting:</b>\n"
    "<i>(Masalan: 345678)</i>"
)
SELLER_NAME_PROMPT = (
    "👤 <b>Telefon egasining ismini kiriting:</b>\n<i>(Masalan: Akmal)</i>"
)
SELLER_PHONE_PROMPT = (
    "📞 <b>Egasining telefon raqamini kiriting:</b>\n"
    "<i>(Masalan: +998901234567)</i>"
)
PAYMENT_PROMPT = "💳 <b>Puli qanday to'landi?</b>"
CHANNEL_PHOTO_PROMPT = (
    "📸 <b>E'lon uchun telefon rasmini yuboring:</b>\n"
    "<i>(1 ta rasm; kanalda shu rasm chiqadi)</i>"
)
CONDITION_PROMPT = "✨ <b>Telefon holatini tanlang:</b>"
SELL_PRICE_PROMPT = (
    "💰 <b>Kanalda ko'rsatiladigan narxni kiriting ($):</b>\n<i>(Masalan: 550)</i>"
)
CONDITIONS = {"Ideal", "Yaxshi", "O'rta"}


@router.message(F.text == "📥 Harid qilish")
@safe_handler
async def start_purchase(message: types.Message, state: FSMContext):
    active, role, name = await io_worker.call(
        sheets_service.check_member, message.from_user.id, force_refresh=False
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        raise BusinessRuleError("Xarid uchun ruxsat berilmagan.")
    await begin_flow(state, message.from_user.id)
    await state.update_data(
        buyer_staff_name=name or message.from_user.full_name,
        buyer_staff_id=message.from_user.id,
    )
    await state.set_state(HaridStates.choosing_brand)
    await message.answer("📥 <b>Yangi xarid</b>", reply_markup=cancel_kb())
    await message.answer(
        "📱 <b>Qurilma turini tanlang:</b>", reply_markup=brand_kb()
    )


@router.callback_query(HaridStates.choosing_brand, F.data.startswith("brand:"))
@safe_handler
async def brand_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    brand = call.data.partition(":")[2]
    if brand not in {"iPhone", "Android", "Boshqa"}:
        raise BusinessRuleError("Qurilma rusumini qayta tanlang.")
    await state.update_data(brand=brand)
    await close_prompt(call)
    if brand != "iPhone":
        await state.set_state(HaridStates.input_custom_model)
        item_text = (
            "✍️ <b>Telefon modelining to'liq nomini yozing:</b>\n"
            "<i>(Masalan: Samsung S24 Ultra yoki Xiaomi 14)</i>"
            if brand == "Android"
            else "✍️ <b>Qurilma modelining to'liq nomini yozing:</b>\n"
            "<i>(Masalan: iPad Air 5, Apple Watch yoki AirPods Pro)</i>"
        )
        await call.message.answer(item_text, reply_markup=cancel_kb())
        return
    models = await io_worker.call(sheets_service.get_models)
    versions = list(
        dict.fromkeys(
            (
                str(m.get("Versiya", "")).strip()
                for m in models
                if str(m.get("Brend", "")).strip().lower() == "iphone"
                and m.get("Versiya")
            )
        )
    )
    if not versions:
        raise BusinessRuleError("Modellar varag‘iga iPhone versiyalarini kiriting.")
    choices = {callback_key(v): v for v in versions}
    await state.update_data(version_choices=choices)
    kb_rows = []
    row = []
    for key, v in choices.items():
        btn_text = f"iPhone {v}" if not v.lower().startswith("iphone") else v
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"ver:{key}"))
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


@router.callback_query(HaridStates.choosing_version, F.data.startswith("ver:"))
@safe_handler
async def version_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    version = data.get("version_choices", {}).get(call.data.partition(":")[2])
    if not version:
        raise BusinessRuleError("Versiya tanlovi eskirgan yoki noto‘g‘ri.")
    await state.update_data(version=version)
    await close_prompt(call)
    models = await io_worker.call(sheets_service.get_models)
    kinds = []
    for model in models:
        if (
            str(model.get("Brend", "")).strip().lower() == "iphone"
            and str(model.get("Versiya", "")).strip() == version
        ):
            for kind in str(model.get("Turlari", "")).split(","):
                kind = kind.strip()
                if (
                    kind
                    and kind not in kinds
                    and (kind.lower() not in {"-", "yo‘q", "yo'q", "none"})
                ):
                    kinds.append(kind)
    if len(kinds) <= 1:
        kind = kinds[0] if kinds else ""
        await set_model_and_photo(call.message, state, version, kind)
        return
    choices = {callback_key(k): k for k in kinds}
    await state.update_data(type_choices=choices)
    await state.set_state(HaridStates.choosing_type)
    kb_rows = []
    row = []
    for key, k in choices.items():
        if k.lower() in [version.lower(), "oddiy", "standart"]:
            btn_text = f"{version}"
        elif version.lower() in k.lower():
            btn_text = f"{k}"
        else:
            btn_text = f"{version} {k}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"type:{key}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    await call.message.answer(
        f"🍏 <b>iPhone {version} turini tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.callback_query(HaridStates.choosing_type, F.data.startswith("type:"))
@safe_handler
async def type_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    kind = data.get("type_choices", {}).get(call.data.partition(":")[2])
    if not kind:
        raise BusinessRuleError("Qurilma turini qayta tanlang.")
    await close_prompt(call)
    await set_model_and_photo(call.message, state, data["version"], kind)


@router.message(HaridStates.input_custom_model, F.text)
@safe_handler
async def custom_model_entered(message: types.Message, state: FSMContext):
    model = message.text.strip()
    if not model or len(model) > 120:
        raise BusinessRuleError("Model nomi 1–120 belgi bo‘lsin.")
    await state.update_data(model=model, version=model, type="")
    await ask_imei_photo(message, state, model)


@router.callback_query(HaridStates.waiting_imei_photo, F.data == "skip_imei_photo")
@safe_handler
async def imei_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(imei_photo_file_id=None)
    await state.set_state(HaridStates.choosing_memory)
    await call.message.answer(MEMORY_PROMPT, reply_markup=memory_kb())


@router.message(HaridStates.waiting_imei_photo, F.photo)
@safe_handler
async def imei_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    file_id = photo.file_id
    await state.update_data(imei_photo_file_id=file_id)
    await state.set_state(HaridStates.choosing_memory)
    await message.answer(MEMORY_PROMPT, reply_markup=memory_kb())


@router.message(HaridStates.waiting_imei_photo, F.text.in_(SKIP_TEXTS))
@safe_handler
async def imei_photo_skipped(message: types.Message, state: FSMContext):
    await state.update_data(imei_photo_file_id=None)
    await state.set_state(HaridStates.choosing_memory)
    await message.answer(MEMORY_PROMPT, reply_markup=memory_kb())


@router.callback_query(HaridStates.choosing_memory, F.data.startswith("mem:"))
@safe_handler
async def memory_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    mem = call.data.partition(":")[2]
    if mem not in {"64 GB", "128 GB", "256 GB", "512 GB", "1 TB", "-"}:
        raise BusinessRuleError("Xotira tanlovi noto‘g‘ri.")
    await state.update_data(memory=mem)
    await close_prompt(call, SKIPPED if mem == "-" else mem)
    await state.set_state(HaridStates.waiting_battery)
    await call.message.answer(
        BATTERY_PROMPT, reply_markup=skip_inline_kb("skip_battery")
    )


@router.message(HaridStates.choosing_memory, F.text)
@safe_handler
async def memory_message_handler(message: types.Message, state: FSMContext):
    mem = "-" if message.text in SKIP_TEXTS else message.text.strip()
    await state.update_data(memory=mem)
    await state.set_state(HaridStates.waiting_battery)
    await message.answer(BATTERY_PROMPT, reply_markup=skip_inline_kb("skip_battery"))


@router.callback_query(HaridStates.waiting_battery, F.data == "skip_battery")
@safe_handler
async def battery_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(battery="-")
    await state.set_state(HaridStates.waiting_color)
    await call.message.answer(COLOR_PROMPT, reply_markup=skip_inline_kb("skip_color"))


@router.message(HaridStates.waiting_battery, F.text)
@safe_handler
async def battery_entered(message: types.Message, state: FSMContext):
    if message.text in SKIP_TEXTS:
        value = "-"
    else:
        value = message.text.strip().removesuffix("%").strip()
        if not value.isascii() or not value.isdigit() or (not 1 <= int(value) <= 100):
            raise BusinessRuleError("Batareya foizini 1–100 orasida kiriting.")
    await state.update_data(battery=value)
    await state.set_state(HaridStates.waiting_color)
    await message.answer(COLOR_PROMPT, reply_markup=skip_inline_kb("skip_color"))


@router.callback_query(HaridStates.waiting_color, F.data == "skip_color")
@safe_handler
async def color_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(color="-")
    await state.set_state(HaridStates.waiting_imei_6)
    await call.message.answer(IMEI_PROMPT, reply_markup=cancel_kb())


@router.message(HaridStates.waiting_color, F.text)
@safe_handler
async def color_entered(message: types.Message, state: FSMContext):
    color = "-" if message.text in SKIP_TEXTS else message.text.strip()
    await state.update_data(color=color)
    await state.set_state(HaridStates.waiting_imei_6)
    await message.answer(IMEI_PROMPT, reply_markup=cancel_kb())


@router.message(HaridStates.waiting_imei_6, F.text)
@safe_handler
async def imei_6_entered(message: types.Message, state: FSMContext):
    imei = message.text.strip().lstrip("'")
    if not imei.isascii() or not imei.isalnum() or (not 4 <= len(imei) <= 64):
        raise BusinessRuleError(
            "IMEI/seriya 4–64 ta harf yoki raqamdan iborat bo‘lsin."
        )
    try:
        phone = await io_worker.call(
            sheets_service.get_phone_by_imei, imei, fresh=True, exact=True
        )
    except AmbiguousPhone as exc:
        if any((p.get("Holati") != "Sotildi" for p in exc.matches)):
            raise BusinessRuleError(
                "Bu IMEI bo‘yicha sotilmagan telefon mavjud."
            ) from exc
        phone = None
    if phone and phone.get("Holati") != "Sotildi":
        raise BusinessRuleError("Bu IMEI bo‘yicha sotilmagan telefon mavjud.")
    await state.update_data(imei=imei, imei_6=imei)
    await state.set_state(HaridStates.waiting_box)
    await message.answer("📦 <b>Karobkasi bormi?</b>", reply_markup=box_kb())


@router.message(
    HaridStates.waiting_box,
    F.text.in_(["✅ Ha", "❌ Yo'q", "⏳ Keladi", "Ha", "Yo'q", "Keladi"]),
)
@safe_handler
async def box_chosen(message: types.Message, state: FSMContext):
    if "Ha" in message.text:
        has_box = "Ha"
    elif "Keladi" in message.text:
        has_box = "Keladi"
    else:
        has_box = "Yo'q"
    await state.update_data(has_box=has_box)
    await state.set_state(HaridStates.waiting_buy_price)
    await message.answer(
        "💵 <b>Sotib olish narxini kiriting ($):</b>\n<i>(Masalan: 450)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_buy_price, F.text)
@safe_handler
async def buy_price_entered(message: types.Message, state: FSMContext):
    price = clean_currency(message.text)
    await state.update_data(buy_price=price)
    await state.set_state(HaridStates.waiting_seller_name)
    await message.answer(
        SELLER_NAME_PROMPT, reply_markup=skip_inline_kb("skip_seller_name")
    )


@router.callback_query(HaridStates.waiting_seller_name, F.data == "skip_seller_name")
@safe_handler
async def seller_name_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(seller_name="Mijoz")
    await state.set_state(HaridStates.waiting_seller_phone)
    await call.message.answer(
        SELLER_PHONE_PROMPT, reply_markup=skip_inline_kb("skip_seller_phone")
    )


@router.message(HaridStates.waiting_seller_name, F.text)
@safe_handler
async def seller_name_entered(message: types.Message, state: FSMContext):
    name = "Mijoz" if message.text in SKIP_TEXTS else message.text.strip()
    await state.update_data(seller_name=name)
    await state.set_state(HaridStates.waiting_seller_phone)
    await message.answer(
        SELLER_PHONE_PROMPT, reply_markup=skip_inline_kb("skip_seller_phone")
    )


@router.callback_query(HaridStates.waiting_seller_phone, F.data == "skip_seller_phone")
@safe_handler
async def seller_phone_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(seller_phone="-")
    await state.set_state(HaridStates.waiting_payment_type)
    await call.message.answer(PAYMENT_PROMPT, reply_markup=payment_type_kb())


@router.message(HaridStates.waiting_seller_phone, F.text)
@safe_handler
async def seller_phone_entered(message: types.Message, state: FSMContext):
    phone = "-" if message.text in SKIP_TEXTS else message.text.strip()
    await state.update_data(seller_phone=phone)
    await state.set_state(HaridStates.waiting_payment_type)
    await message.answer(PAYMENT_PROMPT, reply_markup=payment_type_kb())


@router.message(HaridStates.waiting_payment_type, F.text.in_(["💵 Naqd", "💳 Qarzga"]))
@safe_handler
async def payment_type_chosen(message: types.Message, state: FSMContext):
    data = await state.get_data()
    payment = "Naqd" if "Naqd" in message.text else "Qarz"
    await state.update_data(
        payment_type=payment,
        debt_amount=data["buy_price"] if payment == "Qarz" else "0.00",
    )
    data = await state.get_data()
    await state.set_state(HaridStates.confirm_purchase)
    await answer_preview(
        message,
        build_purchase_summary(data),
        photo=data.get("imei_photo_file_id"),
        reply_markup=yes_no_kb(),
    )


@router.message(HaridStates.confirm_purchase, F.text.in_(["✅ Ha", "❌ Yo'q"]))
@safe_handler
async def confirm_purchase_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("❌ Xarid bekor qilindi.", reply_markup=main_menu_kb())
        return
    identifier = await operation_id(state)
    async with progress(message, "Ma'lumotlar saqlanmoqda, kutib turing..."):
        link = await store_photo(
            bot, state, "imei_photo_file_id", "imei_photo_url", public=False
        )
        data = await state.get_data()
        if link:
            data["imei_photo_url"] = link
        notifications = []
        if config.GROUP_HARID_ID:
            notifications.append(
                {
                    "kind": "buy_group",
                    "bot_id": bot.id,
                    "data": data,
                    "photo": data.get("imei_photo_file_id"),
                }
            )
        await commit(
            state,
            message.from_user.id,
            sheets_service.add_phone,
            data,
            notifications=notifications,
        )
        await state.update_data(
            phone_id=identifier,
            purchase_operation_id=identifier,
            operation_id=str(uuid.uuid4()),
        )
        await state.set_state(HaridStates.ask_post_channel)
    await message.answer("✅ <b>Telefon qabul qilindi va bazaga saqlandi.</b>")
    await message.answer(
        "📢 <b>Telegram kanalga e'lon joylansinmi?</b>",
        reply_markup=post_channel_kb(),
    )


@router.message(
    HaridStates.ask_post_channel,
    F.text.in_(["📢 Joylash", "Joylash", "✅ Ha", "Ha", "❌ Yo'q", "Yo'q"]),
)
@safe_handler
async def ask_post_channel_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text in ["❌ Yo'q", "Yo'q"]:
        await state.clear()
        await message.answer(
            "✅ Xarid yakunlandi. Kanalga e'lon berilmadi.", reply_markup=main_menu_kb()
        )
        return
    await state.set_state(HaridStates.waiting_channel_photo)
    await message.answer("📢 <b>Kanalga e'lon</b>", reply_markup=cancel_kb())
    await message.answer(
        CHANNEL_PHOTO_PROMPT, reply_markup=skip_inline_kb("skip_channel_photo")
    )


@router.callback_query(
    HaridStates.waiting_channel_photo, F.data == "skip_channel_photo"
)
@safe_handler
async def channel_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(HaridStates.waiting_condition)
    await call.message.answer(CONDITION_PROMPT, reply_markup=condition_inline_kb("hcond"))


@router.message(HaridStates.waiting_channel_photo, F.text.in_(SKIP_TEXTS))
@safe_handler
async def channel_photo_skipped(message: types.Message, state: FSMContext):
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(HaridStates.waiting_condition)
    await message.answer(CONDITION_PROMPT, reply_markup=condition_inline_kb("hcond"))


@router.message(HaridStates.waiting_channel_photo, F.photo)
@safe_handler
async def channel_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    await state.update_data(phone_photo_file_id=photo.file_id)
    await state.set_state(HaridStates.waiting_condition)
    await message.answer(CONDITION_PROMPT, reply_markup=condition_inline_kb("hcond"))


@router.callback_query(HaridStates.waiting_condition, F.data.startswith("hcond:"))
@safe_handler
async def harid_condition_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await choose_condition(call, state, HaridStates.waiting_sell_price)


@router.message(HaridStates.waiting_condition, F.text)
@safe_handler
async def harid_condition_text(message: types.Message, state: FSMContext):
    await type_condition(message, state, HaridStates.waiting_sell_price)


@router.message(HaridStates.waiting_sell_price, F.text)
@safe_handler
async def sell_price_received(message: types.Message, state: FSMContext, bot: Bot):
    await queue_listing(message, state, bot)


@router.message(F.text == "📢 Telegram kanalga e'lon berish")
@safe_handler
async def start_channel_post(message: types.Message, state: FSMContext):
    active, role, _ = await io_worker.call(
        sheets_service.check_member, message.from_user.id, force_refresh=False
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        raise BusinessRuleError("E’lon berishga ruxsat berilmagan.")
    await begin_flow(state, message.from_user.id)
    await state.set_state(ChannelPostStates.waiting_imei_search)
    await message.answer("📢 <b>Kanalga e'lon</b>", reply_markup=cancel_kb())
    await message.answer(IMEI_PROMPT)


@router.message(ChannelPostStates.waiting_imei_search, F.text)
@safe_handler
async def imei_searched(message: types.Message, state: FSMContext):
    phone = await find_phone(message.text.strip(), state)
    if not phone:
        raise BusinessRuleError("Telefon topilmadi. IMEI ni tekshiring.")
    if phone.get("Holati") != "Sotuvda":
        raise BusinessRuleError("Sotilgan qurilmaga qayta e’lon berish bloklangan.")
    await state.update_data(
        phone_id=phone["Telefon ID"],
        imei=phone["IMEI"],
        imei_6=phone["IMEI"],
        model=phone["Model"],
        phone_data=phone,
        existing_photo_url=phone.get("Telefon rasmi", ""),
    )
    await state.set_state(ChannelPostStates.waiting_channel_photo)
    lines = [
        f"📱 <b>{safe_html(phone['Model'])}</b>",
        f"🔍 IMEI: <code>{safe_html(phone['IMEI'])}</code>",
    ]
    if str(phone.get("Kanal post ID") or "").strip():
        price = str(phone.get("Elon narxi ($)") or "").strip()
        lines.append(
            "\nℹ️ Bu telefon kanalda e'lon qilingan"
            + (f" (narxi: <b>${safe_html(price)}</b>)" if price else "")
            + ". E'lon yangilanadi."
        )
    await message.answer("\n".join(lines))
    await message.answer(
        CHANNEL_PHOTO_PROMPT, reply_markup=skip_inline_kb("skip_post_photo")
    )


@router.callback_query(
    ChannelPostStates.waiting_channel_photo, F.data == "skip_post_photo"
)
@safe_handler
async def post_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(ChannelPostStates.waiting_condition)
    await call.message.answer(CONDITION_PROMPT, reply_markup=condition_inline_kb("pcond"))


@router.message(ChannelPostStates.waiting_channel_photo, F.text.in_(SKIP_TEXTS))
@safe_handler
async def post_photo_skipped(message: types.Message, state: FSMContext):
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(ChannelPostStates.waiting_condition)
    await message.answer(CONDITION_PROMPT, reply_markup=condition_inline_kb("pcond"))


@router.message(ChannelPostStates.waiting_channel_photo, F.photo)
@safe_handler
async def post_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    await state.update_data(phone_photo_file_id=photo.file_id)
    await state.set_state(ChannelPostStates.waiting_condition)
    await message.answer(CONDITION_PROMPT, reply_markup=condition_inline_kb("pcond"))


@router.callback_query(ChannelPostStates.waiting_condition, F.data.startswith("pcond:"))
@safe_handler
async def post_condition_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await choose_condition(call, state, ChannelPostStates.waiting_sell_price)


@router.message(ChannelPostStates.waiting_condition, F.text)
@safe_handler
async def post_condition_text(message: types.Message, state: FSMContext):
    await type_condition(message, state, ChannelPostStates.waiting_sell_price)


@router.message(ChannelPostStates.waiting_sell_price, F.text)
@safe_handler
async def post_sell_price_received(message: types.Message, state: FSMContext, bot: Bot):
    await queue_listing(message, state, bot)


@router.message(F.text.in_(["📦 Karobka", "Karobka"]))
@safe_handler
async def start_karobka_update(message: types.Message, state: FSMContext):
    active, role, _ = await io_worker.call(
        sheets_service.check_member, message.from_user.id, force_refresh=False
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        raise BusinessRuleError("Karobka holatini o‘zgartirishga ruxsat berilmagan.")
    await begin_flow(state, message.from_user.id)
    await state.set_state(KarobkaStates.waiting_imei)
    await message.answer("📦 <b>Karobka keltirildi</b>", reply_markup=cancel_kb())
    await message.answer(IMEI_PROMPT)


@router.message(KarobkaStates.waiting_imei, F.text)
@safe_handler
async def process_karobka_imei(message: types.Message, state: FSMContext):
    phone = await find_phone(message.text.strip(), state)
    if not phone:
        raise BusinessRuleError("Telefon topilmadi.")
    if phone.get("Holati") != "Sotuvda":
        raise BusinessRuleError(
            "Sotilgan telefon ombor ma’lumotini o‘zgartirib bo‘lmaydi."
        )
    if str(phone.get("Karobka", "")).lower() in {"ha", "bor"}:
        await state.clear()
        await message.answer(
            "ℹ️ Bu telefonning karobkasi allaqachon bor.", reply_markup=main_menu_kb()
        )
        return
    await state.update_data(
        phone_id=phone["Telefon ID"], imei=phone["IMEI"], model=phone["Model"]
    )
    await state.set_state(KarobkaStates.confirm_phone)
    info_text = (
        "📱 <b>Qurilma ma'lumotlari:</b>\n\n"
        f"🏷 Model: <b>{safe_html(phone.get('Model', 'Telefon'))}</b>\n"
        f"💾 Xotira: <b>{safe_html(phone.get('Xotira', '-'))}</b>\n"
        f"🎨 Rang: <b>{safe_html(phone.get('Rang', '-'))}</b>\n"
        f"🔍 IMEI: <code>{safe_html(phone.get('IMEI', '-'))}</code>\n"
        f"📅 Harid sanasi: <b>{safe_html(phone.get('Harid sanasi', '-'))}</b>\n"
        f"📦 Joriy karobka holati: <b>{safe_html(phone.get('Karobka', 'Mavjud emas'))}</b>\n\n"
        "❓ <b>Rostdan ham ushbu telefonning karobkasi keltirildimi?</b>"
    )
    await message.answer(info_text, reply_markup=yes_no_kb())


@router.message(
    KarobkaStates.confirm_phone, F.text.in_(["✅ Ha", "❌ Yo'q", "Ha", "Yo'q"])
)
@safe_handler
async def confirm_karobka_update(message: types.Message, state: FSMContext):
    if "Yo'q" in message.text:
        await state.set_state(KarobkaStates.waiting_imei)
        await message.answer(IMEI_PROMPT, reply_markup=cancel_kb())
        return
    data = await state.get_data()
    if not data.get("phone_id"):
        raise BusinessRuleError("Telefonni qayta tanlang.")
    await commit(
        state,
        message.from_user.id,
        sheets_service.update_phone,
        data["phone_id"],
        {"Karobka": "Ha"},
    )
    await state.clear()
    await message.answer("✅ Karobka holati saqlandi.", reply_markup=main_menu_kb())


@router.message(KarobkaStates.confirm_phone, F.text)
@safe_handler
async def invalid_confirm_karobka(message: types.Message):
    await message.answer(
        "Iltimos, pastdagi tugmalardan birini tanlang.", reply_markup=yes_no_kb()
    )


async def set_model_and_photo(message, state, version, kind):
    if kind.lower() in {version.lower(), "oddiy", "standart"}:
        kind = ""
    model = (
        f"iPhone {kind}"
        if kind and version.lower() in kind.lower()
        else " ".join(filter(None, ("iPhone", version, kind)))
    )
    await state.update_data(type=kind, model=model)
    await ask_imei_photo(message, state, model)


async def ask_imei_photo(message, state, model):
    # The model line matters when the type was picked automatically.
    await state.set_state(HaridStates.waiting_imei_photo)
    await message.answer(
        f"📱 <b>{safe_html(model)}</b>\n\n"
        "📸 <b>IMEI rasmini yuboring:</b>\n<i>(1 ta rasm; faqat ichki hisob uchun)</i>",
        reply_markup=skip_inline_kb("skip_imei_photo"),
    )


async def choose_condition(call, state, next_state):
    condition = call.data.partition(":")[2]
    if condition not in CONDITIONS:
        raise BusinessRuleError("Telefon holatini tugmadan tanlang.")
    await close_prompt(call)
    await state.update_data(condition=condition)
    await state.set_state(next_state)
    await call.message.answer(SELL_PRICE_PROMPT, reply_markup=cancel_kb())


async def type_condition(message, state, next_state):
    typed = message.text.replace("✨", "").replace("👍", "").replace("👌", "").strip()
    known = {c.casefold(): c for c in CONDITIONS} | {"orta": "O'rta"}
    condition = known.get(typed.casefold())
    if not condition:
        raise BusinessRuleError("Telefon holatini tugmadan tanlang: Ideal, Yaxshi yoki O'rta.")
    await state.update_data(condition=condition)
    await state.set_state(next_state)
    await message.answer(SELL_PRICE_PROMPT, reply_markup=cancel_kb())


async def store_photo(bot, state, file_key, link_key, *, public):
    data = await state.get_data()
    if data.get(link_key + "_uploaded"):
        return data.get(link_key, "")
    file_id = data.get(file_key)
    if not file_id or not config.DRIVE_FOLDER_ID:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        path = tmp.name
    try:
        await bot.download(file_id, destination=path)
        try:
            link, _, _ = await io_worker.call(
                drive_service.upload_photo,
                path,
                str(uuid.uuid4()) + ".jpg",
                public=public,
            )
        except DriveUnavailable as exc:
            raise StorageWriteError("Rasmni arxivlash tasdiqlanmadi") from exc
        await state.update_data(**{link_key: link, link_key + "_uploaded": True})
        return link
    finally:
        if os.path.exists(path):
            os.remove(path)


async def queue_listing(message, state, bot):
    if not config.CHANNEL_ID:
        raise BusinessRuleError("Kanal ID sozlanmagan. E’lon navbatga olinmadi.")
    price = clean_currency(message.text)
    identifier = await operation_id(state)
    data = await state.get_data()
    intent = data.get("listing_intent")
    if intent and (intent["operation_id"] != identifier or intent["price"] != price):
        raise BusinessRuleError(
            "Oldingi e'lon natijasini tekshiring. Shu amal bilan narxni almashtirmang; "
            "yangi narx uchun avval amalni yakunlang va yangi e'lon boshlang."
        )
    reference = data.get("phone_id") or data.get("imei")
    if not reference:
        raise BusinessRuleError("Telefonni qayta tanlang.")
    phone = await io_worker.call(sheets_service.get_phone_by_id, reference, fresh=True)
    if not phone and data.get("imei"):
        phone = await io_worker.call(sheets_service.get_phone_by_imei, data["imei"], fresh=True)
    if not phone or phone.get("Holati") != "Sotuvda":
        raise BusinessRuleError(
            "Sotilgan yoki mavjud bo‘lmagan telefonga e’lon berib bo‘lmaydi."
        )
    reference = phone["Telefon ID"]
    had_post = bool(str(phone.get("Kanal post ID") or "").strip())
    async with progress(message, "E'lon kanalga joylanmoqda, kutib turing..."):
        await save_listing(message, state, bot, phone, reference, identifier, price, intent)
        status = await wait_for_delivery(identifier)
    await state.clear()
    if status is None:
        text = "🕓 E'lon saqlandi va navbatga qo'yildi. Bir necha daqiqada kanalda chiqadi."
    elif status["state"] == "sent":
        text = (
            "✅ <b>Kanaldagi e'lon yangilandi.</b>"
            if had_post
            else "✅ <b>E'lon kanalga joylandi.</b>"
        )
    else:
        text = (
            "⚠️ <b>E'lon kanalga joylanmadi.</b> Narx saqlandi; hisobchi tekshiradi.\n"
            f"Amal: /amal {safe_html(identifier)}"
        )
    await message.answer(text, reply_markup=main_menu_kb())


async def save_listing(message, state, bot, phone, reference, identifier, price, intent):
    if not intent:
        link = await store_photo(
            bot, state, "phone_photo_file_id", "phone_photo_url", public=True
        )
        data = await state.get_data()
        updates = {"Elon narxi ($)": price}
        if link:
            updates["Telefon rasmi"] = link
        notifications = [
            {
                "kind": "publish_channel",
                "phone_id": phone["Telefon ID"],
                "actor_id": message.from_user.id,
                "bot_id": bot.id,
                # The condition exists only in this flow; the sheet has no column.
                "data": {
                    **phone,
                    "sell_price": price,
                    "condition": data.get("condition", ""),
                },
                "photo": data.get("phone_photo_file_id"),
            }
        ]
        # Persist before submitting Sheets. The first batch may have committed
        # even if its response was lost; retries must have the exact same hash.
        intent = {
            "operation_id": identifier,
            "price": price,
            "updates": updates,
            "notifications": notifications,
        }
        await state.update_data(sell_price=price, listing_intent=intent)
    await commit(
        state,
        message.from_user.id,
        sheets_service.update_phone,
        reference,
        intent["updates"],
        notifications=intent["notifications"],
    )
