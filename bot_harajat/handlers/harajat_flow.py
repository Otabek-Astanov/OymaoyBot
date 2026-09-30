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
    skip_or_cancel_kb,
    skip_inline_kb,
    chiqim_categories_kb,
    kirim_categories_kb,
    rahbariyat_persons_kb,
    partners_inline_kb,
    staff_inline_kb,
    yes_no_kb,
    format_money_label,
)
from services.google_sheets import sheets_service
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
    is_active, role, name = sheets_service.check_member(user_id, force_refresh=True)

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
    elif role in ["Admin", "Hisobchi"]:
        await message.answer(
            f"Assalomu alaykum, <b>{name}</b>!\n"
            f"Sizning rolingiz: <b>{role}</b>\n\n"
            "OymaOy Harajat va Kirim/Chiqim botiga xush kelibsiz.",
            reply_markup=hisobchi_menu_kb(),
        )
    else:  # Masalan: Sotuvchi
        await message.answer(
            f"⛔ <b>Kechirasiz, {name}!</b>\n\n"
            f"Ushbu bot faqat <b>Hisobchi</b> va <b>Rahbariyat</b> uchun mo'ljallangan.\n"
            f"Sizning rolingiz: <b>{role}</b>\n\n"
            "💡 Iltimos, telefonlar haridi va sotuvi uchun <b>Harid Boti</b> yoki <b>Sotuv Boti</b>dan foydalaning.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return


@router.message(F.text == "🚫 Bekor qilish")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    _, role, _ = sheets_service.check_member(user_id)
    if role in ["Rahbariyat", "Investor"]:
        kb = rahbariyat_menu_kb()
    elif role in ["Admin", "Hisobchi"]:
        kb = hisobchi_menu_kb()
    else:
        kb = types.ReplyKeyboardRemove()
    await message.answer("Jarayon bekor qilindi.", reply_markup=kb)


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
# BALANCE KO'RISH
# ==========================================

@router.message(F.text == "💰 Balance")
async def view_balance(message: types.Message):
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active or role not in ["Admin", "Hisobchi", "Rahbariyat", "Investor"]:
        await message.answer("Sizga ruxsat berilmagan.")
        return

    summary = sheets_service.get_financial_summary()
    kassa = summary["kassa_balance"]
    partners = summary["partner_debts"]
    phone_debts = summary["store_phone_debts"]
    kpi_debts = summary["staff_kpi_debts"]
    profit = summary["total_net_profit"]

    text = (
        "📊 <b>OYMAOY MOLIYAVIY BALANS:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Kassadagi naqd pul:</b> {kassa:,.2f}$\n"
        f"🤝 <b>Hamkorlarning qarzdorligi:</b> {partners:,.2f}$\n"
        f"📱 <b>Do'konning telefonlar bo'yicha qarzi:</b> {phone_debts:,.2f}$\n"
        f"🎁 <b>Xodimlarning to'lanmagan KPI qarzi:</b> {kpi_debts:,.2f}$\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>Jami ko'rilgan sof foyda:</b> {profit:,.2f}$\n\n"
        "<i>Ma'lumotlar Google Sheets bazasidan real vaqtda hisoblandi.</i>"
    )
    await message.answer(text)


# ==========================================
# CHIQIM OQIMI
# ==========================================

@router.message(F.text == "📉 Chiqim")
async def start_chiqim(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active or role not in ["Admin", "Hisobchi"]:
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
        staff = sheets_service.get_staff_list()
        if not staff:
            await call.message.answer(
                "⚠️ Hozircha faol xodimlar topilmadi. Avval Google Sheets 'Xodimlar' jadvaliga xodimlarni kiriting.",
                reply_markup=hisobchi_menu_kb(),
            )
            return

        await state.set_state(ChiqimStates.choosing_kpi_staff)
        await call.message.answer(
            "👨‍💼 <b>Qaysi xodimga KPI to'lanmoqda?</b>",
            reply_markup=staff_inline_kb(staff),
        )

    elif cat == "Remont":
        await state.set_state(ChiqimStates.waiting_remont_imei)
        await call.message.answer(
            "🛠 <b>Remont qilingan telefonning IMEI kodini kiriting:</b>",
            reply_markup=cancel_kb(),
        )

    elif cat == "Telefon":
        await state.set_state(ChiqimStates.waiting_phone_debt_imei)
        await call.message.answer(
            "📱 <b>Qarzi to'lanayotgan telefonning IMEI kodini kiriting:</b>",
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
    user_name = message.from_user.full_name

    # Google Sheets Chiqimlar jadvaliga yozish
    ok = sheets_service.record_expense(
        expense_type=str(cat),
        amount=float(amount),
        creator_name=user_name,
    )

    await state.clear()
    if not ok:
        await message.answer(
            "❌ <b>Xatolik: Ma'lumotlarni Google Sheets'ga saqlashda xatolik yuz berdi.</b>",
            reply_markup=hisobchi_menu_kb(),
        )
        return

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
    if not amount or float(amount) <= 0:
        await message.answer("Iltimos, to'g'ri summa kiriting:")
        return

    data = await state.get_data()
    staff_name = data.get("staff_name")
    user_name = message.from_user.full_name

    ok = sheets_service.pay_staff_kpi(staff_name, float(amount), user_name)

    await state.clear()
    if not ok:
        await message.answer(
            "❌ <b>Xatolik: Ma'lumotlarni Google Sheets'ga saqlashda xatolik yuz berdi.</b>",
            reply_markup=hisobchi_menu_kb(),
        )
        return

    await message.answer(
        f"✅ <b>KPI to'lovi amalga oshirildi!</b>\n\n"
        f"Xodim: <b>{staff_name}</b>\n"
        f"To'langan summa: <b>{amount}$</b>\n"
        "Google Sheets 'Xodimlar' va 'Chiqimlar' varaqlariga yozildi.",
        reply_markup=hisobchi_menu_kb(),
    )


# --- Remont chiqimi (Tannarxga qo'shiladi) ---
@router.message(ChiqimStates.waiting_remont_imei)
async def remont_imei_entered(message: types.Message, state: FSMContext):
    imei_input = message.text.strip()
    if len(imei_input) < 4:
        await message.answer("Iltimos, to'g'ri IMEI kodini kiriting:")
        return

    phone = sheets_service.get_phone_by_imei(imei_input)

    if not phone:
        await message.answer(f"❌ <code>{imei_input}</code> raqamli telefon topilmadi! Qaytadan kiriting:")
        return

    actual_imei = phone.get("IMEI", phone.get("IMEI (oxirgi 6)", imei_input))
    await state.update_data(imei=actual_imei, imei_6=actual_imei, phone_data=phone, row_index=phone.get("_row_index"))
    info = (
        f"📱 Telefon: <b>{phone.get('Model')}</b>\n"
        f"🔍 IMEI: <code>{actual_imei}</code>\n"
        f"Hozirgi harid narxi: <b>{format_money_label(phone.get('Harid narxi ($)'))}</b>\n\n"
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
    if not amount or float(amount) <= 0:
        await message.answer("Iltimos, to'g'ri summa kiriting:")
        return

    data = await state.get_data()
    imei_val = data.get("imei", data.get("imei_6", ""))
    phone = data.get("phone_data", {})
    user_name = message.from_user.full_name

    buy_price = clean_num(phone.get("Harid narxi ($)", 0))
    current_repair = clean_num(phone.get("Remont xarajati ($)", 0))
    clean_amt = clean_num(amount)
    new_repair = clean_num(current_repair + clean_amt)
    total_cost = clean_num(buy_price + new_repair)

    row_idx = data.get("row_index")
    if row_idx:
        sheets_service.update_phone(
            row_idx,
            {
                "Remont xarajati ($)": new_repair,
                "Jami tannarx ($)": total_cost,
            },
        )

    # Google Sheets Chiqimlar jadvaliga yozish
    ok = sheets_service.record_expense(
        expense_type="Remont",
        amount=clean_amt,
        imei=imei_val,
        creator_name=user_name,
    )

    await state.clear()
    if not ok:
        await message.answer(
            "❌ <b>Xatolik: Ma'lumotlarni Google Sheets'ga saqlashda xatolik yuz berdi.</b>",
            reply_markup=hisobchi_menu_kb(),
        )
        return

    await message.answer(
        f"✅ <b>Remont xarajati kiritildi va tannarxga qo'shildi!</b>\n\n"
        f"IMEI: <code>{imei_val}</code>\n"
        f"Remont summasi: <b>+{amount}$</b>\n"
        f"Yangi umumiy tannarx: <b>{total_cost}$</b>\n"
        "Google Sheets 'Chiqimlar' varag'iga yozildi.",
        reply_markup=hisobchi_menu_kb(),
    )


# --- Telefon qarzi chiqimi ---
@router.message(ChiqimStates.waiting_phone_debt_imei)
async def phone_debt_imei_entered(message: types.Message, state: FSMContext):
    imei_input = message.text.strip()
    if len(imei_input) < 4:
        await message.answer("Iltimos, to'g'ri IMEI kodini kiriting:")
        return

    phone = sheets_service.get_phone_by_imei(imei_input)

    if not phone:
        await message.answer(f"❌ <code>{imei_input}</code> raqamli telefon topilmadi! Qaytadan kiriting:")
        return

    actual_imei = phone.get("IMEI", phone.get("IMEI (oxirgi 6)", imei_input))
    cur_debt = phone.get("Harid qarz summasi ($)", phone.get("Qarz summasi ($)", "0"))
    await state.update_data(imei=actual_imei, imei_6=actual_imei, phone_data=phone, row_index=phone.get("_row_index"))
    await state.set_state(ChiqimStates.waiting_phone_debt_amount)
    await message.answer(
        f"📱 Telefon: <b>{phone.get('Model')}</b>\n"
        f"🔍 IMEI: <code>{actual_imei}</code>\n"
        f"Qarz summasi: <b>{format_money_label(cur_debt)}</b>\n\n"
        "💵 <b>To'lanayotgan summa ($) ni kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(ChiqimStates.waiting_phone_debt_amount)
async def phone_debt_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    if not amount or float(amount) <= 0:
        await message.answer("Iltimos, to'g'ri summa kiriting:")
        return

    data = await state.get_data()
    imei_val = data.get("imei", data.get("imei_6", ""))
    user_name = message.from_user.full_name

    # Telefon qarzini to'lash va Chiqimlar jadvaliga yozish
    ok, new_debt = sheets_service.pay_phone_debt(imei_val, float(amount), user_name)

    await state.clear()
    if not ok:
        await message.answer(
            "❌ <b>Xatolik: Ma'lumotlarni Google Sheets'ga saqlashda xatolik yuz berdi.</b>",
            reply_markup=hisobchi_menu_kb(),
        )
        return

    await message.answer(
        f"✅ <b>Telefon qarzi uchun {amount}$ to'landi!</b>\n"
        f"IMEI: <code>{imei_val}</code>\n"
        f"Qolgan qarz summasi: <b>{new_debt}$</b>\n"
        "Google Sheets 'Chiqimlar' varag'iga yozildi.",
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
    if not amount or float(amount) <= 0:
        await message.answer("Iltimos, to'g'ri summa kiriting:")
        return

    data = await state.get_data()
    person = data.get("recipient")
    user_name = message.from_user.full_name

    # Google Sheets Chiqimlar jadvaliga yozish
    ok = sheets_service.record_expense(
        expense_type="Rahbariyat",
        amount=float(amount),
        recipient=person,
        creator_name=user_name,
    )

    await state.clear()
    if not ok:
        await message.answer(
            "❌ <b>Xatolik: Ma'lumotlarni Google Sheets'ga saqlashda xatolik yuz berdi.</b>",
            reply_markup=hisobchi_menu_kb(),
        )
        return

    await message.answer(
        f"✅ <b>{person}ga {amount}$ chiqim amalga oshirildi va kassa balansidan yechildi!</b>\n"
        "Google Sheets 'Chiqimlar' varag'iga yozildi.",
        reply_markup=hisobchi_menu_kb(),
    )


# ==========================================
# KIRIM OQIMI
# ==========================================

@router.message(F.text == "📈 Kirim")
async def start_kirim(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active or role not in ["Admin", "Hisobchi"]:
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
            "🏪 <b>Telefonning IMEI kodini kiriting (ixtiyoriy):</b>\n<i>(Umumiy kirim bo'lsa '⏭ Tashlab ketish'ni bosing)</i>",
            reply_markup=skip_inline_kb("skip_dokon_imei"),
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

    # Hamkorning joriy qarzdorligini olish
    partners = sheets_service.get_partners(force_refresh=True)
    cur_debt = "0"
    for p in partners:
        if str(p.get("Hamkor nomi", "")).strip().lower() == partner_name.strip().lower():
            raw_d = str(p.get("Hozirgi qarzdorlik ($)", "0")).replace("$", "").replace(",", "").strip()
            try:
                fd = float(raw_d)
                cur_debt = f"${int(fd):,}" if fd.is_integer() else f"${fd:,.2f}"
            except Exception:
                cur_debt = f"${raw_d}"
            break

    await state.set_state(KirimStates.waiting_partner_amount)
    await call.message.answer(
        f"🤝 Hamkor: <b>{partner_name}</b>\n"
        f"📉 Hozirgi qarzdorlik: <b>{cur_debt}</b>\n\n"
        "💵 <b>Kirim summasini kiriting ($):</b>\n"
        "<i>(Ushbu summa kassa balansiga qo'shiladi va hamkorning qarzi kamayadi)</i>",
        reply_markup=cancel_kb(),
    )


@router.message(KirimStates.waiting_partner_amount)
async def inc_partner_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    if not amount or float(amount) <= 0:
        await message.answer("Iltimos, to'g'ri summa kiriting:")
        return

    data = await state.get_data()
    partner_name = data.get("partner_name")
    user_name = message.from_user.full_name

    ok = sheets_service.reduce_partner_debt(partner_name, float(amount), user_name)

    await state.clear()
    if not ok:
        await message.answer(
            "❌ <b>Xatolik: Ma'lumotlarni Google Sheets'ga saqlashda xatolik yuz berdi.</b>\n"
            "Iltimos, qaytadan urinib ko'ring yoki internet aloqasini tekshiring.",
            reply_markup=hisobchi_menu_kb(),
        )
        return

    await message.answer(
        f"✅ <b>{partner_name}dan {amount}$ kirim qabul qilindi!</b>\n\n"
        f"• Kassaga qo'shildi: +{amount}$\n"
        "• Hamkor qarzi kamaytirildi va Google Sheets'ga yozildi.",
        reply_markup=hisobchi_menu_kb(),
    )


@router.callback_query(KirimStates.waiting_dokon_imei, F.data == "skip_dokon_imei")
async def dokon_imei_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(imei="-", imei_6="-", phone_data=None)
    await state.set_state(KirimStates.waiting_dokon_amount)
    msg_text = "🔍 IMEI: <code>-</code>\n\n💵 <b>Do'konga kiritilgan summa ($) ni kiriting:</b>"
    await call.message.answer(
        msg_text,
        reply_markup=cancel_kb(),
    )


@router.message(KirimStates.waiting_dokon_imei)
async def dokon_imei_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        actual_imei = "-"
        cur_debt = "0"
        phone = None
    else:
        imei_input = message.text.strip()
        if len(imei_input) < 4:
            await message.answer(
                "Iltimos, to'g'ri IMEI kodini kiriting yoki '⏭ Tashlab ketish'ni bosing:",
                reply_markup=skip_inline_kb("skip_dokon_imei"),
            )
            return

        phone = sheets_service.get_phone_by_imei(imei_input)
        actual_imei = phone.get("IMEI", phone.get("IMEI (oxirgi 6)", imei_input)) if phone else imei_input
        cur_debt = phone.get("Harid qarz summasi ($)", "0") if phone else "0"

    await state.update_data(imei=actual_imei, imei_6=actual_imei, phone_data=phone)
    await state.set_state(KirimStates.waiting_dokon_amount)
    msg_text = f"🔍 IMEI: <code>{actual_imei}</code>\n"
    if str(cur_debt).replace("$", "").strip() not in ["0", "0.0", "0.00", ""]:
        msg_text += f"Hozirgi qarz: <b>{format_money_label(cur_debt)}</b>\n"
    msg_text += "\n💵 <b>Do'konga kiritilgan summa ($) ni kiriting:</b>"
    await message.answer(
        msg_text,
        reply_markup=cancel_kb(),
    )


@router.message(KirimStates.waiting_dokon_amount)
async def dokon_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    if not amount or float(amount) <= 0:
        await message.answer("Iltimos, to'g'ri summa kiriting:")
        return

    data = await state.get_data()
    imei_val = data.get("imei", data.get("imei_6", ""))
    user_name = message.from_user.full_name

    ok, new_debt = sheets_service.close_store_phone_debt(imei_val, float(amount), user_name)

    await state.clear()
    if not ok:
        await message.answer(
            "❌ <b>Xatolik: Ma'lumotlarni Google Sheets'ga saqlashda xatolik yuz berdi.</b>",
            reply_markup=hisobchi_menu_kb(),
        )
        return

    await message.answer(
        f"✅ <b>Do'kondan {amount}$ kirim qilindi va kassa balansiga qo'shildi!</b>\n"
        f"IMEI: <code>{imei_val}</code> | Qolgan qarz: <b>{new_debt}$</b>\n"
        "Google Sheets 'Kirimlar' varag'iga yozildi.",
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
    if not amount or float(amount) <= 0:
        await message.answer("Iltimos, to'g'ri summa kiriting:")
        return

    data = await state.get_data()
    person = data.get("sender")
    user_name = message.from_user.full_name

    ok = sheets_service.record_income(
        income_type="Rahbariyat",
        amount=float(amount),
        source=str(person),
        creator_name=user_name,
    )

    await state.clear()
    if not ok:
        await message.answer(
            "❌ <b>Xatolik: Ma'lumotlarni Google Sheets'ga saqlashda xatolik yuz berdi.</b>",
            reply_markup=hisobchi_menu_kb(),
        )
        return

    await message.answer(
        f"✅ <b>{person}dan {amount}$ kirim bo'ldi va kassa balansiga qo'shildi!</b>\n"
        "Google Sheets 'Kirimlar' varag'iga yozildi.",
        reply_markup=hisobchi_menu_kb(),
    )
