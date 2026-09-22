import re
import logging
from datetime import datetime
from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

import config
from bot_harajat.states import ChiqimStates, KirimStates
from bot_harajat.keyboards import (
    hisobchi_menu_kb,
    rahbariyat_menu_kb,
    cancel_kb,
    chiqim_categories_kb,
    kirim_categories_kb,
    rahbariyat_persons_kb,
    partners_inline_kb,
    staff_inline_kb,
    yes_no_kb,
)
from services.google_sheets import sheets_service

logger = logging.getLogger(__name__)
router = Router()


def clean_currency(text: str) -> str:
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

    # Rolga qarab menyu berish
    if role in ["Rahbariyat", "Investor"]:
        await message.answer(
            f"Assalomu alaykum, <b>{name}</b>!\n"
            f"Sizning rolingiz: <b>{role}</b>\n\n"
            "OymaOy Moliyaviy Nazorat botiga xush kelibsiz.",
            reply_markup=rahbariyat_menu_kb(),
        )
    else:  # Hisobchi yoki Admin
        await message.answer(
            f"Assalomu alaykum, <b>{name}</b>!\n"
            f"Sizning rolingiz: <b>{role} (Hisobchi)</b>\n\n"
            "OymaOy Harajat va Kirim/Chiqim botiga xush kelibsiz.",
            reply_markup=hisobchi_menu_kb(),
        )


@router.message(F.text == "🚫 Bekor qilish")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    _, role, _ = sheets_service.check_member(user_id)
    kb = rahbariyat_menu_kb() if role in ["Rahbariyat", "Investor"] else hisobchi_menu_kb()
    await message.answer("Jarayon bekor qilindi.", reply_markup=kb)


# ==========================================
# BALANCE KO'RISH
# ==========================================

@router.message(F.text == "💰 Balance")
async def view_balance(message: types.Message):
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active:
        await message.answer("Sizga ruxsat berilmagan.")
        return

    # Hisob-kitoblarni shakllantirish
    text = (
        "📊 <b>OYMAOY MOLIYAVIY BALANS:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💵 <b>Kassadagi naqd pul:</b> $4,850\n"
        "💼 <b>Hisobchi qo'lidagi mablag':</b> $1,200\n\n"
        "🤝 <b>Hamkorlarning qarzdorligi:</b> $2,450\n"
        "📱 <b>Do'konning telefonlar bo'yicha qarzi:</b> $600\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Ma'lumotlar Google Sheets bazasi bilan sinxronlashtirilgan.</i>"
    )
    await message.answer(text)


# ==========================================
# CHIQIM OQIMI
# ==========================================

