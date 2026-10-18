"""Slow Google connections: retried quickly, and the user is told what happened."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import config


def _msg():
    return SimpleNamespace(answer=AsyncMock(), from_user=SimpleNamespace(id=1))


@pytest.mark.asyncio
async def test_photo_upload_failure_says_what_to_do():
    from bot_common.handler_support import safe_handler
    from services.errors import PhotoUploadError

    @safe_handler
    async def step(message, state):
        raise PhotoUploadError("Rasmni arxivlash tasdiqlanmadi")

    msg = _msg()
    await step(msg, None)
    text = msg.answer.call_args.args[0]
    assert "Rasm Google Drive'ga yuklanmadi" in text
    assert "Hech narsa saqlanmadi" in text and "qayta yuboring" in text


@pytest.mark.asyncio
async def test_other_google_failures_say_nothing_was_saved():
    from bot_common.handler_support import safe_handler
    from services.errors import StorageReadError

    @safe_handler
    async def step(message, state):
        raise StorageReadError("Telefonlar: o'qib bo'lmadi")

    msg = _msg()
    await step(msg, None)
    text = msg.answer.call_args.args[0]
    assert "Google Sheets bilan aloqa bo'lmadi" in text and "Hech narsa saqlanmadi" in text


class _Request:
    def __init__(self, calls, name, result):
        self.calls, self.name, self.result = calls, name, result

    def execute(self, **kwargs):
        self.calls.append((self.name, kwargs))
        return self.result


class _Service:
    def __init__(self):
        self.calls = []
        self.media = None

    def files(self):
        outer = self

        class Files:
            def create(self, **kwargs):
                outer.media = kwargs["media_body"]
                return _Request(outer.calls, "create", {"id": "abc", "webViewLink": "https://drive.google.com/file/d/abc/view"})

            def get_media(self, **kwargs):
                return _Request(outer.calls, "get_media", b"jpeg")

        return Files()

    def permissions(self):
        outer = self

        class Permissions:
            def create(self, **kwargs):
                return _Request(outer.calls, "permission", {})

        return Permissions()


def test_drive_requests_retry_stalled_connections(tmp_path, monkeypatch):
    from services import google_drive

    monkeypatch.setattr(config, "DRIVE_FOLDER_ID", "folder")
    drive = google_drive.GoogleDriveService()
    drive.service = _Service()
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"\xff\xd8\xff")
    link, direct, _ = drive.upload_photo(str(photo), "x.jpg", public=True)
    assert link.endswith("/abc/view") and direct
    assert drive.download_photo("abc") == b"jpeg"
    assert [name for name, _ in drive.service.calls] == ["create", "permission", "get_media"]
    assert all(kw == {"num_retries": google_drive.DRIVE_RETRIES} for _, kw in drive.service.calls)
    assert drive.service.media.resumable() is False  # one request, not a multi-step upload
    assert google_drive.DRIVE_ATTEMPT_SECONDS * (google_drive.DRIVE_RETRIES + 1) < 45
