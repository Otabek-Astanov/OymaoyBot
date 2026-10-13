from bot_common.handler_support import begin_flow
from services.errors import AmbiguousPhone, StorageWriteError
from services.google_drive import DriveUnavailable
from bot_common.handler_support import (
    clean_currency,
    commit,
    find_phone,
    safe_handler,
    operation_id,
    answer_preview,
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


@router.message(F.text == "📥 Harid qilish")
@safe_handler
async def start_purchase(message: types.Message, state: FSMContext):
    active, role, name = await io_worker.call(
        sheets_service.check_member, message.from_user.id, force_refresh=True
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        raise BusinessRuleError("Xarid uchun ruxsat berilmagan.")
    await begin_flow(state, message.from_user.id)
    await state.update_data(
        buyer_staff_name=name or message.from_user.full_name,
        buyer_staff_id=message.from_user.id,
    )
    await state.set_state(HaridStates.choosing_brand)
    await message.answer("Qurilma rusumini tanlang:", reply_markup=brand_kb())


@router.callback_query(HaridStates.choosing_brand, F.data.startswith("brand:"))
@safe_handler
async def brand_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    brand = call.data.partition(":")[2]
    if brand not in {"iPhone", "Android", "Boshqa"}:
        raise BusinessRuleError("Qurilma rusumini qayta tanlang.")
    await state.update_data(brand=brand)
    if brand != "iPhone":
        await state.set_state(HaridStates.input_custom_model)
        await call.message.answer(
            "Qurilma modelining to‘liq nomini yozing:", reply_markup=cancel_kb()
        )
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
    kb = [
        [InlineKeyboardButton(text=v, callback_data=f"ver:{key}")]
        for key, v in choices.items()
    ]
    await state.set_state(HaridStates.choosing_version)
    await call.message.answer(
        "iPhone versiyasini tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
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
    models = await io_worker.call(sheets_service.get_models, force_refresh=True)
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
    kb = [
        [InlineKeyboardButton(text=k, callback_data=f"type:{key}")]
        for key, k in choices.items()
    ]
    await call.message.answer(
        "Qurilma turini tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@router.callback_query(HaridStates.choosing_type, F.data.startswith("type:"))
@safe_handler
async def type_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    kind = data.get("type_choices", {}).get(call.data.partition(":")[2])
    if not kind:
        raise BusinessRuleError("Qurilma turini qayta tanlang.")
    await set_model_and_photo(call.message, state, data["version"], kind)


@router.message(HaridStates.input_custom_model, F.text)
@safe_handler
async def custom_model_entered(message: types.Message, state: FSMContext):
    model = message.text.strip()
    if not model or len(model) > 120:
        raise BusinessRuleError("Model nomi 1–120 belgi bo‘lsin.")
    await state.update_data(model=model, version=model, type="")
    await state.set_state(HaridStates.waiting_imei_photo)
    await message.answer(
        f"Model: <b>{safe_html(model)}</b>\nIMEI rasmini yuboring yoki tashlab keting:",
        reply_markup=skip_inline_kb("skip_imei_photo"),
    )


@router.callback_query(HaridStates.waiting_imei_photo, F.data == "skip_imei_photo")
@safe_handler
async def imei_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(imei_photo_file_id=None)
    await state.set_state(HaridStates.choosing_memory)
    await call.message.answer(
        "💾 <b>Xotirasini tanlang:</b>\n<i>(Tugmalardan tanlang, yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=memory_kb(),
    )


@router.message(HaridStates.waiting_imei_photo, F.photo)
@safe_handler
async def imei_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    file_id = photo.file_id
    await state.update_data(imei_photo_file_id=file_id)
    await state.set_state(HaridStates.choosing_memory)
    await message.answer(
        "💾 <b>Xotirasini tanlang:</b>\n<i>(Tugmalardan tanlang, yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=memory_kb(),
    )


@router.message(
    HaridStates.waiting_imei_photo, F.text.in_(["⏭ Tashlab ketish", "Tashlab ketish"])
)
@safe_handler
async def imei_photo_skipped(message: types.Message, state: FSMContext):
    await state.update_data(imei_photo_file_id=None)
    await state.set_state(HaridStates.choosing_memory)
    await message.answer(
        "💾 <b>Xotirasini tanlang:</b>\n<i>(Tugmalardan tanlang, yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=memory_kb(),
    )


@router.callback_query(HaridStates.choosing_memory, F.data.startswith("mem:"))
@safe_handler
async def memory_chosen(call: types.CallbackQuery, state: FSMContext):
    mem = call.data.partition(":")[2]
    if mem not in {"64 GB", "128 GB", "256 GB", "512 GB", "1 TB", "-"}:
        raise BusinessRuleError("Xotira tanlovi noto‘g‘ri.")
    await state.update_data(memory=mem)
    try:
        await call.message.delete()
    except Exception:
        pass
    await state.set_state(HaridStates.waiting_battery)
    mem_text = "" if mem == "-" else f"Tanlandi: <b>{safe_html(mem)}</b>\n\n"
    await call.message.answer(
        f"{mem_text}🔋 <b>Batareya foizini (%) kiriting:</b>\n<i>(Masalan: 88 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_battery"),
    )


@router.message(HaridStates.choosing_memory, F.text)
@safe_handler
async def memory_message_handler(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        mem = "-"
    else:
        mem = message.text.strip()
    await state.update_data(memory=mem)
    await state.set_state(HaridStates.waiting_battery)
    mem_text = "" if mem == "-" else f"Xotira: <b>{safe_html(mem)}</b>\n\n"
    await message.answer(
        f"{mem_text}🔋 <b>Batareya foizini (%) kiriting:</b>\n<i>(Masalan: 88 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_battery"),
    )


@router.callback_query(HaridStates.waiting_battery, F.data == "skip_battery")
@safe_handler
async def battery_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(battery="-")
    await state.set_state(HaridStates.waiting_color)
    await call.message.answer(
        "🎨 <b>Rangini kiriting:</b>\n<i>(Masalan: Qora, Moviy yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_color"),
    )


@router.message(HaridStates.waiting_battery, F.text)
@safe_handler
async def battery_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        value = "-"
    else:
        value = message.text.strip().removesuffix("%").strip()
        if not value.isascii() or not value.isdigit() or (not 1 <= int(value) <= 100):
            raise BusinessRuleError("Batareya foizini 1–100 orasida kiriting.")
    await state.update_data(battery=value)
    await state.set_state(HaridStates.waiting_color)
    await message.answer(
        "Rangini yozing yoki tashlab keting:", reply_markup=skip_inline_kb("skip_color")
    )


@router.callback_query(HaridStates.waiting_color, F.data == "skip_color")
@safe_handler
async def color_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(color="-")
    await state.set_state(HaridStates.waiting_imei_6)
    await call.message.answer(
        "🔢 <b>IMEI yoki Seriya raqamini kiriting:</b>", reply_markup=cancel_kb()
    )


@router.message(HaridStates.waiting_color, F.text)
@safe_handler
async def color_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        color = "-"
    else:
        color = message.text.strip()
    await state.update_data(color=color)
    await state.set_state(HaridStates.waiting_imei_6)
    await message.answer(
        "🔢 <b>IMEI yoki Seriya raqamini kiriting:</b>", reply_markup=cancel_kb()
    )


@router.message(HaridStates.waiting_imei_6, F.text)
@safe_handler
async def imei_6_entered(message: types.Message, state: FSMContext):
    imei = message.text.strip().lstrip("'")
    if not imei.isascii() or not imei.isalnum() or (not 4 <= len(imei) <= 64):
        raise BusinessRuleError(
            "To‘liq IMEI/seriya 4–64 ta harf yoki raqamdan iborat bo‘lsin."
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
    await message.answer("Karobka holatini tanlang:", reply_markup=box_kb())


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
        "💵 <b>Sotib olish narxini kiriting ($):</b>\n<i>(Masalan: 450 yoki $450)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_buy_price, F.text)
@safe_handler
async def buy_price_entered(message: types.Message, state: FSMContext):
    price = clean_currency(message.text)
    await state.update_data(buy_price=price)
    await state.set_state(HaridStates.waiting_seller_name)
    await message.answer(
        "👤 <b>Egasining ismini kiriting:</b>\n<i>(Masalan: Akmal yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_seller_name"),
    )


@router.callback_query(HaridStates.waiting_seller_name, F.data == "skip_seller_name")
@safe_handler
async def seller_name_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(seller_name="Mijoz")
    await state.set_state(HaridStates.waiting_seller_phone)
    await call.message.answer(
        "📞 <b>Egasining telefon raqamini kiriting:</b>\n<i>(Masalan: +998901234567 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_seller_phone"),
    )


@router.message(HaridStates.waiting_seller_name, F.text)
@safe_handler
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
@safe_handler
async def seller_phone_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(seller_phone="-")
    await state.set_state(HaridStates.waiting_payment_type)
    await call.message.answer(
        "💳 <b>Puli qanday to'landi?</b>", reply_markup=payment_type_kb()
    )


@router.message(HaridStates.waiting_seller_phone, F.text)
@safe_handler
async def seller_phone_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        phone = "-"
    else:
        phone = message.text.strip()
    await state.update_data(seller_phone=phone)
    await state.set_state(HaridStates.waiting_payment_type)
    await message.answer(
        "💳 <b>Puli qanday to'landi?</b>", reply_markup=payment_type_kb()
    )


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
        await message.answer("Xarid bekor qilindi.", reply_markup=main_menu_kb())
        return
    identifier = await operation_id(state)
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
    await message.answer(
        "✅ <b>Xarid bazaga saqlandi.</b>\nGuruh bildirishnomasi navbatga olindi. Kanalga e’lon berilsinmi?",
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
            "Tushunarli. Jarayon yakunlandi.", reply_markup=main_menu_kb()
        )
        return
    data = await state.get_data()
    item_label = "qurilmaning" if data.get("brand") == "Boshqa" else "telefonning"
    await state.set_state(HaridStates.waiting_channel_photo)
    await message.answer(
        "📢 <b>Kanalga e'lon berish jarayoni:</b>", reply_markup=cancel_kb()
    )
    await message.answer(
        f"📸 <b>{item_label.capitalize()} o'zini rasmini yuboring:</b>\n<i>(Faqat 1 ta sifatli rasm yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_channel_photo"),
    )


