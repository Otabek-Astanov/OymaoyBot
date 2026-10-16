"""Google Sheets domain service: explicit startup, exact money, one atomic writer."""

import logging
import re
import time
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

import config
from services.errors import (
    AccessDenied,
    AmbiguousPhone,
    BusinessRuleError,
    SchemaError,
    StorageReadError,
    StorageUnavailable,
)
from services.operation_journal import OperationJournal
from services.operations import OperationCoordinator
from services.sheet_schema import Formula, SheetSchema, records_with_rows
from utils.money import money_value, validate_payment

logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
ZERO = Decimal("0.00")
WRITE_ROLES = {"admin", "sotuvchi", "hisobchi", "rahbariyat"}
ACCOUNTING_ROLES = {"admin", "hisobchi"}


# Only links our Drive upload produced become clickable formulas; any other
# text stays a plain string cell and is never evaluated by Sheets.
DRIVE_FILE_LINK = re.compile(r"https://drive\.google\.com/file/d/[A-Za-z0-9_-]+/view(\?[A-Za-z0-9_=&.-]*)?")


def get_tashkent_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Tashkent"))


def get_now_str() -> str:
    return get_tashkent_now().strftime("%Y-%m-%d %H:%M")


def clean_num(value) -> Decimal:
    """Compatibility helper; corrupt values now raise instead of becoming zero."""
    return money_value(value, signed=True, empty_is_zero=True)


