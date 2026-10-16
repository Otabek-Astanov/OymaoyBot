from uuid import uuid4

import pytest

from services.errors import OutcomeUnknown, SchemaError, StorageReadError
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


def _drop_phone_id_column(service, sheet):
    headers = sheet.sheets["Telefonlar"].values[0]
    headers.pop(headers.index("Telefon ID"))
    service.reload_cache()


def _purchase(service, imei, operation_id):
    return service.add_phone(
        {
            "imei": imei,
            "brand": "iPhone",
            "version": "14",
            "type": "Pro",
            "buy_price": "700",
            "payment_type": "Naqd",
            "debt_amount": "0",
        },
        operation_id=operation_id,
        actor_id=1,
    )


def test_failed_update_does_not_change_cached_phone(storage):
    service, sheet = storage
    add_phone(sheet)
    cached = service.get_phone_by_id("phone-1")
    sheet.fail = TimeoutError("request outcome unknown")
    with pytest.raises(OutcomeUnknown):
        service.update_phone(
            "phone-1", {"Karobka": "Ha"}, operation_id=str(uuid4()), actor_id=1
        )
    assert service.get_phone_by_id("phone-1") == cached
    assert service.get_phone_by_id("phone-1").get("Karobka") != "Ha"


def test_failed_fresh_read_never_falls_back_to_stale_cache(storage):
    service, sheet = storage
    add_phone(sheet)
    service.get_phone_by_id("phone-1")
    sheet.read_failure = "Telefonlar"
    with pytest.raises(StorageReadError):
        service.get_phone_by_id("phone-1", fresh=True)


def test_purchase_requires_telefon_id_column(storage):
    # Without stable IDs a re-purchased IMEI cannot be told apart; prepare adds them.
    service, sheet = storage
    _drop_phone_id_column(service, sheet)
    with pytest.raises(SchemaError, match="manage_data.py prepare"):
        _purchase(service, "999888777666", str(uuid4()))
    assert not sheet.calls


def test_lookup_phone_by_operation_id(storage):
    service, sheet = storage
    op_id = str(uuid4())
    service.add_phone(
        {
            "imei": "111222333444",
            "brand": "iPhone",
            "version": "14",
            "type": "Pro Max",
            "buy_price": "700",
            "payment_type": "Naqd",
            "debt_amount": "0",
            "seller_name": "Test Seller",
            "buyer_name": "Test Buyer",
        },
        operation_id=op_id,
        actor_id=1,
    )
    phone = service.get_phone_by_id(op_id)
    assert phone is not None
    assert phone["IMEI"] == "111222333444"

    phone2 = service._phone(op_id)
    assert phone2["IMEI"] == "111222333444"


def test_verify_rejects_duplicate_unsold_imei_instead_of_guessing(storage):
    # A manual copy of the appended row must not be "confirmed" as the bot's write.
    service, sheet = storage
    op_id = str(uuid4())
    _purchase(service, "123123123123", op_id)
    batch = service.journal.get(op_id)["batch"]
    phones = sheet.sheets["Telefonlar"].values
    phones.append(list(phones[-1]))
    service.reload_cache()
    with pytest.raises(StorageReadError):
        service._verify_batch(batch)


def test_repurchase_of_sold_imei_gets_its_own_phone_id(storage):
    service, sheet = storage
    _purchase(service, "321321321321", str(uuid4()))
    phones = sheet.sheets["Telefonlar"].values
    phones[-1][phones[0].index("Holati")] = "Sotildi"
    service.reload_cache()
    second = str(uuid4())
    assert _purchase(service, "321321321321", second) is True
    assert service._phone(second)["Holati"] == "Sotuvda"


def test_write_uses_fresh_headers_after_column_is_inserted(storage):
    # Status checks may cache headers, but a write must not use stale column indexes.
    service, sheet = storage
    _purchase(service, "444555666777", str(uuid4()))
    for row in sheet.sheets["Telefonlar"].values:
        row.insert(0, "Izoh" if row is sheet.sheets["Telefonlar"].values[0] else "")
    service.reload_cache()
    assert _purchase(service, "888999000111", str(uuid4())) is True
    latest = sheet.records("Telefonlar")[-1]
    assert latest["IMEI"] == "888999000111"
    assert latest["Holati"] == "Sotuvda"


def test_drive_photos_are_written_as_named_links_like_old_rows(storage):
    service, sheet = storage
    link = "https://drive.google.com/file/d/AbC_12-x/view?usp=drivesdk"
    op_id = str(uuid4())
    service.add_phone(
        {
            "imei": "333444",
            "buy_price": "100",
            "payment_type": "Naqd",
            "imei_photo_url": link,
        },
        operation_id=op_id,
        actor_id=1,
    )
    service.update_phone(
        op_id, {"Telefon rasmi": link}, operation_id=str(uuid4()), actor_id=1
    )
    row = sheet.records("Telefonlar")[-1]
    assert row["IMEI rasmi"] == f'=HYPERLINK("{link}","📷 imei_333444.jpg")'
    assert row["Telefon rasmi"] == f'=HYPERLINK("{link}","📷 phone_333444.jpg")'


def test_non_drive_photo_text_is_never_turned_into_a_formula(storage):
    service, sheet = storage
    service.add_phone(
        {
            "imei": "555444",
            "buy_price": "100",
            "payment_type": "Naqd",
            "imei_photo_url": '=IMPORTXML("https://evil.example","//a")',
        },
        operation_id=str(uuid4()),
        actor_id=1,
    )
    append = sheet.calls[-1]["requests"][0]["appendCells"]["rows"][0]["values"]
    headers = sheet.sheets["Telefonlar"].values[0]
    cell = append[headers.index("IMEI rasmi")]["userEnteredValue"]
    assert "stringValue" in cell and "formulaValue" not in cell


def test_writes_do_not_relist_worksheets_once_readiness_listed_them(storage):
    service, sheet = storage
    del sheet.sheets["Amallar"]  # the ledger sheet is optional and absent here
    service.readiness()
    calls = []
    original = sheet.worksheets
    sheet.worksheets = lambda: calls.append(1) or original()
    _purchase(service, "909090", str(uuid4()))
    assert calls == []
