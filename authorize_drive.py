import os
import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]

CLIENT_SECRET_FILE = Path(__file__).resolve().parent / "client_secret.json"
TOKEN_FILE = Path(__file__).resolve().parent / "token.json"


def main():
    if not CLIENT_SECRET_FILE.exists():
        print(f"\n❌ XATOLIK: '{CLIENT_SECRET_FILE.name}' fayli topilmadi!")
        print("\nQuyidagi amallarni bajaring:")
        print("1. Google Cloud Console'dan OAuth 2.0 Client ID (Desktop app) yarating.")
        print(f"2. Yuklab olingan JSON faylni '{CLIENT_SECRET_FILE}' nomi bilan ushbu papkaga tashlang.")
        sys.exit(1)

    print("\n🚀 Google Drive OAuth 2.0 avtorizatsiyasi boshlanmoqda...")
    print("Brauzerda Google akkauntingizga kirish sahifasi ochiladi. Unga ruxsat bering.")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_FILE), SCOPES
    )
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as token:
        token.write(creds.to_json())

    print(f"\n✅ Muvaffaqiyatli! '{TOKEN_FILE.name}' yaratildi.")
    print("Endi bot sizning shaxsiy Google Drive'ingizga to'g'ridan-to'g'ri rasm yuklay oladi!")


if __name__ == "__main__":
    main()
