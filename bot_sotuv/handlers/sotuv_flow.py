from bot_common.handler_support import begin_flow
from bot_common.handler_support import (
    clean_currency,
    close_prompt,
    commit,
    find_phone,
    operation_id,
    progress,
    safe_handler,
    answer_preview,
    wait_for_delivery,
)
from services.io_worker import io_worker
from services.errors import BusinessRuleError
from utils.money import money_value
from utils.formatters import safe_html
from bot_common.callbacks import resolve_callback_key

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
from utils.formatters import build_sale_summary, build_sotuv_phone_info

logger = logging.getLogger(__name__)
router = Router()

SKIPPED = "Tashlab ketildi"
SKIP_TEXTS = ["⏭ Tashlab ketish", "Tashlab ketish"]
KPI_ROLES = {"Sotuvchi", "Hisobchi", "Rahbariyat"}
IMEI_PROMPT = (
    "🔢 <b>Sotilayotgan qurilmaning IMEI yoki seriya raqamini kiriting:</b>\n"
    "<i>(Masalan: 345678)</i>"
)
PRICE_PROMPT = "💰 <b>Sotuv narxini kiriting ($):</b>\n<i>(Masalan: 650)</i>"
BUYER_NAME_PROMPT = "👤 <b>Xaridor ismini kiriting:</b>\n<i>(Masalan: Jamshid)</i>"
BUYER_PHONE_PROMPT = (
    "📞 <b>Xaridorning telefon raqamini kiriting:</b>\n"
    "<i>(Masalan: +998901234567)</i>"
)
PAYMENT_PROMPT = "💳 <b>To'lov turini tanlang:</b>"
PARTNER_PROMPT = "🤝 <b>Qarz kim orqali? Hamkorni tanlang:</b>"
INITIAL_PAYMENT_PROMPT = (
    "💵 <b>Boshlang'ich to'lovni kiriting ($):</b>\n"
    "<i>(Masalan: 100; to'lov bo'lmasa tashlab keting)</i>"
)
KPI_COUNT_PROMPT = (
    "👥 <b>KPI necha kishiga yoziladi?</b>\n<i>(Ko'pi bilan 2 kishi)</i>"
)
SECOND_STAFF_PROMPT = "👥 <b>Ikkinchi xodimni tanlang:</b>"
KPI_HINT = "\n<i>(Tugmadan tanlang yoki yozing)</i>"


async def staff_name(user):
    _, _, name = await io_worker.call(sheets_service.check_member, user.id)
    return name or user.full_name


