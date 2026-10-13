from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from tests.storage_fakes import FakeSpreadsheet, add_phone


class OperationTests(unittest.TestCase):
    def setUp(self):
        from services.google_sheets import GoogleSheetsService

        self.directory = TemporaryDirectory()
        self.spreadsheet = FakeSpreadsheet()
        self.service = GoogleSheetsService(
            spreadsheet=self.spreadsheet,
            journal_path=Path(self.directory.name) / "journal.sqlite",
        )
        self.service.initialize()

    def tearDown(self):
        if hasattr(self, "service"):
            self.service.close()
        self.directory.cleanup()

    def test_sale_is_atomic_and_uses_fresh_cost(self):
        add_phone(self.spreadsheet, cost=120)
        self.spreadsheet.add_record(
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
        result = self.service.record_sale(
            "phone-1",
            {
                "sell_price": "150",
                "payment_type": "Naqd",
                "seller_kpi": "10",
                "sellers": [{"id": 2, "kpi": "10"}],
            },
            {"Jami tannarx ($)": 100},
            operation_id=str(uuid4()),
            actor_id=1,
        )
        self.assertEqual(result, (True, Decimal("20.00")))
        self.assertEqual(len(self.spreadsheet.calls), 1)
        self.assertEqual(
            self.service.get_phone_by_id("phone-1", fresh=True)["Holati"], "Sotildi"
        )

    def test_second_sale_is_rejected_without_second_batch(self):
        from services.errors import BusinessRuleError

        add_phone(self.spreadsheet)
        self.service.record_sale(
            "phone-1",
            {"sell_price": "150", "payment_type": "Naqd"},
            operation_id=str(uuid4()),
            actor_id=1,
        )
        with self.assertRaises(BusinessRuleError):
            self.service.record_sale(
                "phone-1",
                {"sell_price": "150", "payment_type": "Naqd"},
                operation_id=str(uuid4()),
                actor_id=1,
            )
        self.assertEqual(len(self.spreadsheet.calls), 1)

    def test_zero_kpi_does_not_require_bootstrap_admin_staff_row(self):
        import config
        from unittest.mock import patch

        add_phone(self.spreadsheet)
        with patch.object(config, "ADMIN_IDS", [3]):
            result = self.service.record_sale(
                "phone-1",
                {
                    "sell_price": "150",
                    "seller_kpi": "0",
                    "sellers": [{"id": 3, "kpi": "0"}],
                },
                operation_id=str(uuid4()),
                actor_id=3,
            )
        self.assertTrue(result[0])
        self.assertEqual(len(self.spreadsheet.calls), 1)

    def test_repair_never_silently_recalculates_unreconciled_historical_cost(self):
        from services.errors import BusinessRuleError

        add_phone(self.spreadsheet, cost=100)
        ws = self.spreadsheet.sheets["Telefonlar"]
        ws.values[1][ws.values[0].index("Remont xarajati ($)")] = 20
        ws.values[1][ws.values[0].index("Jami tannarx ($)")] = 200
        with self.assertRaisesRegex(BusinessRuleError, "yarashtir"):
            self.service.record_repair(
                "phone-1", "10", "Admin", operation_id=str(uuid4()), actor_id=1
            )
        self.assertFalse(self.spreadsheet.calls)
