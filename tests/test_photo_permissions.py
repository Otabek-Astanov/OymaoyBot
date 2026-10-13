import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.google_drive import DriveUnavailable, GoogleDriveService


class PhotoPermissionTests(unittest.TestCase):
    def test_drive_http_transport_has_finite_timeout(self):
        with patch.object(GoogleDriveService, "_init_service"):
            service = GoogleDriveService()
        service.token_file = Path("/nonexistent/test-token.json")
        with (
            patch("config.IO_TIMEOUT_SECONDS", 45),
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "services.google_drive.ServiceAccountCredentials.from_service_account_file",
                return_value=Mock(),
            ),
            patch("services.google_drive.build") as build,
        ):
            service.initialize()
        transport = build.call_args.kwargs.get("http")
        self.assertIsNotNone(
            transport, "Drive must not use an unbounded default HTTP transport"
        )
        self.assertLessEqual(transport.http.timeout, 30)

    def test_failed_atomic_token_replace_preserves_previous_token(self):
        with patch.object(GoogleDriveService, "_init_service"):
            service = GoogleDriveService()
        with tempfile.TemporaryDirectory() as temporary:
            service.token_file = Path(temporary) / "token.json"
            service.token_file.write_text("old token fixture")
            with patch(
                "services.google_drive.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(OSError):
                    service._persist_token("new token fixture")
            self.assertEqual(service.token_file.read_text(), "old token fixture")
            self.assertEqual(list(Path(temporary).glob(".token-*")), [])
            service._persist_token("new token fixture")
            self.assertEqual(service.token_file.read_text(), "new token fixture")
            self.assertEqual(os.stat(service.token_file).st_mode & 0o777, 0o600)

    def test_constructing_drive_service_does_not_initialize_network(self):
        with patch.object(GoogleDriveService, "_init_service") as initialize:
            GoogleDriveService()
        initialize.assert_not_called()

    def _service(self):
        with patch.object(GoogleDriveService, "_init_service"):
            service = GoogleDriveService()
        drive = Mock()
        drive.files().create().execute.return_value = {
            "id": "abc123",
            "webViewLink": "https://drive.google.com/file/d/abc123/view",
        }
        drive.permissions().list().execute.return_value = {"permissions": []}
        drive.reset_mock()
        service.service = drive
        return service, drive

    def test_internal_photo_is_private_by_default(self):
        service, drive = self._service()
        with (
            tempfile.NamedTemporaryFile(suffix=".jpg") as photo,
            patch("config.DRIVE_FOLDER_ID", "folder-id"),
        ):
            result = service.upload_photo(photo.name, "imei.jpg")
        self.assertTrue(result[0])
        drive.permissions().create.assert_not_called()
        self.assertEqual(
            result[1],
            "",
            "Private files must not be represented as publicly fetchable images",
        )

    def test_private_upload_rejects_public_inherited_folder_permission(self):
        service, drive = self._service()
        drive.permissions().list().execute.return_value = {
            "permissions": [{"type": "anyone", "role": "reader"}]
        }
        drive.reset_mock()
        with (
            tempfile.NamedTemporaryFile(suffix=".jpg") as photo,
            patch("config.DRIVE_FOLDER_ID", "folder-id"),
        ):
            with self.assertRaises(DriveUnavailable):
                service.upload_photo(photo.name, "imei.jpg")
        drive.files().create.assert_not_called()

    def test_private_folder_audit_checks_every_permissions_page(self):
        service, drive = self._service()
        drive.permissions().list().execute.side_effect = [
            {"permissions": [{"type": "user"}], "nextPageToken": "next-page"},
            {"permissions": [{"type": "anyone"}]},
        ]
        drive.reset_mock()
        with (
            tempfile.NamedTemporaryFile(suffix=".jpg") as photo,
            patch("config.DRIVE_FOLDER_ID", "folder-id"),
        ):
            with self.assertRaises(DriveUnavailable):
                service.upload_photo(photo.name, "imei.jpg")
        self.assertEqual(drive.permissions().list.call_count, 2)
        drive.files().create.assert_not_called()

    def test_public_photo_requires_explicit_opt_in(self):
        service, drive = self._service()
        with (
            tempfile.NamedTemporaryFile(suffix=".jpg") as photo,
            patch("config.DRIVE_FOLDER_ID", "folder-id"),
        ):
            result = service.upload_photo(photo.name, "product.jpg", public=True)
        drive.permissions().create.assert_called_once()
        self.assertTrue(result[1])

    def test_readiness_reads_configured_folder_instead_of_only_service_object(self):
        service, drive = self._service()
        drive.files().get().execute.return_value = {
            "id": "folder-id",
            "mimeType": "application/vnd.google-apps.folder",
            "trashed": False,
        }
        with patch("config.DRIVE_FOLDER_ID", "folder-id"):
            self.assertTrue(service.readiness())
        self.assertEqual(drive.files().get.call_args.kwargs["fileId"], "folder-id")

    def test_oauth_refresh_failure_never_builds_client_with_invalid_token(self):
        with patch.object(GoogleDriveService, "_init_service"):
            service = GoogleDriveService()
        with tempfile.TemporaryDirectory() as tmp:
            service.token_file = Path(tmp) / "token.json"
            service.token_file.write_text("{}")
            creds = SimpleNamespace(
                expired=True,
                refresh_token="example",
                valid=False,
                refresh=Mock(side_effect=RuntimeError("refresh failed")),
            )
            with (
                patch(
                    "services.google_drive.UserCredentials.from_authorized_user_file",
                    return_value=creds,
                ),
                patch("services.google_drive.build") as build,
            ):
                service.initialize()
            build.assert_not_called()
        self.assertFalse(service.is_connected())


if __name__ == "__main__":
    unittest.main()
