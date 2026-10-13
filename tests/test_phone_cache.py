from uuid import uuid4

import pytest

from services.errors import OutcomeUnknown, StorageReadError
from tests.storage_fakes import add_phone
from tests.test_idempotency import storage as storage_fixture

storage = storage_fixture


def test_failed_update_does_not_change_cached_phone(storage):
    service, sheet = storage
    add_phone(sheet)
    cached = service.get_phone_by_id("phone-1")
    sheet.fail = TimeoutError("request outcome unknown")
    with pytest.raises(OutcomeUnknown):
        service.update_phone(
            "phone-1", {"Karobka": "Ha"}, operation_id=str(uuid4()), actor_id=1
        )
    assert service.get_phone_by_id("phone-1") == cached
    assert service.get_phone_by_id("phone-1").get("Karobka") != "Ha"


def test_failed_fresh_read_never_falls_back_to_stale_cache(storage):
    service, sheet = storage
    add_phone(sheet)
    service.get_phone_by_id("phone-1")
    sheet.read_failure = "Telefonlar"
    with pytest.raises(StorageReadError):
        service.get_phone_by_id("phone-1", fresh=True)