@router.message(F.text == "📱 Yangi sotuvni rasmiylashtirish")
@safe_handler
async def start_sale(message: types.Message, state: FSMContext):
    active, role, _ = await io_worker.call(
        sheets_service.check_member, message.from_user.id
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Sotuvchi"}:
        raise BusinessRuleError("Sotuv uchun ruxsat berilmagan.")
    await begin_flow(state, message.from_user.id)
    await state.set_state(SotuvStates.waiting_imei)
    await message.answer("📱 <b>Yangi sotuv</b>", reply_markup=cancel_kb())
    await message.answer(IMEI_PROMPT)


@router.message(SotuvStates.waiting_imei, F.text)
@safe_handler
async def imei_entered(message: types.Message, state: FSMContext):
    phone = await find_phone(message.text.strip(), state)
    if not phone:
        raise BusinessRuleError("Telefon topilmadi. IMEI ni tekshiring.")
    if phone.get("Holati") == "Sotildi":
        # Sent as HTML; error messages are escaped and would show raw tags.
        await message.answer(sold_phone_card(phone))
        return
    if phone.get("Holati") != "Sotuvda":
        raise BusinessRuleError("Bu qurilma sotuvga tayyor emas.")
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


def sold_phone_card(phone):
    lines = [
        "⚠️ <b>Bu qurilma allaqachon sotilgan.</b>\n",
        f"📱 Model: <b>{safe_html(phone.get('Model', 'Qurilma'))}</b>",
        f"🔍 IMEI / Seriya: <code>{safe_html(phone.get('IMEI', '-'))}</code>",
    ]
    details = (
        ("📅 Sotilgan sana", phone.get("Sotilgan sana"), ""),
        ("👤 Xaridor", phone.get("Xaridor ismi"), ""),
        ("📞 Xaridor tel", phone.get("Xaridor telefoni"), ""),
        ("💰 Sotilgan narxi", phone.get("Sotuv narxi ($)"), "$"),
        ("👨‍💼 Sotgan xodim", phone.get("Do'kon sotuvchisi"), ""),
    )
    for label, value, suffix in details:
        value = str(value or "").strip()
        if value and value not in {"-", "Mijoz"}:
            lines.append(f"{label}: <b>{safe_html(value)}{suffix}</b>")
    lines.append("\n<i>Do'kondagi boshqa qurilmaning IMEI raqamini kiriting.</i>")
    return "\n".join(lines)


@router.message(SotuvStates.confirm_phone, F.text.in_(["✅ Ha", "❌ Yo'q"]))
@safe_handler
async def confirm_phone_chosen(message: types.Message, state: FSMContext):
    if message.text == "❌ Yo'q":
        await state.set_state(SotuvStates.waiting_imei)
        await message.answer(IMEI_PROMPT, reply_markup=cancel_kb())
        return
    await state.set_state(SotuvStates.waiting_sell_price)
    await message.answer(PRICE_PROMPT, reply_markup=cancel_kb())


@router.message(SotuvStates.waiting_sell_price, F.text)
@safe_handler
async def sell_price_entered(message: types.Message, state: FSMContext):
    price = clean_currency(message.text)
    await state.update_data(sell_price=price)
    await state.set_state(SotuvStates.waiting_buyer_name)
    await message.answer(
        BUYER_NAME_PROMPT, reply_markup=skip_inline_kb("skip_buyer_name")
    )


@router.callback_query(SotuvStates.waiting_buyer_name, F.data == "skip_buyer_name")
@safe_handler
async def buyer_name_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(buyer_name="Mijoz")
    await state.set_state(SotuvStates.waiting_buyer_phone)
    await call.message.answer(
        BUYER_PHONE_PROMPT, reply_markup=skip_inline_kb("skip_buyer_phone")
    )


@router.message(SotuvStates.waiting_buyer_name, F.text)
@safe_handler
async def buyer_name_entered(message: types.Message, state: FSMContext):
    name = "Mijoz" if message.text in SKIP_TEXTS else message.text.strip()
    await state.update_data(buyer_name=name)
    await state.set_state(SotuvStates.waiting_buyer_phone)
    await message.answer(
        BUYER_PHONE_PROMPT, reply_markup=skip_inline_kb("skip_buyer_phone")
    )


@router.callback_query(SotuvStates.waiting_buyer_phone, F.data == "skip_buyer_phone")
@safe_handler
async def buyer_phone_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, SKIPPED)
    await state.update_data(buyer_phone="-")
    await state.set_state(SotuvStates.waiting_payment_type)
    await call.message.answer(PAYMENT_PROMPT, reply_markup=payment_type_kb())


@router.message(SotuvStates.waiting_buyer_phone, F.text)
@safe_handler
async def buyer_phone_entered(message: types.Message, state: FSMContext):
    phone = "-" if message.text in SKIP_TEXTS else message.text.strip()
    await state.update_data(buyer_phone=phone)
    await state.set_state(SotuvStates.waiting_payment_type)
    await message.answer(PAYMENT_PROMPT, reply_markup=payment_type_kb())


async def prompt_kpi_start(message, state, note=""):
    await state.set_state(SotuvStates.choosing_kpi_count)
    await message.answer(f"{note}{KPI_COUNT_PROMPT}", reply_markup=kpi_person_count_kb())


async def _process_payment_type(ptype, message, state):
    if ptype not in {"Naqd", "Qarz"}:
        raise BusinessRuleError("To‘lov turini qayta tanlang.")
    await state.update_data(payment_type=ptype)
    if ptype == "Qarz":
        partners = await io_worker.call(sheets_service.get_partners)
        await state.set_state(SotuvStates.choosing_partner)
        await message.answer(PARTNER_PROMPT, reply_markup=partners_kb(partners))
    else:
        await state.update_data(partner_name="-", initial_payment="0", partner_debt="0")
        await prompt_kpi_start(message, state)


@router.callback_query(SotuvStates.waiting_payment_type, F.data.startswith("pay:"))
@safe_handler
async def payment_type_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    ptype = call.data.partition(":")[2]
    if ptype in {"Naqd", "Qarz"}:
        await close_prompt(call)
    await _process_payment_type(ptype, call.message, state)


@router.message(
    SotuvStates.waiting_payment_type,
    F.text.in_(["💵 Naqd", "💳 Qarzga", "Naqd", "Qarzga"]),
)
@safe_handler
async def payment_type_chosen(message: types.Message, state: FSMContext):
    ptype = "Naqd" if "Naqd" in message.text else "Qarz"
    await _process_payment_type(ptype, message, state)


