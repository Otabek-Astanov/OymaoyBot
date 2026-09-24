import logging
from datetime import datetime
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


class GoogleSheetsService:
    def __init__(self):
        self.client: Optional[Any] = None
        self.spreadsheet: Optional[Any] = None
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

    def check_member(self, telegram_id: int) -> Tuple[bool, str, str]:
        """
        Foydalanuvchini tekshiradi.
        Qaytaradi: (ruxsat_bormi: bool, roli: str, ismi: str)
        Agar admin_ids ichida bo'lsa, avtomatik ruxsat beradi.
        """
        if telegram_id in config.ADMIN_IDS:
            return True, "Admin", "Bosh Admin"

        if not self.spreadsheet:
            # Agar baza ulanmagan bo'lsa (ishlab chiqish jarayonida) ruxsat beriladi
            logger.warning("Baza ulanmagan: test rejimida a'zoga ruxsat berildi.")
            return True, "Admin", "Test Foydalanuvchi"

        try:
            ws = self.spreadsheet.worksheet(config.SHEET_MEMBERS)
            records = ws.get_all_records()
            for row in records:
                row_tg_id = str(row.get("Telegram ID", "")).strip()
                if row_tg_id == str(telegram_id):
                    is_active = str(row.get("Holati", "")).lower() == "faol"
                    role = str(row.get("Roli", "Sotuvchi"))
                    name = str(row.get("F.I.Sh", "Noma'lum"))
                    return is_active, role, name
            return False, "", ""
        except Exception as e:
            logger.error(f"check_member xatosi: {e}")
            return False, "", ""

    def add_member(self, telegram_id: int, full_name: str, phone_number: str, role: str = "Sotuvchi") -> bool:
        """Yangi a'zo qo'shish."""
        if not self.spreadsheet:
            return False
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_MEMBERS)
            ws.append_row([str(telegram_id), full_name, phone_number, role, "Faol"])
            return True
        except Exception as e:
            logger.error(f"add_member xatosi: {e}")
            return False

    def add_phone(self, phone_data: Dict[str, Any]) -> bool:
        """
        Yangi harid qilingan telefonni 'Telefonlar' varag'iga yozadi.
        """
        if not self.spreadsheet:
            logger.warning(f"Baza ulanmagan. Telefon saqlanmadi: {phone_data}")
            return True

        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PHONES)
            buy_price = float(phone_data.get("buy_price", 0))
            # Ustunlar tartibi: DEFAULT_HEADERS[SHEET_PHONES] (32 ta ustun)
            row = [
                # 1. Harid ma'lumotlari
                datetime.now().strftime("%Y-%m-%d %H:%M"),  # Harid sanasi (1-ustun)
                str(phone_data.get("imei_6", "")),
                str(phone_data.get("brand", "iPhone")),
                str(phone_data.get("model", "")),
                str(phone_data.get("version", "")),
                str(phone_data.get("type", "")),
                str(phone_data.get("memory", "")),
                str(phone_data.get("battery", "")),
                str(phone_data.get("color", "")),
                str(phone_data.get("has_box", "Yo'q")),
                str(buy_price),
                str(phone_data.get("seller_name", "")),       # Telefon egasi
                str(phone_data.get("seller_phone", "")),      # Telefon egasi telefoni
                str(phone_data.get("payment_type", "Naqd")),
                str(phone_data.get("debt_amount", 0)),
                str(phone_data.get("imei_photo_url", "")),
                str(phone_data.get("phone_photo_url", "")),
                # 2. Tannarx va Remont
                "0",  # Remont xarajati
                str(buy_price),  # Jami tannarx
                # 3. Kanal
                "",   # Kanal post ID
                # 4. Sotuv ma'lumotlari (boshida bo'sh)
                "", "", "", "", "", "", "", "", "", "",
                # 5. Natija va Foyda
                "",   # Sof foyda
                "Sotuvda",  # Holati
            ]
            ws.append_row(row)
            return True
        except Exception as e:
            logger.error(f"add_phone xatosi: {e}")
            return False

    def get_phone_by_imei(self, imei_6: str) -> Optional[Dict[str, Any]]:
        """IMEI (oxirgi 6) bo'yicha telefonni qidiradi."""
        if not self.spreadsheet:
            # Mock data test uchun
            if imei_6 == "123456":
                return {
                    "Harid sanasi": "2026-09-24 12:00",
                    "IMEI (oxirgi 6)": "123456",
                    "Brend": "iPhone",
                    "Model": "iPhone 13 Pro",
                    "Versiya": "13",
                    "Turi": "Pro",
                    "Xotira": "128 GB",
                    "Batareya %": "86",
                    "Rang": "Sierra Blue",
                    "Karobka": "Ha",
                    "Harid narxi ($)": "550",
                    "Telefon egasi": "Akmal",
                    "Telefon egasi telefoni": "+998901234567",
                    "Remont xarajati ($)": "0",
                    "Jami tannarx ($)": "550",
                    "Holati": "Sotuvda",
                    "Kanal post ID": "",
                    "_row_index": 2,
                }
            return None

        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PHONES)
            records = ws.get_all_records()
            for idx, row in enumerate(records, start=2):
                if str(row.get("IMEI (oxirgi 6)", "")).strip() == str(imei_6).strip():
                    row["_row_index"] = idx
                    return row
            return None
        except Exception as e:
            logger.error(f"get_phone_by_imei xatosi: {e}")
            return None

    def update_phone(self, row_index: int, updates: Dict[str, Any]) -> bool:
        """Mavjud telefon qatoridagi ma'lumotlarni yangilash."""
        if not self.spreadsheet:
            return True
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PHONES)
            headers = ws.row_values(1)
            current_row = ws.row_values(row_index)
            # Row uzunligini headers bilan tenglashtirish
            while len(current_row) < len(headers):
                current_row.append("")

            for key, val in updates.items():
                if key in headers:
                    col_idx = headers.index(key)
                    current_row[col_idx] = str(val)

            # Bitta so'rovda butun qatorni yangilash
            ws.update(f"A{row_index}:{gspread.utils.rowcol_to_a1(row_index, len(headers))}", [current_row])
            return True
        except Exception as e:
            logger.error(f"update_phone xatosi: {e}")
            return False

    def record_sale(self, row_index: int, sale_data: Dict[str, Any], phone_data: Dict[str, Any]) -> Tuple[bool, float]:
        """
        Sotuvni yagona 'Telefonlar' jadvaliga yozadi va sof foydani hisoblaydi.
        Sof foyda = Sotuv narxi - Jami tannarx - Sotuvchi KPI
        """
        sell_price = float(sale_data.get("sell_price", 0))
        total_cost = float(phone_data.get("Jami tannarx ($)", phone_data.get("Harid narxi ($)", 0)))
        kpi = float(sale_data.get("seller_kpi", 0))
        profit = sell_price - total_cost - kpi

        updates = {
            "Sotuv narxi ($)": str(sell_price),
            "Xaridor ismi": str(sale_data.get("buyer_name", "")),
            "Xaridor telefoni": str(sale_data.get("buyer_phone", "")),
            "Sotuv to'lov turi": str(sale_data.get("payment_type", "Naqd")),
            "Hamkor nomi": str(sale_data.get("partner_name", "-")),
            "Boshlang'ich to'lov ($)": str(sale_data.get("initial_payment", "0")),
            "Hamkor qarzi ($)": str(sale_data.get("partner_debt", "0")),
            "Xodim KPI ($)": str(kpi),
            "Do'kon sotuvchisi": str(sale_data.get("seller_name", "")),
            "Sotilgan sana": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "Sof foyda ($)": str(profit),
            "Holati": "Sotildi",
        }

        success = self.update_phone(row_index, updates)

        # Agar hamkor tanlangan bo'lsa, hamkor qarzini yangilash
        partner_name = sale_data.get("partner_name")
        partner_debt = float(sale_data.get("partner_debt", 0))
        if partner_name and partner_name != "-" and partner_debt > 0:
            self._add_partner_debt(partner_name, partner_debt)

        return success, profit

    def _add_partner_debt(self, partner_name: str, delta_amount: float) -> None:
        """Hamkorning qarzini oshirish."""
        if not self.spreadsheet:
            return
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PARTNERS)
            records = ws.get_all_records()
            for idx, r in enumerate(records, start=2):
                if str(r.get("Hamkor nomi", "")).strip().lower() == partner_name.strip().lower():
                    cur_debt = float(r.get("Hozirgi qarzdorlik ($)", 0))
                    ws.update_cell(idx, 2, str(cur_debt + delta_amount))
                    return
            # Agar ro'yxatda bo'lmasa, yangi qo'shish
            ws.append_row([partner_name, str(delta_amount)])
        except Exception as e:
            logger.error(f"_add_partner_debt xatosi: {e}")

    def get_models(self) -> List[Dict[str, str]]:
        """Modellar ro'yxatini qaytaradi."""
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
            return ws.get_all_records()
        except Exception as e:
            logger.error(f"get_models xatosi: {e}")
            return []

    def get_partners(self) -> List[Dict[str, Any]]:
        """Hamkorlar ro'yxatini qaytaradi."""
        if not self.spreadsheet:
            return [
                {"Hamkor nomi": "Alif Nasiya", "Hozirgi qarzdorlik ($)": "1200"},
                {"Hamkor nomi": "Uzum Nasiya", "Hozirgi qarzdorlik ($)": "850"},
                {"Hamkor nomi": "Iman Pay", "Hozirgi qarzdorlik ($)": "400"},
            ]
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_PARTNERS)
            return ws.get_all_records()
        except Exception as e:
            logger.error(f"get_partners xatosi: {e}")
            return []

    def get_template(self, template_type: str = "Elon") -> str:
        """Kanal uchun e'lon shablonini oladi."""
        default_tpl = (
            "📱 <b>{model}</b>\n\n"
            "💾 Xotirasi: <b>{memory}</b>\n"
            "🔋 Batareya holati: <b>{battery}%</b>\n"
            "🎨 Rangi: <b>{color}</b>\n"
            "📦 Karobkasi: <b>{box}</b>\n"
            "🔍 IMEI (oxirgi 6): <code>{imei_6}</code>\n\n"
            "💰 Sotuv narxi: <b>{price}$</b>\n\n"
            "📞 Bog'lanish: @oymaoy_admin | +998 90 123 45 67\n"
            "📍 Toshkent shahri"
        )
        if not self.spreadsheet:
            return default_tpl
        try:
            ws = self.spreadsheet.worksheet(config.SHEET_TEMPLATES)
            records = ws.get_all_records()
            for r in records:
                if str(r.get("Shablon turi", "")).strip().lower() == template_type.lower():
                    return str(r.get("Matn", default_tpl))
            return default_tpl
        except Exception as e:
            logger.error(f"get_template xatosi: {e}")
            return default_tpl


# Singleton instansiya
sheets_service = GoogleSheetsService()
