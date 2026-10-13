import pytest


class DirectWorker:
    async def call(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


class ReadinessService:
    def __init__(self, result=True):
        self.calls = 0
        self.result = result

    def readiness(self):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class BotStub:
    id = 123
    token = "unused-token"


@pytest.mark.asyncio
async def test_status_does_real_schema_read_and_caches_the_result(
    monkeypatch, tmp_path
):
    import config
    from services.health_check import SystemHealthChecker

    path = tmp_path / "credentials.json"
    path.write_text("{}")
    monkeypatch.setattr(config, "GOOGLE_SERVICE_ACCOUNT_FILE", str(path))
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    sheets = ReadinessService()
    checker = SystemHealthChecker(
        sheets=sheets, drive=ReadinessService(), worker=DirectWorker()
    )
    first = await checker.run_diagnostics(BotStub(), features=("harajat",))
    second = await checker.run_diagnostics(BotStub(), features=("harajat",))
    assert first[0] is True
    assert first == second
    assert sheets.calls == 1


@pytest.mark.asyncio
async def test_readiness_failure_is_not_reported_as_connected(monkeypatch, tmp_path):
    import config
    from services.health_check import SystemHealthChecker

    path = tmp_path / "credentials.json"
    path.write_text("{}")
    monkeypatch.setattr(config, "GOOGLE_SERVICE_ACCOUNT_FILE", str(path))
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    sheets = ReadinessService(RuntimeError("PRIVATE_SECRET_should_never_be_rendered"))
    checker = SystemHealthChecker(
        sheets=sheets, drive=ReadinessService(), worker=DirectWorker()
    )
    ready, report, flags = await checker.run_diagnostics(
        BotStub(), features=("harajat",)
    )
    assert ready is False
    assert flags["sheets_connected"] is False
    assert "PRIVATE_SECRET" not in report


@pytest.mark.asyncio
async def test_non_admin_diagnostics_cannot_trigger_external_reads(monkeypatch):
    import config
    from services.health_check import SystemHealthChecker

    monkeypatch.setattr(config, "ADMIN_IDS", [1])
    sheets = ReadinessService()
    checker = SystemHealthChecker(
        sheets=sheets, drive=ReadinessService(), worker=DirectWorker()
    )
    ready, report, _ = await checker.run_diagnostics(BotStub(), caller_id=2)
    assert ready is False
    assert sheets.calls == 0
    assert "ruxsat" in report.lower()


@pytest.mark.asyncio
async def test_temporary_bot_session_closes_when_chat_read_fails(monkeypatch, tmp_path):
    import config
    import services.health_check as module

    closed = []

    class TemporaryBot:
        id = 456
        token = "separate-token"

        @property
        def session(self):
            return self

        async def get_chat(self, *_):
            raise RuntimeError("not allowed")

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(module, "Bot", lambda **kwargs: TemporaryBot())
    monkeypatch.setattr(config, "HARID_BOT_TOKEN", "separate-token")
    monkeypatch.setattr(config, "CHANNEL_ID", "-100123")
    monkeypatch.setattr(config, "GROUP_HARID_ID", "")
    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "")
    path = tmp_path / "credentials.json"
    path.write_text("{}")
    monkeypatch.setattr(config, "GOOGLE_SERVICE_ACCOUNT_FILE", str(path))
    checker = module.SystemHealthChecker(
        sheets=ReadinessService(), drive=ReadinessService(), worker=DirectWorker()
    )
    await checker.run_diagnostics(BotStub(), features=("harid",))
    assert closed == [True]
