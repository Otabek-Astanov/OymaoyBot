from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from services.errors import BusinessRuleError
from services.google_sheets import GoogleSheetsService
from tests.storage_fakes import FakeSpreadsheet, add_phone


@pytest.fixture
def storage():
    with TemporaryDirectory() as directory:
        sheet = FakeSpreadsheet()
        service = GoogleSheetsService(
            spreadsheet=sheet, journal_path=Path(directory) / "operations.sqlite"
        )
        service.initialize()
        yield service, sheet
        service.close()


@pytest.mark.parametrize(
    "kind",
    [
        "purchase",
        "sale",
        "expense",
        "income",
        "repair",
        "kpi_payment",
        "phone_debt_payment",
        "partner_payment",
    ],
)
def test_every_financial_operation_replays_without_second_batch(storage, kind):
    service, sheet = storage
    operation_id = str(uuid4())
    context = dict(operation_id=operation_id, actor_id=1)
    add_phone(sheet, debt=100)
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
    sheet.add_record(
        "Hamkorlar", {"Hamkor nomi": "Hamkor", "Hozirgi qarzdorlik ($)": 100}
    )
    if kind == "partner_payment":
        ws = sheet.sheets["Telefonlar"]
        ws.values[1][ws.values[0].index("Hamkor nomi")] = "Hamkor"
        ws.values[1][ws.values[0].index("Hamkor qarzi ($)")] = 100
        ws.values[1][ws.values[0].index("Holati")] = "Sotildi"
        ws.values[1][ws.values[0].index("Sotuv to'lov turi")] = "Qarz"
    methods = {
        "purchase": lambda: service.add_phone(
            {"imei": "000043", "buy_price": "100", "payment_type": "Naqd"}, **context
        ),
        "sale": lambda: service.record_sale(
            "phone-1", {"sell_price": "150", "payment_type": "Naqd"}, **context
        ),
        "expense": lambda: service.record_expense("Arenda", "10", **context),
        "income": lambda: service.record_income("Rahbariyat", "10", **context),
        "repair": lambda: service.record_repair("phone-1", "10", "Admin", **context),
        "kpi_payment": lambda: service.pay_staff_kpi(2, "10", **context),
        "phone_debt_payment": lambda: service.pay_phone_debt(
            "phone-1", "10", **context
        ),
        "partner_payment": lambda: service.reduce_partner_debt(
            "Hamkor", "10", **context
        ),
    }
    first = methods[kind]()
    second = methods[kind]()
    assert first == second
    assert len(sheet.calls) == 1
    assert len(sheet.records("Amallar")) == 1


def test_changed_payload_same_uuid_is_rejected(storage):
    service, sheet = storage
    operation_id = str(uuid4())
    service.record_expense("Arenda", "10", operation_id=operation_id, actor_id=1)
    with pytest.raises(BusinessRuleError, match="boshqa ma'lumot"):
        service.record_expense("Arenda", "20", operation_id=operation_id, actor_id=1)
    assert len(sheet.calls) == 1


def test_duplicate_sale_does_not_double_staff_kpi(storage):
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
    sale = {
        "sell_price": "150",
        "seller_kpi": "10",
        "seller_id": 2,
        "payment_type": "Naqd",
    }
    operation_id = str(uuid4())
    assert service.record_sale("phone-1", sale, operation_id=operation_id, actor_id=1)[
        1
    ] == Decimal("40.00")
    service.record_sale("phone-1", sale, operation_id=operation_id, actor_id=1)
    staff = next(
        row
        for row in service.get_staff_list(fresh=True)
        if str(row["Telegram ID"]) == "2"
    )
    assert staff["Jami KPI ($)"] == 10
