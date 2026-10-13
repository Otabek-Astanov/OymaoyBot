from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


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
    access.sheets_service.check_member.assert_called_with(123, force_refresh=True)


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
