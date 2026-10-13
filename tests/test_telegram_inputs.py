import unittest
from html import unescape

from bot_harajat.keyboards import (
    format_money_label,
    partners_inline_kb,
    staff_inline_kb as kpi_staff_kb,
)
from bot_sotuv.keyboards import partners_kb, staff_inline_kb
from utils.formatters import (
    build_buy_group_caption,
    build_purchase_summary,
    build_sotuv_phone_info,
    render_channel_template,
)


class TelegramInputTests(unittest.TestCase):
    def test_template_escapes_inserted_values_preserving_trusted_markup(self):
        rendered = render_channel_template(
            "<b>{model}</b> {color}", {"model": "<i>Unsafe</i>&", "color": "<script>"}
        )
        self.assertEqual(
            rendered, "<b>&lt;i&gt;Unsafe&lt;/i&gt;&amp;</b> &lt;script&gt;"
        )

    def test_template_values_with_backslashes_are_literal(self):
        rendered = render_channel_template(
            "{battery}% {price}$", {"battery": r"70\1", "sell_price": r"100\g<0>"}
        )
        self.assertEqual(unescape(rendered), r"70\1% 100\g<0>$")

    def test_all_phone_captions_escape_user_text(self):
        data = {
            "model": "<u>A&B</u>",
            "seller_name": "<i>Seller</i>",
            "buy_price": "100",
            "payment_type": "Naqd",
        }
        self.assertIn("&lt;u&gt;A&amp;B&lt;/u&gt;", build_buy_group_caption(data))
        self.assertIn("&lt;i&gt;Seller&lt;/i&gt;", build_purchase_summary(data))
        self.assertIn(
            "&lt;u&gt;A&amp;B&lt;/u&gt;",
            build_sotuv_phone_info({"Model": data["model"]}),
        )

    def test_staff_callbacks_contain_only_id_even_for_long_colon_names(self):
        staff = [{"Telegram ID": "123456789", "F.I.Sh": "Ў:" * 100, "Roli": "Sotuvchi"}]
        self.assertEqual(
            staff_inline_kb(staff).inline_keyboard[0][0].callback_data,
            "staff_sel:123456789",
        )
        self.assertEqual(
            kpi_staff_kb(staff).inline_keyboard[0][0].callback_data, "staff:123456789"
        )

    def test_keyboard_money_decimal_comma_is_not_treated_as_thousands(self):
        self.assertEqual(format_money_label("10,50"), "$10.50")

    def test_keyboard_money_invalid_cell_is_not_presented_as_a_balance(self):
        with self.assertRaises(ValueError):
            format_money_label("#REF!")

    def test_partner_callbacks_are_short_and_do_not_embed_names(self):
        name = "Ҳамкор: " * 30
        partners = [{"Hamkor nomi": name}]
        for keyboard in (partners_inline_kb(partners), partners_kb(partners)):
            for row in keyboard.inline_keyboard:
                value = row[0].callback_data
                self.assertLessEqual(len(value.encode("utf-8")), 64)
                self.assertNotIn(name, value)


if __name__ == "__main__":
    unittest.main()
