"""Short opaque callback values resolved against fresh authorized records."""

import hashlib
from collections.abc import Iterable
from typing import Any


def callback_key(name: str) -> str:
    return hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:24]


def resolve_callback_key(
    key: str,
    choices: Iterable[dict[str, Any]],
    *,
    name_field: str = "Hamkor nomi",
) -> dict[str, Any]:
    matches = [
        record
        for record in choices
        if callback_key(str(record.get(name_field, "")).strip()) == key
    ]
    if len(matches) != 1:
        raise ValueError("Tanlov eskirgan yoki noaniq; qaytadan tanlang")
    return matches[0]


def callback_data(prefix: str, value: Any) -> str:
    result = f"{prefix}:{value}"
    if not result or len(result.encode("utf-8")) > 64:
        raise ValueError("Callback 64 UTF-8 baytdan oshmasligi kerak")
    return result


def staff_id(value: Any) -> str:
    text = str(value).strip()
    if not text.isascii() or not text.isdigit() or not 0 < int(text) < 2**63:
        raise ValueError("Telegram ID noto'g'ri")
    return str(int(text))
