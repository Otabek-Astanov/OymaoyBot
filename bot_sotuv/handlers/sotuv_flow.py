import re
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

import config
from bot_sotuv.states import SotuvStates
from bot_sotuv.keyboards import (
    main_menu_kb,
    cancel_kb,
    skip_or_cancel_kb,
    skip_inline_kb,
    payment_type_kb,
    partners_kb,
    kpi_kb,
    kpi_inline_kb,
    yes_no_kb,
)
from services.google_sheets import sheets_service
from services.telegram_poster import poster_service
from services.health_check import health_checker
from utils.formatters import build_sotuv_phone_info
from aiogram.filters import CommandStart, Command

logger = logging.getLogger(__name__)
router = Router()


def clean_currency(text: str) -> str:
    cleaned = re.sub(r"[^\d.]", "", text.strip())
    return cleaned if cleaned else "0"


def extract_drive_file_id(photo_field: Any) -> str:
    """Google Sheets'dagi formula yoki URL ichidan Google Drive file_id ni ajratib oladi."""
    if not photo_field:
        return ""
    text = str(photo_field)
    match = re.search(r'/d/([a-zA-Z0-9_-]{25,})', text)
    if match:
        return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]{25,})', text)
    if match:
        return match.group(1)
    return ""


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
        "OymaOy Sotuv botiga xush kelibsiz. Quyidagi tugma orqali yangi sotuvni rasmiylashtirishingiz mumkin:",
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


@router.message(F.text == "📱 Yangi sotuvni rasmiylashtirish")
async def start_sale(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_active, role, _ = sheets_service.check_member(user_id)
    if not is_active or role == "Investor":
        await message.answer("Sizga ruxsat berilmagan.")
        return

    await state.clear()
    await state.set_state(SotuvStates.waiting_imei)
    await message.answer(
        "🔍 <b>Sotilayotgan qurilmaning IMEI yoki Seriya raqamini kiriting:</b>",
        reply_markup=cancel_kb(),
    )


@router.message(SotuvStates.waiting_imei)
async def imei_entered(message: types.Message, state: FSMContext):
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
    status = phone.get("Holati", "")
    if status == "Sotildi":
        model = phone.get("Model", "Qurilma")
        sold_date = phone.get("Sotilgan sana", "-")
        buyer = phone.get("Xaridor ismi", "-")
        buyer_phone = phone.get("Xaridor telefoni", "-")
        sell_price = phone.get("Sotuv narxi ($)", "-")
        seller = phone.get("Do'kon sotuvchisi", "-")

        lines = [
            "⚠️ <b>Ushbu qurilma allaqachon sotilgan!</b>\n",
            f"📱 Model: <b>{model}</b>",
            f"🔍 IMEI / Seriya: <code>{actual_imei}</code>",
        ]
        if sold_date and sold_date != "-":
            lines.append(f"📅 Sotilgan sana: <b>{sold_date}</b>")
        if buyer and buyer != "-":
            b_info = f"👤 Xaridor: <b>{buyer}</b>"
            if buyer_phone and buyer_phone != "-":
                b_info += f" ({buyer_phone})"
            lines.append(b_info)
        elif buyer_phone and buyer_phone != "-":
            lines.append(f"📞 Xaridor tel: <b>{buyer_phone}</b>")

        if sell_price and sell_price != "-":
            clean_p = str(sell_price).replace("$", "").replace(",", "").strip()
            try:
                fp = float(clean_p)
                p_disp = f"${int(fp):,}" if fp.is_integer() else f"${fp:,.2f}"
            except Exception:
                p_disp = f"${clean_p}"
            lines.append(f"💰 Sotilgan narxi: <b>{p_disp}</b>")
        if seller and seller != "-":
            lines.append(f"👨‍💼 Sotgan xodim: <b>{seller}</b>")

        lines.append("\n<i>Iltimos, do'kondagi boshqa qurilmaning IMEI yoki Seriya raqamini kiriting:</i>")
        sold_text = "\n".join(lines)

        drive_id = extract_drive_file_id(phone.get("Telefon rasmi") or phone.get("IMEI rasmi"))
        photo_sent = False
        if drive_id:
            try:
                photo_url = f"https://lh3.googleusercontent.com/d/{drive_id}"
                await message.answer_photo(
                    photo=photo_url,
                    caption=sold_text,
                    reply_markup=cancel_kb(),
                )
                photo_sent = True
            except Exception as e:
                logger.warning(f"Sotilgan qurilma rasmini yuborishda xatolik: {e}")

        if not photo_sent:
            await message.answer(sold_text, reply_markup=cancel_kb())
        return

    # Qurilma ma'lumotlarini saqlash
    await state.update_data(
        imei=actual_imei,
        imei_6=actual_imei,
        model=phone.get("Model", "Qurilma"),
        phone_data=phone,
        row_index=phone.get("_row_index"),
        channel_post_id=phone.get("Kanal post ID", ""),
    )

    info = build_sotuv_phone_info(phone)

    await state.set_state(SotuvStates.confirm_phone)

    # Telefon rasmi borligini tekshirish (avval Telefon rasmi, bo'lmasa IMEI rasmi)
    drive_id = extract_drive_file_id(phone.get("Telefon rasmi") or phone.get("IMEI rasmi"))
    if drive_id:
        try:
            photo_url = f"https://lh3.googleusercontent.com/d/{drive_id}"
            await message.answer_photo(
                photo=photo_url,
                caption=info,
                reply_markup=yes_no_kb(),
            )
            return
        except Exception as e:
            logger.warning(f"Rasm bilan yuborishda xatolik ({e}), matn shaklida yuboriladi.")

    await message.answer(info, reply_markup=yes_no_kb())


@router.message(SotuvStates.confirm_phone, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def confirm_phone_chosen(message: types.Message, state: FSMContext):
    if message.text == "❌ Yo'q":
        await state.set_state(SotuvStates.waiting_imei)
        await message.answer(
            "Tushunarli.\n\n🔍 <b>Sotilayotgan qurilmaning IMEI yoki Seriya raqamini kiriting:</b>",
            reply_markup=cancel_kb(),
        )
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
        "👤 <b>Mijoz (xaridor) ismini kiriting:</b>\n<i>(Masalan: Jamshid yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_buyer_name"),
    )


