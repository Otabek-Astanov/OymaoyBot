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
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚫 Bekor qilish")]],
        resize_keyboard=True,
    )


def payment_type_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="💵 Naqd"), KeyboardButton(text="💳 Qarzga")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def partners_kb(partners: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🏢 Do'kondan", callback_data="partner:Dokondan")]
    ]
    for p in partners:
        p_name = p.get("Hamkor nomi", "").strip()
        if p_name:
            kb.append([InlineKeyboardButton(text=f"🤝 {p_name}", callback_data=f"partner:{p_name}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def kpi_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="5$"), KeyboardButton(text="10$")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def yes_no_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="✅ Ha"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
