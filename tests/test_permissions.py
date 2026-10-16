from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


@pytest.mark.asyncio
async def test_revoked_role_blocks_running_flow(monkeypatch):
    from bot_common import access

    monkeypatch.setattr(
        access.sheets_service,
        "check_member",
        Mock(return_value=(True, "Investor", "Investor")),
    )
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=123), text="✅ Ha", answer=AsyncMock()
    )
    state = SimpleNamespace(
        get_state=AsyncMock(return_value="SotuvStates:confirm_sale")
    )
    handler = AsyncMock()
    await access.AccessMiddleware({"sotuv"})(handler, event, {"state": state})
    handler.assert_not_called()
    access.sheets_service.check_member.assert_called_with(123)  # cached lookup


@pytest.mark.asyncio
async def test_permission_read_failure_is_closed(monkeypatch):
    from bot_common import access
    from services.errors import StorageUnavailable

    monkeypatch.setattr(
        access.sheets_service, "check_member", Mock(side_effect=StorageUnavailable())
    )
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=123), text="📉 Chiqim", answer=AsyncMock()
    )
    handler = AsyncMock()
    await access.AccessMiddleware({"harajat"})(handler, event, {})
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_seller_cannot_create_financial_expense(monkeypatch):
    from bot_common import access

    monkeypatch.setattr(
        access.sheets_service,
        "check_member",
        Mock(return_value=(True, "Sotuvchi", "Seller")),
    )
    event = SimpleNamespace(
        from_user=SimpleNamespace(id=123), text="📉 Chiqim", answer=AsyncMock()
    )
    handler = AsyncMock()
    await access.AccessMiddleware({"harajat"})(handler, event, {})
    handler.assert_not_called()


@pytest.fixture
def staff_storage(storage, monkeypatch):
    import config

    monkeypatch.setattr(config, "ADMIN_IDS", [777])
    return storage


def _add_staff(sheet, telegram_id, status, role="Admin"):
    sheet.add_record(
        "Xodimlar",
        {"Telegram ID": str(telegram_id), "F.I.Sh": "Bek", "Roli": role, "Holati": status},
    )


def test_inactive_listed_admin_is_inactive_everywhere(staff_storage):
    service, sheet = staff_storage
    _add_staff(sheet, 777, "Nofaol")
    assert service.check_member(777, force_refresh=True)[0] is False
    assert service.check_member(777, fresh=True)[0] is False


@pytest.mark.asyncio
async def test_start_does_not_override_inactive_admin(staff_storage, monkeypatch):
    from bot_common import navigation
    from services.errors import BusinessRuleError

    service, sheet = staff_storage
    _add_staff(sheet, 777, "Nofaol")

    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(navigation, "sheets_service", service)
    monkeypatch.setattr(navigation.io_worker, "call", direct)
    with pytest.raises(BusinessRuleError):
        await navigation.member(777)


def test_unreadable_staff_sheet_uses_last_rows_then_bootstrap_admin(staff_storage):
    service, sheet = staff_storage
    _add_staff(sheet, 555, "Nofaol", role="Sotuvchi")
    service.check_member(555, force_refresh=True)  # fills the cache
    sheet.read_failure = "Xodimlar"
    assert service.check_member(555, force_refresh=True)[0] is False
    assert service.check_member(777, force_refresh=True) == (True, "Admin", "Bosh Admin")
    with pytest.raises(Exception):
        service.check_member(777, fresh=True)  # financial authorization stays strict


def test_cached_access_never_lets_a_revoked_user_write(staff_storage):
    # Navigation may use a cached "active"; the commit re-reads Xodimlar fresh.
    from uuid import uuid4
    from services.errors import AccessDenied

    service, sheet = staff_storage
    _add_staff(sheet, 555, "Faol", role="Sotuvchi")
    assert service.check_member(555)[0] is True  # now cached
    rows = sheet.sheets["Xodimlar"].values
    status = rows[0].index("Holati")
    next(r for r in rows if r and r[0] == "555")[status] = "Nofaol"
    assert service.check_member(555)[0] is True  # still the cached view
    with pytest.raises(AccessDenied):
        service.add_phone(
            {"imei": "777888", "buy_price": "100", "payment_type": "Naqd"},
            operation_id=str(uuid4()),
            actor_id=555,
        )
