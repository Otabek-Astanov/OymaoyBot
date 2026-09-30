import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

# Telegram Bot Tokens
# Agar bitta bot bilan test qilinayotgan bo'lsa, BOT_TOKEN ishlatiladi.
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
HARID_BOT_TOKEN = os.getenv("HARID_BOT_TOKEN", BOT_TOKEN).strip()
SOTUV_BOT_TOKEN = os.getenv("SOTUV_BOT_TOKEN", BOT_TOKEN).strip()
HARAJAT_BOT_TOKEN = os.getenv("HARAJAT_BOT_TOKEN", BOT_TOKEN).strip()

# Admin IDs
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [
    int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()
]

# Telegram Kanallar va Guruhlar
# Masalan: -1001234567890 yoki @kanal_username
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
GROUP_HARID_ID = os.getenv("GROUP_HARID_ID", "").strip()
GROUP_SOTUV_ID = os.getenv("GROUP_SOTUV_ID", "").strip()

# Google Cloud & Sheets sozlamalari
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE", str(BASE_DIR / "credentials.json")
)
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip()
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()

# Google Sheets varaqlari nomlari (To'liq o'zbek tilida)
SHEET_STAFF = "Xodimlar"
SHEET_MEMBERS = SHEET_STAFF  # A'zolar va Xodimlar yagona jadvalga birlashtirildi
SHEET_PHONES = "Telefonlar"
SHEET_EXPENSES = "Chiqimlar"
SHEET_INCOMES = "Kirimlar"
SHEET_PARTNERS = "Hamkorlar"
SHEET_MODELS = "Modellar"
SHEET_TEMPLATES = "Shablonlar"

# Barcha kerakli varaqlar va ularning sarlavhalari (Headers)
DEFAULT_HEADERS = {
    SHEET_STAFF: [
        "Telegram ID", "F.I.Sh", "Telefon raqami", "Roli", "Holati",
        "Jami KPI ($)", "To'langan KPI ($)", "Qoldiq KPI ($)"
    ],
    SHEET_PHONES: [
        # Harid ma'lumotlari
        "Harid sanasi", "IMEI", "Brend", "Versiya", "Turi", "Xotira",
        "Batareya %", "Rang", "Karobka", "Harid narxi ($)", "Telefon egasi",
        "Telefon egasi telefoni", "Qabul qilgan xodim", "Harid to'lov turi", "Harid qarz summasi ($)",
        "IMEI rasmi", "Telefon rasmi",
        # Tannarx va Remont
        "Remont xarajati ($)", "Jami tannarx ($)",
        # Kanal post
        "Kanal post ID",
        # Sotuv ma'lumotlari
        "Sotuv narxi ($)", "Xaridor ismi", "Xaridor telefoni",
        "Sotuv to'lov turi", "Hamkor nomi", "Boshlang'ich to'lov ($)",
        "Hamkor qarzi ($)", "Xodim KPI ($)", "Do'kon sotuvchisi", "Sotilgan sana",
        # Natija va Foyda
        "Sof foyda ($)", "Holati"
    ],
    SHEET_EXPENSES: [
        "ID", "Sana", "Chiqim turi", "Summa ($)", "IMEI", "Xodim ismi",
        "Qabul qiluvchi", "Kiritgan shaxs"
    ],
    SHEET_INCOMES: [
        "ID", "Sana", "Kirim turi", "Summa ($)", "Hamkor nomi", "IMEI",
        "Manba", "Kiritgan shaxs"
    ],
    SHEET_PARTNERS: [
        "Hamkor nomi", "Hozirgi qarzdorlik ($)"
    ],
    SHEET_MODELS: [
        "Brend", "Versiya", "Turlari"
    ],
    SHEET_TEMPLATES: [
        "Shablon turi", "Matn"
    ]
}
