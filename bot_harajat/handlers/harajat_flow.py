from bot_common.handler_support import begin_flow

"""Financial flows commit once through the durable operation coordinator."""

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from bot_common.callbacks import resolve_callback_key
from bot_common.handler_support import clean_currency, commit, find_phone, safe_handler
from bot_harajat.keyboards import (
    cancel_kb,
    chiqim_categories_kb,
    hisobchi_menu_kb,
    kirim_categories_kb,
    partners_inline_kb,
    rahbariyat_persons_kb,
    staff_inline_kb,
    yes_no_kb,
)
from bot_harajat.states import ChiqimStates, KirimStates
from services.errors import BusinessRuleError
from services.google_sheets import sheets_service
from services.io_worker import io_worker
from utils.formatters import safe_html

router = Router(name="harajat")
EXPENSE_CATEGORIES = {"Abed", "Arenda", "KPI", "Remont", "Telefon", "Rahbariyat"}
INCOME_CATEGORIES = {"Hamkorlar", "Dokondan", "Rahbariyat"}
MANAGEMENT_PEOPLE = {"Abduqayum", "Investor"}


async def require_accountant(user_id):
    active, role, _ = await io_worker.call(
        sheets_service.check_member, user_id
    )
    if not active or role not in {"Admin", "Hisobchi"}:
        raise BusinessRuleError("Bu amal faqat Admin va Hisobchi uchun ruxsat etilgan.")


async def save_completed(message, state, text):
    await state.clear()
    await message.answer(text, reply_markup=hisobchi_menu_kb())


@router.message(F.text == "💰 Balance")
@safe_handler
async def view_balance(message: types.Message):
    active, role, _ = await io_worker.call(
        sheets_service.check_member, message.from_user.id
    )
    if not active or role not in {"Admin", "Hisobchi", "Rahbariyat", "Investor"}:
        raise BusinessRuleError("Balansni ko‘rishga ruxsat berilmagan.")
    s = await io_worker.call(sheets_service.get_financial_summary)
    classification_note = (
        f"\n⚠️ Tasniflanmagan chiqim: <b>{s['unclassified_expenses']:,.2f}$</b>. "
        "Operatsion foydaga kiritilmagan; hisobchi tasnifni tekshirsin."
        if s["unclassified_expenses"]
        else ""
    )
    await message.answer(
        "📊 <b>OYMAOY MOLIYAVIY BALANS</b>\n\n"
        f"💵 Kassa: <b>{s['kassa_balance']:,.2f}$</b>\n"
        f"🤝 Xaridor/hamkor qarzi: <b>{s['partner_debts']:,.2f}$</b>\n"
        f"   Xaridor qarzi: <b>{s['customer_debts']:,.2f}$</b>\n"
        f"   Tashqi hamkor qarzi: <b>{s['external_partner_debts']:,.2f}$</b>\n"
        f"📱 Xarid bo‘yicha do‘kon qarzi: <b>{s['store_phone_debts']:,.2f}$</b>\n"
        f"🎁 To‘lanmagan KPI: <b>{s['staff_kpi_debts']:,.2f}$</b>\n\n"
        f"📈 Sotuv marjasi: <b>{s['sales_margin']:,.2f}$</b>\n"
        f"📉 Operatsion foyda: <b>{s['operating_profit']:,.2f}$</b>\n"
        f"Hisobot vaqti: <code>{safe_html(s['generated_at'])}</code>\n"
        "<i>Kapital kirimi foyda hisoblanmaydi. Remont va KPI foydadan ikki marta ayirilmaydi.</i>"
        + classification_note,
    )


@router.message(F.text == "📉 Chiqim")
@safe_handler
async def start_chiqim(message: types.Message, state: FSMContext):
    await require_accountant(message.from_user.id)
    await begin_flow(state, message.from_user.id)
    await state.set_state(ChiqimStates.choosing_category)
    await message.answer(
        "📉 Chiqim toifasini tanlang:", reply_markup=chiqim_categories_kb()
    )


