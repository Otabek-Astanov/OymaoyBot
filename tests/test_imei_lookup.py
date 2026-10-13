from uuid import uuid4

import pytest

from services.errors import AmbiguousPhone, BusinessRuleError
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


def test_missing_full_imei_does_not_fall_back_to_last_six_digits(storage):
    service, sheet = storage
    add_phone(sheet, imei="111111000042")
    assert service.get_phone_by_imei("999999000042", fresh=True) is None


def test_suffix_collision_requires_explicit_choice(storage):
    service, sheet = storage
    add_phone(sheet, imei="111111000042")
    add_phone(sheet, phone_id="phone-2", imei="222222000042")
    with pytest.raises(AmbiguousPhone) as error:
        service.get_phone_by_imei("000042", fresh=True)
    assert {phone["Telefon ID"] for phone in error.value.matches} == {
        "phone-1",
        "phone-2",
    }
    assert service.get_phone_by_imei("000042", fresh=True, exact=True) is None


def test_repurchase_of_sold_imei_has_new_immutable_identity(storage):
    service, sheet = storage
    add_phone(sheet, imei="000042", status="Sotildi")
    operation_id = str(uuid4())
    service.add_phone(
        {"imei": "000042", "buy_price": "100"}, operation_id=operation_id, actor_id=1
    )
    assert service.get_phone_by_id(operation_id, fresh=True)["Holati"] == "Sotuvda"
    assert service.get_phone_by_id("phone-1", fresh=True)["Holati"] == "Sotildi"


def test_sold_phone_cannot_be_published_or_financially_reset(storage):
    service, sheet = storage
    add_phone(sheet, status="Sotildi")
    with pytest.raises(BusinessRuleError):
        service.update_phone(
            "phone-1", {"Elon narxi ($)": "200"}, operation_id=str(uuid4()), actor_id=1
        )
    with pytest.raises(BusinessRuleError):
        service.update_phone(
            "phone-1", {"Holati": "Sotuvda"}, operation_id=str(uuid4()), actor_id=1
        )
    assert not sheet.calls


def test_channel_post_acknowledgement_does_not_reopen_sold_phone(storage):
    service, sheet = storage
    add_phone(sheet, status="Sotildi")
    operation_id = str(uuid4())
    assert service.record_channel_post(
        "phone-1", 123, operation_id=operation_id, actor_id=1
    )
    phone = service.get_phone_by_id("phone-1", fresh=True)
    assert phone["Holati"] == "Sotildi"
    assert phone["Kanal post ID"] == 123
    service.record_channel_post("phone-1", 123, operation_id=operation_id, actor_id=1)
    assert len(sheet.calls) == 1