@router.callback_query(
    HaridStates.waiting_channel_photo, F.data == "skip_channel_photo"
)
@safe_handler
async def channel_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(HaridStates.waiting_condition)
    await call.message.answer(
        "✨ <b>Telefon holatini tanlang:</b>",
        reply_markup=condition_inline_kb("hcond"),
    )


@router.message(
    HaridStates.waiting_channel_photo,
    F.text.in_(["⏭ Tashlab ketish", "Tashlab ketish"]),
)
@safe_handler
async def channel_photo_skipped(message: types.Message, state: FSMContext):
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(HaridStates.waiting_condition)
    await message.answer(
        "✨ <b>Telefon holatini tanlang:</b>",
        reply_markup=condition_inline_kb("hcond"),
    )


@router.message(HaridStates.waiting_channel_photo, F.photo)
@safe_handler
async def channel_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    await state.update_data(phone_photo_file_id=photo.file_id)
    await state.set_state(HaridStates.waiting_condition)
    await message.answer(
        "✨ <b>Telefon holatini tanlang:</b>",
        reply_markup=condition_inline_kb("hcond"),
    )


@router.callback_query(HaridStates.waiting_condition, F.data.startswith("hcond:"))
async def harid_condition_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    cond = call.data.split(":", 1)[1]
    await state.update_data(condition=cond)
    await state.set_state(HaridStates.waiting_sell_price)
    await call.message.answer(
        f"Holat: <b>{cond}</b>\n\n"
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 550)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_condition, F.text)
async def harid_condition_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    clean_cond = text.replace("✨", "").replace("👍", "").replace("👌", "").strip()
    cond_map = {"ideal": "Ideal", "yaxshi": "Yaxshi", "o'rta": "O'rta", "orta": "O'rta"}
    cond = cond_map.get(clean_cond.lower(), clean_cond.capitalize())

    await state.update_data(condition=cond)
    await state.set_state(HaridStates.waiting_sell_price)
    await message.answer(
        f"Holat: <b>{cond}</b>\n\n"
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 550)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(HaridStates.waiting_sell_price, F.text)
@safe_handler
async def sell_price_received(message: types.Message, state: FSMContext, bot: Bot):
    await queue_listing(message, state, bot)


