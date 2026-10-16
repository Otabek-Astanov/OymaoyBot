"""Pure Telegram renderers: trusted markup, escaped record values, no I/O."""

import re
from html import escape
from html.parser import HTMLParser
from typing import Any

DEFAULT_CHANNEL_TEMPLATE = (
    "📱 <b>{model}</b>\n\n"
    "💾 Xotirasi: <b>{memory}</b>\n"
    "🔋 Batareya holati: <b>{battery}%</b>\n"
    "🎨 Rangi: <b>{color}</b>\n"
    "📦 Karobkasi: <b>{box}</b>\n"
    "🔍 IMEI: <code>{imei}</code>\n\n"
    "💰 Narxi: <b>{price}$</b>"
)
OPTIONAL_TEMPLATE_KEYS = {
    "memory",
    "xotira",
    "battery",
    "batareya",
    "color",
    "rang",
    "box",
    "karobka",
    "condition",
    "holat",
    "holati",
    "imei",
    "imei_6",
}
_PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_]+)\}([%$]?)")


def clean_val(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text == "-" or text.lower() in {"none", "null"} else text


def _value(data: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = clean_val(data.get(key))
        if value is not None:
            return value
    return default


def safe_html(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def extract_drive_file_id(photo_field: Any) -> str:
    if not photo_field:
        return ""
    match = re.search(r"(?:/d/|[?&]id=)([a-zA-Z0-9_-]{25,})", str(photo_field))
    return match.group(1) if match else ""


def _model(data: dict[str, Any]) -> str:
    brand = _value(data, "brand", "Brand", "Brend")
    version = _value(data, "version", "Versiya")
    if brand and brand.lower() != "iphone" and version:
        return version
    return _value(data, "model", "Model", default=version or "Qurilma")


def render_channel_template(template: str, data: dict[str, Any]) -> str:
    """Escape substitutions once while retaining the administrator's HTML template."""
    brand = _value(data, "brand", "Brand", "Brend")
    memory = _value(data, "memory", "Xotira")
    battery = _value(data, "battery", "Batareya %").removesuffix("%").strip()
    color = _value(data, "color", "Rang")
    box = _value(data, "has_box", "Karobka")
    condition = _value(data, "condition", "holati", "holat")
    imei = _value(data, "imei", "IMEI").lstrip("'")
    imei_6 = _value(data, "imei_6", "IMEI (oxirgi 6)").lstrip("'") or imei[-6:]
    buy_price = _value(data, "buy_price", "Harid narxi ($)").strip("$ ")
    price = _value(
        data, "sell_price", "Elon narxi ($)", "Sotuv narxi ($)", default=buy_price
    ).strip("$ ")
    context = {
        "model": _model(data),
        "brand": brand,
        "brend": brand,
        "memory": memory,
        "xotira": memory,
        "battery": battery,
        "batareya": battery,
        "color": color,
        "rang": color,
        "box": box,
        "karobka": box,
        "condition": condition,
        "holat": condition,
        "holati": condition,
        "imei": imei,
        "imei_6": imei_6,
        "price": price,
        "narx": price,
        "sell_price": price,
        "sotuv_narxi": price,
        "buy_price": buy_price,
        "harid_narxi": buy_price,
    }

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        if key not in context:
            return match.group(0)
        value = context[key]
        suffix = match.group(2)
        if key in {"battery", "batareya"}:
            suffix = "%" if value else ""
        elif key in {
            "price",
            "narx",
            "sell_price",
            "sotuv_narxi",
            "buy_price",
            "harid_narxi",
        }:
            suffix = "$" if value else ""
        return safe_html(value) + suffix

    lines = []
    for line in template.splitlines():
        placeholders = {match.group(1).lower() for match in _PLACEHOLDER.finditer(line)}
        if any(not context.get(key) for key in placeholders & OPTIONAL_TEMPLATE_KEYS):
            continue
        lines.append(_PLACEHOLDER.sub(substitute, line))

    text = "\n".join(lines)

    # Agar shablonda {holati} kiritilmagan bo'lsa-yu, lekin telefon holati tanlangan bo'lsa:
    if condition and not re.search(r"\{(?:condition|holat|holati)\}", template, flags=re.IGNORECASE):
        cond_line = f"✨ Holati: <b>{safe_html(condition)}</b>"
        lines_out = []
        inserted = False
        for l in text.splitlines():
            lines_out.append(l)
            if not inserted and ("karobka" in l.lower() or "📦" in l):
                lines_out.append(cond_line)
                inserted = True
        if not inserted:
            lines_out2 = []
            for l in lines_out:
                if not inserted and ("narx" in l.lower() or "💰" in l):
                    lines_out2.append(cond_line)
                    inserted = True
                lines_out2.append(l)
            if not inserted:
                lines_out2.append(cond_line)
            lines_out = lines_out2
        text = "\n".join(lines_out)

    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_channel_caption(
    data: dict[str, Any],
    is_sold: bool = False,
    *,
    template: str | None = None,
    sold_template: str | None = None,
) -> str:
    template = template or DEFAULT_CHANNEL_TEMPLATE
    body = render_channel_template(template, data)
    if not is_sold:
        return body
    if (
        sold_template
        and sold_template != template
        and "SOTILDI" in sold_template.upper()
    ):
        return render_channel_template(sold_template, data)
    return f"🔴 <b>SOTILDI ❌</b>\n━━━━━━━━━━━━━━━━━━\n{body}"


def _phone_specs(data: dict[str, Any]) -> list[str]:
    fields = (
        ("💾 Xotira", ("memory", "Xotira")),
        ("🔋 Batareya", ("battery", "Batareya %")),
        ("🎨 Rang", ("color", "Rang")),
        ("📦 Karobka", ("has_box", "Karobka")),
    )
    lines = []
    for label, keys in fields:
        value = _value(data, *keys)
        if value:
            if label == "🔋 Batareya" and not value.endswith("%"):
                value += "%"
            lines.append(f"{label}: <b>{safe_html(value)}</b>")
    imei = _value(data, "imei", "imei_6", "IMEI", "IMEI (oxirgi 6)").lstrip("'")
    if imei:
        lines.append(f"🔍 IMEI / Seriya: <code>{safe_html(imei)}</code>")
    return lines


def _purchase_lines(data: dict[str, Any]) -> list[str]:
    lines = [f"📱 Model: <b>{safe_html(_model(data))}</b>", *_phone_specs(data), ""]
    price = _value(data, "buy_price", "Harid narxi ($)")
    payment_type = _value(data, "payment_type", "Harid to'lov turi", default="Naqd")
    if price:
        lines.append(f"💵 Harid narxi: <b>{safe_html(price)}$</b>")
    lines.append(f"💳 To'lov turi: <b>{safe_html(payment_type)}</b>")
    seller = _value(data, "seller_name", "Telefon egasi")
    phone = _value(data, "seller_phone", "Telefon egasi telefoni")
    if seller and seller != "Mijoz":
        suffix = f" ({safe_html(phone)})" if phone else ""
        lines.append(f"👤 Egasi: <b>{safe_html(seller)}</b>{suffix}")
    elif phone:
        lines.append(f"📞 Tel: <b>{safe_html(phone)}</b>")
    staff = _value(
        data,
        "buyer_staff_name",
        "buyer_name",
        "Oluvchi",
        "Qabul qiluvchi",
        "Qabul qilgan xodim",
    )
    if staff:
        lines.append(f"👨‍💼 Oluvchi: <b>{safe_html(staff)}</b>")
    return lines


def build_buy_group_caption(data: dict[str, Any]) -> str:
    kind = (
        "QURILMA" if _value(data, "brand", "Brand", "Brend") == "Boshqa" else "TELEFON"
    )
    lines = [f"📥 <b>YANGI {kind} HARID QILINDI!</b>\n", *_purchase_lines(data)]
    debt = _value(data, "debt_amount", "Harid qarz summasi ($)")
    if _value(data, "payment_type", "Harid to'lov turi") == "Qarz" and debt:
        lines.append(f"⚠️ Qarz summasi: <b>{safe_html(debt)}$</b>")
    return "\n".join(lines).strip()


def build_purchase_summary(data: dict[str, Any]) -> str:
    return "\n".join(
        [
            "📋 <b>HARID MA'LUMOTLARINI TASDIQLANG:</b>\n",
            *_purchase_lines(data),
            "\n<b>Ma'lumotlar to'g'rimi?</b>",
        ]
    ).strip()


def build_sotuv_phone_info(phone: dict[str, Any]) -> str:
    lines = [
        "📱 <b>Qurilma ma'lumotlari:</b>\n",
        f"Model: <b>{safe_html(_model(phone))}</b>",
        *_phone_specs(phone),
    ]
    price = _value(phone, "Harid narxi ($)")
    if price:
        lines.append(f"Harid narxi: <b>{safe_html(price)}$</b>")
    lines.append("\n<b>Rostdan ham ushbu mahsulot sotilmoqdami?</b>")
    return "\n".join(lines)


def _phone_details(phone: dict[str, Any], fields) -> list[str]:
    lines = [
        f"📱 Model: <b>{safe_html(_model(phone))}</b>",
        f"🔍 IMEI / Seriya: <code>{safe_html(_value(phone, 'IMEI', default='-'))}</code>",
    ]
    for label, key, suffix in fields:
        value = _value(phone, key)
        if value and value != "Mijoz":
            lines.append(f"{label}: <b>{safe_html(value)}{suffix}</b>")
    return lines


SOLD_FIELDS = (
    ("📅 Sotilgan sana", "Sotilgan sana", ""),
    ("👤 Xaridor", "Xaridor ismi", ""),
    ("📞 Xaridor tel", "Xaridor telefoni", ""),
    ("💰 Sotilgan narxi", "Sotuv narxi ($)", "$"),
    ("👨‍💼 Sotgan xodim", "Do'kon sotuvchisi", ""),
)


def build_sold_phone_card(phone: dict[str, Any], footer: str = "") -> str:
    lines = ["⚠️ <b>Bu qurilma allaqachon sotilgan.</b>\n", *_phone_details(phone, SOLD_FIELDS)]
    if footer:
        lines.append(f"\n<i>{safe_html(footer)}</i>")
    return "\n".join(lines)


def build_changed_phone_notice(action: str, phone: dict[str, Any] | None) -> str:
    """Why a final "✅ Ha" was refused: the phone changed after the flow began."""
    head = f"⚠️ <b>{action} saqlanmadi.</b>"  # action is a fixed label, not input
    if not phone:
        return f"{head}\nTelefon jadvalda topilmadi: o'chirilgan yoki o'zgartirilgan bo'lishi mumkin."
    if phone.get("Holati") == "Sotildi":
        return "\n".join(
            [
                f"{head} Bu telefon siz tasdiqlashingizdan oldin sotilgan.\n",
                *_phone_details(phone, SOLD_FIELDS),
            ]
        )
    return f"{head} Telefon holati endi «{safe_html(phone.get('Holati') or '-')}»."


def build_duplicate_purchase_notice(phone: dict[str, Any]) -> str:
    fields = (
        ("📅 Harid sanasi", "Harid sanasi", ""),
        ("👨‍💼 Qabul qilgan xodim", "Qabul qilgan xodim", ""),
    )
    return "\n".join(
        [
            "⚠️ <b>Xarid saqlanmadi.</b> Bu IMEI bilan sotuvdagi telefon allaqachon "
            "kiritilgan (boshqa xodim siz bilan bir vaqtda kiritgan bo'lishi mumkin).\n",
            *_phone_details(phone, fields),
        ]
    )


def build_sale_summary(data: dict[str, Any]) -> str:
    """Confirmation card shown before a sale is saved."""
    lines = [
        "📋 <b>SOTUVNI TASDIQLANG:</b>\n",
        f"📱 Model: <b>{safe_html(_model(data))}</b>",
    ]
    imei = _value(data, "imei", "imei_6")
    if imei:
        lines.append(f"🔍 IMEI / Seriya: <code>{safe_html(imei)}</code>")
    lines += ["", f"💰 Sotuv narxi: <b>{safe_html(_value(data, 'sell_price'))}$</b>"]
    buyer = _value(data, "buyer_name")
    phone = _value(data, "buyer_phone")
    if buyer and buyer != "Mijoz":
        suffix = f" ({safe_html(phone)})" if phone else ""
        lines.append(f"👤 Xaridor: <b>{safe_html(buyer)}</b>{suffix}")
    elif phone:
        lines.append(f"📞 Xaridor tel: <b>{safe_html(phone)}</b>")
    lines.append(f"💳 To'lov turi: <b>{safe_html(_value(data, 'payment_type'))}</b>")
    if data.get("payment_type") == "Qarz":
        lines += [
            f"🤝 Hamkor: <b>{safe_html(_value(data, 'partner_name'))}</b>",
            f"💵 Boshlang'ich to'lov: <b>{safe_html(_value(data, 'initial_payment', default='0'))}$</b>",
            f"📉 Hamkor qarzi: <b>{safe_html(_value(data, 'partner_debt', default='0'))}$</b>",
        ]
    lines.append(
        f"\n🎁 Jami KPI: <b>{safe_html(_value(data, 'seller_kpi', default='0'))}$</b>"
    )
    for seller in data.get("sellers") or ():
        if isinstance(seller, dict):
            lines.append(
                f"   {safe_html(_value(seller, 'name', default='Xodim'))}: "
                f"{safe_html(_value(seller, 'kpi', default='0'))}$"
            )
    lines.append("\n<b>Ma'lumotlar to'g'rimi?</b>")
    return "\n".join(lines)


def build_sell_group_caption(data: dict[str, Any]) -> str:
    fields = (
        ("📱 Model", "model", "Model"),
        ("🔍 IMEI / Seriya", "imei", "imei_6"),
        ("💰 Sotuv narxi", "sell_price", None),
        ("👤 Xaridor", "buyer_name", None),
        ("📞 Xaridor tel", "buyer_phone", None),
        ("💳 To'lov turi", "payment_type", None),
    )
    lines = ["🎉 <b>YANGI SOTUV AMALGA OSHIRILDI!</b>\n"]
    for label, key, fallback in fields:
        value = _value(data, key, *([fallback] if fallback else []))
        if key == "sell_price":
            value += "$"
        tag = "code" if key == "imei" else "b"
        lines.append(f"{label}: <{tag}>{safe_html(value)}</{tag}>")
    if data.get("payment_type") == "Qarz":
        for label, key, suffix in (
            ("🤝 Hamkor", "partner_name", ""),
            ("💵 Boshlang'ich to'lov", "initial_payment", "$"),
            ("📉 Hamkor qarzi", "partner_debt", "$"),
        ):
            lines.append(f"{label}: <b>{safe_html(_value(data, key))}{suffix}</b>")
    lines += [
        f"\n🎁 Jami KPI: <b>{safe_html(_value(data, 'seller_kpi', default='0'))}$</b>"
    ]
    sellers = data.get("sellers")
    if isinstance(sellers, list):
        for seller in sellers:
            if isinstance(seller, dict):
                lines.append(
                    f"{safe_html(_value(seller, 'name', default='Xodim'))}: {safe_html(_value(seller, 'kpi', default='0'))}$"
                )
    lines.append(f"👨‍💼 Sotuvchi: <b>{safe_html(_value(data, 'seller_name'))}</b>")
    return "\n".join(lines)


class _PlainTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.parts.append("\n")


def prepare_telegram_text(html_text: str, limit: int) -> tuple[str, str | None]:
    """Keep short HTML intact; oversized text becomes a safely clipped plain message.

    The conservative UTF-16 length also bounds Telegram entity offsets without
    splitting surrogate pairs or leaving an unterminated HTML tag.
    """
    if limit < 2:
        raise ValueError("Telegram text limit must be at least two")
    if len(html_text.encode("utf-16-le")) // 2 <= limit:
        return html_text, "HTML"
    parser = _PlainTextParser()
    parser.feed(html_text)
    plain = "".join(parser.parts)
    if len(plain.encode("utf-16-le")) // 2 <= limit:
        return plain, None
    budget = limit - 1
    parts = []
    for character in plain:
        units = len(character.encode("utf-16-le")) // 2
        if units > budget:
            break
        parts.append(character)
        budget -= units
    return "".join(parts) + "…", None
