import unittest


class SheetRowsTests(unittest.TestCase):
    def test_blank_rows_keep_physical_index(self):
        from services.sheet_schema import records_with_rows

        rows = records_with_rows([["Telegram ID", "F.I.Sh"], [], ["12", "Ali"]])
        self.assertEqual(rows[0]["_row_index"], 3)

    def test_duplicate_headers_fail_closed(self):
        from services.errors import SchemaError
        from services.sheet_schema import records_with_rows

        with self.assertRaises(SchemaError):
            records_with_rows([["IMEI", "IMEI"], ["12", "34"]])
