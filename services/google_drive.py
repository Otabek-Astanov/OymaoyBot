import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    Credentials = None
    build = None
    MediaFileUpload = None

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]


class GoogleDriveService:
    def __init__(self):
        self.service = None
        self.local_media_dir = config.BASE_DIR / "media"
        self.local_media_dir.mkdir(exist_ok=True)
        self._init_service()

    def _init_service(self):
        if not Credentials or not build:
            logger.warning("googleapiclient o'rnatilmagan.")
            return

        try:
            if os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_FILE):
                creds = Credentials.from_service_account_file(
                    config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
                )
                self.service = build("drive", "v3", credentials=creds)
                logger.info("Google Drive xizmati muvaffaqiyatli ulandi.")
            else:
                logger.warning(f"Google Drive: {config.GOOGLE_SERVICE_ACCOUNT_FILE} topilmadi.")
        except Exception as e:
            logger.warning(f"Google Drive ulanishida ogohlantirish: {e}")

    def is_connected(self) -> bool:
        return self.service is not None

    def upload_photo(self, local_path: str, file_name: str) -> Tuple[str, str, str]:
        """
        Rasmni yuklaydi.
        Qaytaradi: (web_view_link, direct_image_link, sheet_formula)
        """
        # Agar Google Drive ulanmagan bo'lsa, lokal nusxa saqlanadi
        dest_path = self.local_media_dir / file_name
        shutil.copy2(local_path, dest_path)

        if not self.service:
            logger.info(f"Drive ulanmagan: rasm lokal saqlandi: {dest_path}")
            fake_url = f"https://drive.google.com/open?id=local_{file_name}"
            formula = f'=HYPERLINK("{fake_url}", "📷 {file_name}")'
            return fake_url, fake_url, formula

        try:
            file_metadata = {
                "name": file_name,
                "parents": [config.DRIVE_FOLDER_ID] if config.DRIVE_FOLDER_ID else [],
            }
            media = MediaFileUpload(local_path, mimetype="image/jpeg", resumable=True)
            file = (
                self.service.files()
                .create(body=file_metadata, media_body=media, fields="id, webViewLink, webContentLink")
                .execute()
            )
            file_id = file.get("id")

            # Faylga hamma ko'rishi uchun ruxsat berish
            try:
                self.service.permissions().create(
                    fileId=file_id,
                    body={"type": "anyone", "role": "reader"},
                ).execute()
            except Exception as pe:
                logger.warning(f"Ruxsat berishda ogohlantirish: {pe}")

            view_link = file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
            # Google Sheets IMAGE() formulasi uchun to'g'ridan-to'g'ri link
            direct_image_link = f"https://drive.google.com/uc?export=view&id={file_id}"
            
            # Google Sheets katagi uchun formula (ko'rinadi va ustiga bosganda katta hajmda ochiladi)
            sheet_formula = f'=HYPERLINK("{view_link}", IMAGE("{direct_image_link}"))'
            return view_link, direct_image_link, sheet_formula

        except Exception as e:
            logger.error(f"Google Drive'ga rasm yuklashda xatolik: {e}")
            fake_url = f"https://drive.google.com/open?id=error_{file_name}"
            return fake_url, fake_url, f'=HYPERLINK("{fake_url}", "📷 {file_name}")'


# Singleton instansiya
drive_service = GoogleDriveService()
