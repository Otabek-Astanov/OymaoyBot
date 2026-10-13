from bot_common.handler_support import begin_flow
from bot_common.handler_support import (
    clean_currency,
    commit,
    find_phone,
    safe_handler,
    answer_preview,
)
from services.io_worker import io_worker
from services.errors import BusinessRuleError
from utils.money import money_value
from utils.formatters import safe_html
from bot_common.callbacks import resolve_callback_key

import re
from typing import Any
import logging
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
import config
from bot_sotuv.states import SotuvStates
from bot_sotuv.keyboards import (
    main_menu_kb,
    cancel_kb,
    skip_inline_kb,
    payment_type_kb,
    partners_kb,
    kpi_inline_kb,
    kpi_person_count_kb,
    staff_inline_kb,
    yes_no_kb,
)
from services.google_sheets import sheets_service
from utils.formatters import build_sotuv_phone_info

logger = logging.getLogger(__name__)
router = Router()


def extract_drive_file_id(photo_field: Any) -> str:
    """Google Sheets'dagi formula yoki URL ichidan Google Drive file_id ni ajratib oladi."""
    if not photo_field:
        return ""
    text = str(photo_field)
    match = re.search("/d/([a-zA-Z0-9_-]{25,})", text)
    if match:
        return match.group(1)
    match = re.search("id=([a-zA-Z0-9_-]{25,})", text)
    if match:
        return match.group(1)
    return ""


@router.message(F.text == "📱 Yangi sotuvni rasmiylashtirish")
@safe_handler
async def start_sale(message: types.Message, state: FSMContext):
    active, role, _ = await io_worker.call(
        sheets_service.check_member, message.from_user.id, force_refresh=True
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        raise BusinessRuleError("Sotuv uchun ruxsat berilmagan.")
    await begin_flow(state, message.from_user.id)
    await state.set_state(SotuvStates.waiting_imei)
    await message.answer(
        "Sotilayotgan qurilmaning to‘liq IMEI yoki seriya raqamini kiriting:",
        reply_markup=cancel_kb(),
    )


@router.message(SotuvStates.waiting_imei, F.text)
@safe_handler
async def imei_entered(message: types.Message, state: FSMContext):
    phone = await find_phone(message.text.strip(), state)
    if not phone:
        raise BusinessRuleError("Telefon topilmadi. To‘liq IMEI ni tekshiring.")
    if phone.get("Holati") != "Sotuvda":
        raise BusinessRuleError(
            "Ushbu qurilma allaqachon sotilgan yoki sotuvga tayyor emas."
        )
    await state.update_data(
        phone_id=phone["Telefon ID"],
        imei=phone["IMEI"],
        imei_6=phone["IMEI"],
        model=phone["Model"],
        phone_data=phone,
        channel_post_id=phone.get("Kanal post ID", ""),
    )
    await state.set_state(SotuvStates.confirm_phone)
    await answer_preview(
        message, build_sotuv_phone_info(phone), reply_markup=yes_no_kb()
    )


@router.message(SotuvStates.confirm_phone, F.text.in_(["✅ Ha", "❌ Yo'q"]))
@safe_handler
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


@router.message(SotuvStates.waiting_sell_price, F.text)
@safe_handler
async def sell_price_entered(message: types.Message, state: FSMContext):
    price = clean_currency(message.text)
    await state.update_data(sell_price=price)
    await state.set_state(SotuvStates.waiting_buyer_name)
    await message.answer(
        "👤 <b>Mijoz (xaridor) ismini kiriting:</b>\n<i>(Masalan: Jamshid yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_buyer_name"),
    )


@router.callback_query(SotuvStates.waiting_buyer_name, F.data == "skip_buyer_name")
@safe_handler
async def buyer_name_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(buyer_name="Mijoz")
    await state.set_state(SotuvStates.waiting_buyer_phone)
    await call.message.answer(
        "📞 <b>Mijozning telefon raqamini kiriting:</b>\n<i>(Masalan: +998901234567 yoki '⏭ Tashlab ketish'ni bosing)</i>",
        reply_markup=skip_inline_kb("skip_buyer_phone"),
    )


@router.message(SotuvStates.waiting_buyer_name, F.text)
@safe_handler
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
@safe_handler
async def buyer_phone_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(buyer_phone="-")
    await state.set_state(SotuvStates.waiting_payment_type)
    await call.message.answer(
        "💳 <b>To'lov naqd yoki qarzgami?</b>", reply_markup=payment_type_kb()
    )


