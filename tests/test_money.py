from decimal import Decimal
import unittest


class MoneyTests(unittest.TestCase):
    def test_supported_amounts_are_exact(self):
        from utils.money import parse_money

        for text, expected in [
            ("10", "10.00"),
            ("10$", "10.00"),
            ("$10", "10.00"),
            ("10.50", "10.50"),
            ("10,50", "10.50"),
            ("1 000,50", "1000.50"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(parse_money(text), Decimal(expected))

    def test_invalid_amounts_are_not_silently_changed(self):
        from utils.money import InvalidAmount, parse_money

        for text in [
            "-10",
            "1..2",
            "abc",
            "NaN",
            "Infinity",
            "1,000.50",
            "10.123",
            "9" * 30,
            "0",
            "$10$",
            "١٠",
        ]:
            with self.subTest(text=text), self.assertRaises(InvalidAmount):
                parse_money(text)

    def test_zero_is_only_explicitly_allowed(self):
        from utils.money import parse_money

        self.assertEqual(parse_money("0", allow_zero=True), Decimal("0.00"))
