def test_investor_has_balance_in_unified_bot():
    from bot_common.navigation import menu_for

    menu = menu_for("Investor", {"harid", "sotuv", "harajat"})
    assert [[b.text for b in row] for row in menu.keyboard] == [["💰 Balance"]]


def test_accountant_has_income_expense_and_balance():
    from bot_common.navigation import menu_for

    menu = menu_for("Hisobchi", {"harajat"})
    buttons = [b.text for row in menu.keyboard for b in row]
    assert set(buttons) == {"📈 Kirim", "📉 Chiqim", "💰 Balance"}


def test_seller_has_purchase_and_sale():
    from bot_common.navigation import menu_for

    menu = menu_for("Sotuvchi", {"harid", "sotuv", "harajat"})
    buttons = [b.text for row in menu.keyboard for b in row]
    assert "📥 Harid qilish" in buttons
    assert "📱 Yangi sotuvni rasmiylashtirish" in buttons
    assert "📉 Chiqim" not in buttons


def _buttons(menu):
    return [b.text for row in getattr(menu, "keyboard", []) for b in row]


def test_balance_lives_only_in_the_finance_bot():
    from bot_common.navigation import menu_for
    from bot_harid.keyboards import main_menu_kb

    for role in ("Admin", "Hisobchi", "Rahbariyat", "Investor"):
        assert "💰 Balance" not in _buttons(menu_for(role, {"harid"}))
        assert "💰 Balance" not in _buttons(menu_for(role, {"sotuv"}))
        assert "💰 Balance" in _buttons(menu_for(role, {"harajat"}))
    assert "💰 Balance" not in _buttons(main_menu_kb())
    assert _buttons(menu_for("Admin", {"harid"})) == [
        "📥 Harid qilish",
        "📢 Telegram kanalga e'lon berish",
        "📦 Karobka",
    ]


def test_investor_in_a_bot_without_finance_gets_no_menu():
    from aiogram.types import ReplyKeyboardRemove
    from bot_common.navigation import menu_for

    assert isinstance(menu_for("Investor", {"harid", "sotuv"}), ReplyKeyboardRemove)