@router.message(SotuvStates.waiting_buyer_phone, F.text)
@safe_handler
async def buyer_phone_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        phone = "-"
    else:
        phone = message.text.strip()
    await state.update_data(buyer_phone=phone)
    await state.set_state(SotuvStates.waiting_payment_type)
    await message.answer(
        "💳 <b>To'lov naqd yoki qarzgami?</b>", reply_markup=payment_type_kb()
    )


async def prompt_kpi_start(
    target: Any, state: FSMContext, is_callback: bool = False, extra_text: str = ""
):
    """KPI kiritishdan oldin necha kishi uchunligini so'rash."""
    await state.set_state(SotuvStates.choosing_kpi_count)
    prefix = f"{extra_text}\n" if extra_text else ""
    prompt_text = f"{prefix}👥 <b>Ushbu sotuv uchun KPI necha kishi uchun hisoblansin?</b>\n<i>(KPI ko'pi bilan 2 kishiga berilishi mumkin)</i>"
    kb = kpi_person_count_kb()
    if is_callback:
        await target.edit_text(prompt_text, reply_markup=kb)
    else:
        await target.answer(prompt_text, reply_markup=kb)


async def _process_payment_type(
    ptype: str, target: Any, state: FSMContext, is_callback: bool = False
):
    if ptype not in {"Naqd", "Qarz"}:
        raise BusinessRuleError("To‘lov turini qayta tanlang.")
    await state.update_data(payment_type=ptype)
    if ptype == "Qarz":
        partners = await io_worker.call(sheets_service.get_partners)
        await state.set_state(SotuvStates.choosing_partner)
        text = "🤝 <b>Nasiya/Qarz manbasini tanlang:</b>"
        kb = partners_kb(partners)
        if is_callback:
            await target.edit_text(text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb)
    else:
        await state.update_data(partner_name="-", initial_payment="0", partner_debt="0")
        await prompt_kpi_start(target, state, is_callback=is_callback)


@router.callback_query(SotuvStates.waiting_payment_type, F.data.startswith("pay:"))
@safe_handler
async def payment_type_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    ptype = call.data.split(":")[1]
    await _process_payment_type(ptype, call.message, state, is_callback=True)


@router.message(
    SotuvStates.waiting_payment_type,
    F.text.in_(["💵 Naqd", "💳 Qarzga", "Naqd", "Qarzga"]),
)
@safe_handler
async def payment_type_chosen(message: types.Message, state: FSMContext):
    ptype = "Naqd" if "Naqd" in message.text else "Qarz"
    await message.answer("To'lov turi qabul qilindi.", reply_markup=cancel_kb())
    await _process_payment_type(ptype, message, state, is_callback=False)


@router.callback_query(SotuvStates.choosing_partner, F.data.startswith("partner:"))
@safe_handler
async def partner_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    selection = call.data.partition(":")[2]
    partners = await io_worker.call(sheets_service.get_partners, force_refresh=True)
    if selection == "Dokondan":
        partner = "Dokondan"
    else:
        try:
            partner = resolve_callback_key(selection, partners)["Hamkor nomi"]
        except ValueError as exc:
            raise BusinessRuleError("Hamkor tanlovi eskirgan. Qayta tanlang.") from exc
    await state.update_data(partner_name=partner)
    await state.set_state(SotuvStates.waiting_initial_payment)
    await call.message.answer(
        f"Hamkor: <b>{safe_html(partner)}</b>\nBoshlang‘ich to‘lovni kiriting ($). To‘lov yo‘q bo‘lsa 0:",
        reply_markup=skip_inline_kb("skip_initial_payment"),
    )


@router.callback_query(
    SotuvStates.waiting_initial_payment, F.data == "skip_initial_payment"
)
@safe_handler
async def initial_payment_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    price = money_value(data["sell_price"], allow_zero=False)
    await state.update_data(initial_payment="0.00", partner_debt=str(price))
    await prompt_kpi_start(call.message, state)


@router.message(SotuvStates.waiting_initial_payment, F.text)
@safe_handler
async def initial_payment_entered(message: types.Message, state: FSMContext):
    initial = money_value(
        "0"
        if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]
        else clean_currency(message.text, allow_zero=True)
    )
    data = await state.get_data()
    price = money_value(data["sell_price"], allow_zero=False)
    if initial > price:
        raise BusinessRuleError("Boshlang‘ich to‘lov sotuv narxidan oshmasin.")
    await state.update_data(
        initial_payment=str(initial), partner_debt=str(price - initial)
    )
    await prompt_kpi_start(message, state, extra_text=f"Qarz: {price - initial}$")


