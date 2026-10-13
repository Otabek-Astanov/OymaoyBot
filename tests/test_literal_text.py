from uuid import uuid4

from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


def test_names_imei_and_phone_are_written_as_literal_text(storage):
    service, sheet = storage
    operation_id = str(uuid4())
    service.add_phone(
        {
            "imei": "000042",
            "buy_price": "10,50",
            "seller_name": "=1+1",
            "seller_phone": "+99800123",
        },
        operation_id=operation_id,
        actor_id=1,
    )
    row = service.get_phone_by_id(operation_id, fresh=True)
    assert row["IMEI"] == "000042"
    assert row["Telefon egasi"] == "=1+1"
    assert row["Telefon egasi telefoni"] == "+99800123"
    request = sheet.calls[0]["requests"][0]["appendCells"]
    headers = sheet.sheets["Telefonlar"].values[0]
    cells = request["rows"][0]["values"]
    assert cells[headers.index("IMEI")]["userEnteredValue"] == {"stringValue": "000042"}
    assert cells[headers.index("Telefon egasi")]["userEnteredValue"] == {
        "stringValue": "=1+1"
    }
    assert cells[headers.index("Harid narxi ($)")]["userEnteredValue"] == {
        "numberValue": 10.5
    }
