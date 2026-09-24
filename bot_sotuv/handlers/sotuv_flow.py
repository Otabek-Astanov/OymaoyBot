import re
import uuid
from datetime import datetime
import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

import config
from bot_sotuv.states import SotuvStates
from bot_sotuv.keyboards import (
    main_menu_kb,
    cancel_kb,
    payment_type_kb,
    partners_kb,
    kpi_kb,
    yes_no_kb,
)
from services.google_sheets import sheets_service
from services.telegram_poster import poster_service
from services.health_check import health_checker
from aiogram.filters import CommandStart, Command

logger = logging.getLogger(__name__)
router = Router()


def clean_currency(text: str) -> str:
    cleaned = re.sub(r"[^\d.]", "", text.strip())
    return cleaned if cleaned else "0"


@router.message(Command("status"))
@router.message(Command("check"))
async def cmd_check_status(message: types.Message, bot: Bot):
    """Admin uchun tizim konfiguratsiyasi diagnostikasini chiqaradi."""
    user_id = message.from_user.id
    if config.ADMIN_IDS and user_id not in config.ADMIN_IDS:
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

    # 2. Foydalanuvchini tekshirish
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
        "OymaOy Sotuv botiga xush kelibsiz. Quyidagi tugma orqali yangi sotuvni rasmiylashtirishingiz mumkin:",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "🚫 Bekor qilish")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Jarayon bekor qilindi.", reply_markup=main_menu_kb())