async def show_sale_summary(target_msg: types.Message, state: FSMContext):
    data = await state.get_data()
    summary = f"📋 <b>SOTUVNI TASDIQLANG</b>\n\nQurilma: <b>{safe_html(data.get('model'))}</b>\nIMEI: <code>{safe_html(data.get('imei'))}</code>\nNarx: {safe_html(data.get('sell_price'))}$\nXaridor: {safe_html(data.get('buyer_name'))} · {safe_html(data.get('buyer_phone'))}\nTo‘lov: {safe_html(data.get('payment_type'))}\nHamkor: {safe_html(data.get('partner_name'))}\nBoshlang‘ich to‘lov: {safe_html(data.get('initial_payment'))}$\nKPI jami: {safe_html(data.get('seller_kpi'))}$\nSotuvchilar: {safe_html(data.get('seller_name'))}\n\nTasdiqlaysizmi?"
    await state.set_state(SotuvStates.confirm_sale)
    await answer_preview(target_msg, summary, reply_markup=yes_no_kb())


@router.callback_query(SotuvStates.choosing_kpi_count, F.data.startswith("kpi_count:"))
@safe_handler
async def kpi_count_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    count_str = call.data.split(":")[1]
    if count_str not in {"0", "1", "2"}:
        raise BusinessRuleError("KPI xodimlari soni 0, 1 yoki 2 bo‘lsin.")
    user_id = call.from_user.id
    user_name = (
        await io_worker.call(sheets_service.get_staff_name_by_tg_id, user_id)
        or call.from_user.full_name
    )
    if count_str == "0":
        await state.update_data(
            seller_kpi="0",
            seller_name=user_name,
            seller_id=user_id,
            sellers=[],
        )
        await show_sale_summary(call.message, state)
        return
    count = int(count_str)
    await state.update_data(
        kpi_person_count=count, current_user_name=user_name, current_user_id=user_id
    )
    await state.set_state(SotuvStates.waiting_kpi_amount_1)
    if count == 1:
        text = "🎁 <b>O'zingiz uchun belgilangan KPI miqdorini tanlang yoki yozing ($):</b>\n<i>(Tugmalardan tanlang, o'zingiz yozing yoki '⏭ Tashlab ketish'ni bosing)</i>"
    else:
        text = "🎁 <b>1) O'zingiz uchun belgilangan KPI miqdorini tanlang yoki yozing ($):</b>\n<i>(Tugmalardan tanlang, o'zingiz yozing yoki '⏭ Tashlab ketish'ni bosing)</i>"
    await call.message.edit_text(text, reply_markup=kpi_inline_kb())


async def _process_kpi_1_amount(
    amount_str: str,
    target_msg: types.Message,
    state: FSMContext,
    user_id: int,
    user_name: str,
):
    amount = clean_currency(amount_str, allow_zero=True)
    data = await state.get_data()
    if data.get("kpi_person_count", 1) == 1:
        await state.update_data(
            seller_kpi=amount,
            seller_name=user_name,
            seller_id=user_id,
            sellers=[{"id": user_id, "name": user_name, "kpi": amount}],
        )
        await show_sale_summary(target_msg, state)
        return
    staff = await io_worker.call(
        sheets_service.get_staff_list, active_only=True, force_refresh=True
    )
    choices = [
        s
        for s in staff
        if str(s.get("Telegram ID", "")) != str(user_id)
        and s.get("Roli") in {"Sotuvchi", "Hisobchi", "Rahbariyat"}
    ]
    if not choices:
        raise BusinessRuleError(
            "Ikkinchi faol xodim topilmadi. KPI sonini qayta tanlang."
        )
    await state.update_data(
        kpi_1=amount, second_staff_choices=[str(s["Telegram ID"]) for s in choices]
    )
    await state.set_state(SotuvStates.choosing_second_staff)
    await target_msg.answer(
        "Ikkinchi xodimni tanlang:",
        reply_markup=staff_inline_kb(choices, exclude_id=user_id),
    )


@router.callback_query(SotuvStates.waiting_kpi_amount_1, F.data.startswith("kpi:"))
@router.callback_query(SotuvStates.choosing_kpi, F.data.startswith("kpi:"))
@safe_handler
async def kpi_1_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.split(":")[1]
    user_id = call.from_user.id
    user_name = (
        await io_worker.call(sheets_service.get_staff_name_by_tg_id, user_id)
        or call.from_user.full_name
    )
    await _process_kpi_1_amount(val, call.message, state, user_id, user_name)


