"""Drive access initialized explicitly in the application's single I/O worker."""

import logging
import os
import tempfile
from pathlib import Path

from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_httplib2 import AuthorizedHttp, Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from httplib2 import Http

import config

logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/drive"]
# Some new connections to Google stall for 20+ s from the server while a fresh
# one succeeds at once; give up early and retry (3 attempts fit the IO timeout).
DRIVE_ATTEMPT_SECONDS = 12
DRIVE_RETRIES = 2
_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class DriveUnavailable(RuntimeError):
    """The upload has not been confirmed; no usable URL should be recorded."""


class GoogleDriveService:
    def __init__(self):
        self.service = None
        self._token_file = None

    @property
    def token_file(self) -> Path:
        # Configuration is loaded explicitly after module imports. An injected
        # token path stays available for isolated tests and tooling.
        return self._token_file or Path(config.GOOGLE_OAUTH_TOKEN_FILE)

    @token_file.setter
    def token_file(self, path):
        self._token_file = Path(path)

    def initialize(self) -> bool:
        if self.service is None:
            self._init_service()
        return self.is_connected()

    def _init_service(self) -> None:
        self.service = None
        try:
            # A stalled Google connection is retried on a new one instead of
            # waiting it out; attempts stay inside the IO worker timeout.
            http = Http(timeout=DRIVE_ATTEMPT_SECONDS)
            if self.token_file.exists():
                credentials = UserCredentials.from_authorized_user_file(
                    str(self.token_file), SCOPES
                )
                if credentials.expired:
                    if not credentials.refresh_token:
                        raise DriveUnavailable(
                            "OAuth token uchun qayta avtorizatsiya kerak"
                        )
                    credentials.refresh(Request(http))
                    if not credentials.valid:
                        raise DriveUnavailable("OAuth token yangilanmadi")
                    self._persist_token(credentials.to_json())
                if not credentials.valid:
                    raise DriveUnavailable("OAuth token haqiqiy emas")
            elif Path(config.GOOGLE_SERVICE_ACCOUNT_FILE).is_file():
                credentials = ServiceAccountCredentials.from_service_account_file(
                    config.GOOGLE_SERVICE_ACCOUNT_FILE,
                    scopes=SCOPES,
                )
            else:
                return
            self.service = build(
                "drive",
                "v3",
                http=AuthorizedHttp(credentials, http=http),
                cache_discovery=False,
                num_retries=0,
            )
        except Exception as exc:
            # OAuth/API exception text may contain private identifiers or tokens.
            logger.warning(
                "Google Drive initialization failed (%s)", type(exc).__name__
            )

    def _persist_token(self, contents: str) -> None:
        """Replace the refresh token atomically; interrupted writes keep the old file."""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.token_file.parent,
                prefix=".token-",
                delete=False,
            ) as temp:
                temp_path = Path(temp.name)
                os.chmod(temp.name, 0o600)
                temp.write(contents)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_path, self.token_file)
            temp_path = None
            # Persist the rename too where the host filesystem supports it.
            descriptor = os.open(self.token_file.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def is_connected(self) -> bool:
        return self.service is not None

    def _assert_private_access(self, file_id: str) -> None:
        page_token = None
        seen_tokens = set()
        while True:
            arguments = {
                "fileId": file_id,
                "supportsAllDrives": True,
                "fields": "permissions(type,role),nextPageToken",
                "pageSize": 100,
            }
            if page_token:
                arguments["pageToken"] = page_token
            result = self.service.permissions().list(**arguments).execute(num_retries=DRIVE_RETRIES)
            if not isinstance(result, dict) or not isinstance(
                result.get("permissions"), list
            ):
                raise DriveUnavailable("Drive ruxsatlari tekshirilmadi")
            if any(
                permission.get("type") == "anyone"
                for permission in result["permissions"]
            ):
                raise DriveUnavailable(
                    "IMEI rasmi uchun cheklangan Drive papkasi kerak"
                )
            page_token = result.get("nextPageToken")
            if not page_token:
                return
            if page_token in seen_tokens:
                raise DriveUnavailable("Drive ruxsat sahifalari tekshirilmadi")
            seen_tokens.add(page_token)

    def readiness(self) -> bool:
        if not self.service or not config.DRIVE_FOLDER_ID:
            return False
        try:
            folder = (
                self.service.files()
                .get(
                    fileId=config.DRIVE_FOLDER_ID,
                    fields="id,mimeType,trashed",
                    supportsAllDrives=True,
                )
                .execute(num_retries=DRIVE_RETRIES)
            )
            if folder.get("mimeType") != _FOLDER_MIME_TYPE or folder.get(
                "trashed", False
            ):
                return False
            self._assert_private_access(config.DRIVE_FOLDER_ID)
            return True
        except Exception as exc:
            logger.warning("Google Drive folder read failed (%s)", type(exc).__name__)
            return False

    def download_photo(self, file_id: str, *, max_bytes: int = 10_000_000) -> bytes:
        """Bytes of a stored photo; private files work because the bot owns them."""
        if not self.service:
            raise DriveUnavailable("Google Drive rasm o'qish uchun tayyor emas")
        try:
            content = (
                self.service.files()
                .get_media(fileId=file_id, supportsAllDrives=True)
                .execute(num_retries=DRIVE_RETRIES)
            )
        except Exception as exc:
            logger.warning("Google Drive download failed (%s)", type(exc).__name__)
            raise DriveUnavailable("Rasmni Google Drive'dan olib bo'lmadi") from exc
        if not content or len(content) > max_bytes:
            raise DriveUnavailable("Rasm bo'sh yoki Telegram uchun juda katta")
        return content

    def upload_photo(
        self, local_path: str, file_name: str, *, public: bool = False
    ) -> tuple[str, str, str]:
        """Upload a private record photo; public access requires explicit opt-in.

        Returns (authorized-user view URL, public image URL or empty, trusted
        HYPERLINK formula). An IMEI receipt must always keep ``public=False``.
        Calling code must run this method through the shared I/O worker.
        """
        if not self.service or not config.DRIVE_FOLDER_ID:
            raise DriveUnavailable("Google Drive rasm saqlash uchun tayyor emas")
        if not local_path or not Path(local_path).is_file():
            raise DriveUnavailable("Rasm fayli topilmadi")
        try:
            if not public:
                self._assert_private_access(config.DRIVE_FOLDER_ID)
            media = MediaFileUpload(local_path, mimetype="image/jpeg", resumable=False)
            uploaded = (
                self.service.files()
                .create(
                    body={"name": file_name, "parents": [config.DRIVE_FOLDER_ID]},
                    media_body=media,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute(num_retries=DRIVE_RETRIES)
            )
            file_id = uploaded.get("id")
            if not file_id:
                raise DriveUnavailable("Google Drive fayl ID sini qaytarmadi")
            if not public:
                self._assert_private_access(file_id)
            if public:
                # Never claim a public URL if permission creation is rejected.
                self.service.permissions().create(
                    fileId=file_id,
                    body={"type": "anyone", "role": "reader"},
                    supportsAllDrives=True,
                ).execute(num_retries=DRIVE_RETRIES)
            view_link = (
                uploaded.get("webViewLink")
                or f"https://drive.google.com/file/d/{file_id}/view"
            )
            direct_link = (
                f"https://drive.google.com/uc?export=view&id={file_id}"
                if public
                else ""
            )
            label = ("📷 " + str(file_name)).replace('"', '""')
            formula_url = view_link.replace('"', '""')
            # A formula belongs to the trusted formula cell API, never user text.
            separator = getattr(config, "SHEET_FORMULA_SEPARATOR", ";")
            if separator not in {",", ";"}:
                raise DriveUnavailable("Formula ajratgichi noto'g'ri")
            formula = f'=HYPERLINK("{formula_url}"{separator}"{label}")'
            return view_link, direct_link, formula
        except DriveUnavailable:
            raise
        except Exception as exc:
            logger.error("Google Drive upload failed (%s)", type(exc).__name__)
            raise DriveUnavailable(
                "Google Drive rasmni saqlashni tasdiqlamadi"
            ) from exc


drive_service = GoogleDriveService()
