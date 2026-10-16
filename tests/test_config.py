import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:" + "A" * 35


@pytest.fixture
def settings_module(monkeypatch):
    import dotenv

    calls = []
    monkeypatch.setattr(
        dotenv, "load_dotenv", lambda *args, **kwargs: calls.append(args)
    )
    for key in (
        "BOT_TOKEN",
        "HARID_BOT_TOKEN",
        "SOTUV_BOT_TOKEN",
        "HARAJAT_BOT_TOKEN",
        "ADMIN_IDS",
        "SPREADSHEET_ID",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        "FSM_STORAGE_URL",
        "ENABLED_FEATURES",
    ):
        monkeypatch.delenv(key, raising=False)
    spec = importlib.util.spec_from_file_location("isolated_config", ROOT / "config.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "isolated_config", module)
    spec.loader.exec_module(module)
    return module, calls


def test_import_does_not_read_dotenv(settings_module):
    _, calls = settings_module
    assert calls == []


def test_blank_specific_token_falls_back_to_common(settings_module, monkeypatch):
    config, _ = settings_module
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("HARID_BOT_TOKEN", "  ")
    reload_config = getattr(config, "load_runtime_config", None)
    assert callable(reload_config), "Explicit runtime configuration loader is missing"
    reload_config(env_file=None)
    assert config.HARID_BOT_TOKEN == TOKEN


def test_invalid_configuration_is_rejected_before_service_io(settings_module):
    config, _ = settings_module
    validate = getattr(config, "validate_runtime_config", None)
    assert callable(validate), "Startup validation is missing"
    with pytest.raises(config.ConfigurationError, match="TOKEN"):
        validate()


def test_valid_configuration_requires_redis_and_credentials(
    settings_module, monkeypatch, tmp_path
):
    config, _ = settings_module
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("SPREADSHEET_ID", "a" * 40)
    creds = tmp_path / "service-account.json"
    creds.write_text("{}")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(creds))
    loader = getattr(config, "load_runtime_config", None)
    assert callable(loader), "Runtime loader is missing"
    loader(env_file=None)
    with pytest.raises(config.ConfigurationError, match="FSM_STORAGE_URL"):
        config.validate_runtime_config()
    monkeypatch.setenv("FSM_STORAGE_URL", "redis://localhost:6379/0")
    loader(env_file=None)
    config.validate_runtime_config()
    monkeypatch.setenv("FSM_STORAGE_URL", "memory://")
    loader(env_file=None)
    config.validate_runtime_config()
    assert config.fsm_uses_memory()
    monkeypatch.setenv("FSM_STORAGE_URL", "http://localhost:6379/0")
    loader(env_file=None)
    with pytest.raises(config.ConfigurationError, match="FSM_STORAGE_URL"):
        config.validate_runtime_config()


def test_all_required_sheets_and_stable_phone_identity(settings_module):
    config, _ = settings_module
    assert len(config.DEFAULT_HEADERS) == 8
    assert "Telefon ID" in config.DEFAULT_HEADERS[config.SHEET_PHONES]
    assert "Elon narxi ($)" in config.DEFAULT_HEADERS[config.SHEET_PHONES]


def test_enabled_features_switch_off_a_bot_that_shares_bot_token(
    settings_module, monkeypatch
):
    # An empty HARAJAT_BOT_TOKEN falls back to BOT_TOKEN, so only this setting
    # can keep Kirim/Chiqim out of the purchase bot.
    config, _ = settings_module
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("HARAJAT_BOT_TOKEN", "")
    config.load_runtime_config(env_file=None)
    assert config.ENABLED_FEATURES == ("harid", "sotuv", "harajat")
    assert config.HARAJAT_BOT_TOKEN == TOKEN
    monkeypatch.setenv("ENABLED_FEATURES", " Harid, sotuv ,harid ")
    config.load_runtime_config(env_file=None)
    assert config.ENABLED_FEATURES == ("harid", "sotuv")
    monkeypatch.setenv("ENABLED_FEATURES", "harid,kassa")
    config.load_runtime_config(env_file=None)
    with pytest.raises(config.ConfigurationError, match="ENABLED_FEATURES"):
        config.validate_runtime_config()
