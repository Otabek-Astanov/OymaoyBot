from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from typing import List, Dict, Any


def hisobchi_menu_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="📈 Kirim"), KeyboardButton(text="📉 Chiqim")],
        [KeyboardButton(text="💰 Balance")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def rahbariyat_menu_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="💰 Balance")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚫 Bekor qilish")]],
        resize_keyboard=True,
    )


def chiqim_categories_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="🍲 Abed", callback_data="exp:Abed"),
            InlineKeyboardButton(text="🎁 KPI", callback_data="exp:KPI"),
        ],
        [
            InlineKeyboardButton(text="🛠 Remont", callback_data="exp:Remont"),
            InlineKeyboardButton(text="📱 Telefon (qarz)", callback_data="exp:Telefon"),
        ],
        [
            InlineKeyboardButton(text="👔 Rahbariyat", callback_data="exp:Rahbariyat"),
            InlineKeyboardButton(text="🏢 Arenda", callback_data="exp:Arenda"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def kirim_categories_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="🤝 Hamkorlar", callback_data="inc:Hamkorlar"),
            InlineKeyboardButton(text="🏪 Do'kondan", callback_data="inc:Dokondan"),
        ],
        [
            InlineKeyboardButton(text="👔 Rahbariyat", callback_data="inc:Rahbariyat"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def rahbariyat_persons_kb(prefix: str = "rahb") -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="👤 Abduqayum", callback_data=f"{prefix}:Abduqayum"),
            InlineKeyboardButton(text="💼 Investor", callback_data=f"{prefix}:Investor"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def partners_inline_kb(partners: List[Dict[str, Any]], prefix: str = "partner_inc") -> InlineKeyboardMarkup:
    kb = []
    for p in partners:
        name = p.get("Hamkor nomi", "").strip()
        debt = p.get("Hozirgi qarzdorlik ($)", "0")
        if name:
            kb.append([InlineKeyboardButton(text=f"🤝 {name} (${debt})", callback_data=f"{prefix}:{name}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def staff_inline_kb(staff_list: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    kb = []
    for s in staff_list:
        name = s.get("Xodim ismi", "").strip()
        kpi = s.get("Qoldiq KPI ($)", "0")
        if name:
            kb.append([InlineKeyboardButton(text=f"👨‍💼 {name} (${kpi})", callback_data=f"staff:{name}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def yes_no_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="✅ Ha"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
