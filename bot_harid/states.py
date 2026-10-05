from aiogram.fsm.state import State, StatesGroup


class HaridStates(StatesGroup):
    choosing_brand = State()
    choosing_version = State()
    choosing_type = State()
    input_custom_model = State()
    waiting_imei_photo = State()
    choosing_memory = State()
    waiting_battery = State()
    waiting_color = State()
    waiting_imei_6 = State()
    waiting_box = State()
    waiting_buy_price = State()
    waiting_seller_name = State()
    waiting_seller_phone = State()
    waiting_payment_type = State()
    waiting_debt_amount = State()
    confirm_purchase = State()
    ask_post_channel = State()
    waiting_channel_photo = State()
    waiting_sell_price = State()


class ChannelPostStates(StatesGroup):
    waiting_imei_search = State()
    confirm_found_phone = State()
    waiting_channel_photo = State()
    waiting_sell_price = State()
    confirm_post = State()


class KarobkaStates(StatesGroup):
    waiting_imei = State()
    confirm_phone = State()

