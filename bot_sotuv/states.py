from aiogram.fsm.state import State, StatesGroup


class SotuvStates(StatesGroup):
    waiting_imei = State()
    confirm_phone = State()
    waiting_sell_price = State()
    waiting_buyer_name = State()
    waiting_buyer_phone = State()
    waiting_payment_type = State()
    choosing_partner = State()
    waiting_initial_payment = State()
    choosing_kpi = State()
    confirm_sale = State()