@router.callback_query(SotuvStates.choosing_partner, F.data.startswith("partner:"))
@safe_handler
async def partner_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    selection = call.data.partition(":")[2]
    partners = await io_worker.call(sheets_service.get_partners)
    if selection == "Dokondan":
        partner = "Dokondan"
    else:
        try:
            partner = resolve_callback_key(selection, partners)["Hamkor nomi"]
        except ValueError as exc:
            raise BusinessRuleError("Hamkor tanlovi eskirgan. Qayta tanlang.") from exc
    await close_prompt(call)
    await state.update_data(partner_name=partner)
    await state.set_state(SotuvStates.waiting_initial_payment)
    await call.message.answer(
        INITIAL_PAYMENT_PROMPT, reply_markup=skip_inline_kb("skip_initial_payment")
    )


@router.callback_query(
    SotuvStates.waiting_initial_payment, F.data == "skip_initial_payment"
)
@safe_handler
async def initial_payment_skipped_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await close_prompt(call, "To'lov yo'q (0$)")
    data = await state.get_data()
    price = money_value(data["sell_price"], allow_zero=False)
    await state.update_data(initial_payment="0.00", partner_debt=str(price))
    await prompt_kpi_start(call.message, state, debt_note(price))


@router.message(SotuvStates.waiting_initial_payment, F.text)
@safe_handler
async def initial_payment_entered(message: types.Message, state: FSMContext):
    initial = money_value(
        "0"
        if message.text in SKIP_TEXTS
        else clean_currency(message.text, allow_zero=True)
    )
    data = await state.get_data()
    price = money_value(data["sell_price"], allow_zero=False)
    if initial > price:
        raise BusinessRuleError("Boshlang‘ich to‘lov sotuv narxidan oshmasin.")
    await state.update_data(
        initial_payment=str(initial), partner_debt=str(price - initial)
    )
    await prompt_kpi_start(message, state, debt_note(price - initial))


def debt_note(debt):
    # Computed, not echoed: the seller sees what the partner will owe.
    return f"ℹ️ Hamkor qarzi: <b>{safe_html(debt)}$</b>\n\n"


async def show_sale_summary(message, state):
    data = await state.get_data()
    await state.set_state(SotuvStates.confirm_sale)
    await answer_preview(message, build_sale_summary(data), reply_markup=yes_no_kb())


@router.callback_query(SotuvStates.choosing_kpi_count, F.data.startswith("kpi_count:"))
@safe_handler
async def kpi_count_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    count_str = call.data.partition(":")[2]
    if count_str not in {"0", "1", "2"}:
        raise BusinessRuleError("KPI xodimlari soni 0, 1 yoki 2 bo‘lsin.")
    await close_prompt(call, "KPI yo'q (0$)" if count_str == "0" else None)
    user_id = call.from_user.id
    user_name = await staff_name(call.from_user)
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
    title = "Sizning KPI miqdoringiz ($):" if count == 1 else "1-xodim (siz) uchun KPI ($):"
    await call.message.answer(
        f"🎁 <b>{title}</b>{KPI_HINT}", reply_markup=kpi_inline_kb()
    )


async def _process_kpi_1_amount(amount_str, message, state, user_id, user_name):
    amount = clean_currency(amount_str, allow_zero=True)
    data = await state.get_data()
    if data.get("kpi_person_count", 1) == 1:
        await state.update_data(
            seller_kpi=amount,
            seller_name=user_name,
            seller_id=user_id,
            sellers=[{"id": user_id, "name": user_name, "kpi": amount}],
        )
        await show_sale_summary(message, state)
        return
    staff = await io_worker.call(
        sheets_service.get_staff_list, active_only=True
    )
    choices = [
        s
        for s in staff
        if str(s.get("Telegram ID", "")) != str(user_id) and s.get("Roli") in KPI_ROLES
    ]
    if not choices:
        raise BusinessRuleError(
            "Ikkinchi faol xodim topilmadi. KPI sonini qayta tanlang."
        )
    await state.update_data(
        kpi_1=amount, second_staff_choices=[str(s["Telegram ID"]) for s in choices]
    )
    await state.set_state(SotuvStates.choosing_second_staff)
    await message.answer(
        SECOND_STAFF_PROMPT,
        reply_markup=staff_inline_kb(choices, exclude_id=user_id),
    )


def kpi_answer(value):
    return "KPI yo'q (0$)" if str(value) in {"0", "0.00"} else f"{value}$"


@router.callback_query(SotuvStates.waiting_kpi_amount_1, F.data.startswith("kpi:"))
@router.callback_query(SotuvStates.choosing_kpi, F.data.startswith("kpi:"))
@safe_handler
async def kpi_1_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.partition(":")[2]
    await close_prompt(call, kpi_answer(val))
    user_name = await staff_name(call.from_user)
    await _process_kpi_1_amount(val, call.message, state, call.from_user.id, user_name)