@router.callback_query(SotuvStates.waiting_buyer_name, F.data == "skip_buyer_name")
async def buyer_name_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(buyer_name="Mijoz")
    await state.set_state(SotuvStates.waiting_buyer_phone)
    await call.message.answer(
        "📞 <b>Mijozning telefon raqamini kiriting:</b>\n<i>(Masalan: +998901234567 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_buyer_phone"),
    )


@router.message(SotuvStates.waiting_buyer_name)
async def buyer_name_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        name = "Mijoz"
    else:
        name = message.text.strip()
    await state.update_data(buyer_name=name)

    await state.set_state(SotuvStates.waiting_buyer_phone)
    await message.answer(
        "📞 <b>Mijozning telefon raqamini kiriting:</b>\n<i>(Masalan: +998901234567 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_buyer_phone"),
    )


@router.callback_query(SotuvStates.waiting_buyer_phone, F.data == "skip_buyer_phone")
async def buyer_phone_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(buyer_phone="-")
    await state.set_state(SotuvStates.waiting_payment_type)
    await call.message.answer(
        "💳 <b>To'lov naqd yoki qarzgami?</b>",
        reply_markup=payment_type_kb(),
    )


@router.message(SotuvStates.waiting_buyer_phone)
async def buyer_phone_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        phone = "-"
    else:
        phone = message.text.strip()
    await state.update_data(buyer_phone=phone)

    await state.set_state(SotuvStates.waiting_payment_type)
    await message.answer(
        "💳 <b>To'lov naqd yoki qarzgami?</b>",
        reply_markup=payment_type_kb(),
    )


