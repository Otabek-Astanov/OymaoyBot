from copy import deepcopy
from uuid import uuid4

import pytest

from services.errors import (
    AccessDenied,
    OutcomeUnknown,
    StorageUnavailable,
    StorageWriteError,
)
from services.google_sheets import GoogleSheetsService
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


@pytest.mark.parametrize(
    "kind", ["purchase", "metadata", "expense", "income", "sale", "kpi"]
)
def test_disconnected_storage_never_claims_success(kind):
    service = GoogleSheetsService()
    context = dict(operation_id=str(uuid4()), actor_id=1)
    actions = {
        "purchase": lambda: service.add_phone(
            {"imei": "000042", "buy_price": "10"}, **context
        ),
        "metadata": lambda: service.update_phone(
            "phone-1", {"Karobka": "Ha"}, **context
        ),
        "expense": lambda: service.record_expense("Arenda", "10", **context),
        "income": lambda: service.record_income("Rahbariyat", "10", **context),
        "sale": lambda: service.record_sale("phone-1", {"sell_price": "10"}, **context),
        "kpi": lambda: service.pay_staff_kpi(2, "10", **context),
    }
    with pytest.raises(StorageUnavailable):
        actions[kind]()
    assert service._phones_cache is None


def test_google_rejection_leaves_all_financial_sources_unchanged(storage):
    service, sheet = storage
    add_phone(sheet)
    sheet.add_record(
        "Xodimlar",
        {
            "Telegram ID": "2",
            "F.I.Sh": "Ali",
            "Roli": "Sotuvchi",
            "Holati": "Faol",
            "Jami KPI ($)": 0,
            "To'langan KPI ($)": 0,
            "Qoldiq KPI ($)": 0,
        },
    )
    before = deepcopy({title: ws.values for title, ws in sheet.sheets.items()})

    class Rejection(Exception):
        response = type("Response", (), {"status_code": 400})()

    sheet.fail = Rejection("invalid batch")
    operation_id = str(uuid4())
    with pytest.raises(StorageWriteError):
        service.record_sale(
            "phone-1",
            {"sell_price": "150", "seller_kpi": "10", "seller_id": 2},
            operation_id=operation_id,
            actor_id=1,
        )
    assert {title: ws.values for title, ws in sheet.sheets.items()} == before
    assert service.get_operation_status(operation_id)["state"] == "rejected"


def test_permission_removed_after_flow_started_is_rechecked(storage):
    service, sheet = storage
    add_phone(sheet)
    assert service.check_member(1)[0]
    staff = sheet.sheets["Xodimlar"]
    staff.values[1][staff.values[0].index("Holati")] = "Nofaol"
    with pytest.raises(AccessDenied):
        service.record_sale(
            "phone-1", {"sell_price": "150"}, operation_id=str(uuid4()), actor_id=1
        )
    assert not sheet.calls


def test_written_cents_are_verified_and_corruption_is_not_reported_success(
    storage, monkeypatch
):
    service, sheet = storage
    original = sheet.batch_update

    def corrupt_after_commit(batch):
        response = original(batch)
        ws = sheet.sheets["Chiqimlar"]
        ws.values[-1][ws.values[0].index("Summa ($)")] = 10.49
        return response

    monkeypatch.setattr(sheet, "batch_update", corrupt_after_commit)
    operation_id = str(uuid4())
    with pytest.raises(OutcomeUnknown):
        service.record_expense("Arenda", "10.50", operation_id=operation_id, actor_id=1)
    assert service.get_operation_status(operation_id)["state"] == "unknown"
    assert len(sheet.calls) == 1