@router.message(SotuvStates.waiting_kpi_amount_1, F.text)
@router.message(SotuvStates.choosing_kpi, F.text)
@safe_handler
async def kpi_1_entered(message: types.Message, state: FSMContext):
    if message.text in SKIP_TEXTS:
        val = "0"
    else:
        val = clean_currency(message.text, allow_zero=True)
    user_name = await staff_name(message.from_user)
    await _process_kpi_1_amount(val, message, state, message.from_user.id, user_name)


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
        sheets_service.get_staff_list, active_only=True
    )
    person = next(
        (
            s
            for s in staff
            if str(s.get("Telegram ID")) == selection and s.get("Roli") in KPI_ROLES
        ),
        None,
    )
    if not person:
        raise BusinessRuleError("Xodimning joriy roli KPI olishga ruxsat bermaydi.")
    await close_prompt(call)
    await state.update_data(
        second_staff_id=selection, second_staff_name=person["F.I.Sh"]
    )
    await state.set_state(SotuvStates.waiting_kpi_amount_2)
    await call.message.answer(
        f"🎁 <b>{safe_html(person['F.I.Sh'])} uchun KPI ($):</b>{KPI_HINT}",
        reply_markup=kpi_inline_kb(),
    )


async def _process_kpi_2_amount(amount_str, message, state, user_id, user_name):
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
    await show_sale_summary(message, state)


@router.callback_query(SotuvStates.waiting_kpi_amount_2, F.data.startswith("kpi:"))
@safe_handler
async def kpi_2_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.partition(":")[2]
    await close_prompt(call, kpi_answer(val))
    user_name = await staff_name(call.from_user)
    await _process_kpi_2_amount(val, call.message, state, call.from_user.id, user_name)


@router.message(SotuvStates.waiting_kpi_amount_2, F.text)
@safe_handler
async def kpi_2_entered(message: types.Message, state: FSMContext):
    if message.text in SKIP_TEXTS:
        val = "0"
    else:
        val = clean_currency(message.text, allow_zero=True)
    user_name = await staff_name(message.from_user)
    await _process_kpi_2_amount(val, message, state, message.from_user.id, user_name)


@router.message(SotuvStates.confirm_sale, F.text.in_(["✅ Ha", "❌ Yo'q"]))
@safe_handler
async def confirm_sale_handler(message: types.Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Yo'q":
        await state.clear()
        await message.answer("❌ Sotuv bekor qilindi.", reply_markup=main_menu_kb())
        return
    data = await state.get_data()
    reference = data.get("phone_id")
    if not reference:
        raise BusinessRuleError("Qurilmani Telefon ID bo‘yicha qayta tanlang.")
    identifier = await operation_id(state)
    notifications = []
    if config.GROUP_SOTUV_ID:
        notifications.append({"kind": "sell_group", "bot_id": bot.id, "data": data})
    post_id = data.get("channel_post_id")
    has_post = bool(post_id and str(post_id).isdigit())
    channel_index = None
    if config.CHANNEL_ID:
        merged = dict(data.get("phone_data") or {})
        merged.update(data)
        channel_index = len(notifications)
        notifications.append(
            {
                "kind": "sold_channel",
                "bot_id": bot.id,
                "phone_id": reference,
                "post_id": int(post_id) if has_post else 0,
                "data": merged,
            }
        )
    async with progress(message, "Sotuv saqlanmoqda, kutib turing..."):
        _, profit = await commit(
            state,
            message.from_user.id,
            sheets_service.record_sale,
            reference,
            data,
            notifications=notifications,
        )
        channel = None
        if channel_index is not None and has_post:
            channel = await wait_for_delivery(identifier, channel_index)
    await state.clear()
    lines = [
        "✅ <b>Sotuv saqlandi.</b>",
        f"📈 Sotuv foydasi: <b>{profit:.2f}$</b>",
    ]
    if channel_index is not None and has_post:
        if channel is None:
            lines.append("🕓 Kanaldagi e'lon birozdan keyin «Sotildi» bo'ladi.")
        elif channel["state"] == "sent":
            lines.append("📢 Kanaldagi e'lon «Sotildi» deb belgilandi.")
        else:
            lines.append(
                "⚠️ Kanaldagi e'lonni belgilab bo'lmadi; hisobchi tekshiradi.\n"
                f"Amal: /amal {safe_html(identifier)}"
            )
    await message.answer("\n".join(lines), reply_markup=main_menu_kb())
