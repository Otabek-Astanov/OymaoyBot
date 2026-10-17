"""The sales group message carries the stored purchase photo when there is one."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from aiogram.types import BufferedInputFile

from services.notification_queue import NotificationWorker
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture

PHONE_PHOTO = "1PhonePhotoDriveId_abcdefghijklmnop"
IMEI_PHOTO = "1ImeiPhotoDriveId_abcdefghijklmnopq"


def _link(drive_id, label):
    return f'=HYPERLINK("https://drive.google.com/file/d/{drive_id}/view";"📷 {label}")'


def test_photo_id_prefers_phone_photo_then_imei_photo(storage):
    service, sheet = storage
    for phone_id, imei_photo, phone_photo in (
        ("both", _link(IMEI_PHOTO, "imei.jpg"), _link(PHONE_PHOTO, "phone.jpg")),
        ("imei-only", _link(IMEI_PHOTO, "imei.jpg"), ""),
        ("none", "", ""),
    ):
        add_phone(sheet, phone_id=phone_id, imei=phone_id[:4] + "11")
        row = sheet.sheets["Telefonlar"].values[-1]
        headers = sheet.sheets["Telefonlar"].values[0]
        row[headers.index("IMEI rasmi")] = imei_photo
        row[headers.index("Telefon rasmi")] = phone_photo
    assert service.phone_photo_drive_id("both") == PHONE_PHOTO
    assert service.phone_photo_drive_id("imei-only") == IMEI_PHOTO
    assert service.phone_photo_drive_id("none") == ""
    assert service.phone_photo_drive_id("missing") == ""


class DirectWorker:
    async def call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def _worker(drive):
    sheets = SimpleNamespace(phone_photo_drive_id=Mock(return_value=PHONE_PHOTO))
    worker = NotificationWorker(DirectWorker(), sheets, {7: object()}, drive_service=drive)
    worker.poster = SimpleNamespace(post_to_sell_group=AsyncMock(return_value=55))
    return worker


def _row():
    return {
        "operation_id": str(uuid4()),
        "index": 0,
        "payload": {"kind": "sell_group", "bot_id": 7, "phone_id": "phone-1", "data": {"model": "iPhone 14"}},
    }


@pytest.mark.asyncio
async def test_sale_message_is_sent_with_the_stored_photo():
    drive = SimpleNamespace(download_photo=Mock(return_value=b"jpeg-bytes"))
    worker = _worker(drive)
    assert await worker._deliver(_row()) == 55
    photo = worker.poster.post_to_sell_group.call_args.kwargs["photo"]
    assert isinstance(photo, BufferedInputFile) and photo.data == b"jpeg-bytes"
    drive.download_photo.assert_called_once_with(PHONE_PHOTO)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drive",
    [None, SimpleNamespace(download_photo=Mock(side_effect=OSError("drive down")))],
)
async def test_sale_message_falls_back_to_text_without_a_photo(drive):
    worker = _worker(drive)
    assert await worker._deliver(_row()) == 55
    assert worker.poster.post_to_sell_group.call_args.kwargs["photo"] is None


@pytest.mark.asyncio
async def test_sale_notification_names_its_phone(monkeypatch):
    from decimal import Decimal
    from bot_sotuv.handlers import sotuv_flow as flow
    from test_handler_contracts import State, message
    import config

    monkeypatch.setattr(config, "GROUP_SOTUV_ID", "-100777")
    monkeypatch.setattr(config, "CHANNEL_ID", "")
    monkeypatch.setattr(flow.sheets_service, "get_phone_by_id", Mock(return_value={"Holati": "Sotuvda"}))
    write = Mock(return_value=(True, Decimal("20")))
    monkeypatch.setattr(flow.sheets_service, "record_sale", write)
    monkeypatch.setattr(flow, "wait_for_delivery", AsyncMock(return_value=None))
    state = State(phone_id="phone-1", operation_id=str(uuid4()), sell_price="150")
    await flow.confirm_sale_handler(message("✅ Ha"), state, SimpleNamespace(id=7))
    [notice] = write.call_args.kwargs["notifications"]
    assert notice["kind"] == "sell_group" and notice["phone_id"] == "phone-1"


@pytest.mark.asyncio
async def test_group_message_id_is_kept_in_the_journal(storage):
    service, sheet = storage
    phone_id = str(uuid4())
    add_phone(sheet, phone_id=phone_id)
    notice = {"kind": "sell_group", "bot_id": 7, "phone_id": phone_id, "data": {"model": "iPhone 14"}}
    service.update_phone(
        phone_id, {"Karobka": "Ha"}, operation_id=str(uuid4()), actor_id=1,
        notifications=[notice],
    )
    worker = NotificationWorker(DirectWorker(), service, {7: object()})
    worker.poster = SimpleNamespace(post_to_sell_group=AsyncMock(return_value=4321))
    assert await worker.process_once() == 1
    [status] = service.notification_statuses()
    assert status["state"] == "sent" and status["error"] == "message_id=4321"
