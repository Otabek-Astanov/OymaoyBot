import asyncio
import importlib.util
import sys
from types import SimpleNamespace

import pytest


def runtime_module():
    assert importlib.util.find_spec("services.runtime") is not None, (
        "Shared runtime is missing"
    )
    from services import runtime

    return runtime


def test_partial_duplicate_tokens_have_one_group_per_token():
    runtime = runtime_module()
    groups = runtime.group_tokens({"harid": "a", "sotuv": "a", "harajat": "b"})
    assert groups == {"a": ("harid", "sotuv"), "b": ("harajat",)}


def test_no_configured_token_is_a_startup_error():
    runtime = runtime_module()
    with pytest.raises(ValueError):
        runtime.group_tokens({"harid": "", "sotuv": "", "harajat": ""})


def test_writer_lock_rejects_a_second_runtime(tmp_path):
    runtime = runtime_module()
    first = runtime.WriterProcessLock(tmp_path / "writer.lock")
    second = runtime.WriterProcessLock(tmp_path / "writer.lock")
    with first:
        with pytest.raises(runtime.RuntimeStartupError, match="writer"):
            second.acquire()
    with second:
        pass


@pytest.mark.asyncio
async def test_get_me_failure_still_closes_session():
    runtime = runtime_module()
    closed = []

    class Session:
        async def close(self):
            closed.append(True)

    class BrokenBot:
        session = Session()

        async def get_me(self):
            raise RuntimeError("Telegram unavailable")

    with pytest.raises(RuntimeError, match="Telegram unavailable"):
        await runtime.identify_bot(BrokenBot())
    assert closed == [True]


@pytest.mark.asyncio
async def test_one_polling_failure_cancels_every_other_polling():
    runtime = runtime_module()
    cancelled = []

    async def failing():
        await asyncio.sleep(0.01)
        raise RuntimeError("critical polling failure")

    async def other():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    with pytest.raises(RuntimeError, match="critical polling failure"):
        await runtime.supervise([failing(), other()], asyncio.Event())
    assert cancelled == [True]


@pytest.mark.asyncio
async def test_stop_signal_cancels_all_polling():
    runtime = runtime_module()
    stopped = asyncio.Event()
    closed = []

    async def polling():
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    task = asyncio.create_task(runtime.supervise([polling(), polling()], stopped))
    await asyncio.sleep(0)
    stopped.set()
    await task
    assert closed == [True, True]


@pytest.mark.asyncio
async def test_invalid_configuration_never_calls_google_worker(monkeypatch):
    import config

    runtime = runtime_module()
    monkeypatch.setattr(config, "load_runtime_config", lambda: None)
    monkeypatch.setattr(config, "HARID_BOT_TOKEN", "")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Google IO was reached before validation")

    monkeypatch.setattr(runtime.io_worker, "call", forbidden)
    with pytest.raises(config.ConfigurationError):
        await runtime.run(("harid",))


@pytest.mark.asyncio
async def test_runtime_closes_all_resources_when_second_bot_login_fails(
    monkeypatch, tmp_path
):
    import config

    runtime = runtime_module()
    closed_bots, closed_redis = [], []
    monkeypatch.setattr(config, "load_runtime_config", lambda: None)
    monkeypatch.setattr(config, "validate_runtime_config", lambda features: None)
    monkeypatch.setattr(config, "HARID_BOT_TOKEN", "first")
    monkeypatch.setattr(config, "SOTUV_BOT_TOKEN", "second")
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    monkeypatch.setattr(config, "OPERATION_DB_PATH", str(tmp_path / "journal.sqlite"))

    class FakeRedis:
        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()

        async def ping(self):
            return True

        async def aclose(self):
            closed_redis.append(True)

    class FakeBot:
        def __init__(self, token, **kwargs):
            self.token = token
            self.id = 1 if token == "first" else 2
            self.session = self

        async def get_me(self):
            if self.token == "second":
                raise RuntimeError("login failed")
            return SimpleNamespace(id=self.id)

        async def close(self):
            closed_bots.append(self.token)

        async def delete_webhook(self, **kwargs):
            assert kwargs["drop_pending_updates"] is False

    class DirectWorker:
        async def call(self, fn, *args, **kwargs):
            return fn(*args, **kwargs)

        async def close(self):
            pass

    async def no_op():
        pass

    google = SimpleNamespace(
        initialize=lambda: True,
        readiness=lambda: True,
        recover_pending_operations=lambda: [],
    )
    monkeypatch.setitem(
        sys.modules, "services.google_sheets", SimpleNamespace(sheets_service=google)
    )
    monkeypatch.setitem(
        sys.modules, "services.google_drive", SimpleNamespace(drive_service=google)
    )
    monkeypatch.setitem(
        sys.modules,
        "services.notification_queue",
        SimpleNamespace(NotificationWorker=object),
    )
    monkeypatch.setattr(runtime, "Redis", FakeRedis)
    monkeypatch.setattr(runtime, "Bot", FakeBot)
    monkeypatch.setattr(runtime, "io_worker", DirectWorker())
    monkeypatch.setattr(
        runtime,
        "create_dispatcher",
        lambda *args: SimpleNamespace(fsm=SimpleNamespace(close=no_op)),
    )
    with pytest.raises(RuntimeError, match="login failed"):
        await runtime.run(("harid", "sotuv"))
    assert {"first", "second"} <= set(closed_bots)
    assert len(closed_redis) == 2


