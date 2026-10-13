from uuid import uuid4

import pytest

from services.errors import OutcomeUnknown
from services.google_sheets import GoogleSheetsService
from tests.storage_fakes import FakeSpreadsheet


def service_for(sheet, path):
    service = GoogleSheetsService(spreadsheet=sheet, journal_path=path)
    service.initialize()
    return service


def test_google_commit_before_local_confirmation_is_recovered_without_resend(tmp_path):
    sheet = FakeSpreadsheet()
    path = tmp_path / "operations.sqlite"
    service = service_for(sheet, path)
    sheet.fail = TimeoutError("response lost")
    sheet.commit_then_fail = True
    operation_id = str(uuid4())
    with pytest.raises(OutcomeUnknown):
        service.record_income("Rahbariyat", "10", operation_id=operation_id, actor_id=1)
    service.close()
    sheet.fail = None
    service = service_for(sheet, path)
    assert service.recover_pending_operations() == {
        "recovered": [operation_id],
        "quarantined": [],
    }
    assert service.record_income(
        "Rahbariyat", "10", operation_id=operation_id, actor_id=1
    )
    assert len(sheet.calls) == 1
    assert len(sheet.records("Kirimlar")) == 1
    service.close()


def test_absent_remote_ledger_never_causes_blind_resend_and_blocks_other_writes(
    tmp_path,
):
    sheet = FakeSpreadsheet()
    service = service_for(sheet, tmp_path / "operations.sqlite")
    sheet.fail = TimeoutError("connection lost")
    operation_id = str(uuid4())
    with pytest.raises(OutcomeUnknown):
        service.record_income("Rahbariyat", "10", operation_id=operation_id, actor_id=1)
    sheet.fail = None
    assert service.recover_pending_operations()["quarantined"] == [operation_id]
    with pytest.raises(OutcomeUnknown):
        service.record_income("Rahbariyat", "10", operation_id=operation_id, actor_id=1)
    with pytest.raises(OutcomeUnknown):
        service.record_expense("Arenda", "5", operation_id=str(uuid4()), actor_id=1)
    assert len(sheet.calls) == 1
    assert not sheet.records("Kirimlar")
    service.close()


def test_abrupt_stop_after_send_started_becomes_unknown_on_restart(
    tmp_path, monkeypatch
):
    sheet = FakeSpreadsheet()
    path = tmp_path / "operations.sqlite"
    service = service_for(sheet, path)
    operation_id = str(uuid4())
    with monkeypatch.context() as patch:
        patch.setattr(
            sheet, "batch_update", lambda _: (_ for _ in ()).throw(SystemExit())
        )
        with pytest.raises(SystemExit):
            service.record_income(
                "Rahbariyat", "10", operation_id=operation_id, actor_id=1
            )
    assert service.get_operation_status(operation_id)["state"] == "sending"
    service.close()
    service = service_for(sheet, path)
    assert service.get_operation_status(operation_id)["state"] == "unknown"
    assert service.recover_pending_operations()["quarantined"] == [operation_id]
    service.close()


def test_stop_before_sending_allows_safe_prepared_retry(tmp_path, monkeypatch):
    sheet = FakeSpreadsheet()
    service = service_for(sheet, tmp_path / "operations.sqlite")
    operation_id = str(uuid4())
    original = service.journal.transition

    def stop_sending(oid, state, error=""):
        if state == "sending":
            raise SystemExit()
        return original(oid, state, error)

    with monkeypatch.context() as patch:
        patch.setattr(service.journal, "transition", stop_sending)
        with pytest.raises(SystemExit):
            service.record_income(
                "Rahbariyat", "10", operation_id=operation_id, actor_id=1
            )
    assert service.get_operation_status(operation_id)["state"] == "prepared"
    assert not sheet.calls
    assert service.record_income(
        "Rahbariyat", "10", operation_id=operation_id, actor_id=1
    )
    assert len(sheet.calls) == 1
    service.close()


def test_notification_send_started_before_restart_is_quarantined(tmp_path):
    sheet = FakeSpreadsheet()
    path = tmp_path / "operations.sqlite"
    service = service_for(sheet, path)
    operation_id = str(uuid4())
    service.record_income(
        "Rahbariyat",
        "10",
        operation_id=operation_id,
        actor_id=1,
        notifications=[{"kind": "buy_group", "bot_id": 123, "data": {"price": "10"}}],
    )
    assert len(service.pending_notifications()) == 1
    service.mark_notification(operation_id, 0, "sending")
    assert (
        service.journal.connection.execute(
            "SELECT attempts FROM notifications"
        ).fetchone()[0]
        == 1
    )
    service.close()
    service = service_for(sheet, path)
    assert not service.pending_notifications()
    assert (
        service.journal.connection.execute(
            "SELECT state FROM notifications"
        ).fetchone()[0]
        == "unknown"
    )
    assert len(sheet.calls) == 1
    service.close()


def test_remote_ledger_blocks_replay_after_local_backup_loss(tmp_path):
    sheet = FakeSpreadsheet()
    service = service_for(sheet, tmp_path / "operations.sqlite")
    operation_id = str(uuid4())
    notifications = [{"kind": "buy_group", "bot_id": 123, "data": {}}]
    service.record_income(
        "Rahbariyat",
        "10",
        operation_id=operation_id,
        actor_id=1,
        notifications=notifications,
    )
    service.close()
    recovered = service_for(sheet, tmp_path / "older-backup.sqlite")
    assert recovered.record_income(
        "Rahbariyat",
        "10",
        operation_id=operation_id,
        actor_id=1,
        notifications=notifications,
    )
    assert len(sheet.calls) == 1
    assert not recovered.pending_notifications()
    recovered.close()


def test_journal_is_private_and_decimal_payload_is_stored_as_cents(tmp_path):
    import stat

    sheet = FakeSpreadsheet()
    path = tmp_path / "operations.sqlite"
    service = service_for(sheet, path)
    service.record_income("Rahbariyat", "10.50", operation_id=str(uuid4()), actor_id=1)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    raw = service.journal.connection.execute(
        "SELECT payload FROM operations"
    ).fetchone()[0]
    assert '"_money_cents":1050' in raw
    assert service.journal.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert (
        service.journal.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    )
    service.close()


def test_purchase_and_sale_intent_amounts_are_journalled_as_cents(tmp_path):
    from tests.storage_fakes import add_phone

    sheet = FakeSpreadsheet()
    service = service_for(sheet, tmp_path / "operations.sqlite")
    service.add_phone(
        {"imei": "000042", "buy_price": "10.50"}, operation_id=str(uuid4()), actor_id=1
    )
    raw = service.journal.connection.execute(
        "SELECT payload FROM operations WHERE kind='purchase'"
    ).fetchone()[0]
    assert '"buy_price":{"_money_cents":1050}' in raw
    add_phone(sheet)
    service.record_sale(
        "phone-1", {"sell_price": "150.50"}, operation_id=str(uuid4()), actor_id=1
    )
    raw = service.journal.connection.execute(
        "SELECT payload FROM operations WHERE kind='sale'"
    ).fetchone()[0]
    assert '"sell_price":{"_money_cents":15050}' in raw
    service.close()
