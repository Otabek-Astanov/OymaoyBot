from uuid import uuid4

import pytest

from services.errors import SchemaError
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


def test_purchase_uses_existing_reordered_columns(storage):
    service, sheet = storage
    ws = sheet.sheets["Telefonlar"]
    ws.values[0].reverse()
    operation_id = str(uuid4())
    service.add_phone(
        {"imei": "000042", "buy_price": "100"}, operation_id=operation_id, actor_id=1
    )
    phone = service.get_phone_by_id(operation_id, fresh=True)
    assert phone["IMEI"] == "000042"
    assert phone["Harid narxi ($)"] == 100


def test_missing_header_prevents_write_without_mutating_schema(storage):
    service, sheet = storage
    sheet.sheets["Telefonlar"].values[0].remove("IMEI")
    with pytest.raises(SchemaError):
        service.add_phone(
            {"imei": "000042", "buy_price": "100"},
            operation_id=str(uuid4()),
            actor_id=1,
        )
    assert not sheet.calls
    assert "IMEI" not in sheet.sheets["Telefonlar"].values[0]


def test_staff_update_keeps_blank_physical_rows_and_reordered_headers(storage):
    service, sheet = storage
    ws = sheet.sheets["Xodimlar"]
    ws.values.append([])
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
    ws.values = [list(reversed(row)) if row else [] for row in ws.values]
    service.pay_staff_kpi(2, "10", operation_id=str(uuid4()), actor_id=1)
    staff = next(
        row
        for row in service.get_staff_list(fresh=True)
        if str(row["Telegram ID"]) == "2"
    )
    assert staff["_row_index"] == 4
    assert staff["To'langan KPI ($)"] == 10
    assert staff["Qoldiq KPI ($)"] == 90
    assert ws.values[2] == []


def test_explicit_schema_preview_only_adds_identity_listing_and_ledger(storage):
    from scripts.manage_data import schema_proposal
    from tests.storage_fakes import add_phone

    service, sheet = storage
    add_phone(sheet)
    ws = sheet.sheets["Telefonlar"]
    for name in ("Elon narxi ($)", "Telefon ID"):
        column = ws.values[0].index(name)
        for row in ws.values:
            if len(row) > column:
                row.pop(column)
    del sheet.sheets["Amallar"]
    proposal = schema_proposal(service)
    assert proposal["financial_cells_changed"] == 0
    assert proposal == schema_proposal(service)
    assert {change["action"] for change in proposal["changes"]} == {
        "append_headers",
        "assign_phone_id",
        "create_sheet",
    }
    assert not sheet.calls
    for request in proposal["batch"]["requests"]:
        if request.get("updateCells", {}).get("start", {}).get("sheetId") == ws.id:
            assert request["updateCells"]["start"]["columnIndex"] >= 32


def test_schema_preview_does_not_guess_missing_financial_headers(storage):
    from scripts.manage_data import schema_proposal

    service, sheet = storage
    sheet.sheets["Telefonlar"].values[0].remove("Harid narxi ($)")
    with pytest.raises(SchemaError, match="moliyaviy"):
        schema_proposal(service)
    assert not sheet.calls