@pytest.mark.asyncio
async def test_dispatcher_cancels_active_updates_before_fsm_shutdown(monkeypatch):
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    runtime = runtime_module()
    managed = getattr(runtime, "ManagedDispatcher", None)
    assert managed is not None, "Polling shutdown must own active update tasks"
    finished = []

    async def feed(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            finished.append("update")

    monkeypatch.setattr(Dispatcher, "feed_update", feed)
    dispatcher = managed(storage=MemoryStorage())
    task = asyncio.create_task(dispatcher.feed_update(None, None))
    await asyncio.sleep(0)
    await dispatcher.emit_shutdown()
    assert task.cancelled()
    assert finished == ["update"]


@pytest.mark.asyncio
async def test_supervisor_calls_public_shutdown_before_cancelling_polling():
    runtime = runtime_module()
    seen = []
    stop = asyncio.Event()

    async def polling():
        try:
            await asyncio.Event().wait()
        finally:
            seen.append("cancel")

    async def shutdown():
        seen.append("public-stop")

    import inspect

    assert "shutdown" in inspect.signature(runtime.supervise).parameters, (
        "Public dispatcher shutdown is missing"
    )
    task = asyncio.create_task(runtime.supervise([polling()], stop, shutdown=shutdown))
    await asyncio.sleep(0)
    stop.set()
    await task
    assert seen == ["public-stop", "cancel"]


class _StopAfterRedis(Exception):
    pass


def _patch_until_google(monkeypatch, tmp_path, runtime, storage_url, redis_cls):
    import config

    monkeypatch.setattr(config, "load_runtime_config", lambda: None)
    monkeypatch.setattr(config, "validate_runtime_config", lambda features: None)
    monkeypatch.setattr(config, "HARID_BOT_TOKEN", "first")
    monkeypatch.setattr(config, "FSM_STORAGE_URL", storage_url)
    monkeypatch.setattr(config, "OPERATION_DB_PATH", str(tmp_path / "journal.sqlite"))

    def stop():
        raise _StopAfterRedis

    class DirectWorker:
        async def call(self, fn, *args, **kwargs):
            return fn(*args, **kwargs)

        async def close(self):
            pass

    google = SimpleNamespace(initialize=stop)
    monkeypatch.setitem(
        sys.modules, "services.google_sheets", SimpleNamespace(sheets_service=google)
    )
    monkeypatch.setitem(
        sys.modules, "services.google_drive", SimpleNamespace(drive_service=google)
    )
    monkeypatch.setattr(runtime, "Redis", redis_cls)
    monkeypatch.setattr(runtime, "io_worker", DirectWorker())


@pytest.mark.asyncio
async def test_unreachable_redis_refuses_startup_without_memory_fallback(
    monkeypatch, tmp_path
):
    runtime = runtime_module()
    closed = []

    class DownRedis:
        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()

        async def ping(self):
            raise ConnectionError("redis down")

        async def aclose(self):
            closed.append(True)

    _patch_until_google(
        monkeypatch, tmp_path, runtime, "redis://localhost:6379/0", DownRedis
    )
    with pytest.raises(runtime.RuntimeStartupError, match="Redis"):
        await runtime.run(("harid",))
    assert closed == [True]


@pytest.mark.asyncio
async def test_memory_url_skips_redis_explicitly(monkeypatch, tmp_path):
    runtime = runtime_module()

    class NoRedis:
        @classmethod
        def from_url(cls, *args, **kwargs):
            raise AssertionError("memory:// must not connect to Redis")

    _patch_until_google(monkeypatch, tmp_path, runtime, "memory://", NoRedis)
    with pytest.raises(_StopAfterRedis):
        await runtime.run(("harid",))



@pytest.mark.asyncio
async def test_runtime_starts_only_enabled_features(monkeypatch, tmp_path):
    runtime = runtime_module()
    import config

    seen = []

    class Stop(Exception):
        pass

    def validate(features):
        seen.append(features)
        raise Stop

    monkeypatch.setattr(config, "load_runtime_config", lambda: None)
    monkeypatch.setattr(config, "ENABLED_FEATURES", ("harid", "sotuv"))
    monkeypatch.setattr(config, "validate_runtime_config", validate)
    with pytest.raises(Stop):
        await runtime.run()
    assert seen == [("harid", "sotuv")]