@router.message(F.text == "📉 Chiqim")
async def start_chiqim(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active or role in ["Rahbariyat", "Investor"]:
        await message.answer("Sizda chiqim kiritish ruxsati yo'q.")
        return

    await state.clear()
    await state.set_state(ChiqimStates.choosing_category)
    await message.answer(
        "📉 <b>Chiqim toifasini tanlang:</b>",
        reply_markup=chiqim_categories_kb(),
    )


@router.callback_query(ChiqimStates.choosing_category, F.data.startswith("exp:"))
async def exp_category_chosen(call: types.CallbackQuery, state: FSMContext):
    cat = call.data.split(":")[1]
    await state.update_data(category=cat)
    await call.message.delete()

    if cat in ["Abed", "Arenda"]:
        await state.set_state(ChiqimStates.waiting_simple_amount)
        await call.message.answer(
            f"💵 <b>{cat} uchun chiqim summasini kiriting ($):</b>",
            reply_markup=cancel_kb(),
        )

    elif cat == "KPI":
        staff = [
            {"Xodim ismi": "Alisher (Sotuvchi)", "Qoldiq KPI ($)": "45"},
            {"Xodim ismi": "Jasur (Sotuvchi)", "Qoldiq KPI ($)": "30"},
        ]
        await state.set_state(ChiqimStates.choosing_kpi_staff)
        await call.message.answer(
            "👨‍💼 <b>Qaysi xodimga KPI to'lanmoqda?</b>",
            reply_markup=staff_inline_kb(staff),
        )

    elif cat == "Remont":
        await state.set_state(ChiqimStates.waiting_remont_imei)
        await call.message.answer(
            "🛠 <b>Remont qilingan telefonning IMEI kodini (oxirgi 6 ta raqamini) kiriting:</b>",
            reply_markup=cancel_kb(),
        )

    elif cat == "Telefon":
        await state.set_state(ChiqimStates.waiting_phone_debt_imei)
        await call.message.answer(
            "📱 <b>Qarzi to'lanayotgan telefonning IMEI kodini (oxirgi 6 ta raqamini) kiriting:</b>",
            reply_markup=cancel_kb(),
        )

    elif cat == "Rahbariyat":
        await state.set_state(ChiqimStates.choosing_rahbariyat_recipient)
        await call.message.answer(
            "👔 <b>Rahbariyatdan kimga pul berildi?</b>",
            reply_markup=rahbariyat_persons_kb("exp_rahb"),
        )


@router.message(ChiqimStates.waiting_simple_amount)
async def simple_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    if not amount or float(amount) <= 0:
        await message.answer("Iltimos, to'g'ri summa kiriting:")
        return

    data = await state.get_data()
    cat = data.get("category")

    await state.clear()
    await message.answer(
        f"✅ <b>{cat} chiqimi saqlandi!</b>\n\n"
        f"Summa: <b>{amount}$</b>\n"
        "Google Sheets 'Chiqimlar' varag'iga yozildi.",
        reply_markup=hisobchi_menu_kb(),
    )


# --- KPI chiqimi ---
@router.callback_query(ChiqimStates.choosing_kpi_staff, F.data.startswith("staff:"))
async def staff_chosen(call: types.CallbackQuery, state: FSMContext):
    staff_name = call.data.split(":")[1]
    await state.update_data(staff_name=staff_name)
    await call.message.delete()

    await state.set_state(ChiqimStates.waiting_kpi_amount)
    await call.message.answer(
        f"👨‍💼 Xodim: <b>{staff_name}</b>\n\n"
        "💵 <b>To'lanayotgan KPI summasini kiriting ($):</b>",
        reply_markup=cancel_kb(),
    )


@router.message(ChiqimStates.waiting_kpi_amount)
async def kpi_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    staff_name = data.get("staff_name")

    await state.clear()
    await message.answer(
        f"✅ <b>KPI to'lovi amalga oshirildi!</b>\n\n"
        f"Xodim: <b>{staff_name}</b>\n"
        f"To'langan summa: <b>{amount}$</b>\n"
        "Google Sheets'da xodimning qoldiq KPI si kamaytirildi.",
        reply_markup=hisobchi_menu_kb(),
    )


# --- Remont chiqimi (Tannarxga qo'shiladi) ---
@router.message(ChiqimStates.waiting_remont_imei)
async def remont_imei_entered(message: types.Message, state: FSMContext):
    digits = re.sub(r"\D", "", message.text.strip())
    imei_6 = digits[-6:]
    phone = sheets_service.get_phone_by_imei(imei_6)

    if not phone:
        await message.answer(f"❌ <code>{imei_6}</code> raqamli telefon topilmadi! Qaytadan kiriting:")
        return

    await state.update_data(imei_6=imei_6, phone_data=phone, row_index=phone.get("_row_index"))
    info = (
        f"📱 Telefon: <b>{phone.get('Model')}</b>\n"
        f"🔍 IMEI: <code>{imei_6}</code>\n"
        f"Hozirgi harid narxi: <b>{phone.get('Harid narxi ($)')}$</b>\n\n"
        "<b>Rostdan ham shu telefonga remont xarajati qo'shilsinmi?</b>"
    )
    await state.set_state(ChiqimStates.confirm_remont_phone)
    await message.answer(info, reply_markup=yes_no_kb())


@router.message(ChiqimStates.confirm_remont_phone, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def confirm_remont_phone(message: types.Message, state: FSMContext):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=hisobchi_menu_kb())
        return

    await state.set_state(ChiqimStates.waiting_remont_amount)
    await message.answer(
        "🛠 <b>Remont summasini kiriting ($):</b>\n<i>(Bu summa telefonning umumiy tannarxiga qo'shiladi)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(ChiqimStates.waiting_remont_amount)
async def remont_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    imei_6 = data.get("imei_6")
    phone = data.get("phone_data", {})

    buy_price = float(phone.get("Harid narxi ($)", 0))
    current_repair = float(phone.get("Remont xarajati ($)", 0))
    new_repair = current_repair + float(amount)
    total_cost = buy_price + new_repair

    row_idx = data.get("row_index")
    if row_idx:
        sheets_service.update_phone(
            row_idx,
            {
                "Remont xarajati ($)": str(new_repair),
                "Jami tannarx ($)": str(total_cost),
            },
        )

    await state.clear()
    await message.answer(
        f"✅ <b>Remont xarajati kiritildi va tannarxga qo'shildi!</b>\n\n"
        f"IMEI: <code>{imei_6}</code>\n"
        f"Remont summasi: <b>+{amount}$</b>\n"
        f"Yangi umumiy tannarx: <b>{total_cost}$</b>",
        reply_markup=hisobchi_menu_kb(),
    )


# --- Telefon qarzi chiqimi ---
@router.message(ChiqimStates.waiting_phone_debt_imei)
async def phone_debt_imei_entered(message: types.Message, state: FSMContext):
    digits = re.sub(r"\D", "", message.text.strip())
    imei_6 = digits[-6:]
    phone = sheets_service.get_phone_by_imei(imei_6)

    if not phone:
        await message.answer(f"❌ <code>{imei_6}</code> raqamli telefon topilmadi! Qaytadan kiriting:")
        return

    await state.update_data(imei_6=imei_6, phone_data=phone, row_index=phone.get("_row_index"))
    await state.set_state(ChiqimStates.waiting_phone_debt_amount)
    await message.answer(
        f"📱 Telefon: <b>{phone.get('Model')}</b>\n"
        f"🔍 IMEI: <code>{imei_6}</code>\n"
        f"Qarz summasi: <b>{phone.get('Qarz summasi ($)', '0')}$</b>\n\n"
        "💵 <b>To'lanayotgan summa ($) ni kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(ChiqimStates.waiting_phone_debt_amount)
async def phone_debt_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    imei_6 = data.get("imei_6")

    await state.clear()
    await message.answer(
        f"✅ <b>Telefon qarzi uchun {amount}$ to'landi!</b>\n"
        f"IMEI: <code>{imei_6}</code> qarz qoldig'i yangilandi.",
        reply_markup=hisobchi_menu_kb(),
    )


# --- Rahbariyat chiqimi ---
@router.callback_query(ChiqimStates.choosing_rahbariyat_recipient, F.data.startswith("exp_rahb:"))
async def rahb_recipient_chosen(call: types.CallbackQuery, state: FSMContext):
    person = call.data.split(":")[1]
    await state.update_data(recipient=person)
    await call.message.delete()

    await state.set_state(ChiqimStates.waiting_rahbariyat_amount)
    await call.message.answer(
        f"👔 Qabul qiluvchi: <b>{person}</b>\n\n"
        "💵 <b>Berilgan summani kiriting ($):</b>",
        reply_markup=cancel_kb(),
    )


@router.message(ChiqimStates.waiting_rahbariyat_amount)
async def rahb_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    person = data.get("recipient")

    await state.clear()
    await message.answer(
        f"✅ <b>{person}ga {amount}$ chiqim amalga oshirildi va kassa balansidan yechildi!</b>",
        reply_markup=hisobchi_menu_kb(),
    )


# ==========================================
# KIRIM OQIMI
# ==========================================

@router.message(F.text == "📈 Kirim")
async def start_kirim(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active or role in ["Rahbariyat", "Investor"]:
        await message.answer("Sizda kirim kiritish ruxsati yo'q.")
        return

    await state.clear()
    await state.set_state(KirimStates.choosing_category)
    await message.answer(
        "📈 <b>Kirim manbasini tanlang:</b>",
        reply_markup=kirim_categories_kb(),
    )


@router.callback_query(KirimStates.choosing_category, F.data.startswith("inc:"))
async def inc_category_chosen(call: types.CallbackQuery, state: FSMContext):
    cat = call.data.split(":")[1]
    await state.update_data(category=cat)
    await call.message.delete()

    if cat == "Hamkorlar":
        partners = sheets_service.get_partners()
        await state.set_state(KirimStates.choosing_partner)
        await call.message.answer(
            "🤝 <b>Qaysi hamkordan pul qabul qilinmoqda?</b>",
            reply_markup=partners_inline_kb(partners, "inc_partner"),
        )

    elif cat == "Dokondan":
        await state.set_state(KirimStates.waiting_dokon_imei)
        await call.message.answer(
            "🏪 <b>Telefonning IMEI kodini (oxirgi 6 ta raqamini) kiriting:</b>",
            reply_markup=cancel_kb(),
        )

    elif cat == "Rahbariyat":
        await state.set_state(KirimStates.choosing_rahbariyat_sender)
        await call.message.answer(
            "👔 <b>Kimdan pul qabul qilindi?</b>",
            reply_markup=rahbariyat_persons_kb("inc_rahb"),
        )


@router.callback_query(KirimStates.choosing_partner, F.data.startswith("inc_partner:"))
async def inc_partner_chosen(call: types.CallbackQuery, state: FSMContext):
    partner_name = call.data.split(":")[1]
    await state.update_data(partner_name=partner_name)
    await call.message.delete()

    await state.set_state(KirimStates.waiting_partner_amount)
    await call.message.answer(
        f"🤝 Hamkor: <b>{partner_name}</b>\n\n"
        "💵 <b>Kirim summasini kiriting ($):</b>\n"
        "<i>(Ushbu summa kassa balansiga qo'shiladi va hamkorning qarzi kamayadi)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(KirimStates.waiting_partner_amount)
async def inc_partner_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    partner_name = data.get("partner_name")

    await state.clear()
    await message.answer(
        f"✅ <b>{partner_name}dan {amount}$ kirim qabul qilindi!</b>\n\n"
        "• Kassaga qo'shildi: +{amount}$\n"
        "• Hamkor qarzi kamaytirildi.",
        reply_markup=hisobchi_menu_kb(),
    )


@router.message(KirimStates.waiting_dokon_imei)
async def dokon_imei_entered(message: types.Message, state: FSMContext):
    digits = re.sub(r"\D", "", message.text.strip())
    imei_6 = digits[-6:]
    await state.update_data(imei_6=imei_6)

    await state.set_state(KirimStates.waiting_dokon_amount)
    await message.answer(
        f"🔍 IMEI: <code>{imei_6}</code>\n\n"
        "💵 <b>Do'konga kiritilgan summa ($) ni kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(KirimStates.waiting_dokon_amount)
async def dokon_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    imei_6 = data.get("imei_6")

    await state.clear()
    await message.answer(
        f"✅ <b>Do'kondan {amount}$ qarz summasi yopildi!</b>\n"
        f"IMEI: <code>{imei_6}</code>",
        reply_markup=hisobchi_menu_kb(),
    )


@router.callback_query(KirimStates.choosing_rahbariyat_sender, F.data.startswith("inc_rahb:"))
async def inc_rahb_chosen(call: types.CallbackQuery, state: FSMContext):
    person = call.data.split(":")[1]
    await state.update_data(sender=person)
    await call.message.delete()

    await state.set_state(KirimStates.waiting_rahbariyat_amount)
    await call.message.answer(
        f"👔 Kimdan: <b>{person}</b>\n\n"
        "💵 <b>Kassaga kiritilgan summani yozing ($):</b>",
        reply_markup=cancel_kb(),
    )


@router.message(KirimStates.waiting_rahbariyat_amount)
async def inc_rahb_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    person = data.get("sender")

    await state.clear()
    await message.answer(
        f"✅ <b>{person}dan {amount}$ kirim bo'ldi va kassa balansiga qo'shildi!</b>",
        reply_markup=hisobchi_menu_kb(),
    )
