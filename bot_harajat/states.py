from aiogram.fsm.state import State, StatesGroup


class ChiqimStates(StatesGroup):
    choosing_category = State()
    waiting_simple_amount = State()  # Abed, Arenda
    choosing_kpi_staff = State()
    waiting_kpi_amount = State()
    waiting_remont_imei = State()
    confirm_remont_phone = State()
    waiting_remont_amount = State()
    waiting_phone_debt_imei = State()
    waiting_phone_debt_amount = State()
    choosing_rahbariyat_recipient = State()
    waiting_rahbariyat_amount = State()


class KirimStates(StatesGroup):
    choosing_category = State()
    choosing_partner = State()
    waiting_partner_amount = State()
    waiting_dokon_imei = State()
    waiting_dokon_amount = State()
    choosing_rahbariyat_sender = State()
    waiting_rahbariyat_amount = State()
