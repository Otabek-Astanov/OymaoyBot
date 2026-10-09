import re
from typing import Dict, Any, Optional


def extract_drive_file_id(photo_field: Any) -> str:
    """Google Sheets'dagi formula yoki URL ichidan Google Drive file_id ni ajratib oladi."""
    if not photo_field:
        return ""
    text = str(photo_field)
    match = re.search(r'/d/([a-zA-Z0-9_-]{25,})', text)
    if match:
        return match.group(1)
    match = re.search(r'id=([a-zA-Z0-9_-]{25,})', text)
    if match:
        return match.group(1)
    return ""


def clean_val(v: Any) -> Optional[str]:
    """Parametr bo'sh yoki tashlab ketilgan ('-') bo'lsa None qaytaradi."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s == "-" or s.lower() in ["none", "null"]:
        return None
    return s


OPTIONAL_TEMPLATE_KEYS = {
    "memory", "xotira", "battery", "batareya", "color", "rang", "box", "karobka", "imei", "imei_6",
    "condition", "holat", "holati"
}


def render_channel_template(template: str, data: Dict[str, Any]) -> str:
    """Shablon matnini berilgan ma'lumotlar bilan dinamik to'ldiradi."""
    brand = clean_val(data.get("brand") or data.get("Brend")) or ""
    version = clean_val(data.get("version") or data.get("Versiya")) or ""
    if brand and brand.lower() != "iphone" and version:
        model = version
    else:
        model = clean_val(data.get("model") or data.get("Model")) or version or "Telefon"
    memory = clean_val(data.get("memory") or data.get("Xotira")) or ""
    color = clean_val(data.get("color") or data.get("Rang")) or ""
    box = clean_val(data.get("has_box") or data.get("Karobka")) or ""
    condition = clean_val(data.get("condition") or data.get("holati") or data.get("holat")) or ""

    raw_battery = clean_val(data.get("battery") or data.get("Batareya %")) or ""
    battery_digits = raw_battery.replace("%", "").strip() if raw_battery else ""

    raw_imei = (clean_val(data.get("imei") or data.get("IMEI")) or "").strip().lstrip("'")
    raw_imei_6 = (clean_val(data.get("imei_6") or data.get("IMEI (oxirgi 6)")) or "").strip().lstrip("'")
    if not raw_imei_6 and raw_imei:
        raw_imei_6 = raw_imei[-6:] if len(raw_imei) >= 6 else raw_imei

    sell_price = clean_val(data.get("sell_price") or data.get("Sotuv narxi ($)")) or ""
    buy_price = clean_val(data.get("buy_price") or data.get("Harid narxi ($)")) or ""
    price_val = sell_price or buy_price or ""
    price_digits = price_val.replace("$", "").replace(",", "").strip() if price_val else ""
    buy_price_digits = buy_price.replace("$", "").replace(",", "").strip() if buy_price else ""

    context = {
        "model": model,
        "brand": brand,
        "brend": brand,
        "memory": memory,
        "xotira": memory,
        "battery": battery_digits,
        "batareya": battery_digits,
        "color": color,
        "rang": color,
        "box": box,
        "karobka": box,
        "condition": condition,
        "holat": condition,
        "holati": condition,
        "imei": raw_imei,
        "imei_6": raw_imei_6,
        "price": price_digits,
        "narx": price_digits,
        "sell_price": price_digits,
        "sotuv_narxi": price_digits,
        "buy_price": buy_price_digits,
        "harid_narxi": buy_price_digits,
    }

    lines = template.splitlines()
    result_lines = []

    for line in lines:
        placeholders = re.findall(r"\{([a-zA-Z0-9_]+)\}", line)
        if not placeholders:
            result_lines.append(line)
            continue

        skip_line = False
        for p in placeholders:
            p_lower = p.lower()
            val = context.get(p_lower)
            if (val is None or str(val).strip() in ["", "-", "None", "null"]) and p_lower in OPTIONAL_TEMPLATE_KEYS:
                skip_line = True
                break

        if skip_line:
            continue

        if battery_digits:
            line = re.sub(r"\{(?:battery|batareya)\}%", f"{battery_digits}%", line, flags=re.IGNORECASE)
            line = re.sub(r"\{(?:battery|batareya)\}", f"{battery_digits}%", line, flags=re.IGNORECASE)

        if price_digits:
            line = re.sub(r"\{(?:price|narx|sell_price|sotuv_narxi)\}\$", f"{price_digits}$", line, flags=re.IGNORECASE)
            line = re.sub(r"\{(?:price|narx|sell_price|sotuv_narxi)\}", f"{price_digits}$", line, flags=re.IGNORECASE)

        if buy_price_digits:
            line = re.sub(r"\{(?:buy_price|harid_narxi)\}\$", f"{buy_price_digits}$", line, flags=re.IGNORECASE)
            line = re.sub(r"\{(?:buy_price|harid_narxi)\}", f"{buy_price_digits}$", line, flags=re.IGNORECASE)

        def repl(match):
            key = match.group(1).lower()
            val = context.get(key)
            if val is None:
                return match.group(0)
            return str(val)

        new_line = re.sub(r"\{([a-zA-Z0-9_]+)\}", repl, line)
        result_lines.append(new_line)

    text = "\n".join(result_lines)

    # Agar shablonda {holati} kiritilmagan bo'lsa-yu, lekin telefon holati tanlangan bo'lsa:
    if condition and not re.search(r"\{(?:condition|holat|holati)\}", template, flags=re.IGNORECASE):
        cond_line = f"✨ Holati: <b>{condition}</b>"
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

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_channel_caption(data: Dict[str, Any], is_sold: bool = False) -> str:
    """Telegram kanalidagi e'lon matnini 'Shablonlar' jadvalidan olib dinamik shakllantiradi."""
    from services.google_sheets import sheets_service

    template = sheets_service.get_template("Elon")
    body = render_channel_template(template, data)

    if is_sold:
        sold_tpl = sheets_service.get_template("Sotildi")
        if sold_tpl and sold_tpl != template and "SOTILDI" in sold_tpl.upper():
            return render_channel_template(sold_tpl, data)
        return f"🔴 <b>SOTILDI ❌</b>\n━━━━━━━━━━━━━━━━━━\n{body}"

    return body