@router.message(SotuvStates.waiting_kpi_amount_1, F.text)
@router.message(SotuvStates.choosing_kpi, F.text)
@safe_handler
async def kpi_1_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        val = "0"
    else:
        val = clean_currency(message.text, allow_zero=True)
    user_id = message.from_user.id
    user_name = (
        await io_worker.call(sheets_service.get_staff_name_by_tg_id, user_id)
        or message.from_user.full_name
    )
    await _process_kpi_1_amount(val, message, state, user_id, user_name)


@router.callback_query(
    SotuvStates.choosing_second_staff, F.data.startswith("staff_sel:")
)
@safe_handler
async def second_staff_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    selection = call.data.partition(":")[2]
    data = await state.get_data()
    if selection not in data.get("second_staff_choices", []):
        raise BusinessRuleError("Xodim tanlovi noto‘g‘ri yoki eskirgan.")
    staff = await io_worker.call(
        sheets_service.get_staff_list, active_only=True, force_refresh=True
    )
    person = next(
        (
            s
            for s in staff
            if str(s.get("Telegram ID")) == selection
            and s.get("Roli") in {"Sotuvchi", "Hisobchi", "Rahbariyat"}
        ),
        None,
    )
    if not person:
        raise BusinessRuleError("Xodimning joriy roli KPI olishga ruxsat bermaydi.")
    await state.update_data(
        second_staff_id=selection, second_staff_name=person["F.I.Sh"]
    )
    await state.set_state(SotuvStates.waiting_kpi_amount_2)
    await call.message.edit_text(
        f"{safe_html(person['F.I.Sh'])} uchun KPI kiriting ($):",
        reply_markup=kpi_inline_kb(),
    )


async def _process_kpi_2_amount(
    amount_str: str,
    target_msg: types.Message,
    state: FSMContext,
    user_id: int,
    user_name: str,
):
    second = money_value(clean_currency(amount_str, allow_zero=True))
    data = await state.get_data()
    first = money_value(data["kpi_1"])
    second_name = data["second_staff_name"]
    sellers = [
        {"id": user_id, "name": user_name, "kpi": str(first)},
        {"id": data["second_staff_id"], "name": second_name, "kpi": str(second)},
    ]
    await state.update_data(
        seller_kpi=str(first + second),
        seller_name=f"{user_name}, {second_name}",
        seller_id=user_id,
        sellers=sellers,
    )
    await show_sale_summary(target_msg, state)


@router.callback_query(SotuvStates.waiting_kpi_amount_2, F.data.startswith("kpi:"))
@safe_handler
async def kpi_2_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.split(":")[1]
    user_id = call.from_user.id
    user_name = (
        await io_worker.call(sheets_service.get_staff_name_by_tg_id, user_id)
        or call.from_user.full_name
    )
    await _process_kpi_2_amount(val, call.message, state, user_id, user_name)


@router.message(SotuvStates.waiting_kpi_amount_2, F.text)
@safe_handler
async def kpi_2_entered(message: types.Message, state: FSMContext):
    if message.text in ["⏭ Tashlab ketish", "Tashlab ketish"]:
        val = "0"
    else:
        val = clean_currency(message.text, allow_zero=True)
    user_id = message.from_user.id
    user_name = (
        await io_worker.call(sheets_service.get_staff_name_by_tg_id, user_id)
        or message.from_user.full_name
    )
    await _process_kpi_2_amount(val, message, state, user_id, user_name)


@router.message(SotuvStates.confirm_sale, F.text.in_(["✅ Ha", "❌ Yo'q"]))
@safe_handler
async def confirm_sale_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("Sotuv bekor qilindi.", reply_markup=main_menu_kb())
        return
    data = await state.get_data()
    reference = data.get("phone_id")
    if not reference:
        raise BusinessRuleError("Qurilmani Telefon ID bo‘yicha qayta tanlang.")
    notifications = []
    if config.GROUP_SOTUV_ID:
        notifications.append({"kind": "sell_group", "bot_id": bot.id, "data": data})
    post_id = data.get("channel_post_id")
    if config.CHANNEL_ID:
        merged = dict(data.get("phone_data") or {})
        merged.update(data)
        notifications.append(
            {
                "kind": "sold_channel",
                "bot_id": bot.id,
                "phone_id": reference,
                "post_id": int(post_id) if post_id and str(post_id).isdigit() else 0,
                "data": merged,
            }
        )
    _, profit = await commit(
        state,
        message.from_user.id,
        sheets_service.record_sale,
        reference,
        data,
        notifications=notifications,
    )
    await state.clear()
    await message.answer(
        f"✅ <b>Sotuv saqlandi.</b>\nSotuv marjasi: {profit:.2f}$\nGuruh va kanal bildirishlari navbat orqali yuboriladi.",
        reply_markup=main_menu_kb(),
    )
