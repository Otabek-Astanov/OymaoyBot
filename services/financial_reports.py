"""Read-only cash, receivables, payables and profit definitions."""

from datetime import datetime, timezone
from decimal import Decimal
from collections import Counter

import config
from services.errors import StorageReadError
from utils.money import InvalidAmount, money_value

ZERO = Decimal("0.00")


def _amount(title, row, column, *, signed=False, optional=False):
    try:
        return money_value(row.get(column), signed=signed, empty_is_zero=optional)
    except InvalidAmount as exc:
        raise StorageReadError(
            f"{title}:{row.get('_row_index', '?')}: {column} noto'g'ri"
        ) from exc


def validate_partner_balances(sources):
    """Every partner must reconcile; missing history is never an inferred opening balance."""
    registered = {}
    for row in sources[config.SHEET_PARTNERS]:
        name = str(row.get("Hamkor nomi", "")).strip()
        if not name or name in registered:
            raise StorageReadError(
                f"Hamkorlar:{row.get('_row_index', '?')}: hamkor nomi bo'sh yoki takroriy"
            )
        registered[name] = row
    balances = {name: ZERO for name in registered}
    for row in sources[config.SHEET_PHONES]:
        debt = _amount(config.SHEET_PHONES, row, "Hamkor qarzi ($)", optional=True)
        name = str(row.get("Hamkor nomi", "")).strip()
        if debt:
            if name not in registered:
                raise StorageReadError(
                    f"Telefonlar:{row.get('_row_index', '?')}: qarz uchun hamkor yozuvi yo'q"
                )
            if row.get("Holati") != "Sotildi" or row.get("Sotuv to'lov turi") != "Qarz":
                raise StorageReadError(
                    f"Telefonlar:{row.get('_row_index', '?')}: hamkor qarzi sotuv holati bilan mos emas"
                )
            balances[name] += debt
    for row in sources[config.SHEET_INCOMES]:
        name = str(row.get("Hamkor nomi", "")).strip()
        if name:
            if name not in registered:
                raise StorageReadError(
                    f"Kirimlar:{row.get('_row_index', '?')}: kirim hamkori mavjud emas"
                )
            if str(row.get("Kirim turi", "")).strip() != "Hamkor to'lovi":
                raise StorageReadError(
                    f"Kirimlar:{row.get('_row_index', '?')}: hamkorli kirim turi noaniq; avval yarashtiring"
                )
            balances[name] -= _amount(config.SHEET_INCOMES, row, "Summa ($)")
    for name, row in registered.items():
        recorded = _amount(config.SHEET_PARTNERS, row, "Hozirgi qarzdorlik ($)")
        if recorded != balances[name] or balances[name] < 0:
            raise StorageReadError(
                f"Hamkorlar:{row.get('_row_index', '?')}: hamkor qoldig'i telefon/kirim tarixi bilan mos emas; avval yarashtiring"
            )
    return balances