@router.callback_query(ChiqimStates.choosing_category, F.data.startswith("exp:"))
@safe_handler
async def exp_category_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    cat = call.data.partition(":")[2]
    if cat not in EXPENSE_CATEGORIES:
        raise BusinessRuleError("Noto‘g‘ri chiqim toifasi.")
    await state.update_data(category=cat)
    if cat in {"Abed", "Arenda"}:
        await state.set_state(ChiqimStates.waiting_simple_amount)
        await call.message.answer(
            f"{cat} uchun summa kiriting ($):", reply_markup=cancel_kb()
        )
    elif cat == "KPI":
        staff = await io_worker.call(
            sheets_service.get_staff_list, active_only=True
        )
        await state.set_state(ChiqimStates.choosing_kpi_staff)
        await call.message.answer(
            "KPI oluvchi xodimni tanlang:", reply_markup=staff_inline_kb(staff)
        )
    elif cat == "Remont":
        await state.set_state(ChiqimStates.waiting_remont_imei)
        await call.message.answer(
            "Remont qilingan telefon IMEI sini kiriting:", reply_markup=cancel_kb()
        )
    elif cat == "Telefon":
        await state.set_state(ChiqimStates.waiting_phone_debt_imei)
        await call.message.answer(
            "Xarid qarzi to‘lanadigan telefon IMEI sini kiriting:",
            reply_markup=cancel_kb(),
        )
    else:
        await state.set_state(ChiqimStates.choosing_rahbariyat_recipient)
        await call.message.answer(
            "Pul oluvchini tanlang:", reply_markup=rahbariyat_persons_kb("exp_rahb")
        )


@router.message(ChiqimStates.waiting_simple_amount, F.text)
@safe_handler
async def simple_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    cat = data.get("category")
    if cat not in {"Abed", "Arenda"}:
        raise BusinessRuleError("Chiqim toifasini qayta tanlang.")
    await commit(
        state,
        message.from_user.id,
        sheets_service.record_expense,
        expense_type=cat,
        amount=amount,
        creator_name=message.from_user.full_name,
    )
    await save_completed(message, state, f"✅ {cat} chiqimi saqlandi! Summa: {amount}$")


@router.callback_query(ChiqimStates.choosing_kpi_staff, F.data.startswith("staff:"))
@safe_handler
async def staff_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    staff = await io_worker.call(
        sheets_service.get_staff_list, active_only=True
    )
    selection = call.data.partition(":")[2]
    person = next(
        (s for s in staff if str(s.get("Telegram ID", "")) == selection), None
    )
    if not person:
        raise BusinessRuleError("Xodim faol emas yoki tanlov eskirgan.")
    await state.update_data(staff_id=selection, staff_name=person["F.I.Sh"])
    await state.set_state(ChiqimStates.waiting_kpi_amount)
    await call.message.answer(
        f"Xodim: <b>{safe_html(person['F.I.Sh'])}</b>\n"
        f"Qoldiq: {safe_html(person.get('Qoldiq KPI ($)', '0'))}$\nTo‘lanadigan summa kiriting:",
        reply_markup=cancel_kb(),
    )


@router.message(ChiqimStates.waiting_kpi_amount, F.text)
@safe_handler
async def kpi_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    await commit(
        state,
        message.from_user.id,
        sheets_service.pay_staff_kpi,
        data.get("staff_id"),
        amount,
        message.from_user.full_name,
    )
    await save_completed(message, state, f"✅ KPI to‘lovi saqlandi: {amount}$")


@router.message(ChiqimStates.waiting_remont_imei, F.text)
@safe_handler
async def remont_imei_entered(message: types.Message, state: FSMContext):
    phone = await find_phone(message.text.strip(), state)
    if not phone:
        raise BusinessRuleError("Telefon topilmadi. IMEI ni tekshiring.")
    if phone.get("Holati") != "Sotuvda":
        raise BusinessRuleError(
            "Remont faqat ombordagi telefon uchun kiritiladi. Sotuvdan keyingi xarajat qoidasi aniqlanmagan."
        )
    await state.update_data(
        phone_id=phone["Telefon ID"], imei=phone["IMEI"], phone_data=phone
    )
    await state.set_state(ChiqimStates.confirm_remont_phone)
    await message.answer(
        f"Telefon: <b>{safe_html(phone['Model'])}</b>\nIMEI: <code>{safe_html(phone['IMEI'])}</code>\n"
        "Shu telefonga remont xarajati qo‘shilsinmi?",
        reply_markup=yes_no_kb(),
    )


