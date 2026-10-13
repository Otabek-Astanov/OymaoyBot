from decimal import Decimal
import unittest


class FinancialReportTests(unittest.TestCase):
    def example(self):
        return {
            "Telefonlar": [
                {
                    "_row_index": 2,
                    "Harid narxi ($)": 100,
                    "Jami tannarx ($)": 120,
                    "Remont xarajati ($)": 20,
                    "Harid to'lov turi": "Naqd",
                    "Harid qarz summasi ($)": 0,
                    "Holati": "Sotildi",
                    "Sotuv narxi ($)": 150,
                    "Sotuv to'lov turi": "Naqd",
                    "Xodim KPI ($)": 10,
                    "Sof foyda ($)": 20,
                }
            ],
            "Kirimlar": [
                {"_row_index": 2, "Kirim turi": "Rahbariyat", "Summa ($)": 1000}
            ],
            "Chiqimlar": [
                {"_row_index": 2, "Chiqim turi": "Remont", "Summa ($)": 20},
                {"_row_index": 3, "Chiqim turi": "KPI", "Summa ($)": 10},
                {"_row_index": 4, "Chiqim turi": "Arenda", "Summa ($)": 5},
            ],
            "Hamkorlar": [],
            "Xodimlar": [
                {
                    "_row_index": 2,
                    "Jami KPI ($)": 10,
                    "To'langan KPI ($)": 10,
                    "Qoldiq KPI ($)": 0,
                }
            ],
        }

    def test_margin_profit_and_cash_are_distinct(self):
        from services.financial_reports import financial_summary

        result = financial_summary(self.example())
        self.assertEqual(result["sales_margin"], Decimal("20.00"))
        self.assertEqual(result["operating_profit"], Decimal("15.00"))
        self.assertEqual(result["kassa_balance"], Decimal("1015.00"))
        self.assertTrue(result["generated_at"])

    def test_corrupt_formula_is_not_zero(self):
        from services.errors import StorageReadError
        from services.financial_reports import financial_summary

        example = self.example()
        example["Telefonlar"][0]["Harid narxi ($)"] = "#REF!"
        with self.assertRaisesRegex(StorageReadError, "Telefonlar:2"):
            financial_summary(example)

    def test_missing_source_prevents_partial_report(self):
        from services.errors import StorageReadError
        from services.financial_reports import financial_summary

        example = self.example()
        del example["Kirimlar"]
        with self.assertRaises(StorageReadError):
            financial_summary(example)

    def test_partner_total_must_reconcile_to_phone_and_income_sources(self):
        from services.errors import StorageReadError
        from services.financial_reports import financial_summary

        example = self.example()
        example["Hamkorlar"] = [
            {"_row_index": 2, "Hamkor nomi": "Hamkor", "Hozirgi qarzdorlik ($)": 999}
        ]
        with self.assertRaisesRegex(StorageReadError, "Hamkorlar:2"):
            financial_summary(example)