def build_buy_group_caption(data: Dict[str, Any]) -> str:
    """Harid guruhiga yuboriladigan hisobot matnini shakllantiradi."""
    brand = data.get("brand") or data.get("Brand") or data.get("Brend") or ""
    version = data.get("version") or data.get("Versiya") or ""
    if brand and str(brand).strip().lower() != "iphone" and version:
        model = str(version).strip()
    else:
        model = data.get("model") or data.get("Model") or "Qurilma"
    memory = clean_val(data.get("memory") or data.get("Xotira"))
    
    battery = clean_val(data.get("battery") or data.get("Batareya %"))
    if battery and "%" not in battery:
        battery = f"{battery}%"

    color = clean_val(data.get("color") or data.get("Rang"))
    box = clean_val(data.get("has_box") or data.get("Karobka"))
    imei = (clean_val(data.get("imei") or data.get("imei_6") or data.get("IMEI")) or "").strip().lstrip("'")
    buy_price = clean_val(data.get("buy_price") or data.get("Harid narxi ($)"))
    ptype = clean_val(data.get("payment_type") or data.get("Harid to'lov turi")) or "Naqd"
    debt = clean_val(data.get("debt_amount") or data.get("Harid qarz summasi ($)"))
    seller = clean_val(data.get("seller_name") or data.get("Telefon egasi"))
    phone = clean_val(data.get("seller_phone") or data.get("Telefon egasi telefoni"))
    buyer_staff = clean_val(data.get("buyer_staff_name") or data.get("buyer_name") or data.get("Oluvchi") or data.get("Qabul qiluvchi"))

    brand = data.get("brand") or data.get("Brand")
    item_header = "QURILMA" if brand == "Boshqa" else "TELEFON"
    lines = [
        f"📥 <b>YANGI {item_header} HARID QILINDI!</b>\n",
        f"📱 Model: <b>{model}</b>"
    ]
    if memory:
        lines.append(f"💾 Xotira: <b>{memory}</b>")
    if battery:
        lines.append(f"🔋 Batareya: <b>{battery}</b>")
    if color:
        lines.append(f"🎨 Rang: <b>{color}</b>")
    if box:
        lines.append(f"📦 Karobka: <b>{box}</b>")
    if imei:
        lines.append(f"🔍 IMEI / Seriya: <code>{imei}</code>")

    lines.append("")
    if buy_price:
        lines.append(f"💵 Harid narxi: <b>{buy_price}$</b>")
    lines.append(f"💳 To'lov turi: <b>{ptype}</b>")
    if ptype == "Qarz" and debt and float(debt) > 0:
        lines.append(f"⚠️ Qarz summasi: <b>{debt}$</b>")

    if seller and seller != "Mijoz":
        lines.append(f"👤 Egasi: <b>{seller}</b>" + (f" ({phone})" if phone and phone != "-" else ""))
    elif phone and phone != "-":
        lines.append(f"📞 Tel: <b>{phone}</b>")

    if buyer_staff:
        lines.append(f"👨‍💼 Oluvchi: <b>{buyer_staff}</b>")

    return "\n".join(lines).strip()