@router.message(ChiqimStates.confirm_remont_phone, F.text.in_(["✅ Ha", "❌ Yo'q"]))
@safe_handler
async def confirm_remont_phone(message: types.Message, state: FSMContext):
    if message.text == "❌ Yo'q":
        await save_completed(message, state, "Bekor qilindi.")
        return
    await state.set_state(ChiqimStates.waiting_remont_amount)
    await message.answer("Remont summasini kiriting ($):", reply_markup=cancel_kb())


@router.message(ChiqimStates.waiting_remont_amount, F.text)
@safe_handler
async def remont_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    _, total_cost = await commit(
        state,
        message.from_user.id,
        sheets_service.record_repair,
        data.get("phone_id"),
        amount,
        message.from_user.full_name,
    )
    await save_completed(
        message,
        state,
        f"✅ Remont saqlandi: {amount}$. Yangi umumiy tannarx: {total_cost}$",
    )


@router.message(ChiqimStates.waiting_phone_debt_imei, F.text)
@safe_handler
async def phone_debt_imei_entered(message: types.Message, state: FSMContext):
    phone = await find_phone(message.text.strip(), state)
    if not phone:
        raise BusinessRuleError("Telefon topilmadi. IMEI ni tekshiring.")
    await state.update_data(phone_id=phone["Telefon ID"], imei=phone["IMEI"])
    await state.set_state(ChiqimStates.waiting_phone_debt_amount)
    await message.answer(
        f"{safe_html(phone['Model'])}\nIMEI: <code>{safe_html(phone['IMEI'])}</code>\n"
        f"Xarid qarzi: {safe_html(phone.get('Harid qarz summasi ($)', '0'))}$\nTo‘lov summasini kiriting:",
        reply_markup=cancel_kb(),
    )


@router.message(ChiqimStates.waiting_phone_debt_amount, F.text)
@safe_handler
async def phone_debt_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    _, remaining = await commit(
        state,
        message.from_user.id,
        sheets_service.pay_phone_debt,
        data.get("phone_id"),
        amount,
        message.from_user.full_name,
    )
    await save_completed(
        message, state, f"✅ To‘lov: {amount}$. Qolgan xarid qarzi: {remaining}$"
    )


@router.callback_query(
    ChiqimStates.choosing_rahbariyat_recipient, F.data.startswith("exp_rahb:")
)
@safe_handler
async def rahb_recipient_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    person = call.data.partition(":")[2]
    if person not in MANAGEMENT_PEOPLE:
        raise BusinessRuleError("Noto‘g‘ri qabul qiluvchi.")
    await state.update_data(recipient=person)
    await state.set_state(ChiqimStates.waiting_rahbariyat_amount)
    await call.message.answer(
        f"{person} uchun summa kiriting ($):", reply_markup=cancel_kb()
    )


@router.message(ChiqimStates.waiting_rahbariyat_amount, F.text)
@safe_handler
async def rahb_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    if data.get("recipient") not in MANAGEMENT_PEOPLE:
        raise BusinessRuleError("Qabul qiluvchini qayta tanlang.")
    await commit(
        state,
        message.from_user.id,
        sheets_service.record_expense,
        expense_type="Rahbariyat",
        amount=amount,
        recipient=data["recipient"],
        creator_name=message.from_user.full_name,
    )
    await save_completed(
        message, state, f"✅ {data['recipient']} uchun chiqim: {amount}$"
    )


@router.message(F.text == "📈 Kirim")
@safe_handler
async def start_kirim(message: types.Message, state: FSMContext):
    await require_accountant(message.from_user.id)
    await begin_flow(state, message.from_user.id)
    await state.set_state(KirimStates.choosing_category)
    await message.answer("Kirim manbasini tanlang:", reply_markup=kirim_categories_kb())


