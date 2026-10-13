import importlib.util

import pytest

from aiogram.fsm.storage.base import StorageKey


def runtime_module():
    assert importlib.util.find_spec("services.runtime") is not None, (
        "Shared runtime is missing"
    )
    from services import runtime

    return runtime


class PersistedRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_fsm_restart_preserves_operation_id_and_isolates_bot_ids():
    runtime = runtime_module()
    redis = PersistedRedis()
    first = runtime.create_fsm_storage(redis, ttl_seconds=86400)
    key = StorageKey(bot_id=10, chat_id=1, user_id=2)
    another_bot = StorageKey(bot_id=11, chat_id=1, user_id=2)
    await first.set_state(key, "Sale:confirm")
    await first.set_data(key, {"operation_id": "stable-uuid", "price": "150.00"})
    restarted = runtime.create_fsm_storage(redis, ttl_seconds=86400)
    assert await restarted.get_state(key) == "Sale:confirm"
    assert (await restarted.get_data(key))["operation_id"] == "stable-uuid"
    assert await restarted.get_data(another_bot) == {}
    assert set(redis.ttls.values()) == {86400}
    isolation = restarted.create_isolation()
    assert isolation.key_builder.build(key, "lock") != isolation.key_builder.build(
        another_bot, "lock"
    )