def build_purchase_summary(data: Dict[str, Any]) -> str:
    """Harid boti tasdiqlash oynasi uchun xulosa matni."""
    model = data.get("model") or "Qurilma"
    memory = clean_val(data.get("memory"))
    battery = clean_val(data.get("battery"))
    if battery and "%" not in battery:
        battery = f"{battery}%"
    color = clean_val(data.get("color"))
    box = clean_val(data.get("has_box"))
    imei = (clean_val(data.get("imei") or data.get("imei_6")) or "").strip().lstrip("'")
    buy_price = clean_val(data.get("buy_price"))
    ptype = clean_val(data.get("payment_type")) or "Naqd"
    seller = clean_val(data.get("seller_name"))
    phone = clean_val(data.get("seller_phone"))
    buyer_staff = clean_val(data.get("buyer_staff_name") or data.get("buyer_name") or data.get("Oluvchi"))

    lines = [
        "📋 <b>HARID MA'LUMOTLARINI TASDIQLANG:</b>\n",
        f"📱 Model: <b>{model}</b>"
    ]
    if memory:
        lines.append(f"💾 Xotira: <b>{memory}</b>")
    if battery:
        lines.append(f"🔋 Batareya: <b>{battery}</b>")
    if color:
        lines.append(f"🎨 Rang: <b>{color}</b>")
    if box:
        lines.append(f"📦 Karobka: <b>{box}</b>")
    if imei:
        lines.append(f"🔍 IMEI / Seriya: <code>{imei}</code>")

    lines.append("")
    if buy_price:
        lines.append(f"💵 Harid narxi: <b>{buy_price}$</b>")
    lines.append(f"💳 To'lov turi: <b>{ptype}</b>")

    seller_info = ""
    if seller and seller != "Mijoz":
        seller_info = f"👤 Egasi: <b>{seller}</b>"
        if phone and phone != "-":
            seller_info += f" ({phone})"
    elif phone and phone != "-":
        seller_info = f"📞 Tel: <b>{phone}</b>"

    if seller_info:
        lines.append(seller_info)

    if buyer_staff:
        lines.append(f"👨‍💼 Oluvchi: <b>{buyer_staff}</b>")

    lines.append("\n<b>Ma'lumotlar to'g'rimi?</b>")
    return "\n".join(lines).strip()


def build_sotuv_phone_info(phone: Dict[str, Any]) -> str:
    """Sotuv botida IMEI kiritilganda telefon ma'lumotlari matni."""
    actual_imei = str(phone.get("IMEI", phone.get("IMEI (oxirgi 6)", ""))).strip().lstrip("'")
    lines = ["📱 <b>Qurilma ma'lumotlari:</b>\n", f"Model: <b>{phone.get('Model')}</b>"]
    
    specs = []
    mem = clean_val(phone.get("Xotira"))
    bat = clean_val(phone.get("Batareya %"))
    if mem:
        specs.append(f"Xotira: <b>{mem}</b>")
    if bat:
        bat_str = f"{bat}%" if "%" not in bat else bat
        specs.append(f"Batareya: <b>{bat_str}</b>")
    if specs:
        lines.append(" | ".join(specs))

    extra_specs = []
    col = clean_val(phone.get("Rang"))
    bx = clean_val(phone.get("Karobka"))
    if col:
        extra_specs.append(f"Rang: <b>{col}</b>")
    if bx:
        extra_specs.append(f"Karobka: <b>{bx}</b>")
    if extra_specs:
        lines.append(" | ".join(extra_specs))

    buy_p = clean_val(phone.get("Harid narxi ($)"))
    if buy_p:
        lines.append(f"Harid narxi: <b>{buy_p}$</b>")
    lines.append(f"IMEI / Seriya: <code>{actual_imei}</code>\n")
    lines.append("<b>Rostdan ham ushbu mahsulot sotilmoqdami?</b>")
    return "\n".join(lines)
