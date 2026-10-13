"""USD values are validated at input and calculated with exact cents."""

import re
import math
from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")
# This also keeps conversion to a Sheets double within cent precision.
MAX_AMOUNT = Decimal("999999999999.99")
_PATTERN = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:[ \u00a0][0-9]{3})+)(?:[.,][0-9]{1,2})?")


class InvalidAmount(ValueError):
    pass


def parse_money(text: str, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(text, str):
        raise InvalidAmount("Summa matn bo'lishi kerak")
    value = text.strip()
    if value.startswith("$"):
        value = value[1:].strip()
    elif value.endswith("$"):
        value = value[:-1].strip()
    if not _PATTERN.fullmatch(value):
        raise InvalidAmount("Masalan: 10 yoki 10,50 (ikki kasr belgigacha)")
    try:
        amount = Decimal(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))
        if amount > MAX_AMOUNT:
            raise InvalidAmount("Summa ruxsat etilgan chegaradan katta")
        amount = amount.quantize(CENT)
    except InvalidOperation as exc:
        raise InvalidAmount("Summa juda katta yoki noto'g'ri") from exc
    if amount < 0 or (amount == 0 and not allow_zero):
        raise InvalidAmount("Musbat summa kiriting")
    return amount


def money_value(
    value, *, allow_zero: bool = True, signed: bool = False, empty_is_zero: bool = False
) -> Decimal:
    """Validate cents; tolerate only floating-point residue in numeric Sheets cells.

    User text and Decimal inputs always use the strict two-decimal parser. Sheets
    returns doubles, so legacy formulas such as 0.30 - 0.10 can have tiny binary
    residue. The tolerance is below a tenth of a cent even at MAX_AMOUNT.
    """
    if value in (None, "") and empty_is_zero:
        return Decimal("0.00")
    if isinstance(value, bool):
        raise InvalidAmount("Summa noto'g'ri")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidAmount("Summa chekli son bo'lishi kerak")
        if value < 0 and not signed:
            raise InvalidAmount("Musbat summa kiriting")
        amount = Decimal(str(abs(value)))
        if amount > MAX_AMOUNT:
            raise InvalidAmount("Summa ruxsat etilgan chegaradan katta")
        rounded = amount.quantize(CENT)
        tolerance = max(Decimal("0.000000001"), Decimal(str(math.ulp(value))) * 4)
        if abs(amount - rounded) > tolerance:
            raise InvalidAmount("Summa ikki kasr belgidan oshmasin")
        result = parse_money(format(rounded, ".2f"), allow_zero=allow_zero)
        return -result if value < 0 else result
    text = str(value).strip()
    if signed and text.startswith("-"):
        return -parse_money(text[1:], allow_zero=allow_zero)
    return parse_money(text, allow_zero=allow_zero)


def to_cents(amount: Decimal) -> int:
    validated = money_value(amount, signed=True)
    return int(validated * 100)


def validate_payment(amount, remaining) -> Decimal:
    from services.errors import BusinessRuleError

    payment = money_value(amount, allow_zero=False)
    balance = money_value(remaining)
    if payment > balance:
        raise BusinessRuleError(f"To'lov qoldiqdan oshmasin: {balance:.2f}$")
    return payment
