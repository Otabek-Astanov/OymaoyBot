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
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)


def rahbariyat_menu_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="💰 Balance")],
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


def format_money_label(val: Any) -> str:
    """Format money cleanly for buttons: e.g. '$990.00' or 990 -> '$990' or '$990.50'."""
    clean = str(val or "0").replace("$", "").replace(",", "").strip()
    try:
        f = float(clean)
        if f.is_integer():
            return f"${int(f):,}"
        return f"${f:,.2f}"
    except (ValueError, TypeError):
        return f"${clean}" if clean else "$0"


def partners_inline_kb(partners: List[Dict[str, Any]], prefix: str = "partner_inc") -> InlineKeyboardMarkup:
    kb = []
    for p in partners:
        name = p.get("Hamkor nomi", "").strip()
        debt = p.get("Hozirgi qarzdorlik ($)", "0")
        if name and name.lower() not in ["dokondan", "do'kondan"]:
            kb.append([InlineKeyboardButton(text=f"🤝 {name} ({format_money_label(debt)})", callback_data=f"{prefix}:{name}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def staff_inline_kb(staff_list: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    kb = []
    for s in staff_list:
        name = str(s.get("F.I.Sh", s.get("Xodim ismi", ""))).strip()
        kpi = s.get("Qoldiq KPI ($)", "0")
        if name:
            kb.append([InlineKeyboardButton(text=f"👨‍💼 {name} ({format_money_label(kpi)})", callback_data=f"staff:{name}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def yes_no_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="✅ Ha"), KeyboardButton(text="❌ Yo'q")],
        [KeyboardButton(text="🚫 Bekor qilish")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
