import re
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from services.daily_report import (
    TASHKENT,
    DailyStockReport,
    build_stock_report,
    spaced_imei,
)
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


def test_stock_phones_use_real_model_names(storage):
    service, sheet = storage
    add_phone(sheet, phone_id=str(uuid4()), imei="356789012345678")
    sheet.add_record(
        "Telefonlar",
        {"Telefon ID": "p2", "IMEI": "123456", "Brend": "Android", "Versiya": "Samsung A10", "Holati": "Sotuvda"},
    )
    sheet.add_record(
        "Telefonlar",
        {"Telefon ID": "p3", "IMEI": "999999", "Brend": "iPhone", "Versiya": "13", "Holati": "Sotildi"},
    )
    service.reload_cache()
    stock = service.get_stock_phones()
    assert {p["IMEI"]: p["Model"] for p in stock} == {
        "356789012345678": "iPhone 14",
        "123456": "Samsung A10",
    }


def test_report_lists_only_unlisted_phones_in_stock():
    phones = [
        {"IMEI": "356789012345678", "Model": "iPhone 14 Pro", "Brend": "iPhone", "Holati": "Sotuvda", "Jami tannarx ($)": 700},
        {"IMEI": "123456", "Model": "Samsung A10", "Brend": "Android", "Holati": "Sotuvda", "Jami tannarx ($)": 1500},
        {"IMEI": "555555", "Model": "iPhone 13", "Brend": "iPhone", "Holati": "Sotuvda", "Kanal post ID": 5},
        {"IMEI": "777777", "Model": "iPhone 11", "Brend": "iPhone", "Holati": "Sotildi"},
    ]
    [text] = build_stock_report(phones, date(2026, 10, 17))
    head, block = text.split("<blockquote expandable>")
    assert "Kanalga e'lon qilinmagan telefonlar — 17.10.2026" in head
    assert "E'lon qilinmagan: <b>2 ta</b> (sotuvdagi 3 tadan)" in head
    assert "iPhone: 1" in head and "Android: 1" in head
    assert "Tannarx jami: <b>2 200$</b>" in head
    assert block.endswith("</blockquote>")
    assert "<code>1 2 3 4 5 6</code> — Samsung A10" in block
    assert "<code>3 5 6 7 8 9 0 1 2 3 4 5 6 7 8</code> — iPhone 14 Pro" in block
    assert "5 5 5 5 5 5" not in text  # already posted to the channel
    assert "7 7 7 7 7 7" not in text  # sold


def test_long_stock_list_is_split_into_valid_messages():
    phones = [
        {"IMEI": f"35678901234{i:04d}", "Model": "iPhone 15 Pro Max", "Holati": "Sotuvda"}
        for i in range(200)
    ]
    messages = build_stock_report(phones, date(2026, 10, 17))
    assert len(messages) > 1
    assert sum(m.count("</code> —") for m in messages) == 200
    for text in messages:
        assert len(text) <= 4096
        assert text.count("<blockquote expandable>") == text.count("</blockquote>") == 1
    assert re.match(r"📢 <b>Davomi \(2\)</b>", messages[1])


def test_report_when_everything_is_already_listed():
    phones = [{"IMEI": "555555", "Holati": "Sotuvda", "Kanal post ID": 5}]
    [text] = build_stock_report(phones, date(2026, 10, 17))
    assert "barcha telefonlar (1 ta) kanalga e'lon qilingan" in text
    assert "blockquote" not in text


def test_spaced_imei_strips_text_marker():
    assert spaced_imei("'012345") == "0 1 2 3 4 5"


class DirectWorker:
    async def call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def _report(tmp_path, at_now, sheets=None):
    bot = SimpleNamespace(send_message=AsyncMock())
    sheets = sheets or SimpleNamespace(get_stock_phones=lambda: [])
    clock = {"now": at_now}
    report = DailyStockReport(
        DirectWorker(), sheets, bot, "-100123", "14:00", tmp_path / "daily_report.json",
        now=lambda: clock["now"],
    )
    return report, bot, clock


def _at(hour, minute, day=17):
    return datetime(2026, 10, day, hour, minute, tzinfo=TASHKENT)


@pytest.mark.asyncio
async def test_report_is_sent_once_a_day_even_across_restarts(tmp_path):
    report, bot, _ = _report(tmp_path, _at(14, 0))
    assert not report.due(_at(13, 59))
    assert report.due(_at(14, 0))
    await report.send_once(_at(14, 0))
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.kwargs["chat_id"] == "-100123"
    assert not report.due(_at(14, 30))
    restarted, _, _ = _report(tmp_path, _at(15, 0))
    assert not restarted.due(_at(15, 0))
    assert restarted.due(_at(14, 0, day=18))


def test_late_start_catches_up_only_the_same_afternoon(tmp_path):
    report, _, _ = _report(tmp_path, _at(16, 59))
    assert report.due(_at(16, 59))
    assert not report.due(_at(17, 0))
    assert not report.due(_at(23, 0))
    assert report.seconds_until_next(_at(13, 0)) == 3600
    assert report.seconds_until_next(_at(14, 0)) == 24 * 3600


@pytest.mark.asyncio
async def test_failed_send_retries_without_stopping_the_worker(tmp_path):
    class Stop(Exception):
        pass

    calls = {"n": 0}

    def phones():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("Sheets unavailable")
        return []

    report, bot, _ = _report(
        tmp_path, _at(14, 1), SimpleNamespace(get_stock_phones=phones)
    )
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise Stop

    report.sleep = sleep
    with pytest.raises(Stop):
        await report.run()
    assert sleeps[0] == 300  # retry after a failure
    bot.send_message.assert_awaited_once()  # second attempt succeeded


def test_report_time_is_validated(monkeypatch):
    import config

    for value, ok in (("14:00", True), ("off", True), ("25:00", False), ("2pm", False)):
        monkeypatch.setattr(config, "DAILY_REPORT_TIME", value)
        monkeypatch.setattr(config, "FSM_STORAGE_URL", "memory://")
        monkeypatch.setattr(config, "SPREADSHEET_ID", "a" * 40)
        monkeypatch.setattr(config, "GOOGLE_SERVICE_ACCOUNT_FILE", __file__)
        monkeypatch.setattr(config, "HARID_BOT_TOKEN", "123456789:" + "A" * 35)
        try:
            config.validate_runtime_config(("harid",))
            assert ok, value
        except config.ConfigurationError as exc:
            assert not ok and "DAILY_REPORT_TIME" in str(exc), value