@router.message(F.text == "📱 Yangi sotuvni rasmiylashtirish")
async def start_sale(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, _, _ = sheets_service.check_member(user_id)
    if not is_active:
        await message.answer("Sizga ruxsat berilmagan.")
        return

    await state.clear()
    await state.set_state(SotuvStates.waiting_imei)
    await message.answer(
        "🔍 <b>Sotilayotgan telefonning IMEI kodini (oxirgi 6 ta raqamini) kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(SotuvStates.waiting_imei)
async def imei_entered(message: types.Message, state: FSMContext):
    digits = re.sub(r"\D", "", message.text.strip())
    if len(digits) < 6:
        await message.answer("Iltimos, kamida 6 ta raqam kiriting:")
        return

    imei_6 = digits[-6:]
    phone = sheets_service.get_phone_by_imei(imei_6)

    if not phone:
        await message.answer(
            f"❌ Bazadan <code>{imei_6}</code> raqamli telefon topilmadi!\n"
            "Iltimos, IMEI raqamini tekshirib qaytadan kiriting:",
            reply_markup=cancel_kb(),
        )
        return

    status = phone.get("Holati", "")
    if status == "Sotildi":
        await message.answer(
            f"⚠️ Ushbu telefon (IMEI: <code>{imei_6}</code>) allaqachon sotilgan deb belgilangan!",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    # Telefon ma'lumotlarini saqlash
    await state.update_data(
        imei_6=imei_6,
        model=phone.get("Model", "Telefon"),
        phone_data=phone,
        row_index=phone.get("_row_index"),
        channel_post_id=phone.get("Kanal post ID", ""),
    )

    info = (
        "📱 <b>Telefon ma'lumotlari:</b>\n\n"
        f"Model: <b>{phone.get('Model')}</b>\n"
        f"Xotira: <b>{phone.get('Xotira')}</b> | Batareya: <b>{phone.get('Batareya %')}%</b>\n"
        f"Rang: <b>{phone.get('Rang')}</b> | Karobka: <b>{phone.get('Karobka')}</b>\n"
        f"Harid narxi: <b>{phone.get('Harid narxi ($)')}$</b>\n"
        f"IMEI (oxirgi 6): <code>{imei_6}</code>\n\n"
        "<b>Rostdan ham shu telefon sotilmoqdami?</b>"
    )

    await state.set_state(SotuvStates.confirm_phone)
    await message.answer(info, reply_markup=yes_no_kb())


@router.message(SotuvStates.confirm_phone, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def confirm_phone_chosen(message: types.Message, state: FSMContext):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("Sotuv bekor qilindi.", reply_markup=main_menu_kb())
        return

    await state.set_state(SotuvStates.waiting_sell_price)
    await message.answer(
        "💰 <b>Sotuv narxini kiriting ($):</b>\n<i>(Masalan: 650)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(SotuvStates.waiting_sell_price)
async def sell_price_entered(message: types.Message, state: FSMContext):
    price = clean_currency(message.text)
    if not price or float(price) <= 0:
        await message.answer("Iltimos, to'g'ri sotuv narxini kiriting ($ da):")
        return

    await state.update_data(sell_price=price)
    await state.set_state(SotuvStates.waiting_buyer_name)
    await message.answer(
        "👤 <b>Mijoz (xaridor) ismini kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(SotuvStates.waiting_buyer_name)
async def buyer_name_entered(message: types.Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(buyer_name=name)

    await state.set_state(SotuvStates.waiting_buyer_phone)
    await message.answer(
        "📞 <b>Mijozning telefon raqamini kiriting:</b>\n<i>(Masalan: +998901234567)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(SotuvStates.waiting_buyer_phone)
async def buyer_phone_entered(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    await state.update_data(buyer_phone=phone)

    await state.set_state(SotuvStates.waiting_payment_type)
    await message.answer(
        "💳 <b>Telefon naqdga sotildimi yoki qarzgami?</b>",
        reply_markup=payment_type_kb(),
    )


@router.message(SotuvStates.waiting_payment_type, F.text.in_(["💵 Naqd", "💳 Qarzga"]))
async def payment_type_chosen(message: types.Message, state: FSMContext):
    ptype = "Naqd" if "Naqd" in message.text else "Qarz"
    await state.update_data(payment_type=ptype)

    if ptype == "Qarz":
        partners = sheets_service.get_partners()
        await state.set_state(SotuvStates.choosing_partner)
        await message.answer(
            "🤝 <b>Nasiya/Qarz manbasini tanlang:</b>",
            reply_markup=partners_kb(partners),
        )
    else:
        await state.update_data(
            partner_name="-",
            initial_payment="0",
            partner_debt="0",
        )
        await state.set_state(SotuvStates.choosing_kpi)
        await message.answer(
            "🎁 <b>Sotuvchining KPI miqdorini tanlang:</b>",
            reply_markup=kpi_kb(),
        )


@router.callback_query(SotuvStates.choosing_partner, F.data.startswith("partner:"))
async def partner_chosen(call: types.CallbackQuery, state: FSMContext):
    partner = call.data.split(":")[1]
    await state.update_data(partner_name=partner)
    await call.message.delete()

    await state.set_state(SotuvStates.waiting_initial_payment)
    await call.message.answer(
        f"Tanlandi: <b>{partner}</b>\n\n"
        "💵 <b>Boshlang'ich to'lov summasini kiriting ($):</b>\n"
        "<i>(Agar boshlang'ich to'lov bo'lmasa 0 deb yozing)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(SotuvStates.waiting_initial_payment)
async def initial_payment_entered(message: types.Message, state: FSMContext):
    initial_str = clean_currency(message.text)
    initial = float(initial_str) if initial_str else 0.0

    data = await state.get_data()
    sell_price = float(data.get("sell_price", 0))

    partner_debt = max(0.0, sell_price - initial)
    await state.update_data(
        initial_payment=str(initial),
        partner_debt=str(partner_debt),
    )

    await state.set_state(SotuvStates.choosing_kpi)
    await message.answer(
        f"Hisoblandi:\n"
        f"• Sotuv narxi: {sell_price}$\n"
        f"• Boshlang'ich to'lov: {initial}$\n"
        f"• Hamkor/Do'kon qarzi: <b>{partner_debt}$</b>\n\n"
        "🎁 <b>Sotuvchining KPI miqdorini tanlang:</b>",
        reply_markup=kpi_kb(),
    )


@router.message(SotuvStates.choosing_kpi)
async def kpi_chosen(message: types.Message, state: FSMContext):
    kpi = clean_currency(message.text)
    if not kpi or float(kpi) < 0:
        await message.answer("Iltimos, KPI summasini tanlang yoki kiriting (masalan 5$ yoki 10$):")
        return

    await state.update_data(seller_kpi=kpi)

    # Tasdiqlash summary
    data = await state.get_data()
    summary = (
        "📋 <b>SOTUV MA'LUMOTLARINI TASDIQLANG:</b>\n\n"
        f"📱 Telefon: <b>{data.get('model')}</b>\n"
        f"🔍 IMEI: <code>{data.get('imei_6')}</code>\n"
        f"💰 Sotuv narxi: <b>{data.get('sell_price')}$</b>\n\n"
        f"👤 Xaridor: <b>{data.get('buyer_name')}</b> ({data.get('buyer_phone')})\n"
        f"💳 To'lov turi: <b>{data.get('payment_type')}</b>\n"
    )
    if data.get("payment_type") == "Qarz":
        summary += (
            f"🤝 Manba: <b>{data.get('partner_name')}</b>\n"
            f"💵 Boshlang'ich: <b>{data.get('initial_payment')}$</b>\n"
            f"📉 Hamkor qarzi: <b>{data.get('partner_debt')}$</b>\n"
        )
    summary += (
        f"🎁 Sotuvchi KPI: <b>{data.get('seller_kpi')}$</b>\n\n"
        "<b>Ma'lumotlar to'g'rimi? Tasdiqlaysizmi?</b>"
    )

    await state.set_state(SotuvStates.confirm_sale)
    await message.answer(summary, reply_markup=yes_no_kb())


@router.message(SotuvStates.confirm_sale, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def confirm_sale_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("Sotuv bekor qilindi.", reply_markup=main_menu_kb())
        return

    data = await state.get_data()
    user_name = message.from_user.full_name
    data["seller_name"] = user_name
    data["seller_id"] = message.from_user.id

    await message.answer("⏳ Sotuv rasmiylashtirilmoqda, iltimos kuting...")

    # 1. Sotuv guruhiga xabar yuborish
    await poster_service.post_to_sell_group(bot, data)

    # 2. Google Sheets'dagi 'Telefonlar' jadvalida sotuv va sof foydani yozish
    row_idx = data.get("row_index")
    phone_data = data.get("phone_data", {})
    profit = 0.0
    if row_idx:
        _, profit = sheets_service.record_sale(row_idx, data, phone_data)

    # 3. Kanaldagi postni '🔴 SOTILDI ❌' deb edit qilish
    channel_post_id = data.get("channel_post_id")
    if channel_post_id and str(channel_post_id).isdigit():
        await poster_service.mark_as_sold_on_channel(bot, int(channel_post_id))

    await state.clear()
    await message.answer(
        "🎉 <b>Sotuv muvaffaqiyatli rasmiylashtirildi!</b>\n\n"
        f"• Sotuv narxi: <b>{data.get('sell_price')}$</b>\n"
        f"• Sotuvchi KPI: <b>{data.get('seller_kpi')}$</b>\n"
        f"• 💰 <b>Do‘konga sof foyda: +{profit:.1f}$</b>\n\n"
        "• Guruhga hisobot yuborildi ✅\n"
        "• Google Sheets 'Telefonlar' jadvaliga saqlandi ✅\n"
        "• Telegram kanaldagi e'lon tahrirlandi ✅",
        reply_markup=main_menu_kb(),
    )
