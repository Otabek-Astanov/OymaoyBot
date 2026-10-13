from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


class State:
    def __init__(self, **data):
        self.data = data
        self.current = "confirm"
        self.cleared = False

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **data):
        self.data.update(data)

    async def set_state(self, state):
        self.current = str(state)

    async def get_state(self):
        return self.current

    async def clear(self):
        self.cleared = True
        self.data.clear()


def message(text="10"):
    loading = SimpleNamespace(delete=AsyncMock())
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=1, full_name="A & B"),
        answer=AsyncMock(return_value=loading),
        answer_photo=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_expense_failure_preserves_input(monkeypatch):
    from bot_harajat.handlers import harajat_flow as flow

    state = State(category="Arenda", operation_id="old-operation")
    msg = message()
    monkeypatch.setattr(flow.sheets_service, "record_expense", Mock(return_value=False))
    await flow.simple_amount_entered(msg, state)
    assert not state.cleared
    assert state.data["operation_id"] == "old-operation"
    assert not any("saqlandi!" in str(c) for c in msg.answer.call_args_list)


@pytest.mark.asyncio
async def test_remont_uses_one_atomic_operation(monkeypatch):
    from bot_harajat.handlers import harajat_flow as flow

    state = State(
        phone_id="phone-1",
        imei="000042",
        operation_id="repair-1",
        phone_data={"Harid narxi ($)": "100", "Remont xarajati ($)": "5"},
    )
    msg = message("10,50")
    repair = Mock(return_value=(True, "115.50"))
    monkeypatch.setattr(flow.sheets_service, "record_repair", repair, raising=False)
    monkeypatch.setattr(
        flow.sheets_service,
        "record_expense",
        Mock(side_effect=AssertionError("split write")),
    )
    monkeypatch.setattr(
        flow.sheets_service,
        "update_phone",
        Mock(side_effect=AssertionError("split write")),
    )
    await flow.remont_amount_entered(msg, state)
    repair.assert_called_once()
    assert str(repair.call_args.args[1]) == "10.50"
    assert state.cleared


@pytest.mark.asyncio
async def test_sale_failure_sends_no_notification(monkeypatch):
    from bot_sotuv.handlers import sotuv_flow as flow

    state = State(
        operation_id="sale-1",
        phone_id="phone-1",
        row_index=2,
        sell_price="150",
        seller_name="Seller",
        seller_id=1,
        sellers=[{"id": 1, "name": "Seller", "kpi": "0"}],
    )
    msg = message("✅ Ha")
    bot = SimpleNamespace(id=123)
    monkeypatch.setattr(
        flow.sheets_service, "get_staff_name_by_tg_id", Mock(return_value="Seller")
    )
    monkeypatch.setattr(
        flow.sheets_service, "record_sale", Mock(return_value=(False, 0))
    )
    poster = SimpleNamespace(
        post_to_sell_group=AsyncMock(), mark_as_sold_on_channel=AsyncMock()
    )
    monkeypatch.setattr(flow, "poster_service", poster, raising=False)
    await flow.confirm_sale_handler(msg, state, bot)
    poster.post_to_sell_group.assert_not_called()
    poster.mark_as_sold_on_channel.assert_not_called()
    assert not state.cleared


@pytest.mark.asyncio
async def test_overpayment_does_not_advance_sale(monkeypatch):
    from bot_sotuv.handlers import sotuv_flow as flow

    state = State(sell_price="100.00")
    msg = message("200")
    await flow.initial_payment_entered(msg, state)
    assert "initial_payment" not in state.data
    assert state.current == "confirm"


@pytest.mark.asyncio
async def test_linked_store_income_is_blocked(monkeypatch):
    from bot_harajat.handlers import harajat_flow as flow

    state = State(imei="123456789012345", operation_id="receipt-1")
    msg = message("10")
    write = Mock(return_value=(True, 0))
    monkeypatch.setattr(flow.sheets_service, "close_store_phone_debt", write)
    await flow.dokon_amount_entered(msg, state)
    write.assert_not_called()
    assert not state.cleared
