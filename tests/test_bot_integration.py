"""Exercise real aiogram routing/FSM and the domain service without a network."""

from datetime import datetime, timezone
from decimal import Decimal
import importlib

import pytest
from aiogram import Bot, Dispatcher, types
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageText,
    SendMessage,
    SendPhoto,
)

import config
from tests.storage_fakes import FakeSpreadsheet
from services.google_sheets import GoogleSheetsService
from services.io_worker import io_worker


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.last = None

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage)):
            return True
        if isinstance(method, (SendMessage, SendPhoto, EditMessageText)):
            self.sent.append(method)
            self.last = types.Message(
                message_id=len(self.sent),
                date=datetime.now(timezone.utc),
                chat=types.Chat(id=1, type="private"),
                text=getattr(method, "text", None),
                from_user=types.User(id=bot.id, is_bot=True, first_name="Test bot"),
            ).as_(bot)
            return self.last
        raise AssertionError(f"Unexpected Telegram call: {type(method).__name__}")

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("No remote files in this scenario")
        yield b""


@pytest.mark.asyncio
async def test_purchase_sale_kpi_payment_and_balance_through_real_routers(
    tmp_path, monkeypatch
):
    from bot_common import access, navigation
    from services import google_sheets
    from bot_harid.handlers import harid_flow
    from bot_sotuv.handlers import sotuv_flow
    from bot_harajat.handlers import harajat_flow

    flows = [importlib.reload(flow) for flow in (harid_flow, sotuv_flow, harajat_flow)]
    sheet = FakeSpreadsheet()
    service = GoogleSheetsService(
        spreadsheet=sheet, journal_path=tmp_path / "operations.sqlite"
    )
    await io_worker.call(service.initialize)
    for module in [google_sheets, access, navigation, *flows]:
        monkeypatch.setattr(module, "sheets_service", service)
    for key in ("DRIVE_FOLDER_ID", "CHANNEL_ID", "GROUP_HARID_ID", "GROUP_SOTUV_ID"):
        monkeypatch.setattr(config, key, "")
    session = TelegramSession()
    bot = Bot(token="12345:" + "x" * 35, session=session)
    dispatcher = Dispatcher(
        storage=MemoryStorage(), events_isolation=SimpleEventIsolation()
    )
    dispatcher.update.outer_middleware(access.AccessMiddleware(config.FEATURES))
    dispatcher.include_router(navigation.create_navigation_router(config.FEATURES))
    for flow in flows:
        dispatcher.include_router(flow.router)
    user = types.User(id=1, is_bot=False, first_name="Owner")
    counter = 0

    async def send(text):
        nonlocal counter
        counter += 1
        update = types.Update(
            update_id=counter,
            message=types.Message(
                message_id=counter,
                date=datetime.now(timezone.utc),
                chat=types.Chat(id=1, type="private"),
                from_user=user,
                text=text,
            ),
        )
        await dispatcher.feed_update(bot, update)

    async def choose(data):
        nonlocal counter
        counter += 1
        await dispatcher.feed_update(
            bot,
            types.Update(
                update_id=counter,
                callback_query=types.CallbackQuery(
                    id=str(counter),
                    from_user=user,
                    chat_instance="test",
                    message=session.last,
                    data=data,
                ),
            ),
        )

    try:
        await send("/start")
        buttons = {
            button.text
            for row in session.sent[-1].reply_markup.keyboard
            for button in row
        }
        assert {
            "📥 Harid qilish",
            "📱 Yangi sotuvni rasmiylashtirish",
            "📉 Chiqim",
            "💰 Balance",
        } <= buttons
        await send("📥 Harid qilish")
        await choose("brand:Android")
        await send("Pixel <9> & A")
        assert "&lt;9&gt; &amp; A" in session.sent[-1].text
        await choose("skip_imei_photo")
        await choose("mem:-")
        await choose("skip_battery")
        await choose("skip_color")
        await send("00000000012345")
        await send("✅ Ha")
        await send("100,00")
        await choose("skip_seller_name")
        await choose("skip_seller_phone")
        await send("💵 Naqd")
        await send("✅ Ha")
        phone = sheet.records("Telefonlar")[0]
        assert phone["IMEI"] == "00000000012345"
        assert phone["Holati"] == "Sotuvda"
        assert phone["Harid narxi ($)"] == 100
        await send("❌ Yo'q")
        await send("📱 Yangi sotuvni rasmiylashtirish")
        await send("00000000012345")
        await send("✅ Ha")
        await send("150,00")
        await choose("skip_buyer_name")
        await choose("skip_buyer_phone")
        await choose("pay:Naqd")
        await choose("kpi_count:1")
        await choose("kpi:10")
        await send("✅ Ha")
        phone = sheet.records("Telefonlar")[0]
        assert phone["Holati"] == "Sotildi"
        assert phone["Sof foyda ($)"] == 40
        await send("📉 Chiqim")
        await choose("exp:KPI")
        await choose("staff:1")
        await send("10,00")
        await send("💰 Balance")
        assert "Operatsion foyda" in session.sent[-1].text
        summary = await io_worker.call(service.get_financial_summary)
        assert summary["sales_margin"] == Decimal("40.00")
        assert summary["operating_profit"] == Decimal("40.00")
        assert summary["kassa_balance"] == Decimal("40.00")
        assert summary["staff_kpi_debts"] == 0
        assert len(sheet.records("Amallar")) == 3
    finally:
        await dispatcher.fsm.close()
        await bot.session.close()
        await io_worker.call(service.close)


@pytest.mark.asyncio
async def test_pending_operation_cannot_be_replaced_by_menu_button(monkeypatch):
    from bot_common import handler_support
    from services import google_sheets
    from test_handler_contracts import State
    from unittest.mock import Mock
    from services.errors import BusinessRuleError

    monkeypatch.setattr(
        google_sheets.sheets_service,
        "get_actor_pending_operations",
        Mock(return_value=[{"operation_id": "old-uuid", "state": "unknown"}]),
    )
    state = State(operation_id="old-uuid")
    with pytest.raises(BusinessRuleError):
        await handler_support.begin_flow(state, 1)
    assert not state.cleared
    assert state.data["operation_id"] == "old-uuid"