@router.message(F.text == "📢 Telegram kanalga e'lon berish")
@safe_handler
async def start_channel_post(message: types.Message, state: FSMContext):
    active, role, _ = await io_worker.call(
        sheets_service.check_member, message.from_user.id, force_refresh=True
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        raise BusinessRuleError("E’lon berishga ruxsat berilmagan.")
    await begin_flow(state, message.from_user.id)
    await state.set_state(ChannelPostStates.waiting_imei_search)
    await message.answer(
        "E’lon uchun to‘liq IMEI yoki seriya raqamini kiriting:",
        reply_markup=cancel_kb(),
    )


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
    await message.answer(
        f"Qurilma: <b>{safe_html(phone['Model'])}</b>\nIMEI: <code>{safe_html(phone['IMEI'])}</code>\nOmmaviy e’lon rasmini yuboring yoki tashlab keting. Mavjud post tahrirlanadi.",
        reply_markup=skip_inline_kb("skip_post_photo"),
    )


@router.callback_query(
    ChannelPostStates.waiting_channel_photo, F.data == "skip_post_photo"
)
@safe_handler
async def post_photo_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(ChannelPostStates.waiting_condition)
    await call.message.answer(
        "✨ <b>Telefon holatini tanlang:</b>",
        reply_markup=condition_inline_kb("pcond"),
    )


@router.message(
    ChannelPostStates.waiting_channel_photo,
    F.text.in_(["⏭ Tashlab ketish", "Tashlab ketish"]),
)
@safe_handler
async def post_photo_skipped(message: types.Message, state: FSMContext):
    await state.update_data(phone_photo_file_id=None)
    await state.set_state(ChannelPostStates.waiting_condition)
    await message.answer(
        "✨ <b>Telefon holatini tanlang:</b>",
        reply_markup=condition_inline_kb("pcond"),
    )


@router.message(ChannelPostStates.waiting_channel_photo, F.photo)
@safe_handler
async def post_photo_received(message: types.Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    await state.update_data(phone_photo_file_id=photo.file_id)
    await state.set_state(ChannelPostStates.waiting_condition)
    await message.answer(
        "✨ <b>Telefon holatini tanlang:</b>",
        reply_markup=condition_inline_kb("pcond"),
    )


@router.callback_query(ChannelPostStates.waiting_condition, F.data.startswith("pcond:"))
async def post_condition_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    cond = call.data.split(":", 1)[1]
    await state.update_data(condition=cond)
    await state.set_state(ChannelPostStates.waiting_sell_price)
    await call.message.answer(
        f"Holat: <b>{cond}</b>\n\n"
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 600)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(ChannelPostStates.waiting_condition, F.text)
async def post_condition_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    clean_cond = text.replace("✨", "").replace("👍", "").replace("👌", "").strip()
    cond_map = {"ideal": "Ideal", "yaxshi": "Yaxshi", "o'rta": "O'rta", "orta": "O'rta"}
    cond = cond_map.get(clean_cond.lower(), clean_cond.capitalize())

    await state.update_data(condition=cond)
    await state.set_state(ChannelPostStates.waiting_sell_price)
    await message.answer(
        f"Holat: <b>{cond}</b>\n\n"
        "💰 <b>Kanalda ko'rsatiladigan sotuv narxini kiriting ($):</b>\n<i>(Masalan: 600)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(ChannelPostStates.waiting_sell_price, F.text)
@safe_handler
async def post_sell_price_received(message: types.Message, state: FSMContext, bot: Bot):
    await queue_listing(message, state, bot)


@router.message(F.text.in_(["📦 Karobka", "Karobka"]))
@safe_handler
async def start_karobka_update(message: types.Message, state: FSMContext):
    active, role, _ = await io_worker.call(
        sheets_service.check_member, message.from_user.id, force_refresh=True
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        raise BusinessRuleError("Karobka holatini o‘zgartirishga ruxsat berilmagan.")
    await begin_flow(state, message.from_user.id)
    await state.set_state(KarobkaStates.waiting_imei)
    await message.answer("Telefon IMEI sini kiriting:", reply_markup=cancel_kb())


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
            "Bu telefon karobkasi allaqachon mavjud.", reply_markup=main_menu_kb()
        )
        return
    await state.update_data(
        phone_id=phone["Telefon ID"], imei=phone["IMEI"], model=phone["Model"]
    )
    await state.set_state(KarobkaStates.confirm_phone)
    await message.answer(
        f"<b>{safe_html(phone['Model'])}</b> · <code>{safe_html(phone['IMEI'])}</code>\nKarobka keltirildimi?",
        reply_markup=yes_no_kb(),
    )


@router.message(
    KarobkaStates.confirm_phone, F.text.in_(["✅ Ha", "❌ Yo'q", "Ha", "Yo'q"])
)
@safe_handler
async def confirm_karobka_update(message: types.Message, state: FSMContext):
    if "Yo'q" in message.text:
        await state.set_state(KarobkaStates.waiting_imei)
        await message.answer(
            "Boshqa telefon IMEI sini kiriting:", reply_markup=cancel_kb()
        )
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
        "Iltimos, tasdiqlash uchun quyidagi tugmalardan birini tanlang:",
        reply_markup=yes_no_kb(),
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
    await state.set_state(HaridStates.waiting_imei_photo)
    await message.answer(
        f"Tanlandi: <b>{safe_html(model)}</b>\nIMEI rasmini yuboring yoki tashlab keting:",
        reply_markup=skip_inline_kb("skip_imei_photo"),
    )


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
    reference = data.get("phone_id")
    if not reference:
        raise BusinessRuleError("Telefonni qayta tanlang.")
    phone = await io_worker.call(sheets_service.get_phone_by_id, reference, fresh=True)
    if not phone or phone.get("Holati") != "Sotuvda":
        raise BusinessRuleError(
            "Sotilgan yoki mavjud bo‘lmagan telefonga e’lon berib bo‘lmaydi."
        )
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
                "phone_id": reference,
                "actor_id": message.from_user.id,
                "bot_id": bot.id,
                "data": {**phone, "sell_price": price},
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
    await state.clear()
    await message.answer(
        "✅ E’lon ma’lumoti saqlandi. Kanalga yuborish navbatda. Mavjud post tahrirlanadi.",
        reply_markup=main_menu_kb(),
    )
