"""Offline tests must never load production secrets or contact external services."""

import os
import socket
from pathlib import Path

import dotenv
import pytest


ROOT = Path(__file__).resolve().parents[1]
_load_dotenv = dotenv.load_dotenv


def _test_dotenv(path=None, *args, **kwargs):
    if path is None or Path(path).resolve() == ROOT / ".env":
        return False
    return _load_dotenv(path, *args, **kwargs)


# These guards apply at collection time as well as during test execution.
dotenv.load_dotenv = _test_dotenv
os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = "/nonexistent/oymaoy-offline-test.json"
os.environ["OPERATION_DB_PATH"] = ":memory:"


def _deny_network(*args, **kwargs):
    raise AssertionError("Tests must use fakes instead of external network calls")


socket.socket.connect = _deny_network
socket.create_connection = _deny_network
socket.getaddrinfo = _deny_network


@pytest.fixture(autouse=True)
def offline_test(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)
    monkeypatch.setattr(dotenv, "load_dotenv", _test_dotenv)


@pytest.fixture
def isolated_journal(tmp_path, monkeypatch):
    import config

    path = tmp_path / "operations.sqlite"
    monkeypatch.setattr(config, "OPERATION_DB_PATH", str(path), raising=False)
    return path
