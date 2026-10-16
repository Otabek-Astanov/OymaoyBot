"""Configuration constants are pure at import; runtime explicitly loads .env."""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
FEATURES = ("harid", "sotuv", "harajat")
TOKEN_PATTERN = re.compile(r"^[0-9]{5,}:[A-Za-z0-9_-]{30,}$")

# Compatibility names are refreshed together by load_runtime_config(). These
# annotations keep the public settings discoverable without reading .env.
BOT_TOKEN: str
HARID_BOT_TOKEN: str
SOTUV_BOT_TOKEN: str
HARAJAT_BOT_TOKEN: str
ADMIN_IDS_RAW: str
ADMIN_IDS: list[int]
CHANNEL_ID: str
GROUP_HARID_ID: str
GROUP_SOTUV_ID: str
SPREADSHEET_ID: str
DRIVE_FOLDER_ID: str
FSM_STORAGE_URL: str
GOOGLE_SERVICE_ACCOUNT_FILE: str
DRIVE_TOKEN_FILE: str
GOOGLE_OAUTH_TOKEN_FILE: str
MEDIA_DIR: str
OPERATION_DB_PATH: str
FSM_TTL_SECONDS: int
IO_TIMEOUT_SECONDS: int
IO_MAX_PENDING: int
DROP_PENDING_UPDATES: bool


class ConfigurationError(ValueError):
    """Invalid startup settings, with secret-free messages."""