async def _process_payment_type(ptype: str, target: Any, state: FSMContext, is_callback: bool = False):
    await state.update_data(payment_type=ptype)

    if ptype == "Qarz":
        partners = sheets_service.get_partners()
        await state.set_state(SotuvStates.choosing_partner)
        text = "🤝 <b>Nasiya/Qarz manbasini tanlang:</b>"
        kb = partners_kb(partners)
        if is_callback:
            await target.edit_text(text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb)
    else:
        await state.update_data(
            partner_name="-",
            initial_payment="0",
            partner_debt="0",
        )
        await state.set_state(SotuvStates.choosing_kpi)
        text = (
            "🎁 <b>Sotuvchining KPI miqdorini tanlang yoki yozing ($):</b>\n"
            "<i>(Tugmalardan tanlang, o'zingiz yozing yoki '⏭ Tashlab ketish'ni bosing)</i>"
        )
        kb = kpi_inline_kb()
        if is_callback:
            await target.edit_text(text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb)


@router.callback_query(SotuvStates.waiting_payment_type, F.data.startswith("pay:"))
async def payment_type_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    ptype = call.data.split(":")[1]
    await _process_payment_type(ptype, call.message, state, is_callback=True)


@router.message(SotuvStates.waiting_payment_type, F.text.in_(["💵 Naqd", "💳 Qarzga", "Naqd", "Qarzga"]))
async def payment_type_chosen(message: types.Message, state: FSMContext):
    ptype = "Naqd" if "Naqd" in message.text else "Qarz"
    await message.answer("To'lov turi qabul qilindi.", reply_markup=cancel_kb())
    await _process_payment_type(ptype, message, state, is_callback=False)


@router.callback_query(SotuvStates.choosing_partner, F.data.startswith("partner:"))
async def partner_chosen(call: types.CallbackQuery, state: FSMContext):
    partner = call.data.split(":")[1]
    await state.update_data(partner_name=partner)
    await call.message.delete()

    await state.set_state(SotuvStates.waiting_initial_payment)
    await call.message.answer(
        f"Tanlandi: <b>{partner}</b>\n\n"
        "💵 <b>Boshlang'ich to'lov summasini kiriting ($):</b>\n"
        "<i>(Agar boshlang'ich to'lov bo'lmasa 0 deb yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_initial_payment"),
    )


@router.callback_query(SotuvStates.waiting_initial_payment, F.data == "skip_initial_payment")
async def initial_payment_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    sell_price = float(data.get("sell_price", 0))
    await state.update_data(
        initial_payment="0",
        partner_debt=str(sell_price),
    )
    await state.set_state(SotuvStates.choosing_kpi)
    await call.message.answer(
        f"Hisoblandi:\n"
        f"• Sotuv narxi: {sell_price}$\n"
        f"• Boshlang'ich to'lov: 0$\n"
        f"• Hamkor/Do'kon qarzi: <b>{sell_price}$</b>\n\n"
        "🎁 <b>Sotuvchining KPI miqdorini tanlang yoki yozing ($):</b>\n"
        "<i>(Tugmalardan tanlang, o'zingiz yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=kpi_inline_kb(),
    )


@router.message(SotuvStates.waiting_initial_payment)
async def initial_payment_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        initial = 0.0
    else:
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
        "🎁 <b>Sotuvchining KPI miqdorini tanlang yoki yozing ($):</b>\n"
        "<i>(Tugmalardan tanlang, o'zingiz yozing yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=kpi_inline_kb(),
    )


