import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Dict, Any

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_tashkent_now() -> datetime:
    """Toshkent vaqti (UTC+5) bo'yicha hozirgi datetime ob'ektini qaytaradi."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Tashkent"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=5)))


def get_now_str() -> str:
    """Toshkent vaqti formati: YYYY-MM-DD HH:MM"""
    return get_tashkent_now().strftime("%Y-%m-%d %H:%M")


def clean_num(val: Any) -> float | int:
    """Raqamni butun bo'lsa int, kasr bo'lsa float qilib qaytaradi."""
    if val is None:
        return 0
    try:
        f = float(str(val).replace("$", "").replace(",", "").strip())
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return 0


class GoogleSheetsService:
    def __init__(self):
        self.client: Optional[Any] = None
        self.spreadsheet: Optional[Any] = None
        self._models_cache: Optional[List[Dict[str, str]]] = None
        self._models_cache_time: float = 0
        self._models_cache_ttl: float = 300  # 5 daqiqa
        self._phones_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._phones_cache_time: float = 0
        self._phones_cache_ttl: float = 300  # 5 daqiqa
        self._staff_cache: Optional[List[Dict[str, Any]]] = None
        self._staff_cache_time: float = 0
        self._staff_cache_ttl: float = 120  # 2 daqiqa
        self._partners_cache: Optional[List[Dict[str, Any]]] = None
        self._partners_cache_time: float = 0
        self._partners_cache_ttl: float = 300  # 5 daqiqa
        self._templates_cache: Optional[Dict[str, str]] = None
        self._templates_cache_time: float = 0
        self._templates_cache_ttl: float = 60  # 1 daqiqa
        self._init_client()

    def _init_client(self):
        if not gspread or not Credentials:
            logger.warning("gspread yoki google-auth o'rnatilmagan.")
            return

        try:
            creds = Credentials.from_service_account_file(
                config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
            )
            self.client = gspread.authorize(creds)
            if config.SPREADSHEET_ID:
                self.spreadsheet = self.client.open_by_key(config.SPREADSHEET_ID)
                logger.info(f"Google Spreadsheet ochildi: {self.spreadsheet.title}")
            else:
                logger.warning("SPREADSHEET_ID ko'rsatilmagan.")
        except Exception as e:
            logger.warning(f"Google Sheets ulanishida ogohlantirish: {e}")

    def is_connected(self) -> bool:
        return self.spreadsheet is not None

    @property
    def formula_sep(self) -> str:
        """Spreadsheet lokaliga mos formula ajratuvchisi (';' yoki ',')."""
        try:
            if self.spreadsheet:
                locale = getattr(self.spreadsheet, "locale", "") or ""
                if locale.lower().startswith("en"):
                    return ","
        except Exception:
            pass
        return ";"

    def ensure_worksheets(self) -> None:
        """Kerakli barcha varaqlarni va ularning sarlavhalarini tekshirib, kerak bo'lsa yaratadi."""
        if not self.spreadsheet:
            return

        existing_sheets = [ws.title for ws in self.spreadsheet.worksheets()]
        for sheet_name, headers in config.DEFAULT_HEADERS.items():
            if sheet_name not in existing_sheets:
                ws = self.spreadsheet.add_worksheet(title=sheet_name, rows=100, cols=len(headers) + 5)
                ws.append_row(headers)
                logger.info(f"Yangi varaq yaratildi: {sheet_name}")
            else:
                ws = self.spreadsheet.worksheet(sheet_name)
                current_headers = ws.row_values(1)
                if not current_headers:
                    ws.append_row(headers)

    def get_staff_name_by_tg_id(self, telegram_id: int) -> str:
        """
        Telegram ID bo'yicha Xodimlar jadvalidan xodimning F.I.Sh sini topadi.
        Agar topilmasa, bo'sh satr qaytaradi.
        """
        if not telegram_id:
            return ""

        # 1. Keshdan qidirish
        records = self.get_staff_list(active_only=False, force_refresh=False)
        for row in records:
            row_tg_id = str(row.get("Telegram ID", "")).strip()
            if row_tg_id == str(telegram_id):
                name = str(row.get("F.I.Sh", row.get("Xodim ismi", ""))).strip()
                if name:
                    return name

        # 2. Agar keshda bo'lmasa, bazadan yangilab qidirish
        records = self.get_staff_list(active_only=False, force_refresh=True)
        for row in records:
            row_tg_id = str(row.get("Telegram ID", "")).strip()
            if row_tg_id == str(telegram_id):
                name = str(row.get("F.I.Sh", row.get("Xodim ismi", ""))).strip()
                if name:
                    return name

        return ""

    def check_member(self, telegram_id: int, force_refresh: bool = False) -> Tuple[bool, str, str]:
        """
        Foydalanuvchini tekshiradi.
        Qaytaradi: (ruxsat_bormi: bool, roli: str, ismi: str)
        1. Xodimlar jadvalidan qidiradi (kesh yoki force_refresh).
        2. Agar jadvalda bo'lsa, jadvaldagi roli va holatini qaytaradi.
        3. Agar jadvalda bo'lmasa, lekin config.ADMIN_IDS ichida bo'lsa, 'Admin' sifatida ruxsat beradi.
        """
        # 1. Jadvaldan tekshirish
        records = self.get_staff_list(active_only=False, force_refresh=force_refresh)
        for row in records:
            row_tg_id = str(row.get("Telegram ID", "")).strip()
            if row_tg_id == str(telegram_id):
                is_active = str(row.get("Holati", "")).strip().lower() == "faol"
                role = str(row.get("Roli", "Sotuvchi")).strip() or "Sotuvchi"
                name = str(row.get("F.I.Sh", row.get("Xodim ismi", "Noma'lum"))).strip()
                return is_active, role, name or "Noma'lum"

        # 2. Agar keshda topilmagan bo'lsa va force_refresh qilinmagan bo'lsa, bazadan yangilab yana 1 marta tekshirish
        if not force_refresh:
            records = self.get_staff_list(active_only=False, force_refresh=True)
            for row in records:
                row_tg_id = str(row.get("Telegram ID", "")).strip()
                if row_tg_id == str(telegram_id):
                    is_active = str(row.get("Holati", "")).strip().lower() == "faol"
                    role = str(row.get("Roli", "Sotuvchi")).strip() or "Sotuvchi"
                    name = str(row.get("F.I.Sh", row.get("Xodim ismi", "Noma'lum"))).strip()
                    return is_active, role, name or "Noma'lum"

        # 3. Agar jadvalda umuman bo'lmasa, lekin .env dagi ADMIN_IDS da bo'lsa:
        if telegram_id in config.ADMIN_IDS:
            return True, "Admin", "Bosh Admin"

        # Boshqa hech kimga ruxsat yo'q!
        return False, "", ""

    def add_member(self, telegram_id: int, full_name: str, phone_number: str, role: str = "Sotuvchi") -> bool:
        """Yangi a'zo/xodim qo'shish."""
        if not self.spreadsheet:
            return False
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_STAFF)
            new_idx = len(ws.get_all_values()) + 1
            sep = self.formula_sep
            formula = f'=IF(A{new_idx}<>""{sep} F{new_idx}-G{new_idx}{sep} "")'
            ws.append_row([str(telegram_id), full_name, phone_number, role, "Faol", 0, 0, formula], value_input_option="USER_ENTERED")
            self._staff_cache = None
            return True
        except Exception as e:
            logger.error(f"add_member xatosi: {e}")
            return False

    def _update_local_phone_cache(self, imei: str, row: List[Any], row_idx: int) -> None:
        """Keshga yangi yoki yangilangan telefonni yozish."""
        if self._phones_cache is None:
            self._phones_cache = {}
        headers = config.DEFAULT_HEADERS.get(config.SHEET_PHONES, [])
        item = {}
        for h, val in zip(headers, row):
            item[h] = str(val)
        item["_row_index"] = row_idx

        clean_imei = str(imei).strip()
        if "Model" not in item or not item["Model"]:
            brand = item.get("Brend", "")
            version = item.get("Versiya", "")
            turi = item.get("Turi", "")
            item["Model"] = f"{brand} {version} {turi}".replace("  ", " ").strip()

        self._phones_cache[clean_imei] = item
        if len(clean_imei) > 6:
            self._phones_cache[clean_imei[-6:]] = item

    def _load_phones_cache(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """Telefonlar keshini yuklaydi yoki qaytaradi."""
        now = time.time()
        if not force_refresh and self._phones_cache is not None and (now - self._phones_cache_time < self._phones_cache_ttl):
            return self._phones_cache

        if not self.spreadsheet:
            self._phones_cache = {}
            self._phones_cache_time = now
            return self._phones_cache

        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PHONES)
            records = ws.get_all_records()
            formulas: List[List[Any]] = []
            try:
                formulas = ws.get(value_render_option="FORMULA", pad_values=True)
            except Exception as fe:
                logger.warning(f"Telefonlar formulalarini olishda ogohlantirish: {fe}")

            header = formulas[0] if formulas else []
            imei_photo_idx = header.index("IMEI rasmi") if "IMEI rasmi" in header else -1
            phone_photo_idx = header.index("Telefon rasmi") if "Telefon rasmi" in header else -1

            cache: Dict[str, Dict[str, Any]] = {}
            for idx, row in enumerate(records, start=2):
                row["_row_index"] = idx
                if formulas and idx - 1 < len(formulas):
                    f_row = formulas[idx - 1]
                    if imei_photo_idx != -1 and imei_photo_idx < len(f_row) and f_row[imei_photo_idx]:
                        row["IMEI rasmi"] = f_row[imei_photo_idx]
                    if phone_photo_idx != -1 and phone_photo_idx < len(f_row) and f_row[phone_photo_idx]:
                        row["Telefon rasmi"] = f_row[phone_photo_idx]

                if "Model" not in row or not row["Model"]:
                    brand = row.get("Brend", "")
                    version = row.get("Versiya", "")
                    turi = row.get("Turi", "")
                    row["Model"] = f"{brand} {version} {turi}".replace("  ", " ").strip()

                imei = str(row.get("IMEI", row.get("IMEI (oxirgi 6)", ""))).strip().lstrip("'")
                if imei:
                    current_status = str(row.get("Holati", "")).strip()
                    existing = cache.get(imei)
                    # "Sotuvda" bo'lgan faol telefon har doim "Sotildi" bo'lganidan ustun turadi
                    if not existing or current_status == "Sotuvda" or existing.get("Holati") != "Sotuvda":
                        cache[imei] = row
                        if len(imei) > 6:
                            cache[imei[-6:]] = row
            self._phones_cache = cache
            self._phones_cache_time = now
            logger.info(f"Telefonlar keshi yangilandi: {len(records)} ta telefon yuklandi.")
            return cache
        except Exception as e:
            logger.error(f"_load_phones_cache xatosi: {e}")
            return self._phones_cache or {}

    def add_phone(self, phone_data: Dict[str, Any]) -> bool:
        """
        Yangi harid qilingan telefonni 'Telefonlar' varag'iga yozadi.
        """
        buy_price = clean_num(phone_data.get("buy_price", 0))
        debt_amount = clean_num(phone_data.get("debt_amount", 0))
        imei = str(phone_data.get("imei", phone_data.get("imei_6", ""))).strip().lstrip("'")
        # 0 bilan boshlansa, Google Sheets son deb 0 ni o'chirib yubormasligi uchun apostrof bilan yoziladi
        imei_for_sheet = f"'{imei}" if imei.startswith("0") else imei

        row = [
            # 1. Harid ma'lumotlari
            get_now_str(),  # Harid sanasi (1-ustun)
            imei_for_sheet,
            str(phone_data.get("brand", "iPhone")),
            str(phone_data.get("version", "")),
            str(phone_data.get("type", "")),
            str(phone_data.get("memory", "")),
            str(phone_data.get("battery", "")),
            str(phone_data.get("color", "")),
            str(phone_data.get("has_box", "Yo'q")),
            buy_price,
            str(phone_data.get("seller_name", "")),       # Telefon egasi
            str(phone_data.get("seller_phone", "")),      # Telefon egasi telefoni
            str(phone_data.get("buyer_staff_name", phone_data.get("buyer_name", ""))),  # Qabul qilgan xodim
            str(phone_data.get("payment_type", "Naqd")),
            debt_amount,
            str(phone_data.get("imei_photo_url", "")),
            str(phone_data.get("phone_photo_url", "")),
            # 2. Tannarx va Remont
            0,  # Remont xarajati
            buy_price,  # Jami tannarx
            # 3. Kanal
            "",   # Kanal post ID
            # 4. Sotuv ma'lumotlari (boshida bo'sh)
            "", "", "", "", "", "", "", "", "", "",
            # 5. Natija va Foyda
            "",   # Sof foyda
            "Sotuvda",  # Holati
        ]

        if not self.spreadsheet:
            logger.warning(f"Baza ulanmagan. Telefon test keshga saqlanadi: {phone_data}")
            self._update_local_phone_cache(imei, row, 2)
            return True

        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PHONES)
            ws.append_row(row, value_input_option="USER_ENTERED")
            new_idx = len(self._phones_cache or {}) + 2
            self._update_local_phone_cache(imei, row, new_idx)
            return True
        except Exception as e:
            logger.error(f"add_phone xatosi: {e}")
            return False

    def get_phone_by_imei(self, imei_query: str) -> Optional[Dict[str, Any]]:
        """IMEI bo'yicha telefonni 0.0001s tezlikda keshdan qidiradi."""
        clean_imei = str(imei_query).strip().lstrip("'")
        if not clean_imei:
            return None

        def _lookup(c: Dict[str, Dict[str, Any]], q: str) -> Optional[Dict[str, Any]]:
            if q in c:
                return c[q]
            if len(q) > 6 and q[-6:] in c:
                return c[q[-6:]]
            return None

        cache = self._load_phones_cache()
        phone = _lookup(cache, clean_imei)
        if phone:
            return phone

        # Keshda topilmasa, bazani 1 marta majburiy yangilab qayta tekshiramiz
        cache = self._load_phones_cache(force_refresh=True)
        return _lookup(cache, clean_imei)

    def update_phone(self, row_index: int, updates: Dict[str, Any]) -> bool:
        """Mavjud telefon qatoridagi ma'lumotlarni yangilash."""
        # 1. Keshdagi mos telefonni yangilash
        if self._phones_cache:
            for k, phone_item in self._phones_cache.items():
                if phone_item.get("_row_index") == row_index:
                    phone_item.update(updates)

        if not self.spreadsheet:
            return True
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PHONES)
            headers = ws.row_values(1)
            row_range = f"A{row_index}:{gspread.utils.rowcol_to_a1(row_index, len(headers))}"
            # value_render_option="FORMULA" orqali mavjud =HYPERLINK(...) formulalari buzilmasdan saqlanadi
            res = ws.get(row_range, value_render_option="FORMULA")
            current_row = res[0] if res else []
            while len(current_row) < len(headers):
                current_row.append("")

            for key, val in updates.items():
                if key in headers:
                    col_idx = headers.index(key)
                    if "($)" in key or isinstance(val, (int, float)):
                        current_row[col_idx] = clean_num(val)
                    else:
                        current_row[col_idx] = str(val)

            ws.update(row_range, [current_row], value_input_option="USER_ENTERED")
            return True
        except Exception as e:
            logger.error(f"update_phone xatosi: {e}")
            return False

    def record_sale(self, row_index: int, sale_data: Dict[str, Any], phone_data: Dict[str, Any]) -> Tuple[bool, float]:
        """
        Sotuvni yagona 'Telefonlar' jadvaliga yozadi va sof foydani hisoblaydi.
        Sof foyda = Sotuv narxi - Jami tannarx - Sotuvchi KPI
        """
        sell_price = clean_num(sale_data.get("sell_price", 0))
        total_cost = clean_num(phone_data.get("Jami tannarx ($)", phone_data.get("Harid narxi ($)", 0)))
        kpi = clean_num(sale_data.get("seller_kpi", 0))
        profit = clean_num(sell_price - total_cost - kpi)
        initial_payment = clean_num(sale_data.get("initial_payment", 0))
        partner_debt = clean_num(sale_data.get("partner_debt", 0))

        updates = {
            "Sotuv narxi ($)": sell_price,
            "Xaridor ismi": str(sale_data.get("buyer_name", "")),
            "Xaridor telefoni": str(sale_data.get("buyer_phone", "")),
            "Sotuv to'lov turi": str(sale_data.get("payment_type", "Naqd")),
            "Hamkor nomi": str(sale_data.get("partner_name", "-")),
            "Boshlang'ich to'lov ($)": initial_payment,
            "Hamkor qarzi ($)": partner_debt,
            "Xodim KPI ($)": kpi,
            "Do'kon sotuvchisi": str(sale_data.get("seller_name", "")),
            "Sotilgan sana": get_now_str(),
            "Sof foyda ($)": profit,
            "Holati": "Sotildi",
        }

        success = self.update_phone(row_index, updates)

        # Agar sotuvchi KPI bo'lsa, xodim hisobiga KPI qo'shish
        if kpi > 0:
            seller_id = sale_data.get("seller_id")
            seller_name = sale_data.get("seller_name", "")
            self.add_seller_kpi(seller_id, seller_name, kpi)

        # Agar hamkor tanlangan bo'lsa, hamkor qarzini yangilash
        partner_name = sale_data.get("partner_name")
        partner_debt = float(sale_data.get("partner_debt", 0))
        if partner_name and partner_name != "-" and partner_debt > 0:
            self._add_partner_debt(partner_name, partner_debt)

        return success, profit

    def _add_partner_debt(self, partner_name: str, delta_amount: float) -> None:
        """Hamkorning qarzini yangilash yoki yangi hamkor qo'shish."""
        self._partners_cache = None
        if not self.spreadsheet:
            return
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PARTNERS)
            records = ws.get_all_records()
            sep = self.formula_sep
            for idx, r in enumerate(records, start=2):
                if str(r.get("Hamkor nomi", "")).strip().lower() == partner_name.strip().lower():
                    # Mavjud hamkor uchun formula avtomatik Telefonlar va Kirimlar orqali hisoblanadi.
                    # Agar yacheykada formula o'chib ketgan bo'lsa, formulani tiklaymiz.
                    formula = f'=IF(A{idx}<>""{sep} SUMIF(Telefonlar!$Y:$Y{sep} A{idx}{sep} Telefonlar!$AA:$AA) - SUMIF(Kirimlar!$E:$E{sep} A{idx}{sep} Kirimlar!$D:$D){sep} "")'
                    cell_val = ws.cell(idx, 2, value_render_option="FORMULA").value
                    if not str(cell_val).startswith("="):
                        ws.update_cell(idx, 2, formula)
                    return

            # Agar ro'yxatda bo'lmasa, yangi hamkor va avtomatik formulani qo'shish
            new_idx = len(records) + 2
            formula = f'=IF(A{new_idx}<>""{sep} SUMIF(Telefonlar!$Y:$Y{sep} A{new_idx}{sep} Telefonlar!$AA:$AA) - SUMIF(Kirimlar!$E:$E{sep} A{new_idx}{sep} Kirimlar!$D:$D){sep} "")'
            ws.append_row([partner_name, formula], value_input_option="USER_ENTERED")
        except Exception as e:
            logger.error(f"_add_partner_debt xatosi: {e}")

    def reduce_partner_debt(self, partner_name: str, amount: float, creator_name: str = "") -> bool:
        """Hamkor qarzini kamaytirish: Kirimlar jadvaliga yozadi va formula orqali qarz avtomatik kamayadi."""
        self._partners_cache = None
        if not self.spreadsheet:
            return True
        try:
            clean_amt = clean_num(amount)
            # 1. Kirimlar jadvaliga yozish (bu avtomatik tarzda Hamkorlar jadvalining formulasidagi qarzni kamaytiradi)
            ws_inc = self.spreadsheet.worksheet(config.SHEET_INCOMES)
            now_str = get_now_str()
            inc_id = str(int(get_tashkent_now().timestamp()))
            ws_inc.append_row(
                [inc_id, now_str, "Hamkor to'lovi", clean_amt, partner_name, "", "Hamkor", creator_name],
                value_input_option="USER_ENTERED",
            )

            # 2. Hamkorlar jadvalidagi yacheykada formula borligini tekshirish, bo'lmasa formulani tiklash
            ws_part = self.spreadsheet.worksheet(config.SHEET_PARTNERS)
            records = ws_part.get_all_records()
            sep = self.formula_sep
            for idx, r in enumerate(records, start=2):
                if str(r.get("Hamkor nomi", "")).strip().lower() == partner_name.strip().lower():
                    formula = f'=IF(A{idx}<>""{sep} SUMIF(Telefonlar!$Y:$Y{sep} A{idx}{sep} Telefonlar!$AA:$AA) - SUMIF(Kirimlar!$E:$E{sep} A{idx}{sep} Kirimlar!$D:$D){sep} "")'
                    cell_val = ws_part.cell(idx, 2, value_render_option="FORMULA").value
                    if not str(cell_val).startswith("="):
                        ws_part.update_cell(idx, 2, formula)
                    break

            return True
        except Exception as e:
            logger.error(f"reduce_partner_debt xatosi: {e}")
            return False

    def get_staff_list(self, active_only: bool = True, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Xodimlar ro'yxatini qaytaradi (in-memory kesh bilan - 0.0001s)."""
        now = time.time()
        if not force_refresh and self._staff_cache is not None and (now - self._staff_cache_time < self._staff_cache_ttl):
            records = self._staff_cache
        else:
            if not self.spreadsheet:
                records = []
            else:
                try:
                    ws = self.spreadsheet.worksheet(config.SHEET_STAFF)
                    records = ws.get_all_records()
                    self._staff_cache = records
                    self._staff_cache_time = now
                except Exception as e:
                    logger.error(f"get_staff_list xatosi: {e}")
                    records = self._staff_cache or []

        if active_only:
            return [r for r in records if str(r.get("Holati", "")).strip().lower() == "faol"]
        return records

    def add_seller_kpi(self, seller_id: Optional[int], seller_name: str, amount: float) -> bool:
        """Sotuvchiga ishlagan KPI sini qo'shish."""
        if not self.spreadsheet or amount <= 0:
            return True
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_STAFF)
            records = ws.get_all_records()
            headers = ws.row_values(1)
            for idx, r in enumerate(records, start=2):
                row_tg_id = str(r.get("Telegram ID", "")).strip()
                row_name = str(r.get("F.I.Sh", r.get("Xodim ismi", ""))).strip()

                is_match = False
                if seller_id and row_tg_id == str(seller_id):
                    is_match = True
                elif seller_name and row_name.lower() == seller_name.strip().lower():
                    is_match = True

                if is_match:
                    cur_total = clean_num(r.get("Jami KPI ($)", r.get("Jami ishlangan KPI ($)", 0)))
                    cur_paid = clean_num(r.get("To'langan KPI ($)", 0))
                    clean_amt = clean_num(amount)
                    new_total = clean_num(cur_total + clean_amt)
                    new_balance = clean_num(new_total - cur_paid)

                    if "Jami KPI ($)" in headers:
                        ws.update_cell(idx, headers.index("Jami KPI ($)") + 1, new_total)
                    if "Qoldiq KPI ($)" in headers:
                        sep = self.formula_sep
                        formula = f'=IF(A{idx}<>""{sep} F{idx}-G{idx}{sep} "")'
                        ws.update_cell(idx, headers.index("Qoldiq KPI ($)") + 1, formula)
                    self._staff_cache = None
                    logger.info(f"Sotuvchi KPI qo'shildi: {row_name} +{clean_amt}$")
                    return True
            return False
        except Exception as e:
            logger.error(f"add_seller_kpi xatosi: {e}")
            return False

    def pay_staff_kpi(self, staff_name: str, amount: float, creator_name: str = "") -> bool:
        """Xodimga KPI to'lash va Chiqimlar jadvaliga yozish."""
        if not self.spreadsheet or amount <= 0:
            return True
        try:
            ws_staff = self.spreadsheet.worksheet(config.SHEET_STAFF)
            records = ws_staff.get_all_records()
            headers = ws_staff.row_values(1)
            clean_amt = clean_num(amount)
            for idx, r in enumerate(records, start=2):
                row_name = str(r.get("F.I.Sh", r.get("Xodim ismi", ""))).strip()
                if row_name.lower() == staff_name.strip().lower():
                    cur_total = clean_num(r.get("Jami KPI ($)", r.get("Jami ishlangan KPI ($)", 0)))
                    cur_paid = clean_num(r.get("To'langan KPI ($)", 0))
                    new_paid = clean_num(cur_paid + clean_amt)

                    if "To'langan KPI ($)" in headers:
                        ws_staff.update_cell(idx, headers.index("To'langan KPI ($)") + 1, new_paid)
                    if "Qoldiq KPI ($)" in headers:
                        sep = self.formula_sep
                        formula = f'=IF(A{idx}<>""{sep} F{idx}-G{idx}{sep} "")'
                        ws_staff.update_cell(idx, headers.index("Qoldiq KPI ($)") + 1, formula)
                    break

            # Chiqimlar jadvaliga yozish
            ws_exp = self.spreadsheet.worksheet(config.SHEET_EXPENSES)
            now_str = get_now_str()
            exp_id = str(int(get_tashkent_now().timestamp()))
            ws_exp.append_row(
                [exp_id, now_str, "KPI", clean_amt, "", staff_name, staff_name, creator_name],
                value_input_option="USER_ENTERED",
            )
            self._staff_cache = None
            logger.info(f"KPI to'lovi yozildi: {staff_name} - {clean_amt}$")
            return True
        except Exception as e:
            logger.error(f"pay_staff_kpi xatosi: {e}")
            return False

    def record_expense(
        self,
        expense_type: str,
        amount: float,
        imei: str = "",
        staff_name: str = "",
        recipient: str = "",
        creator_name: str = "",
    ) -> bool:
        """Chiqimlar jadvaliga yangi chiqim yozadi."""
        if not self.spreadsheet or amount <= 0:
            return False
        try:
            ws_exp = self.spreadsheet.worksheet(config.SHEET_EXPENSES)
            now_str = get_now_str()
            exp_id = str(int(get_tashkent_now().timestamp()))
            clean_amt = clean_num(amount)
            ws_exp.append_row([
                exp_id,
                now_str,
                expense_type,
                clean_amt,
                str(imei),
                str(staff_name),
                str(recipient),
                str(creator_name),
            ], value_input_option="USER_ENTERED")
            logger.info(f"Chiqim yozildi: {expense_type} - {clean_amt}$ (kirituvchi: {creator_name})")
            return True
        except Exception as e:
            logger.error(f"record_expense xatosi: {e}")
            return False

    def record_income(
        self,
        income_type: str,
        amount: float,
        partner_name: str = "",
        imei: str = "",
        source: str = "",
        creator_name: str = "",
    ) -> bool:
        """Kirimlar jadvaliga yangi kirim yozadi."""
        if not self.spreadsheet or amount <= 0:
            return False
        try:
            ws_inc = self.spreadsheet.worksheet(config.SHEET_INCOMES)
            now_str = get_now_str()
            inc_id = str(int(get_tashkent_now().timestamp()))
            clean_amt = clean_num(amount)
            ws_inc.append_row([
                inc_id,
                now_str,
                income_type,
                clean_amt,
                str(partner_name),
                str(imei),
                str(source),
                str(creator_name),
            ], value_input_option="USER_ENTERED")
            logger.info(f"Kirim yozildi: {income_type} - {clean_amt}$ (kirituvchi: {creator_name})")
            return True
        except Exception as e:
            logger.error(f"record_income xatosi: {e}")
            return False

    def pay_phone_debt(self, imei: str, amount: float, creator_name: str = "") -> Tuple[bool, float]:
        """
        Telefon sotib olishda qolgan qarzni to'lash:
        - Telefonlar jadvalidagi 'Harid qarz summasi ($)' kamaytiriladi
        - Chiqimlar jadvaliga yoziladi
        """
        if not self.spreadsheet or amount <= 0:
            return False, 0.0

        phone = self.get_phone_by_imei(imei)
        if not phone:
            return False, 0.0

        clean_amt = clean_num(amount)
        row_idx = phone.get("_row_index")
        cur_debt = clean_num(phone.get("Harid qarz summasi ($)", 0))
        new_debt = clean_num(max(0.0, cur_debt - clean_amt))

        # 1. Telefonlar jadvalini yangilash
        if row_idx:
            self.update_phone(row_idx, {"Harid qarz summasi ($)": new_debt})

        # 2. Chiqimlar jadvaliga yozish
        recipient = phone.get("Telefon egasi", "")
        self.record_expense(
            expense_type="Telefon (qarz)",
            amount=clean_amt,
            imei=imei,
            recipient=recipient,
            creator_name=creator_name,
        )
        return True, new_debt

    def close_store_phone_debt(self, imei: str, amount: float, creator_name: str = "") -> Tuple[bool, float]:
        """
        Do'kondan qarz yopish / kirim kiritish:
        - Agar telefon bo'lsa, qarzini kamaytiradi (agar mavjud bo'lsa)
        - Kirimlar jadvaliga yoziladi
        """
        if not self.spreadsheet or amount <= 0:
            return False, 0.0

        clean_amt = clean_num(amount)
        phone = self.get_phone_by_imei(imei)
        new_debt = 0.0
        if phone:
            row_idx = phone.get("_row_index")
            cur_debt = clean_num(phone.get("Harid qarz summasi ($)", 0))
            new_debt = clean_num(max(0.0, cur_debt - clean_amt))
            if row_idx:
                self.update_phone(row_idx, {"Harid qarz summasi ($)": new_debt})

        # Kirimlar jadvaliga yozish
        self.record_income(
            income_type="Do'kondan",
            amount=clean_amt,
            imei=imei,
            source="Do'kon",
            creator_name=creator_name,
        )
        return True, new_debt

    def get_financial_summary(self) -> Dict[str, float]:
        """
        Google Sheets jadvallaridan real moliyaviy balansni hisoblaydi:
        - Naqd sotuvlar va boshlang'ich to'lovlar
        - Kirimlar (Kirimlar varag'i)
        - Chiqimlar (Chiqimlar varag'i)
        - Naqd haridlar (Telefonlar varag'i)
        - Hamkorlarning qarzdorligi (Hamkorlar varag'i)
        - Do'konning telefonlar bo'yicha qarzi (Telefonlar varag'i)
        - Xodimlarning qoldiq KPI qarzi (Xodimlar varag'i)
        """
        summary = {
            "kassa_balance": 0.0,
            "total_income": 0.0,
            "total_expense": 0.0,
            "partner_debts": 0.0,
            "store_phone_debts": 0.0,
            "staff_kpi_debts": 0.0,
            "total_net_profit": 0.0,
        }
        if not self.spreadsheet:
            return summary

        try:
            # 1. Kirimlar jadvali
            try:
                ws_inc = self.spreadsheet.worksheet(config.SHEET_INCOMES)
                for r in ws_inc.get_all_records():
                    val = str(r.get("Summa ($)", "0")).replace("$", "").replace(",", "").strip()
                    if val:
                        summary["total_income"] += float(val)
            except Exception as e:
                logger.warning(f"Kirimlar o'qishda xato: {e}")

            # 2. Chiqimlar jadvali
            try:
                ws_exp = self.spreadsheet.worksheet(config.SHEET_EXPENSES)
                for r in ws_exp.get_all_records():
                    val = str(r.get("Summa ($)", "0")).replace("$", "").replace(",", "").strip()
                    if val:
                        summary["total_expense"] += float(val)
            except Exception as e:
                logger.warning(f"Chiqimlar o'qishda xato: {e}")

            # 3. Telefonlar jadvali (Haridlar, Sotuvlar, Telefon qarzlari, Foyda)
            try:
                ws_ph = self.spreadsheet.worksheet(config.SHEET_PHONES)
                for r in ws_ph.get_all_records():
                    status = str(r.get("Holati", "")).strip()
                    if status == "Sotildi":
                        pay_type = str(r.get("Sotuv to'lov turi", "")).strip()
                        if pay_type == "Naqd":
                            sp = str(r.get("Sotuv narxi ($)", "0")).replace("$", "").replace(",", "").strip()
                            if sp:
                                summary["total_income"] += float(sp)
                        elif pay_type == "Qarz":
                            init_p = str(r.get("Boshlang'ich to'lov ($)", "0")).replace("$", "").replace(",", "").strip()
                            if init_p:
                                summary["total_income"] += float(init_p)

                        profit = str(r.get("Sof foyda ($)", "0")).replace("$", "").replace(",", "").strip()
                        if profit:
                            summary["total_net_profit"] += float(profit)

                    # Naqd harid chiqimi
                    buy_type = str(r.get("Harid to'lov turi", "")).strip()
                    if buy_type == "Naqd":
                        bp = str(r.get("Harid narxi ($)", "0")).replace("$", "").replace(",", "").strip()
                        if bp:
                            summary["total_expense"] += float(bp)

                    # Qoldiq telefon qarzi
                    debt = str(r.get("Harid qarz summasi ($)", "0")).replace("$", "").replace(",", "").strip()
                    if debt:
                        summary["store_phone_debts"] += float(debt)
            except Exception as e:
                logger.warning(f"Telefonlar o'qishda xato: {e}")

            # 4. Hamkorlar qarzdorligi
            try:
                ws_part = self.spreadsheet.worksheet(config.SHEET_PARTNERS)
                for r in ws_part.get_all_records():
                    p_debt = str(r.get("Hozirgi qarzdorlik ($)", "0")).replace("$", "").replace(",", "").strip()
                    if p_debt:
                        summary["partner_debts"] += float(p_debt)
            except Exception as e:
                logger.warning(f"Hamkorlar o'qishda xato: {e}")

            # 5. Xodimlar KPI qarzdorligi
            try:
                ws_st = self.spreadsheet.worksheet(config.SHEET_STAFF)
                for r in ws_st.get_all_records():
                    kpi = str(r.get("Qoldiq KPI ($)", "0")).replace("$", "").replace(",", "").strip()
                    if kpi:
                        summary["staff_kpi_debts"] += float(kpi)
            except Exception as e:
                logger.warning(f"Xodimlar o'qishda xato: {e}")

            summary["kassa_balance"] = summary["total_income"] - summary["total_expense"]

        except Exception as e:
            logger.error(f"get_financial_summary xatosi: {e}")

        return summary

    def get_models(self, force_refresh: bool = False) -> List[Dict[str, str]]:
        """Modellar ro'yxatini qaytaradi (in-memory kesh bilan)."""
        now = time.time()
        if not force_refresh and self._models_cache and (now - self._models_cache_time < self._models_cache_ttl):
            return self._models_cache

        if not self.spreadsheet:
            # Standart iPhone ro'yxati (X dan 16 gacha)
            return [
                {"Brend": "iPhone", "Versiya": "X", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "XS", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "XS Max", "Turi": "Max"},
                {"Brend": "iPhone", "Versiya": "XR", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "11", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "11 Pro", "Turi": "Pro"},
                {"Brend": "iPhone", "Versiya": "11 Pro Max", "Turi": "Pro Max"},
                {"Brend": "iPhone", "Versiya": "12", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "12 Pro", "Turi": "Pro"},
                {"Brend": "iPhone", "Versiya": "12 Pro Max", "Turi": "Pro Max"},
                {"Brend": "iPhone", "Versiya": "13", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "13 Pro", "Turi": "Pro"},
                {"Brend": "iPhone", "Versiya": "13 Pro Max", "Turi": "Pro Max"},
                {"Brend": "iPhone", "Versiya": "14", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "14 Plus", "Turi": "Plus"},
                {"Brend": "iPhone", "Versiya": "14 Pro", "Turi": "Pro"},
                {"Brend": "iPhone", "Versiya": "14 Pro Max", "Turi": "Pro Max"},
                {"Brend": "iPhone", "Versiya": "15", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "15 Plus", "Turi": "Plus"},
                {"Brend": "iPhone", "Versiya": "15 Pro", "Turi": "Pro"},
                {"Brend": "iPhone", "Versiya": "15 Pro Max", "Turi": "Pro Max"},
                {"Brend": "iPhone", "Versiya": "16", "Turi": "Oddiy"},
                {"Brend": "iPhone", "Versiya": "16 Pro", "Turi": "Pro"},
                {"Brend": "iPhone", "Versiya": "16 Pro Max", "Turi": "Pro Max"},
            ]
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_MODELS)
            records = ws.get_all_records()
            self._models_cache = records
            self._models_cache_time = now
            return records
        except Exception as e:
            logger.error(f"get_models xatosi: {e}")
            return self._models_cache or []

    def reload_cache(self) -> None:
        """Barcha keshlarni tozalash va yangilash."""
        self._models_cache = None
        self._models_cache_time = 0
        self._phones_cache = None
        self._phones_cache_time = 0
        self._staff_cache = None
        self._staff_cache_time = 0
        self._partners_cache = None
        self._partners_cache_time = 0
        self._templates_cache = None
        self._templates_cache_time = 0

    def get_partners(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Hamkorlar ro'yxatini qaytaradi (in-memory kesh bilan - 0.0001s)."""
        now = time.time()
        if not force_refresh and self._partners_cache is not None and (now - self._partners_cache_time < self._partners_cache_ttl):
            return self._partners_cache

        if not self.spreadsheet:
            self._partners_cache = []
            self._partners_cache_time = now
            return self._partners_cache

        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PARTNERS)
            records = ws.get_all_records()
            self._partners_cache = records
            self._partners_cache_time = now
            return records
        except Exception as e:
            logger.error(f"get_partners xatosi: {e}")
            return self._partners_cache or []

    def get_template(self, template_type: str = "Elon", force_refresh: bool = False) -> str:
        """Kanal va hisobotlar uchun shablonni 'Shablonlar' varag'idan oladi."""
        default_tpl = (
            "📱 <b>{model}</b>\n\n"
            "💾 Xotirasi: <b>{memory}</b>\n"
            "🔋 Batareya holati: <b>{battery}%</b>\n"
            "🎨 Rangi: <b>{color}</b>\n"
            "📦 Karobkasi: <b>{box}</b>\n"
            "🔍 IMEI: <code>{imei}</code>\n\n"
            "💰 Sotuv narxi: <b>{price}$</b>\n\n"
            "📞 Bog‘lanish: +998 90 123 45 67\n"
            "    @oymaoy_admin\n\n"
            "📍 Toshkent shahri"
        )
        now = time.time()
        if not force_refresh and self._templates_cache is not None and (now - self._templates_cache_time < self._templates_cache_ttl):
            return self._templates_cache.get(template_type.lower(), default_tpl)

        if not self.spreadsheet:
            return default_tpl

        try:
            ws = self.spreadsheet.worksheet(config.SHEET_TEMPLATES)
            records = ws.get_all_records()
            cache: Dict[str, str] = {}
            for r in records:
                t_type = str(r.get("Shablon turi", "")).strip().lower()
                text = str(r.get("Matn", "")).strip()
                if t_type and text:
                    cache[t_type] = text
            self._templates_cache = cache
            self._templates_cache_time = now
            return cache.get(template_type.lower(), default_tpl)
        except Exception as e:
            logger.error(f"get_template xatosi: {e}")
            if self._templates_cache and template_type.lower() in self._templates_cache:
                return self._templates_cache[template_type.lower()]
            return default_tpl


# Singleton instansiya
sheets_service = GoogleSheetsService()