class GoogleSheetsService:
    def __init__(self, *, spreadsheet=None, journal_path=None):
        # Importing this module does not open credentials, Sheets or a SQLite file.
        self.client = None
        self.spreadsheet = spreadsheet
        self._journal_path = journal_path
        self.journal = None
        self.coordinator = None
        self._worksheets = {}
        self._schemas = {}
        self._worksheets_listed = False
        self._cache = {}
        self._phones_cache = None
        self._phones_cache_time = 0.0
        self._phones_cache_ttl = 300

    def initialize(self, *, open_journal=True):
        if self.journal is not None:
            return
        if self.spreadsheet is None:
            try:
                credentials = Credentials.from_service_account_file(
                    config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
                )
                self.client = gspread.authorize(credentials)
                from urllib3.util import Retry
                from requests.adapters import HTTPAdapter

                adapter = HTTPAdapter(
                    max_retries=Retry(
                        total=3,
                        backoff_factor=0.3,
                        status_forcelist=[500, 502, 503, 504],
                    )
                )
                session = getattr(self.client.http_client, "session", None)
                if session is not None:
                    session.mount("https://", adapter)
                    session.mount("http://", adapter)
                self.client.set_timeout(config.IO_TIMEOUT_SECONDS)
                self.spreadsheet = self.client.open_by_key(config.SPREADSHEET_ID)
            except Exception as exc:
                self.spreadsheet = None
                raise StorageUnavailable(
                    "Google Sheets ulanmadi; sozlamalar va ruxsatlarni tekshiring"
                ) from exc
        if not open_journal:
            return
        try:
            self.journal = OperationJournal(
                self._journal_path or config.OPERATION_DB_PATH
            )
            source_id = getattr(self.spreadsheet, "id", None) or config.SPREADSHEET_ID
            if source_id:
                self.journal.bind_source(source_id)
            self.coordinator = OperationCoordinator(self, self.journal)
        except Exception as exc:
            if self.journal is not None:
                self.journal.close()
                self.journal = None
            if isinstance(exc, BusinessRuleError):
                raise StorageUnavailable(str(exc)) from exc
            raise StorageUnavailable(
                "Bardoshli operatsiya jurnalini ochib bo'lmadi"
            ) from exc

    def close(self):
        if self.journal is not None:
            self.journal.close()
            self.journal = None
            self.coordinator = None
        client_session = getattr(
            getattr(self.client, "http_client", None), "session", None
        )
        if client_session is not None:
            client_session.close()
        self.client = None
        self.spreadsheet = None
        self._worksheets.clear()
        self._worksheets_listed = False
        self._schemas.clear()
        self.reload_cache()

    def is_connected(self) -> bool:
        return self.spreadsheet is not None

    def _photo_cell(self, url, label):
        """Show a Drive photo as "📷 imei_….jpg" like the original sheet rows."""
        url = str(url or "").strip()
        if not DRIVE_FILE_LINK.fullmatch(url):
            return url
        label = "📷 " + re.sub(r"[^A-Za-z0-9_.-]", "", label)
        return Formula(f'=HYPERLINK("{url}"{self.formula_sep}"{label}")')

    def _require_connected(self):
        if not self.is_connected():
            raise StorageUnavailable("Google Sheets ulanmagan")

    def _worksheet(self, title):
        self._require_connected()
        if title in self._worksheets:
            return self._worksheets[title]
        try:
            ws = self.spreadsheet.worksheet(title)
            self._worksheets[title] = ws
            return ws
        except Exception as exc:
            raise StorageReadError(f"{title}: varaqni o'qib bo'lmadi") from exc

    def _schema(self, title):
        if title in self._schemas:
            return self._schemas[title]
        ws = self._worksheet(title)
        try:
            schema = SheetSchema.from_worksheet(ws, config.DEFAULT_HEADERS[title])
            self._schemas[title] = schema
            return schema
        except SchemaError:
            raise
        except Exception as exc:
            raise StorageReadError(f"{title}: sarlavhalarni o'qib bo'lmadi") from exc

    @staticmethod
    def _safe_get_all_records(ws):
        try:
            return records_with_rows(
                ws.get_all_values(
                    value_render_option="UNFORMATTED_VALUE",
                    date_time_render_option="FORMATTED_STRING",
                )
            )
        except SchemaError:
            raise
        except Exception as exc:
            raise StorageReadError(f"{ws.title}: yozuvlarni o'qib bo'lmadi") from exc

    def _read(self, title):
        self._schema(title)
        return self._safe_get_all_records(self._worksheet(title))

    def readiness(self):
        self._require_connected()
        try:
            for ws in self.spreadsheet.worksheets():
                self._worksheets[ws.title] = ws
            self._worksheets_listed = True
        except Exception:
            pass
        titles = [
            t
            for t in config.DEFAULT_HEADERS
            if t != config.SHEET_OPERATIONS or self._has_sheet(t)
        ]
        schemas = {title: self._schema(title) for title in titles}
        return {"ready": True, "sheets": len(schemas)}

    def _has_sheet(self, title: str) -> bool:
        if not self.spreadsheet:
            return False
        if title in self._worksheets:
            return True
        if self._worksheets_listed:
            # Runtime never creates sheets; avoid a metadata call per write.
            return False
        try:
            return title in [ws.title for ws in self.spreadsheet.worksheets()]
        except Exception:
            return False

    def ensure_worksheets(self):
        """Runtime never creates or silently migrates a production schema."""
        return self.readiness()

    @property
    def formula_sep(self):
        self._require_connected()
        return (
            ","
            if str(getattr(self.spreadsheet, "locale", "")).lower().startswith("en")
            else ";"
        )

    @staticmethod
    def _now():
        return get_now_str()

    def _cached_records(self, title, *, fresh=False, ttl=120):
        cached = self._cache.get(title)
        if not fresh and cached and time.monotonic() - cached[0] < ttl:
            return [dict(row) for row in cached[1]]
        rows = self._read(title)
        self._cache[title] = (time.monotonic(), rows)
        return [dict(row) for row in rows]

    def reload_cache(self):
        self._cache.clear()
        self._phones_cache = None
        self._phones_cache_time = 0.0

    def get_staff_list(self, active_only=True, force_refresh=False, *, fresh=False):
        rows = self._cached_records(config.SHEET_STAFF, fresh=fresh or force_refresh)
        if active_only:
            return [
                row
                for row in rows
                if str(row.get("Holati", "")).strip().casefold() == "faol"
            ]
        return rows

    def check_member(self, telegram_id, force_refresh=False, *, fresh=False):
        """The only access rule: a Xodimlar row decides; ADMIN_IDS only bootstraps.

        A listed admin who is marked inactive stays inactive everywhere. When the
        sheet cannot be read, navigation uses the last read rows and then ADMIN_IDS;
        ``fresh=True`` (financial authorization) never falls back.
        """
        try:
            rows = self.get_staff_list(False, force_refresh, fresh=fresh)
        except SchemaError:
            raise
        except Exception:
            cached = self._cache.get(config.SHEET_STAFF)
            if fresh or not (cached or int(telegram_id) in config.ADMIN_IDS):
                raise
            logger.warning("Xodimlar o'qilmadi; oxirgi ma'lumot bilan tekshirildi")
            rows = cached[1] if cached else []
        matches = [
            row
            for row in rows
            if str(row.get("Telegram ID", "")).strip() == str(telegram_id)
        ]
        if len(matches) > 1:
            raise SchemaError("Xodimlar: takroriy Telegram ID")
        if matches:
            row = matches[0]
            return (
                str(row.get("Holati", "")).strip().casefold() == "faol",
                str(row.get("Roli", "")).strip(),
                str(row.get("F.I.Sh", "")).strip(),
            )
        if int(telegram_id) in config.ADMIN_IDS:
            return True, "Admin", "Bosh Admin"
        return False, "", ""

    def get_staff_name_by_tg_id(self, telegram_id):
        return self.check_member(telegram_id, fresh=True)[2]

    def _authorize(self, actor_id, kind):
        if (
            isinstance(actor_id, bool)
            or not str(actor_id).isascii()
            or not str(actor_id).isdigit()
            or int(actor_id) <= 0
        ):
            raise AccessDenied("Telegram foydalanuvchi ID noto'g'ri")
        active, role, _ = self.check_member(actor_id, fresh=True)
        allowed = (
            ACCOUNTING_ROLES
            if kind
            in {
                "expense",
                "income",
                "repair",
                "kpi_payment",
                "phone_debt_payment",
                "partner_payment",
                "manual_resolution",
            }
            else WRITE_ROLES
        )
        if not active or role.casefold() not in allowed:
            raise AccessDenied("Ushbu amal uchun joriy ruxsat mavjud emas")

    def authorize_channel_publication(self, actor_id):
        """Recheck access immediately before a delayed external publication."""
        self._authorize(actor_id, "phone_metadata")
        return True

    @staticmethod
    def _normalize_phone(record):
        row = dict(record)
        row["IMEI"] = str(row.get("IMEI", "")).strip().lstrip("'")
        brand, version, kind = (
            str(row.get(key, "")).strip() for key in ("Brend", "Versiya", "Turi")
        )
        row["Model"] = (
            " ".join(filter(None, (brand, version, kind)))
            if brand.casefold() == "iphone"
            else version or brand
        )
        return row

    def _load_phones_cache(self, force_refresh=False):
        if (
            not force_refresh
            and self._phones_cache is not None
            and time.monotonic() - self._phones_cache_time < self._phones_cache_ttl
        ):
            return {key: dict(row) for key, row in self._phones_cache.items()}
        records = [
            self._normalize_phone(row) for row in self._read(config.SHEET_PHONES)
        ]
        cache = {}
        for row in records:
            key = str(row.get("Telefon ID", "")).strip() or str(row["_row_index"])
            cache[key] = row
        self._phones_cache = cache
        self._phones_cache_time = time.monotonic()
        return {key: dict(row) for key, row in cache.items()}

    def get_phone_by_imei(self, imei_query, *, fresh=False, exact=False):
        query = str(imei_query).strip().lstrip("'")
        if not query:
            return None
        records = list(self._load_phones_cache(fresh).values())
        if not exact and len(query) == 6 and query.isascii() and query.isdigit():
            matches = [row for row in records if row["IMEI"].endswith(query)]
        else:
            matches = [row for row in records if row["IMEI"] == query]
        if len(matches) > 1:
            active = [
                r
                for r in matches
                if str(r.get("Holati", "")).strip().casefold() == "sotuvda"
            ]
            if len(active) == 1:
                return active[0]
            raise AmbiguousPhone(matches)
        return matches[0] if matches else None

    def get_stock_phones(self):
        """Phones still for sale ("Sotuvda"), read fresh for the daily report."""
        return [
            row
            for row in self._load_phones_cache(True).values()
            if str(row.get("Holati", "")).strip() == "Sotuvda"
        ]

    def get_phone_by_id(self, phone_id, *, fresh=False):
        cache = self._load_phones_cache(fresh)
        if str(phone_id) in cache:
            return cache[str(phone_id)]
        for row in cache.values():
            if str(row["_row_index"]) == str(phone_id) or row["IMEI"] == str(phone_id):
                return row
        return None

    @staticmethod
    def _imei_matches(records, imei):
        matches = [row for row in records if row["IMEI"] == imei]
        if len(matches) > 1:
            active = [
                r
                for r in matches
                if str(r.get("Holati", "")).strip().casefold() == "sotuvda"
            ]
            if len(active) == 1:
                return active
        return matches

    def _phone(self, reference):
        records = list(self._load_phones_cache(True).values())
        matches = [row for row in records if str(row["_row_index"]) == str(reference)]
        if not matches:
            matches = [
                row
                for row in records
                if str(row.get("Telefon ID", "")).strip() == str(reference)
            ]
        if not matches:
            matches = self._imei_matches(records, str(reference).strip().lstrip("'"))
        if len(matches) > 1:
            active = [
                r
                for r in matches
                if str(r.get("Holati", "")).strip().casefold() == "sotuvda"
            ]
            if len(active) == 1:
                return active[0]
            raise AmbiguousPhone(matches)
        if not matches:
            raise BusinessRuleError("Telefon topilmadi")
        return matches[0]

    def _operate(self, operation_id, actor_id, kind, payload, notifications, builder):
        self._require_connected()
        if self.coordinator is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        # Column indexes of a financial write come from headers read now, never
        # from the status-check cache: a moved column would shift every value.
        self._schemas.clear()
        return self.coordinator.run(
            operation_id, kind, actor_id, payload, notifications, builder
        )

    def add_phone(self, phone_data, *, operation_id, actor_id, notifications=()):
        data = dict(phone_data)
        # Transient FSM/UI fields cannot change the identity of a financial retry.
        payload = {
            key: data.get(key, "")
            for key in (
                "imei",
                "imei_6",
                "brand",
                "version",
                "type",
                "memory",
                "battery",
                "color",
                "has_box",
                "buy_price",
                "debt_amount",
                "seller_name",
                "seller_phone",
                "buyer_staff_name",
                "buyer_name",
                "payment_type",
                "imei_photo_url",
                "phone_photo_url",
            )
        }
        payload["buy_price"] = money_value(data.get("buy_price"), allow_zero=False)
        payload["debt_amount"] = money_value(data.get("debt_amount") or "0")

        def build():
            imei = str(data.get("imei", data.get("imei_6", ""))).strip().lstrip("'")
            if len(imei) < 4 or not imei.isascii() or not imei.isalnum():
                raise BusinessRuleError(
                    "IMEI/seriya raqami 4 yoki ko'proq harf/raqamdan iborat bo'lsin"
                )
            for row in self._load_phones_cache(True).values():
                if row["IMEI"] == imei and row.get("Holati") != "Sotildi":
                    raise BusinessRuleError(
                        "Bu IMEI bo'yicha sotilmagan telefon mavjud"
                    )
            price = money_value(data.get("buy_price"), allow_zero=False)
            debt = money_value(data.get("debt_amount", "0"))
            payment = data.get("payment_type", "Naqd")
            if payment not in {"Naqd", "Qarz"} or debt != (
                price if payment == "Qarz" else ZERO
            ):
                raise BusinessRuleError(
                    "Xaridning to'lov turi va qarz summasi mos emas"
                )
            values = {
                "Harid sanasi": self._now(),
                "Telefon ID": operation_id,
                "IMEI": imei,
                "Brend": data.get("brand", "iPhone"),
                "Versiya": data.get("version", ""),
                "Turi": data.get("type", ""),
                "Xotira": data.get("memory", ""),
                "Batareya %": str(data.get("battery", "")),
                "Rang": data.get("color", ""),
                "Karobka": data.get("has_box", "Yo'q"),
                "Harid narxi ($)": price,
                "Telefon egasi": data.get("seller_name", ""),
                "Telefon egasi telefoni": data.get("seller_phone", ""),
                "Qabul qilgan xodim": data.get(
                    "buyer_staff_name", data.get("buyer_name", "")
                ),
                "Harid to'lov turi": payment,
                "Harid qarz summasi ($)": debt,
                "IMEI rasmi": self._photo_cell(
                    data.get("imei_photo_url"), f"imei_{imei}.jpg"
                ),
                "Telefon rasmi": self._photo_cell(
                    data.get("phone_photo_url"), f"phone_{imei}.jpg"
                ),
                "Remont xarajati ($)": ZERO,
                "Jami tannarx ($)": price,
                "Holati": "Sotuvda",
            }
            return (
                [self._schema(config.SHEET_PHONES).append(values)],
                True,
                operation_id,
            )

        return self._operate(
            operation_id, actor_id, "purchase", payload, notifications, build
        )

    def update_phone(
        self,
        row_index_or_stable_id,
        updates,
        *,
        operation_id,
        actor_id,
        notifications=(),
    ):
        values = dict(updates)
        allowed = {
            "Karobka",
            "IMEI rasmi",
            "Telefon rasmi",
            "Kanal post ID",
            "Elon narxi ($)",
        }
        if set(values) - allowed:
            raise BusinessRuleError(
                "Moliyaviy maydon yoki telefon holatini umumiy tahrir bilan o'zgartirib bo'lmaydi"
            )

        def build():
            phone = self._phone(row_index_or_stable_id)
            if phone.get("Holati") != "Sotuvda":
                raise BusinessRuleError(
                    "Sotilgan telefonning e'loni/ombor ma'lumotini o'zgartirib bo'lmaydi"
                )
            publications = [
                item for item in notifications if item.get("kind") == "publish_channel"
            ]
            if publications:
                if (
                    len(publications) != 1
                    or publications[0].get("phone_id") != phone["Telefon ID"]
                ):
                    raise BusinessRuleError(
                        "E'lon faqat tanlangan telefon uchun yaratilishi mumkin"
                    )
                outstanding = self.journal.outstanding_publications(
                    phone["Telefon ID"], exclude_operation_id=operation_id
                )
                if outstanding:
                    raise BusinessRuleError(
                        f"Bu telefon e'loni hali yakunlanmagan. Avval {outstanding[0]['operation_id']} "
                        "bildirish holatini tekshiring va yarashtiring."
                    )
            sanitized = dict(values)
            if "Elon narxi ($)" in sanitized:
                sanitized["Elon narxi ($)"] = money_value(
                    sanitized["Elon narxi ($)"], allow_zero=False
                )
            if "Kanal post ID" in sanitized:
                value = sanitized["Kanal post ID"]
                if (
                    isinstance(value, bool)
                    or not str(value).isascii()
                    or not str(value).isdigit()
                    or int(value) <= 0
                ):
                    raise BusinessRuleError(
                        "Kanal post ID musbat butun son bo'lishi kerak"
                    )
                sanitized["Kanal post ID"] = int(value)
            for name in ("Kanal post ID", "Telefon rasmi", "IMEI rasmi"):
                if name in sanitized and sanitized[name] in (None, "", 0):
                    raise BusinessRuleError(
                        "Mavjud post/rasm qiymatini bo'sh natija bilan o'chirmang"
                    )
            for name, prefix in (("IMEI rasmi", "imei"), ("Telefon rasmi", "phone")):
                if name in sanitized:
                    sanitized[name] = self._photo_cell(
                        sanitized[name], f"{prefix}_{phone['IMEI']}.jpg"
                    )
            requests = self._schema(config.SHEET_PHONES).updates(
                phone["_row_index"], sanitized
            )
            return requests, True, phone["Telefon ID"]

        return self._operate(
            operation_id,
            actor_id,
            "phone_metadata",
            {"phone_ref": row_index_or_stable_id, "updates": values},
            notifications,
            build,
        )

    def record_channel_post(
        self, phone_id, post_id, *, operation_id, actor_id, notifications=()
    ):
        if (
            isinstance(post_id, bool)
            or not str(post_id).isascii()
            or not str(post_id).isdigit()
            or int(post_id) <= 0
        ):
            raise BusinessRuleError("Kanal post ID musbat butun son bo'lishi kerak")
        post_id = int(post_id)

        def build():
            phone = self._phone(phone_id)
            if phone.get("Holati") not in {"Sotuvda", "Sotildi"}:
                raise BusinessRuleError(
                    "Telefon holati noma'lum; post tasdig'ini yarashtiring"
                )
            history = {
                "previous_post_id": phone.get("Kanal post ID", ""),
                "post_id": post_id,
            }
            requests = self._schema(config.SHEET_PHONES).updates(
                phone["_row_index"], {"Kanal post ID": post_id}
            )
            return requests, True, phone["Telefon ID"], {"channel_history": history}

        return self._operate(
            operation_id,
            actor_id,
            "phone_metadata",
            {"phone_id": phone_id, "post_id": post_id},
            notifications,
            build,
        )

    def _verify_batch(self, batch):
        """Read numeric cells back by immutable append IDs and confirm exact cents."""
        money_requests = []
        worksheets = {ws.id: (title, ws) for title, ws in self._worksheets.items()}
        schemas = {}
        tables = {}
        for request in batch.get("requests", ()):
            part = request.get("updateCells") or request.get("appendCells")
            if not part:
                continue
            sheet_id = part.get("sheetId", part.get("start", {}).get("sheetId"))
            if sheet_id not in worksheets:
                # After a restart only Amallar may have been read so far.
                try:
                    for ws in self.spreadsheet.worksheets():
                        self._worksheets[ws.title] = ws
                        worksheets[ws.id] = (ws.title, ws)
                except Exception as exc:
                    raise StorageReadError(
                        "Yozilgan varaqlar metama'lumotini qayta o'qib bo'lmadi"
                    ) from exc
                if sheet_id not in worksheets:
                    raise SchemaError("Operatsiya yozgan varaq endi mavjud emas")
            title, ws = worksheets[sheet_id]
            cells = part["rows"][0]["values"]
            if title not in schemas:
                schemas[title] = self._schema(title)
            schema = schemas[title]
            if "appendCells" in request:
                expected = {
                    schema.headers[index]: cell["userEnteredValue"]
                    for index, cell in enumerate(cells)
                }
                numeric = {
                    name: cell.get("numberValue")
                    for name, cell in expected.items()
                    if "($)" in name
                    and ("numberValue" in cell or "formulaValue" in cell)
                }
                if not numeric:
                    continue
                id_name = (
                    "Telefon ID"
                    if title == config.SHEET_PHONES
                    else "Hamkor nomi"
                    if title == config.SHEET_PARTNERS
                    else "ID"
                )
                identity = expected.get(id_name, {}).get("stringValue")
                if not identity:
                    raise SchemaError(f"{title}: yozuvning barqaror ID si yo'q")
                if title not in tables:
                    tables[title] = self._read(title)
                rows = [
                    row for row in tables[title] if str(row.get(id_name)) == identity
                ]
                if len(rows) != 1:
                    raise StorageReadError(
                        f"{title}: yozilgan ID qayta o'qishda topilmadi yoki takroriy"
                    )
                for name, value in numeric.items():
                    money_requests.append((title, rows[0], name, value))
            else:
                name = schema.headers[part["start"]["columnIndex"]]
                value = cells[0]["userEnteredValue"]
                if "($)" not in name or not (
                    "numberValue" in value or "formulaValue" in value
                ):
                    continue
                if title not in tables:
                    tables[title] = self._read(title)
                row_index = part["start"]["rowIndex"] + 1
                rows = [row for row in tables[title] if row["_row_index"] == row_index]
                if len(rows) != 1:
                    raise StorageReadError(
                        f"{title}:{row_index}: yozilgan qator qayta o'qilmadi"
                    )
                money_requests.append((title, rows[0], name, value.get("numberValue")))
        for title, row, name, expected in money_requests:
            try:
                actual = money_value(row.get(name), signed=True)
            except ValueError as exc:
                raise StorageReadError(
                    f"{title}:{row['_row_index']}: {name} qayta o'qishda noto'g'ri"
                ) from exc
            if expected is None:
                if title == config.SHEET_STAFF and name == "Qoldiq KPI ($)":
                    try:
                        remaining = self._staff_balance(row)
                    except (BusinessRuleError, ValueError) as exc:
                        raise StorageReadError(
                            f"{title}:{row['_row_index']}: KPI formulasi tasdiqlanmadi"
                        ) from exc
                    if actual != remaining:
                        raise StorageReadError(
                            f"{title}:{row['_row_index']}: KPI formulasi qoldig'i mos emas"
                        )
                elif (
                    title == config.SHEET_PARTNERS and name == "Hozirgi qarzdorlik ($)"
                ):
                    try:
                        self._partner_balance(row)
                    except BusinessRuleError as exc:
                        raise StorageReadError(
                            f"{title}:{row['_row_index']}: hamkor formulasi tasdiqlanmadi"
                        ) from exc
            elif actual != money_value(expected, signed=True):
                raise StorageReadError(
                    f"{title}:{row['_row_index']}: {name} sentlari yozilgan qiymatga mos emas"
                )

    def _staff(self, telegram_id):
        matches = [
            row
            for row in self.get_staff_list(False, fresh=True)
            if str(row.get("Telegram ID", "")).strip() == str(telegram_id)
        ]
        if len(matches) != 1:
            raise BusinessRuleError("Xodim Telegram ID bo'yicha bir ma'noli topilmadi")
        return matches[0]

    def _staff_balance_formula(self, schema, row_index):
        total = schema.letter("Jami KPI ($)")
        paid = schema.letter("To'langan KPI ($)")
        return Formula(
            f"=ROUND({total}{row_index}-{paid}{row_index}{self.formula_sep}2)"
        )

    @staticmethod
    def _staff_balance(staff):
        total = money_value(staff.get("Jami KPI ($)"))
        paid = money_value(staff.get("To'langan KPI ($)"))
        remaining = money_value(staff.get("Qoldiq KPI ($)"))
        if remaining != total - paid or paid > total:
            raise BusinessRuleError(
                "KPI qoldig'i hisoblangan/to'langan summaga mos emas; avval yarashtiring"
            )
        return remaining

    def _partner_formula(self, partner_schema, row_index):
        phones = self._schema(config.SHEET_PHONES)
        incomes = self._schema(config.SHEET_INCOMES)
        name_cell = f"{partner_schema.letter('Hamkor nomi')}{row_index}"
        phone_name, phone_debt = (
            phones.letter("Hamkor nomi"),
            phones.letter("Hamkor qarzi ($)"),
        )
        income_name, income_sum = (
            incomes.letter("Hamkor nomi"),
            incomes.letter("Summa ($)"),
        )
        sep = self.formula_sep
        return Formula(
            f"=ROUND(SUMIF('{config.SHEET_PHONES}'!${phone_name}:${phone_name}{sep}{name_cell}{sep}"
            f"'{config.SHEET_PHONES}'!${phone_debt}:${phone_debt})-"
            f"SUMIF('{config.SHEET_INCOMES}'!${income_name}:${income_name}{sep}{name_cell}{sep}"
            f"'{config.SHEET_INCOMES}'!${income_sum}:${income_sum}){sep}2)"
        )

    def _partner(self, name, *, allow_store=False):
        matches = [
            row
            for row in self.get_partners(force_refresh=True)
            if str(row.get("Hamkor nomi", "")).strip() == name
        ]
        if len(matches) > 1:
            raise SchemaError("Hamkorlar: takroriy hamkor nomi")
        if not matches and not (allow_store and name == "Dokondan"):
            raise BusinessRuleError("Hamkor mavjud emas; qayta tanlang")
        return matches[0] if matches else None

    def _partner_balance(self, partner):
        from services.financial_reports import validate_partner_balances

        name = str(partner.get("Hamkor nomi", "")).strip()
        titles = (config.SHEET_PHONES, config.SHEET_INCOMES, config.SHEET_PARTNERS)
        try:
            balances = validate_partner_balances(
                {title: self._read(title) for title in titles}
            )
        except StorageReadError as exc:
            raise BusinessRuleError(
                "Hamkor qoldig'i yoki telefon/kirim tarixi mos emas; avval yarashtiring"
            ) from exc
        return balances[name]

    def record_sale(
        self,
        row_index,
        sale_data,
        phone_data=None,
        *,
        operation_id,
        actor_id,
        notifications=(),
    ):
        data = dict(sale_data)
        payload = {
            key: data.get(key, "")
            for key in (
                "sell_price",
                "seller_kpi",
                "initial_payment",
                "payment_type",
                "partner_name",
                "buyer_name",
                "buyer_phone",
                "seller_name",
                "seller_id",
                "sellers",
            )
        }
        payload["phone_ref"] = row_index
        for key in ("sell_price", "seller_kpi", "initial_payment"):
            payload[key] = money_value(
                data.get(key) or "0", allow_zero=key != "sell_price"
            )
        if isinstance(payload["sellers"], list):
            payload["sellers"] = [
                {**seller, "kpi": money_value(seller.get("kpi") or "0")}
                for seller in payload["sellers"]
            ]

        def build():
            phone = self._phone(row_index)
            if phone.get("Holati") != "Sotuvda":
                raise BusinessRuleError(
                    "Telefon allaqachon sotilgan yoki sotuvga tayyor emas"
                )
            price = money_value(data.get("sell_price"), allow_zero=False)
            total_cost = money_value(phone.get("Jami tannarx ($)"))
            kpi = money_value(data.get("seller_kpi") or "0")
            initial = money_value(data.get("initial_payment") or "0")
            if initial > price:
                raise BusinessRuleError("Boshlang'ich to'lov sotuv narxidan oshmasin")
            payment = data.get("payment_type", "Naqd")
            if payment not in {"Naqd", "Qarz"}:
                raise BusinessRuleError("Sotuv to'lov turi noto'g'ri")
            debt = price - initial if payment == "Qarz" else ZERO
            partner_name = (
                str(data.get("partner_name", "-")).strip() if payment == "Qarz" else "-"
            )
            if payment == "Qarz" and partner_name in {"", "-"}:
                raise BusinessRuleError("Qarz sotuvda hamkor/do'konni tanlang")
            profit = price - total_cost - kpi
            values = {
                "Sotuv narxi ($)": price,
                "Xaridor ismi": data.get("buyer_name", ""),
                "Xaridor telefoni": data.get("buyer_phone", ""),
                "Sotuv to'lov turi": payment,
                "Hamkor nomi": partner_name,
                "Boshlang'ich to'lov ($)": initial if payment == "Qarz" else ZERO,
                "Hamkor qarzi ($)": debt,
                "Xodim KPI ($)": kpi,
                "Do'kon sotuvchisi": data.get("seller_name", ""),
                "Sotilgan sana": self._now(),
                "Sof foyda ($)": profit,
                "Holati": "Sotildi",
            }
            requests = self._schema(config.SHEET_PHONES).updates(
                phone["_row_index"], values
            )
            sellers = data.get("sellers") or (
                [{"id": data.get("seller_id"), "kpi": kpi}] if kpi > 0 else []
            )
            if (
                len(sellers) > 2
                or sum((money_value(s.get("kpi", "0")) for s in sellers), ZERO) != kpi
            ):
                raise BusinessRuleError(
                    "Xodim KPI ulushlari jami sotuv KPI bilan mos emas"
                )
            totals = {}
            for seller in sellers:
                share = money_value(seller.get("kpi", "0"))
                if share == 0:
                    continue
                seller_id = str(seller.get("id", ""))
                if not seller_id.isascii() or not seller_id.isdigit():
                    raise BusinessRuleError("KPI xodimi Telegram ID bilan tanlansin")
                staff = self._staff(seller_id)
                if (
                    str(staff.get("Holati", "")).casefold() != "faol"
                    or str(staff.get("Roli", "")).casefold() not in WRITE_ROLES
                ):
                    raise BusinessRuleError(
                        "KPI oluvchi xodim faol va tegishli rolda bo'lsin"
                    )
                totals[seller_id] = (
                    staff,
                    totals.get(seller_id, (staff, ZERO))[1] + share,
                )
            staff_schema = self._schema(config.SHEET_STAFF)
            for staff, share in totals.values():
                self._staff_balance(staff)
                requests += staff_schema.updates(
                    staff["_row_index"],
                    {
                        "Jami KPI ($)": money_value(staff.get("Jami KPI ($)")) + share,
                        "Qoldiq KPI ($)": self._staff_balance_formula(
                            staff_schema, staff["_row_index"]
                        ),
                    },
                )
            if payment == "Qarz":
                partner = self._partner(partner_name, allow_store=True)
                schema = self._schema(config.SHEET_PARTNERS)
                if partner is None:
                    # Only the controlled writer appends; this row is used exclusively in this batch's formula.
                    partner_row = (
                        len(self._worksheet(config.SHEET_PARTNERS).get_all_values()) + 1
                    )
                    requests.append(
                        schema.append(
                            {
                                "Hamkor nomi": partner_name,
                                "Hozirgi qarzdorlik ($)": self._partner_formula(
                                    schema, partner_row
                                ),
                            }
                        )
                    )
                else:
                    self._partner_balance(partner)
                    requests += schema.updates(
                        partner["_row_index"],
                        {
                            "Hozirgi qarzdorlik ($)": self._partner_formula(
                                schema, partner["_row_index"]
                            )
                        },
                    )
            return requests, [True, profit], phone["Telefon ID"]

        result = self._operate(
            operation_id, actor_id, "sale", payload, notifications, build
        )
        return bool(result[0]), result[1]

    def _expense_row(
        self,
        operation_id,
        expense_type,
        amount,
        imei="",
        staff_name="",
        recipient="",
        creator_name="",
    ):
        return {
            "ID": operation_id,
            "Sana": self._now(),
            "Chiqim turi": expense_type,
            "Summa ($)": amount,
            "IMEI": imei,
            "Xodim ismi": staff_name,
            "Qabul qiluvchi": recipient,
            "Kiritgan shaxs": creator_name,
        }

    def _income_row(
        self,
        operation_id,
        income_type,
        amount,
        partner_name="",
        imei="",
        source="",
        creator_name="",
    ):
        return {
            "ID": operation_id,
            "Sana": self._now(),
            "Kirim turi": income_type,
            "Summa ($)": amount,
            "Hamkor nomi": partner_name,
            "IMEI": imei,
            "Manba": source,
            "Kiritgan shaxs": creator_name,
        }

    def record_expense(
        self,
        expense_type,
        amount,
        imei="",
        staff_name="",
        recipient="",
        creator_name="",
        *,
        operation_id,
        actor_id,
        notifications=(),
    ):
        if expense_type in {"Remont", "KPI", "Telefon (qarz)"}:
            raise BusinessRuleError(
                "Bog'langan chiqim tegishli remont/KPI/qarz amali orqali saqlansin"
            )
        value = money_value(amount, allow_zero=False)
        payload = dict(
            expense_type=expense_type,
            amount=value,
            imei=imei,
            staff_name=staff_name,
            recipient=recipient,
            creator_name=creator_name,
        )

        def build():
            row = self._expense_row(
                operation_id,
                expense_type,
                value,
                imei,
                staff_name,
                recipient,
                creator_name,
            )
            return [self._schema(config.SHEET_EXPENSES).append(row)], True, ""

        return self._operate(
            operation_id, actor_id, "expense", payload, notifications, build
        )

    def record_income(
        self,
        income_type,
        amount,
        partner_name="",
        imei="",
        source="",
        creator_name="",
        *,
        operation_id,
        actor_id,
        notifications=(),
    ):
        if partner_name or imei or income_type == "Hamkor to'lovi":
            raise BusinessRuleError(
                "Telefon/hamkor qarzini umumiy kirim orqali o'zgartirib bo'lmaydi"
            )
        value = money_value(amount, allow_zero=False)
        payload = dict(
            income_type=income_type,
            amount=value,
            source=source,
            creator_name=creator_name,
        )

        def build():
            row = self._income_row(
                operation_id,
                income_type,
                value,
                source=source,
                creator_name=creator_name,
            )
            return [self._schema(config.SHEET_INCOMES).append(row)], True, ""

        return self._operate(
            operation_id, actor_id, "income", payload, notifications, build
        )

    def record_repair(
        self, phone_ref, amount, creator, *, operation_id, actor_id, notifications=()
    ):
        value = money_value(amount, allow_zero=False)

        def build():
            phone = self._phone(phone_ref)
            if phone.get("Holati") != "Sotuvda":
                raise BusinessRuleError(
                    "Sotilgan telefon remonti uchun kafolat xarajati qoidasi hali tasdiqlanmagan"
                )
            previous_repair = money_value(phone.get("Remont xarajati ($)"))
            current_cost = money_value(phone.get("Jami tannarx ($)"))
            buy = money_value(phone.get("Harid narxi ($)"))
            if current_cost != buy + previous_repair:
                raise BusinessRuleError(
                    "Tannarx xarid/remont tarixi bilan mos emas; avval yarashtiring"
                )
            repair = previous_repair + value
            total = current_cost + value
            requests = self._schema(config.SHEET_PHONES).updates(
                phone["_row_index"],
                {"Remont xarajati ($)": repair, "Jami tannarx ($)": total},
            )
            requests.append(
                self._schema(config.SHEET_EXPENSES).append(
                    self._expense_row(
                        operation_id,
                        "Remont",
                        value,
                        phone["IMEI"],
                        creator_name=creator,
                    )
                )
            )
            return requests, [True, total], phone["Telefon ID"]

        result = self._operate(
            operation_id,
            actor_id,
            "repair",
            {"phone_ref": phone_ref, "amount": value, "creator": creator},
            notifications,
            build,
        )
        return bool(result[0]), result[1]

    def pay_staff_kpi(
        self,
        telegram_id,
        amount,
        creator_name="",
        *,
        operation_id,
        actor_id,
        notifications=(),
    ):
        value = money_value(amount, allow_zero=False)

        def build():
            staff = self._staff(telegram_id)
            paid = money_value(staff.get("To'langan KPI ($)"))
            validate_payment(value, self._staff_balance(staff))
            schema = self._schema(config.SHEET_STAFF)
            requests = schema.updates(
                staff["_row_index"],
                {
                    "To'langan KPI ($)": paid + value,
                    "Qoldiq KPI ($)": self._staff_balance_formula(
                        schema, staff["_row_index"]
                    ),
                },
            )
            name = str(staff.get("F.I.Sh", ""))
            requests.append(
                self._schema(config.SHEET_EXPENSES).append(
                    self._expense_row(
                        operation_id,
                        "KPI",
                        value,
                        staff_name=name,
                        recipient=name,
                        creator_name=creator_name,
                    )
                )
            )
            return requests, True, ""

        return self._operate(
            operation_id,
            actor_id,
            "kpi_payment",
            {
                "telegram_id": str(telegram_id),
                "amount": value,
                "creator_name": creator_name,
            },
            notifications,
            build,
        )

    def pay_phone_debt(
        self, imei, amount, creator_name="", *, operation_id, actor_id, notifications=()
    ):
        value = money_value(amount, allow_zero=False)

        def build():
            phone = self._phone(imei)
            balance = money_value(phone.get("Harid qarz summasi ($)"))
            validate_payment(value, balance)
            remaining = balance - value
            requests = self._schema(config.SHEET_PHONES).updates(
                phone["_row_index"], {"Harid qarz summasi ($)": remaining}
            )
            requests.append(
                self._schema(config.SHEET_EXPENSES).append(
                    self._expense_row(
                        operation_id,
                        "Telefon (qarz)",
                        value,
                        phone["IMEI"],
                        recipient=phone.get("Telefon egasi", ""),
                        creator_name=creator_name,
                    )
                )
            )
            return requests, [True, remaining], phone["Telefon ID"]

        result = self._operate(
            operation_id,
            actor_id,
            "phone_debt_payment",
            {"phone_ref": imei, "amount": value, "creator_name": creator_name},
            notifications,
            build,
        )
        return bool(result[0]), result[1]

    def reduce_partner_debt(
        self,
        partner_name,
        amount,
        creator_name="",
        *,
        operation_id,
        actor_id,
        notifications=(),
    ):
        value = money_value(amount, allow_zero=False)

        def build():
            partner = self._partner(partner_name)
            validate_payment(value, self._partner_balance(partner))
            schema = self._schema(config.SHEET_PARTNERS)
            requests = [
                self._schema(config.SHEET_INCOMES).append(
                    self._income_row(
                        operation_id,
                        "Hamkor to'lovi",
                        value,
                        partner_name,
                        source="Hamkor",
                        creator_name=creator_name,
                    )
                )
            ]
            requests += schema.updates(
                partner["_row_index"],
                {
                    "Hozirgi qarzdorlik ($)": self._partner_formula(
                        schema, partner["_row_index"]
                    )
                },
            )
            return requests, True, ""

        return self._operate(
            operation_id,
            actor_id,
            "partner_payment",
            {
                "partner_name": partner_name,
                "amount": value,
                "creator_name": creator_name,
            },
            notifications,
            build,
        )

    def close_store_phone_debt(
        self, imei, amount, creator_name="", *, operation_id, actor_id, notifications=()
    ):
        if imei:
            raise BusinessRuleError(
                "Do'kondan kirimning qarz ma'nosi tasdiqlanmaguncha telefon qarzini o'zgartirish bloklangan"
            )
        result = self.record_income(
            "Dokondan",
            amount,
            source="Umumiy kirim",
            creator_name=creator_name,
            operation_id=operation_id,
            actor_id=actor_id,
            notifications=notifications,
        )
        return result, ZERO

    def get_partners(self, force_refresh=False, *, fresh=False):
        return self._cached_records(config.SHEET_PARTNERS, fresh=fresh or force_refresh)

    def get_models(self, force_refresh=False):
        return self._cached_records(config.SHEET_MODELS, fresh=force_refresh, ttl=300)

    def get_template(self, template_type="Elon", force_refresh=False):
        rows = self._cached_records(config.SHEET_TEMPLATES, fresh=force_refresh, ttl=60)
        for row in rows:
            if (
                str(row.get("Shablon turi", "")).strip().casefold()
                == template_type.casefold()
            ):
                return str(row.get("Matn", ""))
        return ""

    def get_financial_summary(self):
        from services.financial_reports import financial_summary

        # Every source is fresh; one read error prevents a misleading partial balance.
        titles = (
            config.SHEET_PHONES,
            config.SHEET_INCOMES,
            config.SHEET_EXPENSES,
            config.SHEET_PARTNERS,
            config.SHEET_STAFF,
        )
        sources = {title: self._read(title) for title in titles}
        return financial_summary(sources)

    def get_reconciliation_report(self):
        from services.financial_reports import reconciliation_report

        titles = (
            config.SHEET_PHONES,
            config.SHEET_INCOMES,
            config.SHEET_EXPENSES,
            config.SHEET_PARTNERS,
            config.SHEET_STAFF,
        )
        return reconciliation_report({title: self._read(title) for title in titles})

    def recover_pending_operations(self):
        if self.coordinator is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        return self.coordinator.recover()

    def get_operation_status(self, operation_id):
        if self.journal is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        record = self.journal.get(operation_id)
        return (
            {
                key: record[key]
                for key in (
                    "operation_id",
                    "kind",
                    "actor_id",
                    "state",
                    "result",
                    "updated_at",
                )
            }
            if record
            else None
        )

    def resolve_operation_not_applied(self, operation_id, *, actor_id):
        """Admin CLI only: the operator must independently verify non-application."""
        self._authorize(actor_id, "manual_resolution")
        if self.journal is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        record = self.journal.get(operation_id)
        if not record or record["state"] != "unknown":
            raise BusinessRuleError("Faqat noaniq amal qo'lda yarashtirilishi mumkin")
        if self.coordinator.remote_operation(operation_id):
            raise BusinessRuleError(
                "Sheets jurnalida amal mavjud; uni bajarilmagan deb belgilamang"
            )
        self.journal.transition(
            operation_id, "rejected", "Operator bajarilmaganini mustaqil tekshirdi"
        )

    def resolve_notification_outcome(
        self, operation_id, index, *, sent, actor_id, channel_post_id=None
    ):
        """Explicit operator recovery; a delivered listing must retain its post ID."""
        from uuid import UUID, uuid5

        self._authorize(actor_id, "manual_resolution")
        if self.journal is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        operation = self.journal.get(operation_id)
        item = self.journal.get_notification(operation_id, index)
        if (
            not operation
            or operation["state"] != "committed"
            or not item
            or item["state"] != "unknown"
        ):
            raise BusinessRuleError(
                "Faqat yakunlangan amalning noaniq bildirishi qo'lda yarashtiriladi"
            )
        payload = item["payload"]
        if payload.get("kind") == "publish_channel" and sent:
            if (
                isinstance(channel_post_id, bool)
                or not str(channel_post_id).isascii()
                or not str(channel_post_id).isdigit()
                or int(channel_post_id) <= 0
            ):
                raise BusinessRuleError(
                    "Yetkazilgan e'lon uchun tekshirilgan kanal post ID talab qilinadi"
                )
            phone = self._phone(payload.get("phone_id"))
            current_id = phone.get("Kanal post ID")
            if current_id not in (None, "", 0) and str(current_id) != str(
                channel_post_id
            ):
                raise BusinessRuleError(
                    "Telefonning mavjud post ID si boshqa; avval kanal tarixini yarashtiring"
                )
            notifications = []
            if phone.get("Holati") == "Sotildi":
                notifications.append(
                    {
                        "kind": "sold_channel",
                        "phone_id": phone["Telefon ID"],
                        "bot_id": payload["bot_id"],
                        "data": {},
                    }
                )
            metadata_id = str(uuid5(UUID(operation_id), f"channel-post-manual:{index}"))
            self.record_channel_post(
                phone["Telefon ID"],
                int(channel_post_id),
                operation_id=metadata_id,
                actor_id=actor_id,
                notifications=notifications,
            )
        elif channel_post_id is not None:
            raise BusinessRuleError(
                "Kanal post ID faqat yetkazilgan e'lonni yarashtirish uchun kerak"
            )
        self.journal.mark_notification(
            operation_id,
            index,
            "sent" if sent else "pending",
            "Operator natijani mustaqil tekshirdi",
            reset_attempts=not sent,
        )

    def notification_status(self, operation_id, index=0):
        if self.journal is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        item = self.journal.get_notification(operation_id, index)
        if item is None:
            return None
        return {key: item[key] for key in ("state", "attempts", "error")}

    def notification_statuses(self):
        if self.journal is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        rows = self.journal.connection.execute(
            "SELECT operation_id,notification_index AS 'index' "
            "FROM notifications ORDER BY operation_id,notification_index"
        ).fetchall()
        results = []
        for row in rows:
            item = self.journal.get_notification(row["operation_id"], row["index"])
            results.append(
                {
                    key: item[key]
                    for key in ("operation_id", "index", "state", "attempts", "error")
                }
                | {
                    "kind": item["payload"].get("kind"),
                    "phone_id": item["payload"].get("phone_id"),
                }
            )
        return results

    def get_actor_pending_operations(self, actor_id):
        if self.journal is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        rows = self.journal.connection.execute(
            "SELECT operation_id,kind,state,created_at FROM operations "
            "WHERE actor_id=? AND state IN ('prepared','sending','unknown') ORDER BY created_at",
            (str(actor_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def pending_notifications(self):
        if self.journal is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        return self.journal.pending_notifications()

    def mark_notification(self, operation_id, index, status, error=""):
        if self.journal is None:
            raise StorageUnavailable("Operatsiya jurnali ishga tushirilmagan")
        self.journal.mark_notification(operation_id, index, status, error)


sheets_service = GoogleSheetsService()
