"""A flow left open at its final "✅ Ha" must re-check the sheet before saving."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

import config
from test_handler_contracts import State, message
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture

SOLD = {
    "Telefon ID": "phone-1",
    "IMEI": "345678",
    "Model": "iPhone 14 Pro",
    "Holati": "Sotildi",
    "Sotilgan sana": "2026-10-15 12:00",
    "Do'kon sotuvchisi": "Ali",
    "Sotuv narxi ($)": 640,
}


def _texts(msg):
    return [c.args[0] for c in msg.answer.call_args_list]


@pytest.mark.asyncio
async def test_second_seller_cannot_sell_a_phone_sold_meanwhile(storage, monkeypatch):
    from bot_sotuv.handlers import sotuv_flow as flow
    from test_health_check import DirectWorker

    service, sheet = storage
    phone_id = str(uuid4())
    add_phone(sheet, phone_id=phone_id, imei="345678")
    monkeypatch.setattr(flow, "sheets_service", service)
    monkeypatch.setattr(flow, "io_worker", DirectWorker())
    monkeypatch.setattr(config, "CHANNEL_ID", "")
    monkeypatch.setattr(config, "GROUP_SOTUV_ID", "")
    sale = {"sell_price": "150", "payment_type": "Naqd", "seller_name": "Ali", "sellers": []}
    first = State(phone_id=phone_id, operation_id=str(uuid4()), **sale)
    second = State(phone_id=phone_id, operation_id=str(uuid4()), **{**sale, "seller_name": "Vali"})
    with patch("bot_common.handler_support.io_worker", DirectWorker()):
        await flow.confirm_sale_handler(message("✅ Ha"), first, SimpleNamespace(id=1))
        late = message("✅ Ha")
        await flow.confirm_sale_handler(late, second, SimpleNamespace(id=1))
    sold = [r for r in sheet.records("Telefonlar") if r["Telefon ID"] == phone_id]
    assert [r["Holati"] for r in sold] == ["Sotildi"]
    assert sold[0]["Do'kon sotuvchisi"] == "Ali"
    text = _texts(late)[-1]
    assert "Sotuv saqlanmadi" in text and "sotilgan" in text and "Ali" in text
    assert second.cleared


@pytest.mark.asyncio
async def test_purchase_refused_when_imei_was_added_meanwhile(monkeypatch):
    from bot_harid.handlers import harid_flow as flow

    existing = {"IMEI": "345678", "Model": "iPhone 14 Pro", "Holati": "Sotuvda", "Qabul qilgan xodim": "Ali"}
    monkeypatch.setattr(flow.sheets_service, "get_phone_by_imei", Mock(return_value=existing))
    add = Mock(return_value=True)
    monkeypatch.setattr(flow.sheets_service, "add_phone", add)
    state = State(imei="345678", operation_id=str(uuid4()))
    msg = message("✅ Ha")
    await flow.confirm_purchase_handler(msg, state, SimpleNamespace(id=1))
    add.assert_not_called()
    assert state.cleared
    assert "Xarid saqlanmadi" in _texts(msg)[-1] and "Ali" in _texts(msg)[-1]


@pytest.mark.asyncio
async def test_listing_refused_and_closed_when_phone_was_sold(monkeypatch):
    from bot_harid.handlers import harid_flow as flow

    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(flow.sheets_service, "get_phone_by_id", Mock(return_value=SOLD))
    write = Mock(return_value=True)
    monkeypatch.setattr(flow.sheets_service, "update_phone", write)
    state = State(phone_id="phone-1", operation_id=str(uuid4()))
    msg = message("700")
    await flow.post_sell_price_received(msg, state, SimpleNamespace(id=1))
    write.assert_not_called()
    assert state.cleared
    text = _texts(msg)[-1]
    assert "E'lon saqlanmadi" in text and "2026-10-15 12:00" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (SOLD, "Karobka holati saqlanmadi"),
        ({**SOLD, "Holati": "Sotuvda", "Karobka": "Ha"}, "allaqachon belgilangan"),
        (None, "jadvalda topilmadi"),
    ],
)
async def test_box_update_rechecks_the_phone(monkeypatch, current, expected):
    from bot_harid.handlers import harid_flow as flow

    monkeypatch.setattr(flow.sheets_service, "get_phone_by_id", Mock(return_value=current))
    write = Mock(return_value=True)
    monkeypatch.setattr(flow.sheets_service, "update_phone", write)
    state = State(phone_id="phone-1", operation_id=str(uuid4()))
    msg = message("✅ Ha")
    await flow.confirm_karobka_update(msg, state)
    write.assert_not_called()
    assert state.cleared
    assert expected in _texts(msg)[-1]


@pytest.mark.asyncio
async def test_sale_still_saves_when_phone_is_unchanged(monkeypatch):
    from bot_sotuv.handlers import sotuv_flow as flow

    monkeypatch.setattr(config, "CHANNEL_ID", "")
    monkeypatch.setattr(config, "GROUP_SOTUV_ID", "")
    monkeypatch.setattr(flow.sheets_service, "get_phone_by_id", Mock(return_value={"Holati": "Sotuvda"}))
    write = Mock(return_value=(True, Decimal("20")))
    monkeypatch.setattr(flow.sheets_service, "record_sale", write)
    monkeypatch.setattr(flow, "wait_for_delivery", AsyncMock(return_value=None))
    state = State(phone_id="phone-1", operation_id=str(uuid4()), sell_price="150")
    await flow.confirm_sale_handler(message("✅ Ha"), state, SimpleNamespace(id=1))
    write.assert_called_once()