def financial_summary(sources):
    required = (
        config.SHEET_PHONES,
        config.SHEET_INCOMES,
        config.SHEET_EXPENSES,
        config.SHEET_PARTNERS,
        config.SHEET_STAFF,
    )
    if any(title not in sources for title in required):
        raise StorageReadError("Hisobotning barcha varaqlari o'qilishi shart")
    validate_partner_balances(sources)
    result = dict.fromkeys(
        (
            "kassa_balance",
            "total_income",
            "total_expense",
            "partner_debts",
            "store_phone_debts",
            "staff_kpi_debts",
            "total_net_profit",
            "sales_margin",
            "operating_profit",
            "operating_expense",
            "capital_income",
            "unclassified_expenses",
            "customer_debts",
            "external_partner_debts",
        ),
        ZERO,
    )
    for row in sources[config.SHEET_INCOMES]:
        amount = _amount(config.SHEET_INCOMES, row, "Summa ($)")
        result["total_income"] += amount
        if str(row.get("Kirim turi", "")).casefold() == "rahbariyat":
            result["capital_income"] += amount
    for row in sources[config.SHEET_EXPENSES]:
        amount = _amount(config.SHEET_EXPENSES, row, "Summa ($)")
        result["total_expense"] += amount
        kind = str(row.get("Chiqim turi", "")).strip().casefold()
        if kind in {"abed", "arenda"}:
            result["operating_expense"] += amount
        elif kind not in {"remont", "kpi", "telefon (qarz)", "rahbariyat"}:
            # The owner must classify additional categories before treating them as P&L.
            result["unclassified_expenses"] += amount
    for row in sources[config.SHEET_PHONES]:
        buy = _amount(config.SHEET_PHONES, row, "Harid narxi ($)")
        debt = _amount(config.SHEET_PHONES, row, "Harid qarz summasi ($)")
        if debt > buy:
            raise StorageReadError(
                f"Telefonlar:{row.get('_row_index', '?')}: xarid qarzi narxdan katta"
            )
        result["store_phone_debts"] += debt
        buy_type = str(row.get("Harid to'lov turi", "")).strip()
        if buy_type == "Naqd":
            result["total_expense"] += buy
        elif buy_type != "Qarz":
            raise StorageReadError(
                f"Telefonlar:{row.get('_row_index', '?')}: xarid to'lov turi noma'lum"
            )
        if row.get("Holati") == "Sotildi":
            sell = _amount(config.SHEET_PHONES, row, "Sotuv narxi ($)")
            total_cost = _amount(config.SHEET_PHONES, row, "Jami tannarx ($)")
            kpi = _amount(config.SHEET_PHONES, row, "Xodim KPI ($)", optional=True)
            recorded_profit = _amount(
                config.SHEET_PHONES, row, "Sof foyda ($)", signed=True
            )
            profit = sell - total_cost - kpi
            if profit != recorded_profit:
                raise StorageReadError(
                    f"Telefonlar:{row.get('_row_index', '?')}: saqlangan foyda tannarx/KPI bilan mos emas"
                )
            result["sales_margin"] += profit
            sell_type = str(row.get("Sotuv to'lov turi", "")).strip()
            if sell_type == "Naqd":
                result["total_income"] += sell
            elif sell_type == "Qarz":
                initial = _amount(config.SHEET_PHONES, row, "Boshlang'ich to'lov ($)")
                if initial > sell:
                    raise StorageReadError(
                        f"Telefonlar:{row.get('_row_index', '?')}: boshlang'ich to'lov narxdan katta"
                    )
                result["total_income"] += initial
            else:
                raise StorageReadError(
                    f"Telefonlar:{row.get('_row_index', '?')}: sotuv to'lov turi noma'lum"
                )
    for row in sources[config.SHEET_PARTNERS]:
        amount = _amount(config.SHEET_PARTNERS, row, "Hozirgi qarzdorlik ($)")
        result["partner_debts"] += amount
        name = str(row.get("Hamkor nomi", "")).strip().replace("'", "").casefold()
        result[
            "customer_debts" if name == "dokondan" else "external_partner_debts"
        ] += amount
    for row in sources[config.SHEET_STAFF]:
        total = _amount(config.SHEET_STAFF, row, "Jami KPI ($)")
        paid = _amount(config.SHEET_STAFF, row, "To'langan KPI ($)")
        remainder = _amount(config.SHEET_STAFF, row, "Qoldiq KPI ($)")
        if total - paid != remainder:
            raise StorageReadError(
                f"Xodimlar:{row.get('_row_index', '?')}: KPI qoldig'i mos emas"
            )
        result["staff_kpi_debts"] += remainder
    result["kassa_balance"] = result["total_income"] - result["total_expense"]
    result["operating_profit"] = result["sales_margin"] - result["operating_expense"]
    result["total_net_profit"] = result["operating_profit"]
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def reconciliation_report(sources):
    """Expose historical mismatches without guessing balances or rewriting cells."""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "differences": [],
        "errors": [],
        "google_writes": False,
    }
    required = (
        config.SHEET_PHONES,
        config.SHEET_INCOMES,
        config.SHEET_EXPENSES,
        config.SHEET_PARTNERS,
        config.SHEET_STAFF,
    )
    if any(title not in sources for title in required):
        raise StorageReadError("Yarashtirish uchun barcha varaqlar o'qilishi shart")
    try:
        validate_partner_balances(sources)
    except StorageReadError as exc:
        report["errors"].append({"message": str(exc)})
    for title, id_field in (
        (config.SHEET_PHONES, "Telefon ID"),
        (config.SHEET_INCOMES, "ID"),
        (config.SHEET_EXPENSES, "ID"),
        (config.SHEET_STAFF, "Telegram ID"),
    ):
        identities = [str(row.get(id_field, "")).strip() for row in sources[title]]
        duplicates = [
            identity
            for identity, count in Counter(identities).items()
            if identity and count > 1
        ]
        if duplicates or "" in identities:
            report["errors"].append(
                {
                    "sheet": title,
                    "column": id_field,
                    "duplicate_ids": duplicates,
                    "empty_ids": identities.count(""),
                }
            )
    for partner in sources[config.SHEET_PARTNERS]:
        name = str(partner.get("Hamkor nomi", "")).strip()
        try:
            recorded = _amount(config.SHEET_PARTNERS, partner, "Hozirgi qarzdorlik ($)")
            accrued = sum(
                (
                    _amount(config.SHEET_PHONES, row, "Hamkor qarzi ($)", optional=True)
                    for row in sources[config.SHEET_PHONES]
                    if str(row.get("Hamkor nomi", "")).strip() == name
                ),
                ZERO,
            )
            repaid = sum(
                (
                    _amount(config.SHEET_INCOMES, row, "Summa ($)")
                    for row in sources[config.SHEET_INCOMES]
                    if str(row.get("Hamkor nomi", "")).strip() == name
                ),
                ZERO,
            )
            ledger = accrued - repaid
            if recorded != ledger:
                report["differences"].append(
                    {
                        "sheet": config.SHEET_PARTNERS,
                        "row": partner.get("_row_index"),
                        "partner": name,
                        "recorded": recorded,
                        "ledger": ledger,
                        "difference": recorded - ledger,
                    }
                )
        except StorageReadError as exc:
            report["errors"].append({"message": str(exc)})
    for staff in sources[config.SHEET_STAFF]:
        try:
            expected = _amount(config.SHEET_STAFF, staff, "Jami KPI ($)") - _amount(
                config.SHEET_STAFF, staff, "To'langan KPI ($)"
            )
            recorded = _amount(config.SHEET_STAFF, staff, "Qoldiq KPI ($)")
            if recorded != expected:
                report["differences"].append(
                    {
                        "sheet": config.SHEET_STAFF,
                        "row": staff.get("_row_index"),
                        "recorded": recorded,
                        "ledger": expected,
                        "difference": recorded - expected,
                    }
                )
        except StorageReadError as exc:
            report["errors"].append({"message": str(exc)})
    for phone in sources[config.SHEET_PHONES]:
        try:
            buy = _amount(config.SHEET_PHONES, phone, "Harid narxi ($)")
            repair = _amount(
                config.SHEET_PHONES, phone, "Remont xarajati ($)", optional=True
            )
            cost = _amount(config.SHEET_PHONES, phone, "Jami tannarx ($)")
            if cost != buy + repair:
                report["differences"].append(
                    {
                        "sheet": config.SHEET_PHONES,
                        "row": phone.get("_row_index"),
                        "column": "Jami tannarx ($)",
                        "recorded": cost,
                        "ledger": buy + repair,
                        "difference": cost - buy - repair,
                    }
                )
            if phone.get("Holati") == "Sotildi":
                expected = (
                    _amount(config.SHEET_PHONES, phone, "Sotuv narxi ($)")
                    - cost
                    - _amount(
                        config.SHEET_PHONES, phone, "Xodim KPI ($)", optional=True
                    )
                )
                recorded = _amount(
                    config.SHEET_PHONES, phone, "Sof foyda ($)", signed=True
                )
                if recorded != expected:
                    report["differences"].append(
                        {
                            "sheet": config.SHEET_PHONES,
                            "row": phone.get("_row_index"),
                            "column": "Sof foyda ($)",
                            "recorded": recorded,
                            "ledger": expected,
                            "difference": recorded - expected,
                        }
                    )
        except StorageReadError as exc:
            report["errors"].append({"message": str(exc)})
    report["ready"] = not report["differences"] and not report["errors"]
    return report