def _text(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _positive_integer(key: str, default: int) -> int:
    raw = _text(key, str(default))
    try:
        value = int(raw)
    except ValueError:
        return 0  # validation reports the field name without exposing its value
    return value


def _refresh_settings() -> None:
    global BOT_TOKEN, HARID_BOT_TOKEN, SOTUV_BOT_TOKEN, HARAJAT_BOT_TOKEN
    global ADMIN_IDS_RAW, ADMIN_IDS, CHANNEL_ID, GROUP_HARID_ID, GROUP_SOTUV_ID
    global SPREADSHEET_ID, DRIVE_FOLDER_ID, FSM_STORAGE_URL, GOOGLE_SERVICE_ACCOUNT_FILE
    global DRIVE_TOKEN_FILE, GOOGLE_OAUTH_TOKEN_FILE, MEDIA_DIR, OPERATION_DB_PATH
    global FSM_TTL_SECONDS, IO_TIMEOUT_SECONDS, IO_MAX_PENDING, DROP_PENDING_UPDATES
    BOT_TOKEN = _text("BOT_TOKEN")
    HARID_BOT_TOKEN = _text("HARID_BOT_TOKEN") or BOT_TOKEN
    SOTUV_BOT_TOKEN = _text("SOTUV_BOT_TOKEN") or BOT_TOKEN
    HARAJAT_BOT_TOKEN = _text("HARAJAT_BOT_TOKEN") or BOT_TOKEN
    ADMIN_IDS_RAW = _text("ADMIN_IDS")
    ADMIN_IDS = [
        int(item.strip()) for item in ADMIN_IDS_RAW.split(",") if item.strip().isdigit()
    ]
    CHANNEL_ID = _text("CHANNEL_ID")
    GROUP_HARID_ID = _text("GROUP_HARID_ID")
    GROUP_SOTUV_ID = _text("GROUP_SOTUV_ID")
    SPREADSHEET_ID = _text("SPREADSHEET_ID")
    DRIVE_FOLDER_ID = _text("DRIVE_FOLDER_ID")
    FSM_STORAGE_URL = _text("FSM_STORAGE_URL")
    GOOGLE_SERVICE_ACCOUNT_FILE = _text(
        "GOOGLE_SERVICE_ACCOUNT_FILE", str(BASE_DIR / "credentials.json")
    )
    DRIVE_TOKEN_FILE = _text("DRIVE_TOKEN_FILE", str(BASE_DIR / "token.json"))
    GOOGLE_OAUTH_TOKEN_FILE = _text("GOOGLE_OAUTH_TOKEN_FILE", DRIVE_TOKEN_FILE)
    MEDIA_DIR = _text("MEDIA_DIR", str(BASE_DIR / "media"))
    OPERATION_DB_PATH = _text(
        "OPERATION_DB_PATH", str(BASE_DIR / "data" / "operations.sqlite")
    )
    FSM_TTL_SECONDS = _positive_integer("FSM_TTL_SECONDS", 86400)
    IO_TIMEOUT_SECONDS = _positive_integer("IO_TIMEOUT_SECONDS", 45)
    IO_MAX_PENDING = _positive_integer("IO_MAX_PENDING", 64)
    DROP_PENDING_UPDATES = _text("DROP_PENDING_UPDATES", "false").lower() == "true"


def load_runtime_config(env_file: str | Path | None = BASE_DIR / ".env") -> None:
    if env_file is not None:
        load_dotenv(env_file, override=False)
    _refresh_settings()


def fsm_uses_memory() -> bool:
    """Only an explicit memory:// URL selects the volatile FSM; it is never a fallback."""
    return urlparse(FSM_STORAGE_URL).scheme == "memory"


def validate_runtime_config(features: tuple[str, ...] | None = None) -> None:
    features = FEATURES if features is None else features
    if not features or any(feature not in FEATURES for feature in features):
        raise ConfigurationError("Bot features must be harid, sotuv, or harajat")
    for feature in features:
        key = feature.upper() + "_BOT_TOKEN"
        if not TOKEN_PATTERN.fullmatch(globals()[key]):
            raise ConfigurationError(f"{key} yoki BOT_TOKEN noto'g'ri yoki bo'sh")
    if not SPREADSHEET_ID or not re.fullmatch(r"[A-Za-z0-9_-]{10,}", SPREADSHEET_ID):
        raise ConfigurationError("SPREADSHEET_ID noto'g'ri yoki bo'sh")
    if not Path(GOOGLE_SERVICE_ACCOUNT_FILE).is_file():
        raise ConfigurationError("GOOGLE_SERVICE_ACCOUNT_FILE fayli topilmadi")
    parsed = urlparse(FSM_STORAGE_URL)
    if not fsm_uses_memory() and (
        parsed.scheme not in {"redis", "rediss"} or not parsed.hostname
    ):
        raise ConfigurationError(
            "FSM_STORAGE_URL redis://, rediss:// yoki lokal test uchun memory:// bo'lishi kerak"
        )
    if FSM_TTL_SECONDS <= 0 or IO_TIMEOUT_SECONDS <= 0 or IO_MAX_PENDING <= 0:
        raise ConfigurationError(
            "FSM_TTL_SECONDS, IO_TIMEOUT_SECONDS va IO_MAX_PENDING musbat bo'lishi kerak"
        )
    if ADMIN_IDS_RAW and any(
        not item.strip().isdigit() for item in ADMIN_IDS_RAW.split(",")
    ):
        raise ConfigurationError(
            "ADMIN_IDS faqat vergul bilan ajratilgan raqamlardan iborat bo'lishi kerak"
        )
    for key in ("CHANNEL_ID", "GROUP_HARID_ID", "GROUP_SOTUV_ID"):
        value = globals()[key]
        if value and not re.fullmatch(r"-?[0-9]+|@[A-Za-z][A-Za-z0-9_]{4,}", value):
            raise ConfigurationError(
                f"{key} Telegram chat ID yoki @username bo'lishi kerak"
            )


_refresh_settings()

# Google Sheets varaqlari nomlari (To'liq o'zbek tilida)
SHEET_STAFF = "Xodimlar"
SHEET_MEMBERS = SHEET_STAFF  # A'zolar va Xodimlar yagona jadvalga birlashtirildi
SHEET_PHONES = "Telefonlar"
SHEET_EXPENSES = "Chiqimlar"
SHEET_INCOMES = "Kirimlar"
SHEET_PARTNERS = "Hamkorlar"
SHEET_MODELS = "Modellar"
SHEET_TEMPLATES = "Shablonlar"
SHEET_OPERATIONS = "Amallar"

# Barcha kerakli varaqlar va ularning sarlavhalari (Headers)
DEFAULT_HEADERS = {
    SHEET_STAFF: [
        "Telegram ID",
        "F.I.Sh",
        "Telefon raqami",
        "Roli",
        "Holati",
        "Jami KPI ($)",
        "To'langan KPI ($)",
        "Qoldiq KPI ($)",
    ],
    SHEET_PHONES: [
        # Harid ma'lumotlari
        "Harid sanasi",
        "IMEI",
        "Brend",
        "Versiya",
        "Turi",
        "Xotira",
        "Batareya %",
        "Rang",
        "Karobka",
        "Harid narxi ($)",
        "Telefon egasi",
        "Telefon egasi telefoni",
        "Qabul qilgan xodim",
        "Harid to'lov turi",
        "Harid qarz summasi ($)",
        "IMEI rasmi",
        "Telefon rasmi",
        # Tannarx va Remont
        "Remont xarajati ($)",
        "Jami tannarx ($)",
        # Kanal post
        "Kanal post ID",
        "Elon narxi ($)",
        # Sotuv ma'lumotlari
        "Sotuv narxi ($)",
        "Xaridor ismi",
        "Xaridor telefoni",
        "Sotuv to'lov turi",
        "Hamkor nomi",
        "Boshlang'ich to'lov ($)",
        "Hamkor qarzi ($)",
        "Xodim KPI ($)",
        "Do'kon sotuvchisi",
        "Sotilgan sana",
        # Natija va Foyda
        "Sof foyda ($)",
        "Holati",
        "Telefon ID",
    ],
    SHEET_EXPENSES: [
        "ID",
        "Sana",
        "Chiqim turi",
        "Summa ($)",
        "IMEI",
        "Xodim ismi",
        "Qabul qiluvchi",
        "Kiritgan shaxs",
    ],
    SHEET_INCOMES: [
        "ID",
        "Sana",
        "Kirim turi",
        "Summa ($)",
        "Hamkor nomi",
        "IMEI",
        "Manba",
        "Kiritgan shaxs",
    ],
    SHEET_PARTNERS: ["Hamkor nomi", "Hozirgi qarzdorlik ($)"],
    SHEET_MODELS: ["Brend", "Versiya", "Turlari"],
    SHEET_TEMPLATES: ["Shablon turi", "Matn"],
    SHEET_OPERATIONS: [
        "Operatsiya ID",
        "Amal turi",
        "Telegram foydalanuvchi ID",
        "Telefon ID",
        "Sana",
        "Natija",
        "Bildirish holati",
        "Bildirish ma'lumoti",
    ],
}
