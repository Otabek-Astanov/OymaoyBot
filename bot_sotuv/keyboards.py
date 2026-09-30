from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from typing import List, Dict, Any


def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="📱 Yangi sotuvni rasmiylashtirish")],
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


def payment_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💵 Naqd", callback_data="pay:Naqd"),
                InlineKeyboardButton(text="💳 Qarzga", callback_data="pay:Qarz"),
            ]
        ]
    )


def partners_kb(partners: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🏢 Do'kondan", callback_data="partner:Dokondan")]
    ]
    for p in partners:
        p_name = p.get("Hamkor nomi", "").strip()
        if p_name:
            kb.append([InlineKeyboardButton(text=f"🤝 {p_name}", callback_data=f"partner:{p_name}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def kpi_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="5$", callback_data="kpi:5"), InlineKeyboardButton(text="10$", callback_data="kpi:10")],
            [InlineKeyboardButton(text="⏭ Tashlab ketish", callback_data="kpi:0")],
        ]
    )


def kpi_kb() -> ReplyKeyboardMarkup:
    return cancel_kb()


def yes_no_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="✅ Ha"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)
