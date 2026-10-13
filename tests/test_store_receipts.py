from uuid import uuid4

import pytest

from services.errors import BusinessRuleError
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


def test_ambiguous_store_income_cannot_reduce_purchase_debt(storage):
    service, sheet = storage
    add_phone(sheet, debt=100)
    with pytest.raises(BusinessRuleError):
        service.close_store_phone_debt(
            "phone-1", "10", operation_id=str(uuid4()), actor_id=1
        )
    assert (
        service.get_phone_by_id("phone-1", fresh=True)["Harid qarz summasi ($)"] == 100
    )
    assert not sheet.calls


def test_unlinked_store_cash_receipt_does_not_change_any_phone_debt(storage):
    service, sheet = storage
    add_phone(sheet, debt=100)
    service.record_income(
        "Dokondan", "10", source="Umumiy kirim", operation_id=str(uuid4()), actor_id=1
    )
    assert (
        service.get_phone_by_id("phone-1", fresh=True)["Harid qarz summasi ($)"] == 100
    )
    assert sheet.records("Kirimlar")[0]["Summa ($)"] == 10