@router.callback_query(KirimStates.choosing_category, F.data.startswith("inc:"))
@safe_handler
async def inc_category_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    cat = call.data.partition(":")[2]
    if cat not in INCOME_CATEGORIES:
        raise BusinessRuleError("Noto‘g‘ri kirim toifasi.")
    await state.update_data(category=cat)
    if cat == "Hamkorlar":
        partners = await io_worker.call(sheets_service.get_partners)
        await state.set_state(KirimStates.choosing_partner)
        await call.message.answer(
            "Hamkorni tanlang:",
            reply_markup=partners_inline_kb(partners, "inc_partner"),
        )
    elif cat == "Dokondan":
        await state.update_data(imei="-")
        await state.set_state(KirimStates.waiting_dokon_amount)
        await call.message.answer(
            "Umumiy kirim summasini kiriting ($).\n"
            "<i>IMEI ga bog‘langan qarz to‘lovi hisob qoidasi aniqlanmaguncha bloklangan. "
            "Bu kirim xarid qarzini kamaytirmaydi.</i>",
            reply_markup=cancel_kb(),
        )
    else:
        await state.set_state(KirimStates.choosing_rahbariyat_sender)
        await call.message.answer(
            "Kimdan pul olindi?", reply_markup=rahbariyat_persons_kb("inc_rahb")
        )


@router.callback_query(KirimStates.choosing_partner, F.data.startswith("inc_partner:"))
@safe_handler
async def inc_partner_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    partners = await io_worker.call(sheets_service.get_partners)
    try:
        partner = resolve_callback_key(call.data.partition(":")[2], partners)
    except ValueError as exc:
        raise BusinessRuleError("Hamkor tanlovi eskirgan. Qayta tanlang.") from exc
    await state.update_data(partner_name=partner["Hamkor nomi"])
    await state.set_state(KirimStates.waiting_partner_amount)
    await call.message.answer(
        f"Hamkor: <b>{safe_html(partner['Hamkor nomi'])}</b>\n"
        f"Qarz: {safe_html(partner['Hozirgi qarzdorlik ($)'])}$\nTo‘lov summasini kiriting:",
        reply_markup=cancel_kb(),
    )


@router.message(KirimStates.waiting_partner_amount, F.text)
@safe_handler
async def inc_partner_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    await commit(
        state,
        message.from_user.id,
        sheets_service.reduce_partner_debt,
        data.get("partner_name"),
        amount,
        message.from_user.full_name,
    )
    await save_completed(message, state, f"✅ Hamkor to‘lovi saqlandi: {amount}$")


@router.message(KirimStates.waiting_dokon_amount, F.text)
@safe_handler
async def dokon_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    if data.get("imei") not in {None, "", "-"}:
        raise BusinessRuleError(
            "IMEI ga bog‘langan kirim qoidasi aniqlanmagan. Xarid qarzini kirim bilan kamaytirish bloklangan."
        )
    await commit(
        state,
        message.from_user.id,
        sheets_service.record_income,
        income_type="Dokondan",
        amount=amount,
        source="Umumiy kirim",
        creator_name=message.from_user.full_name,
    )
    await save_completed(
        message,
        state,
        f"✅ Umumiy kirim saqlandi: {amount}$. Qarz qoldiqlari o‘zgarmadi.",
    )


@router.callback_query(
    KirimStates.choosing_rahbariyat_sender, F.data.startswith("inc_rahb:")
)
@safe_handler
async def inc_rahb_chosen(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
    person = call.data.partition(":")[2]
    if person not in MANAGEMENT_PEOPLE:
        raise BusinessRuleError("Noto‘g‘ri kirim manbasi.")
    await state.update_data(sender=person)
    await state.set_state(KirimStates.waiting_rahbariyat_amount)
    await call.message.answer(
        f"{person}dan kirim summasini kiriting ($):", reply_markup=cancel_kb()
    )


@router.message(KirimStates.waiting_rahbariyat_amount, F.text)
@safe_handler
async def inc_rahb_amount_entered(message: types.Message, state: FSMContext):
    amount = clean_currency(message.text)
    data = await state.get_data()
    if data.get("sender") not in MANAGEMENT_PEOPLE:
        raise BusinessRuleError("Kirim manbasini qayta tanlang.")
    await commit(
        state,
        message.from_user.id,
        sheets_service.record_income,
        income_type="Rahbariyat",
        amount=amount,
        source=data["sender"],
        creator_name=message.from_user.full_name,
    )
    await save_completed(message, state, f"✅ {data['sender']}dan kirim: {amount}$")