async def show_sale_summary(target_msg: types.Message, state: FSMContext):
    """Sotuv tasdiqlash oynasini ko'rsatish."""
    data = await state.get_data()
    summary = (
        "📋 <b>SOTUV MA'LUMOTLARINI TASDIQLANG:</b>\n\n"
        f"📱 Model: <b>{data.get('model')}</b>\n"
        f"🔍 IMEI / Seriya: <code>{data.get('imei_6')}</code>\n"
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

    phone_data = data.get("phone_data", {})
    drive_id = extract_drive_file_id(
        phone_data.get("Telefon rasmi")
        or phone_data.get("phone_photo_url")
        or phone_data.get("IMEI rasmi")
        or phone_data.get("imei_photo_url")
    )
    if drive_id:
        try:
            photo_url = f"https://lh3.googleusercontent.com/d/{drive_id}"
            await target_msg.answer_photo(
                photo=photo_url,
                caption=summary,
                reply_markup=yes_no_kb(),
            )
            return
        except Exception as e:
            logger.warning(f"Sotuv tasdiqlashda rasm bilan yuborishda xatolik ({e}), matn shaklida yuboriladi.")

    await target_msg.answer(summary, reply_markup=yes_no_kb())


@router.callback_query(SotuvStates.choosing_kpi, F.data.startswith("kpi:"))
async def kpi_callback_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    kpi_val = call.data.split(":")[1]
    await state.update_data(seller_kpi=kpi_val)
    await show_sale_summary(call.message, state)


@router.message(SotuvStates.choosing_kpi)
async def kpi_chosen(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        kpi = "0"
    else:
        kpi = clean_currency(message.text)
        if not kpi or float(kpi) < 0:
            await message.answer("Iltimos, KPI summasini tanlang, yozing yoki '⏭ Tashlab ketish'ni bosing:", reply_markup=kpi_inline_kb())
            return

    await state.update_data(seller_kpi=kpi)
    await show_sale_summary(message, state)


@router.message(SotuvStates.confirm_sale, F.text.in_(["✅ Ha", "❌ Yo'q"]))
async def confirm_sale_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("Sotuv bekor qilindi.", reply_markup=main_menu_kb())
        return

    data = await state.get_data()
    user_id = message.from_user.id
    user_name = sheets_service.get_staff_name_by_tg_id(user_id) or message.from_user.full_name
    data["seller_name"] = user_name
    data["seller_id"] = user_id

    loading_msg = await message.answer("⏳ Sotuv rasmiylashtirilmoqda, iltimos kuting...")

    # 1. Sotuv guruhiga xabar yuborish
    group_msg_id = await poster_service.post_to_sell_group(bot, data)

    # 2. Google Sheets'dagi 'Telefonlar' jadvalida sotuv va sof foydani yozish
    row_idx = data.get("row_index")
    phone_data = data.get("phone_data", {})
    profit = 0.0
    if row_idx:
        _, profit = sheets_service.record_sale(row_idx, data, phone_data)

    # 3. Kanaldagi postni '🔴 SOTILDI ❌' deb edit qilish
    channel_post_id = data.get("channel_post_id")
    channel_edited = False
    if channel_post_id and str(channel_post_id).isdigit():
        merged_info = dict(phone_data)
        merged_info.update(data)
        channel_edited = await poster_service.mark_as_sold_on_channel(
            bot, int(channel_post_id), phone_data=merged_info
        )

    try:
        await loading_msg.delete()
    except Exception:
        pass

    group_status = "• Guruhga hisobot yuborildi ✅" if group_msg_id else "• Guruhga hisobot yuborilmadi ⚠️"
    channel_status = ""
    if channel_post_id and str(channel_post_id).isdigit():
        channel_status = "\n• Telegram kanaldagi e'lon tahrirlandi ✅" if channel_edited else "\n• Telegram kanaldagi e'lon tahrirlanmadi ⚠️"

    await state.clear()
    await message.answer(
        "🎉 <b>Sotuv muvaffaqiyatli rasmiylashtirildi!</b>\n\n"
        f"• Sotuv narxi: <b>{data.get('sell_price')}$</b>\n"
        f"• Sotuvchi KPI: <b>{data.get('seller_kpi')}$</b>\n"
        f"• 💰 <b>Do‘konga sof foyda: +{profit:.1f}$</b>\n\n"
        f"{group_status}\n"
        "• Google Sheets 'Telefonlar' jadvaliga saqlandi ✅"
        f"{channel_status}",
        reply_markup=main_menu_kb(),
    )
