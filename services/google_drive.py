import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

try:
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google.oauth2.credentials import Credentials as UserCredentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    ServiceAccountCredentials = None
    UserCredentials = None
    Request = None
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
        self.token_file = config.BASE_DIR / "token.json"
        self._init_service()

    def _init_service(self):
        if not build:
            logger.warning("googleapiclient o'rnatilmagan.")
            return

        try:
            # 1. Avval User OAuth (token.json) tekshiriladi (agar foydalanuvchi ruxsat bergan bo'lsa)
            if self.token_file.exists() and UserCredentials:
                creds = UserCredentials.from_authorized_user_file(str(self.token_file), SCOPES)
                if creds and creds.expired and creds.refresh_token and Request:
                    try:
                        creds.refresh(Request())
                        with open(self.token_file, "w") as tf:
                            tf.write(creds.to_json())
                    except Exception as re:
                        logger.warning(f"OAuth token yangilashda xato: {re}")
                self.service = build("drive", "v3", credentials=creds)
                logger.info("Google Drive xizmati User OAuth orqali muvaffaqiyatli ulandi.")
                return

            # 2. Aks holda Service Account orqali ulanish
            if os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_FILE) and ServiceAccountCredentials:
                creds = ServiceAccountCredentials.from_service_account_file(
                    config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
                )
                self.service = build("drive", "v3", credentials=creds)
                logger.info("Google Drive xizmati Service Account orqali ulandi.")
            else:
                logger.warning(f"Google Drive: {config.GOOGLE_SERVICE_ACCOUNT_FILE} topilmadi.")
        except Exception as e:
            logger.warning(f"Google Drive ulanishida ogohlantirish: {e}")

    def is_connected(self) -> bool:
        return self.service is not None

    def _get_formula_sep(self) -> str:
        try:
            from services.google_sheets import sheets_service
            return sheets_service.formula_sep
        except Exception:
            return ";"

    def upload_photo(self, local_path: str, file_name: str) -> Tuple[str, str, str]:
        """
        Rasmni Google Drive'ga yuklaydi.
        Agar Google Drive ulanmagan yoki DRIVE_FOLDER_ID bo'lmasa, lokalda saqlanmaydi va bo'sh qiymat qaytaradi.
        Qaytaradi: (web_view_link, direct_image_link, sheet_formula)
        """
        if not self.service or not config.DRIVE_FOLDER_ID:
            logger.info("Google Drive sozlanmagan, rasm yuklanmadi.")
            return "", "", ""

        if not local_path or not os.path.exists(local_path):
            logger.warning(f"Yuklash uchun rasm fayli topilmadi: {local_path}")
            return "", "", ""

        try:
            file_metadata = {
                "name": file_name,
                "parents": [config.DRIVE_FOLDER_ID],
            }
            media = MediaFileUpload(local_path, mimetype="image/jpeg", resumable=True)
            file = (
                self.service.files()
                .create(
                    body=file_metadata,
                    media_body=media,
                    fields="id, webViewLink, webContentLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
            file_id = file.get("id")

            # Faylga hamma ko'rishi uchun ruxsat berish
            try:
                self.service.permissions().create(
                    fileId=file_id,
                    body={"type": "anyone", "role": "reader"},
                    supportsAllDrives=True,
                ).execute()
            except Exception as pe:
                logger.warning(f"Ruxsat berishda ogohlantirish: {pe}")

            view_link = file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
            direct_image_link = f"https://drive.google.com/uc?export=view&id={file_id}"
            # Google Sheets katagi uchun formula: bosilganda Drive'da ochiladigan havola
            sep = self._get_formula_sep()
            sheet_formula = f'=HYPERLINK("{view_link}"{sep} "📷 {file_name}")'
            return view_link, direct_image_link, sheet_formula

        except Exception as e:
            logger.error(f"Google Drive'ga rasm yuklashda xatolik: {e}")
            return "", "", ""


# Singleton instansiya
drive_service = GoogleDriveService()
