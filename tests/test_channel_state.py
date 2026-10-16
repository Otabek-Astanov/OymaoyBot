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
    # No worker runs in this test, so the user is told the post is queued.
    assert "navbatga qo'yildi" in msg.answer.call_args.args[0]


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


def _listing(monkeypatch, *, post_id, delivery):
    from bot_harid.handlers import harid_flow as flow
    import config

    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    identifier = str(uuid4())
    phone = {"Telefon ID": identifier, "Holati": "Sotuvda", "Kanal post ID": post_id}
    monkeypatch.setattr(flow.sheets_service, "get_phone_by_id", Mock(return_value=phone))
    write = Mock(return_value=True)
    monkeypatch.setattr(flow.sheets_service, "update_phone", write)
    monkeypatch.setattr(flow, "wait_for_delivery", AsyncMock(return_value=delivery))
    state = State(phone_id=identifier, operation_id=str(uuid4()), condition="Yaxshi")
    msg = message("700")
    return flow, state, msg, write


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("post_id", "delivery", "expected"),
    [
        ("", {"state": "sent"}, "E'lon kanalga joylandi"),
        ("9", {"state": "sent"}, "Kanaldagi e'lon yangilandi"),
        ("", {"state": "unknown"}, "E'lon kanalga joylanmadi"),
    ],
)
async def test_listing_reports_the_real_channel_outcome(
    monkeypatch, post_id, delivery, expected
):
    flow, state, msg, write = _listing(monkeypatch, post_id=post_id, delivery=delivery)
    await flow.post_sell_price_received(msg, state, SimpleNamespace(id=123))
    texts = [c.args[0] for c in msg.answer.call_args_list]
    assert "joylanmoqda" in texts[0]  # shown before the slow work starts
    msg.answer.return_value.delete.assert_awaited()  # and removed afterwards
    assert expected in texts[-1]
    assert state.cleared


@pytest.mark.asyncio
async def test_listing_carries_the_chosen_condition_to_the_channel(monkeypatch):
    flow, state, msg, write = _listing(monkeypatch, post_id="", delivery=None)
    await flow.post_sell_price_received(msg, state, SimpleNamespace(id=123))
    assert write.call_args.kwargs["notifications"][0]["data"]["condition"] == "Yaxshi"


@pytest.mark.asyncio
async def test_typed_condition_must_be_a_known_value():
    from bot_harid.handlers import harid_flow as flow

    state = State()
    msg = message("zo'r")
    await flow.post_condition_text(msg, state)
    assert "condition" not in state.data
    assert "tugmadan tanlang" in msg.answer.call_args.args[0]
    await flow.post_condition_text(message("👍 yaxshi"), state)
    assert state.data["condition"] == "Yaxshi"


@pytest.mark.asyncio
async def test_answered_inline_question_keeps_text_and_drops_buttons():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from bot_common.handler_support import close_prompt

    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="128 GB", callback_data="mem:128 GB")]]
    )
    prompt = SimpleNamespace(
        text="Xotira", html_text="💾 <b>Xotira</b>", reply_markup=markup, edit_text=AsyncMock()
    )
    await close_prompt(SimpleNamespace(data="mem:128 GB", message=prompt))
    prompt.edit_text.assert_awaited_once_with(
        "💾 <b>Xotira</b>\n✅ <b>128 GB</b>", reply_markup=None
    )


@pytest.mark.asyncio
async def test_wait_for_delivery_returns_when_the_worker_finishes(monkeypatch):
    from bot_common import handler_support
    from services import notification_queue
    from services.google_sheets import sheets_service

    states = iter([{"state": "pending"}, {"state": "sending"}, {"state": "sent"}])
    monkeypatch.setattr(sheets_service, "notification_status", lambda *a: next(states))

    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(handler_support.io_worker, "call", direct)
    monkeypatch.setattr(notification_queue, "_running_workers", 0)
    assert await handler_support.wait_for_delivery("op", interval=0) is None
    monkeypatch.setattr(notification_queue, "_running_workers", 1)
    status = await handler_support.wait_for_delivery("op", interval=0)
    assert status == {"state": "sent"}
