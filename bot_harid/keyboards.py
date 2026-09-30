from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="📥 Harid qilish")],
        [KeyboardButton(text="📢 Telegram kanalga e'lon berish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)


def cancel_kb(placeholder: str = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚫 Bekor qilish")]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=placeholder,
    )


def skip_or_cancel_kb(placeholder: str = None) -> ReplyKeyboardMarkup:
    # Tashlab ketish klaviaturadan olib tashlandi (faqat inline tugma sifatida bo'ladi)
    return cancel_kb(placeholder)


def skip_inline_kb(callback_data: str = "skip") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭ Tashlab ketish", callback_data=callback_data)]]
    )


def brand_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="🍏 iPhone", callback_data="brand:iPhone"),
            InlineKeyboardButton(text="🤖 Android", callback_data="brand:Android"),
        ],
        [InlineKeyboardButton(text="📦 Boshqa qurilmalar", callback_data="brand:Boshqa")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def memory_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="64 GB", callback_data="mem:64 GB"),
            InlineKeyboardButton(text="128 GB", callback_data="mem:128 GB"),
        ],
        [
            InlineKeyboardButton(text="256 GB", callback_data="mem:256 GB"),
            InlineKeyboardButton(text="512 GB", callback_data="mem:512 GB"),
        ],
        [InlineKeyboardButton(text="1 TB", callback_data="mem:1 TB")],
        [InlineKeyboardButton(text="⏭ Tashlab ketish", callback_data="mem:-")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def box_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="✅ Ha"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)


def payment_type_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="💵 Naqd"), KeyboardButton(text="💳 Qarzga")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)


def yes_no_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="✅ Ha"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)


def post_channel_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="📢 Joylash"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)
