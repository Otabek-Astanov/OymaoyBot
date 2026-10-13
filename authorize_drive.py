import os
import sys
import tempfile
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

import config

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]

CLIENT_SECRET_FILE = Path(__file__).resolve().parent / "client_secret.json"


def main():
    config.load_runtime_config()
    if not CLIENT_SECRET_FILE.exists():
        print(f"\n❌ XATOLIK: '{CLIENT_SECRET_FILE.name}' fayli topilmadi!")
        print("\nQuyidagi amallarni bajaring:")
        print("1. Google Cloud Console'dan OAuth 2.0 Client ID (Desktop app) yarating.")
        print(
            f"2. Yuklab olingan JSON faylni '{CLIENT_SECRET_FILE}' nomi bilan ushbu papkaga tashlang."
        )
        sys.exit(1)

    print("\n🚀 Google Drive OAuth 2.0 avtorizatsiyasi boshlanmoqda...")
    print(
        "Brauzerda Google akkauntingizga kirish sahifasi ochiladi. Unga ruxsat bering."
    )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    target = Path(config.GOOGLE_OAUTH_TOKEN_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, delete=False
        ) as token:
            temporary = Path(token.name)
            token.write(creds.to_json())
            token.flush()
            os.fsync(token.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()

    print(f"\n✅ Muvaffaqiyatli! '{target.name}' yaratildi.")
    print(
        "Endi bot sizning shaxsiy Google Drive'ingizga to'g'ridan-to'g'ri rasm yuklay oladi!"
    )


if __name__ == "__main__":
    main()
