from uuid import uuid4

import pytest

from services.errors import BusinessRuleError
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


@pytest.mark.parametrize("amount", ["101", "200"])
def test_purchase_debt_overpayment_never_commits(storage, amount):
    service, sheet = storage
    add_phone(sheet, debt=100)
    with pytest.raises(BusinessRuleError):
        service.pay_phone_debt("phone-1", amount, operation_id=str(uuid4()), actor_id=1)
    assert not sheet.calls


def test_initial_payment_cannot_exceed_sale_price(storage):
    service, sheet = storage
    add_phone(sheet)
    with pytest.raises(BusinessRuleError):
        service.record_sale(
            "phone-1",
            {"sell_price": "100", "initial_payment": "200", "payment_type": "Qarz"},
            operation_id=str(uuid4()),
            actor_id=1,
        )
    assert not sheet.calls


def test_staff_and_partner_overpayments_are_rejected(storage):
    service, sheet = storage
    sheet.add_record(
        "Xodimlar",
        {
            "Telegram ID": "2",
            "F.I.Sh": "Ali",
            "Roli": "Sotuvchi",
            "Holati": "Faol",
            "Jami KPI ($)": 100,
            "To'langan KPI ($)": 90,
            "Qoldiq KPI ($)": 10,
        },
    )
    sheet.add_record(
        "Hamkorlar", {"Hamkor nomi": "Hamkor", "Hozirgi qarzdorlik ($)": 10}
    )
    for function, ref in [
        (service.pay_staff_kpi, 2),
        (service.reduce_partner_debt, "Hamkor"),
    ]:
        with pytest.raises(BusinessRuleError):
            function(ref, "11", operation_id=str(uuid4()), actor_id=1)
    assert not sheet.calls


def test_staff_payment_uses_id_not_name(storage):
    service, sheet = storage
    sheet.add_record(
        "Xodimlar",
        {
            "Telegram ID": "2",
            "F.I.Sh": "Ali",
            "Roli": "Sotuvchi",
            "Holati": "Faol",
            "Jami KPI ($)": 100,
            "To'langan KPI ($)": 0,
            "Qoldiq KPI ($)": 100,
        },
    )
    with pytest.raises(BusinessRuleError):
        service.pay_staff_kpi("Ali", "10", operation_id=str(uuid4()), actor_id=1)
    assert not sheet.calls


def test_partner_payment_never_replaces_unreconciled_historical_balance(storage):
    service, sheet = storage
    sheet.add_record(
        "Hamkorlar", {"Hamkor nomi": "Hamkor", "Hozirgi qarzdorlik ($)": 100}
    )
    with pytest.raises(BusinessRuleError, match="yarashtir"):
        service.reduce_partner_debt(
            "Hamkor", "10", operation_id=str(uuid4()), actor_id=1
        )
    assert not sheet.calls
    assert service.get_partners(force_refresh=True)[0]["Hozirgi qarzdorlik ($)"] == 100
