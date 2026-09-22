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
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚫 Bekor qilish")]],
        resize_keyboard=True,
    )


def brand_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="🍏 iPhone", callback_data="brand:iPhone"),
            InlineKeyboardButton(text="🤖 Android", callback_data="brand:Android"),
        ],
        [InlineKeyboardButton(text="📱 Boshqa", callback_data="brand:Boshqa")],
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
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def box_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="✅ Ha"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def payment_type_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="💵 Naqd"), KeyboardButton(text="💳 Qarzga")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def yes_no_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="✅ Ha"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
