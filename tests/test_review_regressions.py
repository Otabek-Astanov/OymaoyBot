"""Real storage/FSM boundaries for failures found during the final review."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

import config
from services.errors import BusinessRuleError
from services.google_sheets import GoogleSheetsService
from tests.storage_fakes import FakeSpreadsheet, add_phone
from test_handler_contracts import State, message
from utils.money import InvalidAmount, money_value, parse_money


@pytest.fixture
def storage(tmp_path):
    sheet = FakeSpreadsheet()
    service = GoogleSheetsService(
        spreadsheet=sheet, journal_path=tmp_path / "operations.sqlite"
    )
    service.initialize()
    yield service, sheet
    service.close()


@pytest.mark.parametrize(
    "number,expected",
    [
        (0.30 - 0.10, "0.20"),
        (0.1 + 0.2, "0.30"),
        (1.00 - 0.99, "0.01"),
    ],
)
def test_trusted_sheet_doubles_preserve_exact_cents(number, expected):
    assert money_value(number) == Decimal(expected)


@pytest.mark.parametrize("number", [10.123, float("inf"), float("nan"), -0.01, True])
def test_non_cent_sheet_values_are_still_rejected(number):
    with pytest.raises(InvalidAmount):
        money_value(number)


def test_user_precision_is_not_relaxed_for_formula_tolerance():
    with pytest.raises(InvalidAmount):
        parse_money("0.19999999999999998")


def test_a_durable_journal_cannot_be_reused_for_another_spreadsheet(tmp_path):
    from services.errors import StorageUnavailable

    path = tmp_path / "operations.sqlite"
    first_sheet = FakeSpreadsheet()
    first_sheet.id = "spreadsheet-a"
    first = GoogleSheetsService(spreadsheet=first_sheet, journal_path=path)
    first.initialize()
    first.record_income("Rahbariyat", "10", operation_id=str(uuid4()), actor_id=1)
    first.close()
    second_sheet = FakeSpreadsheet()
    second_sheet.id = "spreadsheet-b"
    second = GoogleSheetsService(spreadsheet=second_sheet, journal_path=path)
    try:
        with pytest.raises(StorageUnavailable, match="boshqa"):
            second.initialize()
        assert not second_sheet.calls
    finally:
        second.close()


def test_drive_token_path_uses_explicit_runtime_configuration_at_initialization(
    monkeypatch, tmp_path
):
    from services.google_drive import GoogleDriveService

    service = GoogleDriveService()
    configured = tmp_path / "runtime-token.json"
    monkeypatch.setattr(config, "GOOGLE_OAUTH_TOKEN_FILE", str(configured))
    observed = []
    monkeypatch.setattr(
        service, "_init_service", lambda: observed.append(service.token_file)
    )
    service.initialize()
    assert observed == [configured]


def test_fractional_kpi_payment_leaves_a_readable_balance(storage):
    service, sheet = storage
    sheet.add_record(
        "Xodimlar",
        {
            "Telegram ID": "2",
            "F.I.Sh": "Ali",
            "Roli": "Sotuvchi",
            "Holati": "Faol",
            "Jami KPI ($)": 0.30,
            "To'langan KPI ($)": 0,
            "Qoldiq KPI ($)": 0.30,
        },
    )
    service.pay_staff_kpi(2, "0.10", operation_id=str(uuid4()), actor_id=1)
    assert service.get_financial_summary()["staff_kpi_debts"] == Decimal("0.20")


def test_repair_adds_to_existing_repair_cost_in_one_atomic_batch(storage):
    service, sheet = storage
    add_phone(sheet, cost=100)
    phone_sheet = sheet.sheets["Telefonlar"]
    phone_sheet.values[1][phone_sheet.values[0].index("Remont xarajati ($)")] = 5
    phone_sheet.values[1][phone_sheet.values[0].index("Jami tannarx ($)")] = 105
    result = service.record_repair(
        "phone-1", "10", "Admin", operation_id=str(uuid4()), actor_id=1
    )
    assert result == (True, Decimal("115.00"))
    assert len(sheet.calls) == 1
    assert sheet.records("Telefonlar")[0]["Remont xarajati ($)"] == 15
    assert sheet.records("Chiqimlar")[0]["Summa ($)"] == 10
    assert len(sheet.records("Amallar")) == 1


def test_fractional_partner_payment_can_be_reported_and_paid_again(storage):
    service, sheet = storage
    add_phone(sheet, cost=0.10)
    sheet.add_record(
        "Hamkorlar", {"Hamkor nomi": "Hamkor", "Hozirgi qarzdorlik ($)": 0}
    )
    service.record_sale(
        "phone-1",
        {"sell_price": "0.30", "payment_type": "Qarz", "partner_name": "Hamkor"},
        operation_id=str(uuid4()),
        actor_id=1,
    )
    service.reduce_partner_debt("Hamkor", "0.10", operation_id=str(uuid4()), actor_id=1)
    assert service.get_financial_summary()["partner_debts"] == Decimal("0.20")
    service.reduce_partner_debt("Hamkor", "0.20", operation_id=str(uuid4()), actor_id=1)
    assert service.get_financial_summary()["partner_debts"] == Decimal("0.00")


@pytest.mark.parametrize("action", ["payment", "sale"])
def test_new_kpi_operations_never_replace_an_unreconciled_historical_remainder(
    storage, action
):
    service, sheet = storage
    sheet.add_record(
        "Xodimlar",
        {
            "Telegram ID": "2",
            "F.I.Sh": "Ali",
            "Roli": "Sotuvchi",
            "Holati": "Faol",
            "Jami KPI ($)": 100,
            "To'langan KPI ($)": 20,
            "Qoldiq KPI ($)": 90,
        },
    )
    add_phone(sheet)
    with pytest.raises(BusinessRuleError, match="yarashtir"):
        if action == "payment":
            service.pay_staff_kpi(2, "10", operation_id=str(uuid4()), actor_id=1)
        else:
            service.record_sale(
                "phone-1",
                {"sell_price": "150", "seller_kpi": "10", "seller_id": 2},
                operation_id=str(uuid4()),
                actor_id=1,
            )
    assert not sheet.calls
    assert sheet.records("Xodimlar")[-1]["Qoldiq KPI ($)"] == 90


def test_unreadable_committed_formula_is_quarantined_instead_of_reported_as_success(
    storage, monkeypatch
):
    from services.errors import OutcomeUnknown

    service, sheet = storage
    sheet.add_record(
        "Xodimlar",
        {
            "Telegram ID": "2",
            "F.I.Sh": "Ali",
            "Roli": "Sotuvchi",
            "Holati": "Faol",
            "Jami KPI ($)": 100,
            "To'langan KPI ($)": 0,
            "Qoldiq KPI ($)": 100,
        },
    )
    original_batch = sheet.batch_update

    def corrupt_formula_after_commit(batch):
        result = original_batch(batch)
        ws = sheet.sheets["Xodimlar"]
        ws.values[-1][ws.values[0].index("Qoldiq KPI ($)")] = "#REF!"
        return result

    monkeypatch.setattr(sheet, "batch_update", corrupt_formula_after_commit)
    identifier = str(uuid4())
    with pytest.raises(OutcomeUnknown):
        service.pay_staff_kpi(2, "10", operation_id=identifier, actor_id=1)
    assert service.get_operation_status(identifier)["state"] == "unknown"
    assert len(sheet.calls) == 1


@pytest.mark.asyncio
async def test_listing_retry_uses_the_original_intent_after_lost_sheets_response(
    storage, monkeypatch
):
    from bot_harid.handlers import harid_flow as flow

    service, sheet = storage
    phone_id = str(uuid4())
    add_phone(sheet, phone_id=phone_id)
    monkeypatch.setattr(flow, "sheets_service", service)
    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    state = State(phone_id=phone_id, operation_id=str(uuid4()))
    msg = message("150")
    sheet.fail = TimeoutError("response lost after commit")
    sheet.commit_then_fail = True
    # Use a direct worker: the fixture's SQLite connection belongs to this thread.
    from test_health_check import DirectWorker

    monkeypatch.setattr(flow, "io_worker", DirectWorker())
    with patch("bot_common.handler_support.io_worker", DirectWorker()):
        await flow.post_sell_price_received(msg, state, SimpleNamespace(id=123))
        assert not state.cleared
        sheet.fail = None
        await flow.post_sell_price_received(msg, state, SimpleNamespace(id=123))
    assert state.cleared
    assert len(sheet.calls) == 1
    assert len(service.pending_notifications()) == 1


@pytest.mark.parametrize("notification_state", ["pending", "sending", "unknown"])
def test_new_listing_cannot_bypass_an_unresolved_publication_with_a_new_uuid(
    storage, notification_state
):
    service, sheet = storage
    phone_id = str(uuid4())
    add_phone(sheet, phone_id=phone_id)
    first = str(uuid4())
    notification = {
        "kind": "publish_channel",
        "phone_id": phone_id,
        "actor_id": 1,
        "bot_id": 123,
        "data": {"sell_price": "150"},
    }
    service.update_phone(
        phone_id,
        {"Elon narxi ($)": "150"},
        operation_id=first,
        actor_id=1,
        notifications=[notification],
    )
    if notification_state != "pending":
        service.mark_notification(first, 0, "sending")
    if notification_state == "unknown":
        service.mark_notification(first, 0, "unknown", "post_id=99")
    with pytest.raises(BusinessRuleError, match="e.lon"):
        service.update_phone(
            phone_id,
            {"Elon narxi ($)": "160"},
            operation_id=str(uuid4()),
            actor_id=1,
            notifications=[notification],
        )
    assert len(sheet.calls) == 1


@pytest.mark.asyncio
async def test_revoked_actor_cannot_publish_a_previously_committed_listing(
    storage, monkeypatch
):
    from services.notification_queue import NotificationWorker
    from test_health_check import DirectWorker
    from tests.test_notifications import fake_bot

    service, sheet = storage
    phone_id = str(uuid4())
    add_phone(sheet, phone_id=phone_id)
    identifier = str(uuid4())
    service.update_phone(
        phone_id,
        {"Elon narxi ($)": "150"},
        operation_id=identifier,
        actor_id=1,
        notifications=[
            {
                "kind": "publish_channel",
                "phone_id": phone_id,
                "actor_id": 1,
                "bot_id": 123,
                "data": {"sell_price": "150"},
            }
        ],
    )
    staff = sheet.sheets["Xodimlar"]
    staff.values[1][staff.values[0].index("Holati")] = "Nofaol"
    bot = fake_bot()
    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    worker = NotificationWorker(DirectWorker(), service, {123: bot})
    await worker.process_once()
    bot.send_message.assert_not_called()
    bot.send_photo.assert_not_called()
    assert service.notification_statuses()[0]["state"] == "unknown"


@pytest.mark.asyncio
async def test_manual_publication_reconciliation_records_post_before_allowing_new_listing(
    storage, monkeypatch
):
    from services.notification_queue import NotificationWorker
    from test_health_check import DirectWorker
    from tests.test_notifications import fake_bot

    service, sheet = storage
    phone_id = str(uuid4())
    add_phone(sheet, phone_id=phone_id)
    identifier = str(uuid4())
    payload = {
        "kind": "publish_channel",
        "phone_id": phone_id,
        "actor_id": 1,
        "bot_id": 123,
        "data": {"sell_price": "150"},
    }
    service.update_phone(
        phone_id,
        {"Elon narxi ($)": "150"},
        operation_id=identifier,
        actor_id=1,
        notifications=[payload],
    )
    service.mark_notification(identifier, 0, "sending")
    service.mark_notification(identifier, 0, "unknown", "post_id=99")
    with pytest.raises(BusinessRuleError, match="post ID"):
        service.resolve_notification_outcome(identifier, 0, sent=True, actor_id=1)
    assert service.notification_statuses()[0]["state"] == "unknown"
    service.resolve_notification_outcome(
        identifier, 0, sent=True, actor_id=1, channel_post_id=99
    )
    assert service.get_phone_by_id(phone_id, fresh=True)["Kanal post ID"] == 99
    service.update_phone(
        phone_id,
        {"Elon narxi ($)": "160"},
        operation_id=str(uuid4()),
        actor_id=1,
        notifications=[{**payload, "data": {"sell_price": "160"}}],
    )
    bot = fake_bot()
    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    worker = NotificationWorker(DirectWorker(), service, {123: bot})
    await worker.process_once()
    bot.send_message.assert_not_called()
    assert bot.edit_message_caption.call_args.kwargs["message_id"] == 99


@pytest.mark.asyncio
async def test_manual_publication_reconciliation_queues_sold_edit_for_a_sold_phone(
    storage, monkeypatch
):
    from services.notification_queue import NotificationWorker
    from test_health_check import DirectWorker
    from tests.test_notifications import fake_bot

    service, sheet = storage
    phone_id, identifier = str(uuid4()), str(uuid4())
    add_phone(sheet, phone_id=phone_id)
    service.update_phone(
        phone_id,
        {"Elon narxi ($)": "150"},
        operation_id=identifier,
        actor_id=1,
        notifications=[
            {
                "kind": "publish_channel",
                "phone_id": phone_id,
                "actor_id": 1,
                "bot_id": 123,
                "data": {"sell_price": "150"},
            }
        ],
    )
    service.mark_notification(identifier, 0, "sending")
    service.mark_notification(identifier, 0, "unknown", "post_id=99")
    service.record_sale(
        phone_id, {"sell_price": "150"}, operation_id=str(uuid4()), actor_id=1
    )
    service.resolve_notification_outcome(
        identifier, 0, sent=True, actor_id=1, channel_post_id=99
    )
    assert [item["payload"]["kind"] for item in service.pending_notifications()] == [
        "sold_channel"
    ]
    bot = fake_bot()
    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    worker = NotificationWorker(DirectWorker(), service, {123: bot})
    await worker.process_once()
    assert "SOTILDI" in bot.edit_message_caption.call_args.kwargs["caption"]
    assert service.get_phone_by_id(phone_id, fresh=True)["Holati"] == "Sotildi"
    bot.send_message.assert_not_called()


def test_manual_notification_resolution_requires_a_current_accounting_role(storage):
    from services.errors import AccessDenied

    service, sheet = storage
    sheet.add_record(
        "Xodimlar",
        {"Telegram ID": "2", "F.I.Sh": "Ali", "Roli": "Sotuvchi", "Holati": "Faol"},
    )
    with pytest.raises(AccessDenied):
        service.resolve_notification_outcome(str(uuid4()), 0, sent=False, actor_id=2)


@pytest.mark.asyncio
async def test_revocation_during_telegram_ack_is_quarantined_until_post_id_is_reconciled(
    storage, monkeypatch
):
    from services.notification_queue import NotificationWorker
    from test_health_check import DirectWorker
    from tests.test_notifications import fake_bot

    service, sheet = storage
    phone_id, identifier = str(uuid4()), str(uuid4())
    add_phone(sheet, phone_id=phone_id)
    payload = {
        "kind": "publish_channel",
        "phone_id": phone_id,
        "actor_id": 1,
        "bot_id": 123,
        "data": {"sell_price": "150"},
    }
    service.update_phone(
        phone_id,
        {"Elon narxi ($)": "150"},
        operation_id=identifier,
        actor_id=1,
        notifications=[payload],
    )
    staff = sheet.sheets["Xodimlar"]
    status_column = staff.values[0].index("Holati")
    bot = fake_bot()

    async def acknowledge(**kwargs):
        staff.values[1][status_column] = "Nofaol"
        return SimpleNamespace(message_id=99)

    bot.send_message.side_effect = acknowledge
    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    worker = NotificationWorker(DirectWorker(), service, {123: bot})
    await worker.process_once()
    assert "post_id=99" in service.notification_statuses()[0]["error"]
    assert not service.get_phone_by_id(phone_id, fresh=True)["Kanal post ID"]
    staff.values[1][status_column] = "Faol"
    with pytest.raises(BusinessRuleError):
        service.update_phone(
            phone_id,
            {"Elon narxi ($)": "150"},
            operation_id=str(uuid4()),
            actor_id=1,
            notifications=[payload],
        )
    service.resolve_notification_outcome(
        identifier, 0, sent=True, actor_id=1, channel_post_id=99
    )
    assert service.get_phone_by_id(phone_id, fresh=True)["Kanal post ID"] == 99
    assert bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_verified_not_sent_resolution_allows_a_fresh_bounded_delivery_attempt(
    storage, monkeypatch
):
    from services.notification_queue import NotificationWorker
    from test_health_check import DirectWorker
    from tests.test_notifications import fake_bot

    service, _ = storage
    identifier = str(uuid4())
    service.add_phone(
        {"imei": "000042", "buy_price": "100"},
        operation_id=identifier,
        actor_id=1,
        notifications=[{"kind": "buy_group", "bot_id": 123, "data": {}}],
    )
    for attempt in range(3):
        service.mark_notification(identifier, 0, "sending")
        service.mark_notification(
            identifier, 0, "unknown" if attempt == 2 else "pending"
        )
    service.resolve_notification_outcome(identifier, 0, sent=False, actor_id=1)
    bot = fake_bot()
    monkeypatch.setattr(config, "GROUP_HARID_ID", "-100123")
    worker = NotificationWorker(DirectWorker(), service, {123: bot})
    await worker.process_once()
    assert bot.send_message.await_count == 1
    assert service.notification_statuses()[0]["state"] == "sent"


@pytest.mark.asyncio
async def test_balance_discloses_unclassified_historical_expenses(storage, monkeypatch):
    from bot_harajat.handlers import harajat_flow as flow
    from test_health_check import DirectWorker

    service, sheet = storage
    sheet.add_record(
        "Chiqimlar",
        {"ID": "historical-expense", "Chiqim turi": "Tasnifsiz", "Summa ($)": 7},
    )
    monkeypatch.setattr(flow, "sheets_service", service)
    monkeypatch.setattr(flow, "io_worker", DirectWorker())
    msg = message("💰 Balance")
    await flow.view_balance(msg)
    assert "Tasniflanmagan chiqim" in msg.answer.call_args.args[0]
    assert "7.00$" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_sotuv_only_diagnostics_check_channel_edit_permission(
    monkeypatch, tmp_path
):
    from services.health_check import SystemHealthChecker
    from test_health_check import DirectWorker, ReadinessService

    class SalesBot:
        id = 123
        token = "sales-token"

        async def get_chat(self, destination):
            return SimpleNamespace(id=destination)

        async def get_chat_member(self, destination, user_id):
            return SimpleNamespace(
                status="administrator", can_edit_messages=False, can_post_messages=True
            )

    path = tmp_path / "credentials.json"
    path.write_text("{}")
    monkeypatch.setattr(config, "GOOGLE_SERVICE_ACCOUNT_FILE", str(path))
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(config, "GROUP_SOTUV_ID", "")
    monkeypatch.setattr(config, "HARID_BOT_TOKEN", "")
    monkeypatch.setattr(config, "SOTUV_BOT_TOKEN", "sales-token")
    checker = SystemHealthChecker(
        sheets=ReadinessService(), drive=ReadinessService(), worker=DirectWorker()
    )
    ready, _, flags = await checker.run_diagnostics(SalesBot(), features=("sotuv",))
    assert not ready
    assert not flags["channel_ok"]


@pytest.mark.asyncio
async def test_diagnostics_ignore_a_disabled_feature_on_a_shared_token(
    monkeypatch, tmp_path
):
    from services.health_check import SystemHealthChecker
    from test_health_check import DirectWorker, ReadinessService

    class PurchaseBot:
        id = 321
        token = "shared-token"

        async def get_chat(self, destination):
            return SimpleNamespace(id=destination)

        async def get_chat_member(self, destination, user_id):
            return SimpleNamespace(
                status="administrator", can_edit_messages=True, can_post_messages=True
            )

    path = tmp_path / "credentials.json"
    path.write_text("{}")
    monkeypatch.setattr(config, "GOOGLE_SERVICE_ACCOUNT_FILE", str(path))
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    monkeypatch.setattr(config, "HARID_BOT_TOKEN", "shared-token")
    monkeypatch.setattr(config, "HARAJAT_BOT_TOKEN", "shared-token")
    monkeypatch.setattr(config, "ENABLED_FEATURES", ("harid", "sotuv"))
    checker = SystemHealthChecker(
        sheets=ReadinessService(), drive=ReadinessService(), worker=DirectWorker()
    )
    await checker.run_diagnostics(PurchaseBot())
    assert list(checker._cache) == [(321, ("harid",))]
