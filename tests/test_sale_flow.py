from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from test_handler_contracts import State, message


@pytest.mark.asyncio
async def test_sold_phone_card_is_sent_as_html_and_asks_again(monkeypatch):
    from bot_sotuv.handlers import sotuv_flow as flow

    phone = {
        "Holati": "Sotildi",
        "Model": "iPhone <13>",
        "IMEI": "345678",
        "Xaridor ismi": "Jamshid",
        "Sotuv narxi ($)": "640",
    }
    monkeypatch.setattr(flow.sheets_service, "get_phone_by_imei", Mock(return_value=phone))
    state = State()
    msg = message("345678")
    await flow.imei_entered(msg, state)
    text = msg.answer.call_args.args[0]
    assert text.startswith("⚠️ <b>Bu qurilma allaqachon sotilgan.</b>")
    assert "iPhone &lt;13&gt;" in text and "640$" in text
    assert state.current == "confirm"  # unchanged: the next IMEI is still expected


def test_sale_summary_shows_partner_lines_only_for_debt_sales():
    from utils.formatters import build_sale_summary

    data = {
        "model": "iPhone 13",
        "imei": "345678",
        "sell_price": "650",
        "buyer_name": "<Ali>",
        "payment_type": "Naqd",
        "seller_kpi": "10",
        "sellers": [{"name": "Bek", "kpi": "5"}, {"name": "Aziz", "kpi": "5"}],
    }
    cash = build_sale_summary(data)
    assert "Hamkor" not in cash
    assert "&lt;Ali&gt;" in cash
    assert "Bek: 5$" in cash and "Aziz: 5$" in cash
    debt = build_sale_summary(
        {**data, "payment_type": "Qarz", "partner_name": "Uzum", "partner_debt": "550"}
    )
    assert "🤝 Hamkor: <b>Uzum</b>" in debt and "550$" in debt


@pytest.mark.asyncio
async def test_payment_choice_keeps_question_and_asks_partner_below(monkeypatch):
    from bot_sotuv.handlers import sotuv_flow as flow

    monkeypatch.setattr(flow.sheets_service, "get_partners", Mock(return_value=[]))
    prompt = message()
    prompt.html_text = "💳 <b>To'lov turini tanlang:</b>"
    prompt.reply_markup = flow.payment_type_kb()
    prompt.edit_text = AsyncMock()
    call = SimpleNamespace(data="pay:Qarz", answer=AsyncMock(), message=prompt)
    state = State()
    await flow.payment_type_callback(call, state)
    prompt.edit_text.assert_awaited_once()
    assert "✅ <b>💳 Qarzga</b>" in prompt.edit_text.call_args.args[0]
    assert "Hamkorni tanlang" in prompt.answer.call_args.args[0]


def _sale(monkeypatch, *, post_id, delivery):
    from bot_sotuv.handlers import sotuv_flow as flow
    import config

    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(config, "GROUP_SOTUV_ID", "")
    monkeypatch.setattr(
        flow.sheets_service, "record_sale", Mock(return_value=(True, Decimal("20")))
    )
    monkeypatch.setattr(flow, "wait_for_delivery", AsyncMock(return_value=delivery))
    state = State(
        phone_id="phone-1",
        operation_id=str(uuid4()),
        channel_post_id=post_id,
        sell_price="150",
    )
    return flow, state, message("✅ Ha")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("post_id", "delivery", "expected", "absent"),
    [
        ("7", {"state": "sent"}, "«Sotildi» deb belgilandi", None),
        ("7", {"state": "unknown"}, "belgilab bo'lmadi", None),
        ("", None, "Sotuv saqlandi", "Kanaldagi"),
    ],
)
async def test_sale_reports_saving_and_channel_outcome(
    monkeypatch, post_id, delivery, expected, absent
):
    flow, state, msg = _sale(monkeypatch, post_id=post_id, delivery=delivery)
    await flow.confirm_sale_handler(msg, state, SimpleNamespace(id=123))
    texts = [c.args[0] for c in msg.answer.call_args_list]
    assert "saqlanmoqda" in texts[0]
    msg.answer.return_value.delete.assert_awaited()
    assert "Sotuv foydasi: <b>20.00$</b>" in texts[-1]
    assert expected in texts[-1]
    if absent:
        assert absent not in texts[-1]
    assert state.cleared
