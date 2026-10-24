from uuid import uuid4

import pytest

import config
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


def test_explicit_schema_preview_only_adds_identity_and_listing(storage):
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
    # The operation ledger stays in the local SQLite journal, not in Sheets.
    assert {change["action"] for change in proposal["changes"]} == {
        "insert_headers",
        "assign_phone_id",
    }
    assert not sheet.calls
    expected = config.DEFAULT_HEADERS["Telefonlar"]
    inserted = next(
        c["headers"] for c in proposal["changes"] if c["action"] == "insert_headers"
    )
    # Each new column lands where DEFAULT_HEADERS puts it, not at the far right.
    assert inserted == [
        {"header": "Elon narxi ($)", "column": expected.index("Elon narxi ($)")},
        {"header": "Telefon ID", "column": expected.index("Telefon ID")},
    ]
    id_writes = [
        r["updateCells"]["start"]["columnIndex"]
        for r in proposal["batch"]["requests"]
        if r.get("updateCells", {}).get("start", {}).get("rowIndex", 0) > 0
    ]
    assert id_writes and set(id_writes) == {expected.index("Telefon ID")}


def test_schema_preview_does_not_guess_missing_financial_headers(storage):
    from scripts.manage_data import schema_proposal

    service, sheet = storage
    sheet.sheets["Telefonlar"].values[0].remove("Harid narxi ($)")
    with pytest.raises(SchemaError, match="moliyaviy"):
        schema_proposal(service)
    assert not sheet.calls


def test_missing_headers_follow_their_default_neighbours():
    from scripts.manage_data import missing_header_positions

    expected = ["A", "B", "C", "D"]
    layout, placed = missing_header_positions(["A", "C", "X"], expected, ["B", "D"])
    assert layout == ["A", "B", "C", "D", "X"]
    assert placed == [("B", 1), ("D", 3)]
    layout, placed = missing_header_positions(["C"], expected, ["A"])
    assert placed == [("A", 0)] and layout == ["A", "C"]


def test_inserting_a_column_before_phone_ids_keeps_existing_ids(storage):
    from scripts.manage_data import schema_proposal
    from tests.storage_fakes import add_phone

    service, sheet = storage
    ws = sheet.sheets["Telefonlar"]
    add_phone(sheet, phone_id="phone-1", imei="111111")
    add_phone(sheet, phone_id="", imei="222222")
    column = ws.values[0].index("Elon narxi ($)")
    for row in ws.values:
        row.pop(column)
    proposal = schema_proposal(service)
    assigned = [c for c in proposal["changes"] if c["action"] == "assign_phone_id"]
    # Only the row without an ID gets one, written at the shifted ID column.
    assert [c["row"] for c in assigned] == [3]
    writes = [
        r["updateCells"]["start"]
        for r in proposal["batch"]["requests"]
        if r.get("updateCells", {}).get("start", {}).get("rowIndex", 0) > 0
    ]
    assert writes == [
        {
            "sheetId": ws.id,
            "rowIndex": 2,
            "columnIndex": config.DEFAULT_HEADERS["Telefonlar"].index("Telefon ID"),
        }
    ]


def test_inserted_columns_do_not_inherit_neighbour_formatting(storage):
    from scripts.manage_data import schema_proposal

    service, sheet = storage
    ws = sheet.sheets["Telefonlar"]
    column = ws.values[0].index("Telefon ID")
    for row in ws.values:
        row.pop(column)
    proposal = schema_proposal(service)
    inserts = [r["insertDimension"] for r in proposal["batch"]["requests"] if "insertDimension" in r]
    assert inserts and all(i["inheritFromBefore"] is False for i in inserts)
