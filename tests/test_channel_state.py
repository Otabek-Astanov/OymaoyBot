from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from test_handler_contracts import State, message


@pytest.mark.asyncio
async def test_channel_skipping_never_exposes_imei_photo():
    from bot_harid.handlers import harid_flow as flow

    state = State(imei_photo_file_id="private-evidence-photo")
    await flow.channel_photo_skipped(message("Tashlab ketish"), state)
    assert state.data["phone_photo_file_id"] is None


@pytest.mark.asyncio
async def test_sold_phone_cannot_be_listed(monkeypatch):
    from bot_harid.handlers import harid_flow as flow

    monkeypatch.setattr(
        flow.sheets_service,
        "get_phone_by_imei",
        Mock(return_value={"Holati": "Sotildi"}),
    )
    state = State()
    msg = message("000042")
    await flow.imei_searched(msg, state)
    assert state.current == "confirm"
    assert "phone_id" not in state.data


@pytest.mark.asyncio
async def test_listing_is_a_durable_notification_with_separate_price(monkeypatch):
    from bot_harid.handlers import harid_flow as flow
    import config

    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    identifier = str(uuid4())
    phone = {
        "Telefon ID": identifier,
        "Holati": "Sotuvda",
        "IMEI": "000042",
        "Kanal post ID": "5",
        "Sotuv narxi ($)": "",
    }
    monkeypatch.setattr(
        flow.sheets_service, "get_phone_by_id", Mock(return_value=phone)
    )
    write = Mock(return_value=True)
    monkeypatch.setattr(flow.sheets_service, "update_phone", write)
    state = State(phone_id=identifier, operation_id=str(uuid4()))
    msg = message("150,50")
    await flow.post_sell_price_received(msg, state, SimpleNamespace(id=123))
    assert write.call_args.args == (identifier, {"Elon narxi ($)": "150.50"})
    notification = write.call_args.kwargs["notifications"][0]
    assert notification["kind"] == "publish_channel"
    assert notification["phone_id"] == identifier
    assert state.cleared
    assert "yuborish navbatda" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_failed_listing_keeps_state_and_existing_post(monkeypatch):
    from bot_harid.handlers import harid_flow as flow
    import config

    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    phone = {"Telefon ID": "phone-1", "Holati": "Sotuvda", "Kanal post ID": "9"}
    monkeypatch.setattr(
        flow.sheets_service, "get_phone_by_id", Mock(return_value=phone)
    )
    monkeypatch.setattr(flow.sheets_service, "update_phone", Mock(return_value=False))
    state = State(phone_id="phone-1", operation_id=str(uuid4()))
    msg = message("150")
    await flow.post_sell_price_received(msg, state, SimpleNamespace(id=123))
    assert not state.cleared
    assert phone["Kanal post ID"] == "9"
    assert not any(
        "E’lon ma’lumoti saqlandi" in str(c) for c in msg.answer.call_args_list
    )


@pytest.mark.asyncio
async def test_sale_always_queues_fresh_channel_lookup(monkeypatch):
    from bot_sotuv.handlers import sotuv_flow as flow
    import config
    from decimal import Decimal

    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(config, "GROUP_SOTUV_ID", "")
    write = Mock(return_value=(True, Decimal("20.00")))
    monkeypatch.setattr(flow.sheets_service, "record_sale", write)
    state = State(
        phone_id="phone-1",
        operation_id=str(uuid4()),
        channel_post_id="",
        sell_price="150",
    )
    await flow.confirm_sale_handler(message("✅ Ha"), state, SimpleNamespace(id=123))
    notification = write.call_args.kwargs["notifications"][0]
    assert notification["kind"] == "sold_channel"
    assert notification["phone_id"] == "phone-1"


@pytest.mark.asyncio
async def test_long_model_versions_have_bounded_callbacks(monkeypatch):
    from bot_harid.handlers import harid_flow as flow

    version = "Model: " + "O‘" * 60
    monkeypatch.setattr(
        flow.sheets_service,
        "get_models",
        Mock(return_value=[{"Brend": "iPhone", "Versiya": version}]),
    )
    msg = message()
    call = SimpleNamespace(data="brand:iPhone", answer=AsyncMock(), message=msg)
    state = State()
    await flow.brand_chosen(call, state)
    callback = (
        msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
    )
    assert len(callback.encode()) <= 64
    assert version in state.data["version_choices"].values()
