# OymaoyBot auditi va tuzatishlar implementatsiya rejasi

> **Agentik ijrochilar uchun:** Agar subagentlar mavjud bo'lsa, ushbu reja bajarilishi uchun `superpowers:subagent-driven-development`, aks holda `superpowers:executing-plans` ishlatilsin. Qadamlar kuzatish uchun checkbox (`- [ ]`) sintaksisidan foydalanadi.

**Maqsad:** Xarid, sotuv, qarz va KPI amallarining ishonchli saqlanishini ta'minlash, noto'g'ri hisob-kitoblarni bartaraf etish va botni tekshiriladigan tartibda ishga tushirish.

**Arxitektura:** Dastlab mavjud aiogram va Google Sheets tizimida aniq xatolar tuzatiladi. Keyingi bosqichda moliyaviy yozuvlar yagona yozuvchi orqali, operatsiya identifikatori va birgalikda bajariladigan Sheets so'rovi bilan boshqariladi; Telegram xabarlari saqlangan operatsiyadan keyin yuboriladi. Sheets bilan parallel qo'lda tahrirlash yoki bir nechta yozuvchi zarur bo'lsa, alohida tranzaksion baza loyihasi ochiladi: bu audit avtomatik migratsiyani taklif qilmaydi.

**Texnologiyalar steki:** Python 3.12, aiogram 3, gspread, Google Sheets API v4, Google Drive API, Docker.

---

## Audit doirasi va dalillar

- Sana: 2026-10-06, loyiha: `/Users/bek/Projects/OymaoyBot`.
- Tekshirilgan Git holati: `50bc0d2`; boshlang'ich ishchi daraxt toza edi.
- Jadvaldagi qator manzillari audit boshlanishidagi `50bc0d2` nusxasiga tegishli. Audit yakunida boshqa ish natijasida `bot_harid/handlers/harid_flow.py`, `bot_sotuv/handlers/sotuv_flow.py`, `services/google_sheets.py` va `utils/formatters.py` o'zgargani aniqlandi. Bu audit ularni o'zgartirmadi yoki qaytarmadi; o'zgarishlar IMEI apostrofini ko'rsatish/saqlashga taalluqli. Yangi fayllar sintaktik tekshirildi va 25 ta nuqson ssenariysi shu holatda qayta takrorlandi.
- 22 ta Python fayl, uchta bot oqimi, umumiy xizmatlar, Docker sozlamalari va mavjud ikki tavsif hujjati o'rganildi.
- 22 ta Python fayl `compile()` orqali sintaktik tekshiruvdan o'tdi; fayllarga bytecode yozilmadi.
- `venv/bin/python -m pip check`: `No broken requirements found.`
- Mahalliy muhit: Python 3.12.12, aiogram 3.31.0, gspread 6.2.1, google-api-python-client 2.200.0. Bular ishlab chiqarish serverining versiyalari sifatida talqin qilinmasin.
- Tashqi ulanishlar o'rnini sun'iy obyektlar egallagan sinovda **25 ta nuqson ssenariysi** takrorlandi. Bu loyiha regressiya testlari o'tganini anglatmaydi: sinov hozirgi noto'g'ri xatti-harakatlarni tasdiqladi.
- Sinov dasturi: `/private/tmp/oymaoy-audit-2026-10-06.py`. Buyruq: `venv/bin/python -B /private/tmp/oymaoy-audit-2026-10-06.py`; yakuniy bajarilish kodi `0`. Dastur vaqtinchalik, keyingi implementatsiyada quyidagi doimiy regressiya testlari yaratiladi.
- Sinov `.env`, haqiqiy Google kalitlari yoki OAuth tokenlarini yuklamadi; tarmoq ulanishlari bloklandi. Botlar ishga tushirilmadi, Telegram xabari yuborilmadi va Google jadvallariga yozilmadi.
- Docker Compose konfiguratsiyasi tasdiqlanmadi: mahalliy Docker CLI da `compose` buyrug'i mavjud emas. Docker image yig'ilmadi.
- Tokenning haqiqiyligi, ishlab chiqarishdagi ma'lumotlar sifati, amaldagi Google ruxsatlari va real yuklama tekshirilmagan.
- Hozirgi natija audit va reja; ushbu audit tomonidan ilova kodiga tuzatish kiritilmagan.

## Loyiha qanday ishlaydi

`run_all.py` tokenlar soniga qarab uchta botni alohida yoki bitta umumiy botni ishga tushiradi. Har bir bot aiogram FSM orqali ketma-ket ma'lumot yig'adi. `services/google_sheets.py` ma'lumotlarni saqlaydi va kassa/qarz/KPI hisobini o'qiydi; `services/google_drive.py` rasmlarni yuklaydi; `services/telegram_poster.py` kanal va guruh xabarlarini yuboradi.

Google Sheets hozir asosiy ma'lumotlar ombori. `Xodimlar`, `Telefonlar`, `Chiqimlar`, `Kirimlar`, `Hamkorlar`, `Modellar`, `Shablonlar` — jami yettita varaq bor. Xizmatlar import paytida yaratiladi. Google chaqiruvlari sinxron, lekin ular asinxron handler ichida bevosita bajarilmoqda. FSM uchun maxsus saqlash tizimi berilmagan.

## Topilgan muammolar

**P0:** zudlik bilan ko'rib chiqiladigan maxfiy ma'lumot. **P1:** ma'lumot/pul hisobi buzilishi yoki asosiy oqim ishlamasligi. **P2:** ishonchlilik, imkoniyat yoki ekspluatatsiya kamchiligi.

| ID | Daraja | Aniq holat va ta'sir | Kod dalili | Sinov |
|---|---|---|---|---|
| A01 | P0 | `.env.example` ichida namunaviy o'rinbosar o'rniga Telegram tokeni formatidagi qiymat Git tomonidan kuzatilmoqda. Faolligi tekshirilmagan; ishlaydigan token bo'lsa uni almashtirish kerak. | `.env.example:2` | F21 |
| A02 | P1 | Sheets ulanmasa `add_phone`, `update_phone`, KPI to'lovi va hamkor to'lovi ayrim hollarda `True` qaytaradi. Telefonning soxta kesh yozuvi navbatdagi qidiruvda ham yo'qolishi mumkin. | `services/google_sheets.py:365`, `:413`, `:517`, `:610` | F03 |
| A03 | P1 | Xarid va sotuv handlerlari saqlash natijasini tekshirmaydi. Sotuv guruhi xabari yozuvdan oldin yuboriladi; yozuv muvaffaqiyatsiz bo'lsa ham kanal va foydalanuvchi muvaffaqiyat xabari yangilanadi. Karobka va kanal oqimlari ham yozuv natijasini e'tiborsiz qoldiradi. | `bot_harid/handlers/harid_flow.py:715`, `:835`, `:1072`, `:1199`; `bot_sotuv/handlers/sotuv_flow.py:809`, `:816`, `:853` | F04, F05 |
| A04 | P1 | Telefon yozuvi bajarilmasa ham KPI qo'shiladi. Qarz to'lovi ichki ikki yozuv muvaffaqiyatsiz bo'lsa ham `True` qaytaradi. KPI va remont ham bir nechta mustaqil yozuvdan iborat. Qisman bajarilish va qayta urinish hisobni buzishi mumkin. | `services/google_sheets.py:466`, `:474`, `:608`, `:733`, `:737`, `:744`, `:763`, `:766`; `bot_harajat/handlers/harajat_flow.py:466`, `:475` | F06, F07 |
| A05 | P1 | Sotuv yakunida telefonning joriy holati qayta tekshirilmaydi, operatsiya ID si yo'q. Bir xil sotuvni ikki marta yuborish KPI ni ikki marta qo'shadi. Xarid qatori `len(col_a)+1` orqali topilib, keyin yoziladi; bir nechta jarayon ishlasa bir qator ustiga yozish xavfi bor. | `services/google_sheets.py:372`, `:439`, `:474`; `bot_sotuv/handlers/sotuv_flow.py:796` | F10; parallel jarayon xavfi koddan aniqlandi, real parallel server sinovi o'tkazilmadi |
| A06 | P1 | `update_phone` keshni API natijasidan oldin o'zgartiradi. Muvaffaqiyatsiz yozuvdan keyin keshda telefon sotilgan, Sheets da esa sotilmagan bo'lishi mumkin. | `services/google_sheets.py:408`, `:433` | F08 |
| A07 | P1 | `_safe_get_all_records` bo'sh qatorlarni olib tashlaydi; KPI/hamkor yangilash esa ro'yxatni `enumerate(..., start=2)` bilan jismoniy qatorga tenglashtiradi. Bo'sh qator bo'lsa boshqa qator yangilanadi. | `services/google_sheets.py:240`, `:497`, `:534`, `:577`, `:617` | F09 |
| A08 | P1 | Xarid yozuvi ustunlarni standart tartibda yozadi, mavjud varaq sarlavhalari tekshirilmaydi. Ustunlar o'rni o'zgarsa sana IMEI ustuniga tushishi mumkin. Hamkor/KPI formulalarida ham Y/AA/F/G kabi qat'iy ustun harflari bor. | `services/google_sheets.py:115`, `:334`, `:376`, `:501`, `:598` | F22 |
| A09 | P1 | To'liq IMEI topilmasa uning oxirgi olti raqami bilan boshqa telefon qaytariladi. Bir xil oxirgi olti raqamga ega telefonlar bitta lug'at kalitini almashtiradi. | `services/google_sheets.py:315`, `:389`, `:392` | F11 |
| A10 | P1 | `clean_currency` minus va vergulni olib tashlaydi: `-10 → 10`, `10,50 → 1050`; `1..2` esa handlerda `ValueError` chiqaradi. `float` bilan pul hisoblash yaxlitlashni bir xil kafolatlamaydi. | Har uch handlerdagi `clean_currency`; `bot_sotuv/handlers/sotuv_flow.py:370`, `:524` | F02 |
| A11 | P1 | Sotuv narxi 100 bo'lsa boshlang'ich to'lov 200 ham qabul qilinadi. Xarid qarzi 100 bo'lsa 150 to'lash qabul qilinib, 150 chiqim yoziladi. KPI va hamkor qarz to'lovida ham chegara yoki avans qoidasi ajratilmagan. | `bot_sotuv/handlers/sotuv_flow.py:529`; `services/google_sheets.py:729`, `:739`, `:608`, `:514` | F12, F24 |
| A12 | P1 | Remont summasi kiritilganda `clean_num` nomi topilmaydi: import yo'q. | `bot_harajat/handlers/harajat_flow.py:24`, `:458` | F01 |
| A13 | P1 | Alohida e'lon oqimi sotilgan telefonni ham qabul qilib, e'lon yakunida `Holati=Sotuvda` yozadi. Sotuv narxi va kanal post ID si ham almashtiriladi; oldingi postni boshqarish yo'qolishi mumkin. | `bot_harid/handlers/harid_flow.py:910`, `:976`, `:1076`, `:1077` | F23 |
| A14 | P1 | Bitta token rejimida uchta routerda bir xil `/start` va bekor qilish handleri bor. Birinchi Harid routeri xabarni ushlab qoladi: Investor balans menyusi o'rniga rad javobi oladi. Boshqa foydalanuvchiga ham faqat xarid menyusi chiqadi. | `run_all.py:55`; har uch handlerning `cmd_start`/`cancel_handler` funksiyalari | F15 |
| A15 | P1 | Ruxsatlar asosan oqim boshlanishida tekshiriladi. Jarayon davomida xodim o'chirilsa yoki roli almashtirilsa yakuniy moliyaviy handler joriy ruxsatni tekshirmaydi. | `bot_harajat/handlers/harajat_flow.py:264`, `:328`; `bot_sotuv/handlers/sotuv_flow.py:790`; `bot_harid/handlers/harid_flow.py:684` | F14, F05 |
| A16 | P1 | Varaq o'qish xatosi yashiriladi va qisman/nol moliyaviy hisobot qaytariladi; UI uni real vaqtdagi balans deydi. `total_net_profit` faqat telefon sotuv marjasini yig'adi: 100 marja va 50 ijara bo'lsa ham 100 ko'rsatiladi. Ko'rsatkich ta'rifi to'g'rilanishi kerak. | `services/google_sheets.py:247`, `:805`, `:837`, `:872`; `bot_harajat/handlers/harajat_flow.py:251`, `:252` | F13 |
| A17 | P1/P2 | Foydalanuvchi matni `USER_ENTERED` bilan yoziladi: `=1+1` ism o'rniga formulaga aylanadi. HTML matnlari ham ekranlanmaydi: `<unexpected>` model nomi yoki `A&B` xabarning formatini buzishi mumkin. | `services/google_sheets.py:376`, `:433`, `:673`; `utils/formatters.py:173`; `services/telegram_poster.py:113` | F25, F18 |
| A18 | P2 | Sinxron Google chaqiruvi umumiy event loop ni to'xtatadi. Sun'iy 150 ms Sheets chaqiruvida 20 ms rejalashtirilgan boshqa ish 156 ms da bajarildi; haqiqiy internet kechikishi o'lchanmadi. | Barcha oqimlardagi bevosita `sheets_service.*` va `drive_service.upload_photo` chaqiruvlari | F19 |
| A19 | P2 | `forward_from_chat`/`forward_from` filtrlari zamonaviy `forward_origin` update larini tanimaydi. Hamkor/xodim ismi callback ichiga joylanadi; 70 belgili ism 76 baytli callback yaratadi. | Har uch handlerning forward filtrlari; `bot_harajat/keyboards.py:104`, `:114`; `bot_sotuv/keyboards.py:55`, `:84` | F16, F17 |
| A20 | P2 | `.env.example` dagi alohida bot tokenlari bo'sh bo'lsa, `os.getenv(key, BOT_TOKEN)` umumiy tokenni ishlatmaydi. Ikki bir xil va uchinchi boshqa token bo'lsa ikki polling bir botni chaqiradi. Har bir Dispatcher signal handler o'rnatadi; umumiy to'xtash boshqaruvi yo'q. `get_me` xatosi ayrim yo'llarda sessiya yopiladigan `try/finally` tashqarisida. | `config.py:12`; `run_all.py:28`, `:39`, `:59`, `:93`, `:104`; bot `main.py` fayllari | F20; qolganlari manba ko'rigi |
| A21 | P2 | FSM xotirada, qayta ishga tushganda tugallanmagan jarayon yo'qoladi. Ayrim rejimlarda `drop_pending_updates=True`; xodim bot ishlamagan paytda yuborgan yangilanishlar ataylab tashlanadi. | `run_all.py:25`, `:52`, `:64`; bot `main.py` fayllari | Mahalliy aiogram manbasi va rasmiy saqlash hujjati |
| A22 | P2 | Testlar va CI yo'q; `test_connection.py` biznes qoidalarini tekshirmaydi. Paketlar faqat `>=` bilan ko'rsatilgan. Compose butun loyiha papkasini containerga ulaydi; image ichidagi kod o'rniga host kodi ishlaydi. | `test_connection.py`, `requirements.txt`, `docker-compose.yml:7` | Fayllar inventari |
| A23 | P2 | Onboarding qo'llanmasi mavjud bo'lmagan `scripts/setup_new_client.py` ni ishga tushirishni so'raydi, oltita varaq deydi va avtomatik guruhga qo'shilish xabarini va'da qiladi. Bunday skript yoki `my_chat_member` handleri yo'q. | `docs/CLIENT_ONBOARDING_UZ.md:66`, `:71`, `:76` | Fayl mavjudligi va handler qidiruvi |

**Yakuniy tashqi o'zgarishdan kelib chiqqan qo'shimcha xavf:** `add_phone` endi IMEI oldiga apostrof qo'ymaydi, ammo butun qator hamon `USER_ENTERED` bilan yoziladi. Raqamga o'xshagan matnning raqamga aylanishi IMEI boshidagi nollarni yo'qotishi mumkin. Bu xavf yangi kod va API parse qoidasi asosida aniqlandi; haqiqiy Sheets dagi konversiya tekshirilmadi. Vazifa 5 da IMEI uchun `stringValue` va `000042` kabi boshlang'ich nolli ID ni qayta o'qish testi majburiy. [Google Sheets qiymat turlari](https://developers.google.com/workspace/sheets/api/reference/rest/v4/ValueInputOption).

### Hisob qoidasi aniqlashtirilishi kerak bo'lgan holatlar

1. **Kirim → Do'kondan.** Hozir `close_store_phone_debt` kirim yozib, `Harid qarz summasi ($)` ni kamaytiradi. Sotuvdagi `Dokondan` nasiya esa `Hamkor qarzi ($)` maydonida va Hamkorlar formulasida saqlanadi. Dastlabki TZZ ham xarid qarzini tilga olgani uchun bu audit uni avtomatik ravishda yangi ma'noga o'tkazmaydi. Foydalanuvchidan kirim xaridor nasiya to'lovi, kassalar o'rtasidagi o'tkazma yoki boshqa do'kon to'lovi ekanini aniqlash so'raldi; javob reja yozilgan paytda olinmagan.
2. **Sof foyda.** Sotuv marjasi, operatsion foyda va kassa qoldig'i alohida tushunchalar. Remont tannarxga kirgan bo'lsa foydadan yana ayirilmasin; KPI hisoblanganida sotuv marjasidan ayirilgan bo'lsa KPI to'lovida ikkinchi marta xarajat qilinmasin. Investor mablag'i kirimi foyda emas; rahbariyatga berilgan pulning ma'nosi alohida belgilanadi.
3. **Qarz/KPI dan ortiq to'lov.** Qoldiqdan ortiq summa xato, avans yoki qaytim ekanini aniqlash kerak. Hozirgi `max(0, qarz-summa)` ortiqcha pulning hisobini yashiradi. Qoida aniqlanguncha qoldiqdan ortiq to'lov bloklansin.
4. **Sotilgan telefonga remont.** Bu oqim hozir telefon holatini cheklamaydi. Sotuvdan keyingi kafolat xarajati bilan ombordagi telefon tannarxini oshirish alohida qoidalar bo'lishi kerak.

## Chunk 1: Tuzatishlarni bajarish tartibi

### Vazifa 1: Maxfiy qiymat va test poydevori — P0/P1

**Fayllar:**
- O'zgartirish: `.env.example:2`, `requirements.txt`.
- Yaratish: `requirements-dev.txt`, `tests/conftest.py`, `tests/test_config.py`, `tests/test_secrets.py`.

- [ ] **1-qadam:** `.env.example` tokenini `your_bot_token_here` o'rinbosariga almashtirish; maxfiy qiymatni reja, log, test va commit tavsifida takrorlamaslik.
- [ ] **2-qadam:** Agar bu haqiqiy token bo'lsa, bot egasi orqali BotFather'da yangisini olish va tegishli deploy konfiguratsiyasini yangilash tartibini tayyorlash. Faqat fayldan o'chirish Git tarixidagi oshkor bo'lishni bekor qilmaydi. Git tarixini o'zboshimchalik bilan qayta yozmaslik.
- [ ] **3-qadam:** `pytest`, `pytest-asyncio`, `ruff` uchun alohida ishlab chiqish bog'liqliklarini qo'shish. Testlarda real `.env` o'qilishi va barcha tashqi tarmoq chaqiruvlarini bloklaydigan fixture yaratish.
- [ ] **4-qadam:** Asl konfiguratsiya uchun bo'sh alohida token umumiy tokenni ishlatishini va namunada maxfiy qiymat yo'qligini tekshiradigan test yozish. Avval muammoni ko'rsatuvchi testni bajarish.
- [ ] **5-qadam:** Keyingi vazifada fallback tuzatilgach `venv/bin/python -m pytest tests/test_config.py tests/test_secrets.py -q` buyrug'ini bajarish; kutilgan natija — barcha tekshiruvlar o'tadi, tarmoq chaqiruvi `0`.

### Vazifa 2: Remont oqimini tiklash — P1

**Fayllar:**
- O'zgartirish: `bot_harajat/handlers/harajat_flow.py:24`, `:446`.
- Sinov: `tests/test_remont.py`.

- [ ] **1-qadam:** `Harid narxi ($)=100`, `Remont xarajati ($)=5`, yangi remont `10` bo'lgan handler testini yozish. Kutilgan tannarx `115`; hozir `NameError` chiqishi tasdiqlansin.
- [ ] **2-qadam:** Dastlab `from services.google_sheets import sheets_service, clean_num` bilan yo'q importni tiklash. Umumiy pul parseri tayyor bo'lgach uni ham shu oqimga ulash.
- [ ] **3-qadam:** `update_phone=False` bo'lsa remontga oid muvaffaqiyat xabari yuborilmasin; telefon holati sotilgan bo'lsa biznes qoidasi tasdiqlanguncha tannarx o'zgartirilmasin.
- [ ] **4-qadam:** `venv/bin/python -m pytest tests/test_remont.py -q` va `venv/bin/python -m ruff check bot_harajat/handlers/harajat_flow.py --select F821` ni bajarish. Kutilgan natija — `NameError` yo'q; mavjud bo'lmagan nom qolmagan.

### Vazifa 3: Saqlash natijasi va kesh yaxlitligi — P1

**Fayllar:**
- Yaratish: `services/errors.py`.
- O'zgartirish: `services/google_sheets.py:365`, `:405`, `:439`, `:514`, `:608`, `:713`, `:746`; har uch oqimning saqlash handlerlari.
- Sinov: `tests/test_write_failures.py`, `tests/test_phone_cache.py`.

- [ ] **1-qadam:** F03–F08 ni to'g'ri xatti-harakat kutiladigan doimiy testga aylantirish: ulanish yo'q yoki yozuv xatosi bo'lsa muvaffaqiyat qaytmasligi, kesh o'zgarmasligi, Telegram posti chiqmasligi.
- [ ] **2-qadam:** `StorageUnavailable`, `StorageWriteError`, `OutcomeUnknown` xatolarini ajratish. Sheets ulanmasa demo keshga yozishni to'xtatish. Vaqtincha `bool` interfeysi qolgan metodlar barcha bajarilmagan yozuvlarga `False` qaytarsin; yangi operatsiya xizmatida xatolar turlari saqlansin.
- [ ] **3-qadam:** `update_phone` da Sheets yozuvi tasdiqlangandan keyin keshni yangilash yoki bekor qilish. Yozuv xatosida kesh eski qiymatni yangi holat sifatida ko'rsatmasin. Barcha yangilashlar sarlavhalarning mavjudligini tekshirsin.
- [ ] **4-qadam:** `record_sale` telefon yozuvi muvaffaqiyatsiz bo'lsa darhol qaytsin. KPI yozuvi muvaffaqiyatsiz bo'lsa sotuvni to'liq muvaffaqiyatli deb qaytarmasin. Qarz va remont ichidagi barcha yozuvlar natijasi tekshirilsin.
- [ ] **5-qadam:** Handlerlar xatoda kiritilgan ma'lumotni saqlab qolsin, xabarni xato turiga mos bersin. Natijasi noaniq yoki qisman bajarilgan operatsiyaga avtomatik qayta yozish taklif qilinmasin: Vazifa 8 dagi identifikator bilan tekshirish talab qilinadi.
- [ ] **6-qadam:** Sotuv/xarid haqida Telegram xabari faqat moliyaviy yozuv muvaffaqiyatidan keyin yuborilsin. Kanal va karobka handlerlari ham `False` ni muvaffaqiyatga aylantirmasin.
- [ ] **7-qadam:** `venv/bin/python -m pytest tests/test_write_failures.py tests/test_phone_cache.py -q`; kutilgan natija — xato yozuvlar uchun soxta muvaffaqiyat `0`, xatoda kesh buzilishi `0`.

**Bosqich cheklovi:** Faqat natijani tekshirish bir nechta Sheets yozuvini tranzaksiyaga aylantirmaydi. Vazifa 8 tugamaguncha qisman yozuv xavfi bartaraf etildi deb aytilmasin.

### Vazifa 4: Pul kiritish va chegara qoidalari — P1

**Fayllar:**
- Yaratish: `utils/money.py`.
- O'zgartirish: har uch oqimdagi `clean_currency`, `services/google_sheets.py:37` va moliyaviy hisoblar.
- Sinov: `tests/test_money.py`, `tests/test_payment_limits.py`.

- [ ] **1-qadam:** `10`, `10$`, `$10`, `10.50`, `10,50`, `1 000,50` uchun kutilgan qiymatlar; `-10`, `1..2`, `abc`, `NaN`, `Infinity`, bir nechta ajratgich, ikki kasr xonasidan ortiq qiymat va 30 xonali raqam uchun `InvalidAmount` testi yozish.
- [ ] **2-qadam:** Quyidagi qat'iy parserni yagona joyda yaratish. `,` o'nlik ajratgich sifatida olinadi; minglik vergul qo'llab-quvvatlanmasligi UI da ko'rsatiladi. Natijani jim o'zgartirish yoki noto'g'ri qiymatni nolga aylantirish taqiqlanadi.

```python
import re
from decimal import Decimal, InvalidOperation


class InvalidAmount(ValueError):
    pass


def parse_money(text: str, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(text, str):
        raise InvalidAmount("Summa matn bo'lishi kerak")
    value = text.strip()
    if value.startswith("$"):
        value = value[1:].strip()
    elif value.endswith("$"):
        value = value[:-1].strip()
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:[ \u00a0][0-9]{3})+)(?:[.,][0-9]{1,2})?", value):
        raise InvalidAmount("Masalan: 10 yoki 10,50")
    normalized = value.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        amount = Decimal(normalized).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise InvalidAmount("Summa juda katta yoki noto'g'ri") from exc
    if amount < 0 or (amount == 0 and not allow_zero):
        raise InvalidAmount("Musbat summa kiriting")
    return amount
```

- [ ] **3-qadam:** Har uch handler bu parserdan foydalansin, `InvalidAmount` ushlansin; foydalanuvchi bir xil holatda qayta summa kirita olsin. `F.text` filtri bilan rasm/stiker pul yoki IMEI handleriga kirib `None.strip()` xatosi chiqarmasin.
- [ ] **4-qadam:** `0 ≤ boshlang'ich to'lov ≤ sotuv narxi`, `0 < qarz to'lovi ≤ qarz qoldig'i`, `0 < KPI to'lovi ≤ KPI qoldig'i` qoidalarini xizmat darajasida ham tekshirish. Hamkor avansi qoidasi tasdiqlanmaguncha qarzdan ortiq kirim rad etilsin.
- [ ] **5-qadam:** `Decimal` FSM ichida satr, operatsiya jurnalida sent sifatidagi butun son ko'rinishida saqlansin. Google Sheets raqamli kataklariga uzatish chegarasida format tanlanib, sentlar aniqligi qayta o'qib tekshirilsin; ikki kasr belgili raqamga jim nol qiymat berilmasin.
- [ ] **6-qadam:** `venv/bin/python -m pytest tests/test_money.py tests/test_payment_limits.py -q`; kutilgan natija — `10,50=10.50`, minus rad etiladi, 100 narxga 200 boshlang'ich to'lov rad etiladi, noto'g'ri input handlerni yiqitmaydi.

### Vazifa 5: Qator, ustun va matn turlari — P1

**Fayllar:**
- Yaratish: `services/sheet_schema.py`.
- O'zgartirish: `services/google_sheets.py:102`, `:223`, `:324`, `:488`, `:547`, `:569`, `:608`; `config.py:46`.
- Sinov: `tests/test_sheet_schema.py`, `tests/test_sheet_rows.py`, `tests/test_literal_text.py`.

- [ ] **1-qadam:** Xodim qatori oldida bo'sh qator, almashtirilgan ustunlar, takroriy sarlavha va yetishmayotgan ustun uchun test yozish. Bo'sh qator mavjud bo'lsa fiziki 3-qator fiziki 3-qator sifatida qaytsin.
- [ ] **2-qadam:** O'qilgan yozuvlarga `_row_index` berish; `enumerate(records, start=2)` ishlatayotgan KPI va hamkor metodlari ushbu fizik indeksni ishlatsin. Xodim tanlash ism orqali emas Telegram ID orqali bajarilsin.

```python
def records_with_rows(values: list[list[str]]) -> list[dict]:
    if not values:
        return []
    headers = [str(value).strip() for value in values[0]]
    named = [name for name in headers if name]
    if len(named) != len(set(named)):
        raise ValueError("Takroriy sarlavha")
    records = []
    for row_index, cells in enumerate(values[1:], start=2):
        if not any(cells):
            continue
        record = {name: cells[index] if index < len(cells) else ""
                  for index, name in enumerate(headers) if name}
        record["_row_index"] = row_index
        records.append(record)
    return records
```

- [ ] **3-qadam:** Xarid qatorini sarlavha → qiymat xaritasidan haqiqiy ustun tartibiga mos tuzish. Formulalarni tekshirilgan sarlavha xaritasidan hosil qilish. Yetishmayotgan yoki takrorlangan muhim ustunda yozuvni to'xtatish, ishlab chiqarish jadvalini avtomatik qayta tartiblashdan saqlanish.
- [ ] **4-qadam:** Foydalanuvchi matni uchun `stringValue`, summa uchun `numberValue`, faqat tizim yaratgan formula uchun `formulaValue` ishlatadigan katak quruvchi tayyorlash. Matn `=`, `+`, `-`, `@` bilan boshlanganida ham literal matn bo'lsin; IMEI va telefon raqami nol va `+` belgilarini saqlasin.
- [ ] **5-qadam:** `values.append` ishlatilsa javobdagi `updates.updatedRange` dan foydalanish. `AppendCells` qator/range qaytarmaydi: batch tugagach yozuvni barqaror `phone_id`/`operation_id` bo'yicha qayta topish va jismoniy indeksni shundan olish. Qator indeksini taxmin qilib keshga yozmaslik; Vazifa 8 da yangi qator ajratish yagona yozuvchi nazoratida bo'lsin.
- [ ] **6-qadam:** `venv/bin/python -m pytest tests/test_sheet_schema.py tests/test_sheet_rows.py tests/test_literal_text.py -q`; kutilgan natija — bo'sh qator/ustun ko'chirishda boshqa yozuv buzilmaydi, `=1+1` ism matn bo'lib qoladi.

### Vazifa 6: Telefonni aniq tanlash va e'lon holati — P1

**Fayllar:**
- O'zgartirish: `services/google_sheets.py:251`, `:383`; `bot_harid/handlers/harid_flow.py:540`, `:799`, `:884`, `:1028`; `bot_sotuv/handlers/sotuv_flow.py:246`, `:790`.
- Sinov: `tests/test_imei_lookup.py`, `tests/test_channel_state.py`.

- [ ] **1-qadam:** Ikki telefonning oxirgi olti raqami bir xil bo'lishi va mavjud bo'lmagan to'liq IMEI uchun test yozish.
- [ ] **2-qadam:** To'liq IMEI/seriya qidiruvi faqat to'liq moslikni qaytarsin. Aynan olti raqamli qisqa qidiruv barcha mos yozuvlar ro'yxatini qaytarsin; bir nechta topilsa foydalanuvchi model, to'liq IMEI va holat bo'yicha tanlasin. Sotilgan telefon qayta xarid qilinishi alohida xarid yozuvi sifatida saqlansin.
- [ ] **3-qadam:** Har bir xaridga ichki o'zgarmas `phone_id` berish; yangi sotuv, remont va e'lon amallari shu identifikatorga bog'lansin. Mavjud qatorlarga ID kiritish alohida nusxa jadvalda, oldin/keyin moslashtirish bilan tayyorlansin.
- [ ] **4-qadam:** E'lon narxi `Sotuv narxi ($)` dan ajratilsin: `Elon narxi ($)` yoki operatsiya metama'lumoti ishlatilsin. E'lon yuborish telefonning moliyaviy holatini o'zgartirmasin. Sotilgan telefon uchun e'lon rad etilsin.
- [ ] **5-qadam:** Post muvaffaqiyatsiz bo'lsa mavjud post ID va rasmni bo'sh qiymat bilan o'chirmaslik. Takroriy e'londa eski postni tahrirlash yoki yangi post yaratish qoidasi aniq bo'lsin; tarix operatsiya jurnalida saqlansin.
- [ ] **6-qadam:** `venv/bin/python -m pytest tests/test_imei_lookup.py tests/test_channel_state.py -q`; kutilgan natija — noto'g'ri to'liq IMEI boshqa telefonni topmaydi, e'lon sotilgan telefonni omborga qaytarmaydi.

### Vazifa 7: Ruxsat va Telegram input chegaralari — P1/P2

**Fayllar:**
- Yaratish: `bot_common/access.py`, `bot_common/callbacks.py`.
- O'zgartirish: har uch handler va `keyboards.py`; `utils/formatters.py`; `services/telegram_poster.py`; `services/google_drive.py:110`.
- Sinov: `tests/test_permissions.py`, `tests/test_telegram_inputs.py`, `tests/test_photo_permissions.py`.

- [ ] **1-qadam:** Sotuvchi, Hisobchi, Rahbariyat, Investor, Admin, faol bo'lmagan foydalanuvchi va oqim o'rtasida roli o'zgargan foydalanuvchi uchun xizmat/handler ruxsat testini yozish.
- [ ] **2-qadam:** Yozuvchi amallar va callbacklarda umumiy ruxsat tekshiruvini o'rnatish. Moliyaviy yakunlashdan oldin rol yangidan o'qilsin; ruxsat ma'lumotini olish xatosi yozishga ruxsat bo'lib ketmasin. Google jadvali ulanishi muvaffaqiyatsiz bo'lsa faqat sozlash diagnostikasi ishlasin.
- [ ] **3-qadam:** `html.escape()` bilan foydalanuvchi/model/hamkor matnlarini ekranlash. Ishonilgan Telegram HTML shabloni belgilarini saqlab, faqat shablonga qo'yiladigan qiymatlarni ekranlash; matn/caption uzunligi uchun tushunarli qisqartirish yoki matnli fallback belgilash.
- [ ] **4-qadam:** Callbackga ism joylashtirish o'rniga qisqa barqaror ID ishlatish; server ID ni ruxsat etilgan tanlovdan tekshirsin. UTF-8 bayt uzunligi 64 dan oshmasin; nom ichidagi `:` ham ma'lumotni kesmasin.
- [ ] **5-qadam:** Forward oqimlarini `forward_origin` ning channel/chat/user/hidden-user turlariga moslashtirish. Yashirilgan foydalanuvchi ID sini topilgandek ko'rsatmaslik.
- [ ] **6-qadam:** Drive yuklashda IMEI rasmi va ommaviy kanal rasmini ajratish. Hozir barcha rasmlarga `anyone/reader` berilmoqda; ichki IMEI rasmi uchun cheklangan ruxsat ishlatish, kanal rasmi yoki Telegram `file_id` uchun alohida siyosat tayyorlash. Mavjud rasmlarning ruxsatlarini audit bosqichida avtomatik o'zgartirmaslik.
- [ ] **7-qadam:** `venv/bin/python -m pytest tests/test_permissions.py tests/test_telegram_inputs.py tests/test_photo_permissions.py -q`; kutilgan natija — ruxsat olib tashlangach yozuv yo'q, uzun ism callbackni buzmaydi, ichki rasm ommaga ochilmaydi.

### Vazifa 8: Moliyaviy operatsiyalarni birgalikda saqlash — P1

**Fayllar:**
- Yaratish: `services/operations.py`, `services/operation_journal.py`, `services/notification_queue.py`.
- O'zgartirish: `services/google_sheets.py`, `run_all.py`, `config.py`, `.env.example`, `docker-compose.yml`, `.gitignore`, `.dockerignore`; uch botning moliyaviy yakunlash handlerlari.
- Sinov: `tests/test_operations.py`, `tests/test_idempotency.py`, `tests/test_journal_recovery.py`, `tests/test_notifications.py`.

**Majburiy shart:** Ushbu bosqich vaqtincha bitta boshqariladigan yozuvchi jarayonga mo'ljallangan. Sheets `batchUpdate` bir so'rovdagi o'zgarishlarni birgalikda qo'llaydi, lekin boshqa foydalanuvchi/jarayonning parallel tahririni tranzaksion izolyatsiya bilan to'xtatmaydi. [Google Sheets hujjati](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate).

- [ ] **1-qadam:** Ikki foydalanuvchi bir telefon sotuvini bir paytda tasdiqlashi, bir `operation_id` ikki marta kelishi, ikkinchi so'rovda xato va tarmoq natijasi noaniq qolishi uchun test yozish. Xarid, oddiy kirim/chiqim, qarz, KPI va remontning takroriy yuborilishiga ham shu test qo'llansin. Kutilgan natija — bitta sotuv, bitta KPI, qisman moliyaviy commit yo'q. So'rovdan oldin, Google commitidan keyin mahalliy tasdiqdan oldin va Telegram yuborishidan keyin jarayon uzilishi alohida test qilinsin.
- [ ] **2-qadam:** Yagona yozuvchi navbati yaratish; moliyaviy o'qish → tekshirish → yozish butun operatsiya davomida navbatda bajarilsin. Jarayon darajasidagi qo'shimcha ishga tushishni rad etuvchi qulf o'rnatish; alohida bot entrypointlari ham shu umumiy runtime orqali ishlasin. Bir nechta host/replica zarur bo'lsa bu yechim ishlatishdan oldin tranzaksion baza rejasi tanlansin.
- [ ] **3-qadam:** Konfiguratsiya va schema tekshiruvida `Amallar` varag'ini nusxa jadvalda tayyorlash. Sarlavhalar: `Operatsiya ID`, `Amal turi`, `Telegram foydalanuvchi ID`, `Telefon ID`, `Sana`, `Natija`, `Bildirish holati`, `Bildirish ma'lumoti`. UUID oqim yaratilganida berilib, retryda o'sha UUID saqlansin; vaqtning sekund qiymati yagona ID bo'lib ishlatilmasin. Google so'rovidan **oldin** SQLite jurnaliga `operation_id UNIQUE`, amal turi, bajaruvchi, ma'lumot hash'i, yuboriladigan batch va `Tayyorlandi` holati tranzaksiyada yozilsin. Yuborishdan oldin `Yuborilmoqda` holati bardoshli saqlansin; bir xil ID bilan boshqa ma'lumot kelishi rad etilsin. SQLite uchun `OPERATION_DB_PATH=/app/data/operations.sqlite`, `WAL` va `synchronous=FULL` sozlamalari, `/app/data` volume, yozish huquqi va backup tartibi shu vazifada tayyorlansin. DB, WAL va SHM fayllari Git/Docker build kontekstiga kirmasin; Volume/startup tiklanishi Vazifa 12 gacha kechiktirilmasin.
- [ ] **4-qadam:** Xarid uchun telefon va zarur bog'liq yozuvlar; oddiy kirim/chiqim uchun moliyaviy jurnal qatori; sotuv uchun telefon holati, KPI va zarur hamkor yozuvi; qarz/KPI/remont to'lovi uchun tegishli qoldiq va kirim/chiqim — bitta `spreadsheets.batchUpdate` ichida `UpdateCells`/`AppendCells` bilan tayyorlansin. Operatsiya jurnalining `Natija=Yakunlandi` qatori va zarur Telegram navbati shu batchga kirsin. Hisoblangan qoldiq yozishdan avval yangidan o'qilsin. Handler moliyaviy yozuvni operatsiya xizmatini chetlab o'tib bajarmasin.
- [ ] **5-qadam:** Holat o'tishi aniq bo'lsin: xarid `Sotuvda`, sotuv `Sotuvda → Sotildi`; allaqachon `Sotildi` bo'lgan yozuv uchun boshqa sotuv rad etilsin. Tannarx tasdiqlashda yana o'qilsin: foydalanuvchining eski FSM nusxasi sof foyda uchun asos bo'lmasin.
- [ ] **6-qadam:** Natijasi noaniq tarmoq xatosida batchni ko'r-ko'rona qaytarmaslik. SQLite holati `Noaniq` bo'lib saqlansin; shu operatsiya va unga zid moliyaviy yozuvlar karantinga olinib, `Operatsiya ID` Sheets dagi yangi o'qishda tekshirilsin: jurnal mavjud bo'lsa `Yakunlandi` natijasi tiklansin; mavjud bo'lmasa avtomatik ikkinchi commit qilinmasin, tekshirish va yarashtirish orqali hal qilinsin. Restartda `Yuborilmoqda` holatidagi barcha yozuvlar ham `Noaniq` deb tekshirilsin. Faqat hali yuborishga o'tmagan `Tayyorlandi` holatiga xavfsiz davom ettirish ruxsat etilsin.
- [ ] **7-qadam:** Telegram ishchisi batch muvaffaqiyatidan keyin yuborsin. Muvaffaqiyatsiz post moliyaviy yozuvni takrorlamasin. Yuborish va uning holatini saqlash orasidagi uzilishda Telegram xabari takrorlanishi mumkinligi aniq qayd etilsin; Telegram uchun mutlaq bir marta yetkazish va'da qilinmasin.
- [ ] **8-qadam:** Ushbu davrda moliyaviy ustunlarni boshqa bot/qo'lda tahrirlash va qatorlarni sort/delete qilishni qo'llab-quvvatlash chegarasini hujjatlashtirish. Bu talab biznesga mos bo'lmasa Sheets ni hisobot nusxasi sifatida qoldirib, asosiy tranzaksiyalar uchun PostgreSQL kabi baza alohida loyiha bilan rejalashtirilsin.
- [ ] **9-qadam:** `venv/bin/python -m pytest tests/test_operations.py tests/test_idempotency.py tests/test_journal_recovery.py tests/test_notifications.py -q`; kutilgan natija — takroriy ID moliyaviy ta'sirni ko'paytirmaydi, bir telefon uchun faqat bitta sotuv, noaniq natijada yoki commitdan keyingi restartda avtomatik qayta commit yo'q.

### Vazifa 9: Kassa, qarz va foyda hisobotlari — P1

**Fayllar:**
- Yaratish: `services/financial_reports.py`, `docs/HISOB_QOIDALARI_UZ.md`.
- O'zgartirish: `services/google_sheets.py:746`, `:775`; `bot_harajat/handlers/harajat_flow.py:228`, `:727`, `:759`.
- Sinov: `tests/test_financial_reports.py`, `tests/test_store_receipts.py`.

- [ ] **1-qadam:** Yuqoridagi to'rtta biznes qoidasini egasi/hisobchisi bilan aniqlashtirish va hujjatga yozish. Ayniqsa `Do'kondan` kirim ma'nosi aniqlanmaguncha tegishli qarz maydonini almashtirmaslik.
- [ ] **2-qadam:** 100 xarid, 20 remont, 150 sotuv, 10 hisoblangan KPI, 5 operatsion xarajat misolini testga aylantirish: sotuv marjasi `20`, operatsion foyda `15`; KPI ni to'lash foydani yana kamaytirmaydi. Kassa esa haqiqiy kirim/chiqim sanalari bo'yicha hisoblanadi.
- [ ] **3-qadam:** Kassa qoldig'i, sotuv marjasi, operatsion foyda, xaridor qarzi, xarid bo'yicha do'kon qarzi va KPI qoldig'ini alohida hisoblash. Kapital kirimi foydaga qo'shilmasin. Barcha hisoblar sent/Decimal bilan yuritilsin.
- [ ] **4-qadam:** Bir varaq o'qilmasa to'liq moliyaviy hisobotni chiqarishni to'xtatish. Xato katakni yoki `#REF!`/`#VALUE!` ni nolga aylantirmaslik; xato varaq/qator ko'rsatiladigan diagnostika va hisobot sanasini berish.
- [ ] **5-qadam:** `Do'kondan` xaridor qarz to'lovi bo'lsa sotuv qarzi/hamkor jurnaliga yozish; kassalar o'tkazmasi bo'lsa manba va qabul qiluvchi kassa ajratilishi hamda umumiy hisobotda ikki marta kirim sanalmasligi kerak. Tanlangan qoida uchun ikki tomondan oldin/keyin qoldiq testini yozish.
- [ ] **6-qadam:** Mavjud jadvallardagi qoldiqlarni avval o'qish orqali yarashtirish; aniqlanmagan tarixiy xatolarni jim qayta hisoblab yozmaslik. Qarz/KPI bo'yicha oldin/keyin farq va tuzatish operatsiyasi qayd etilsin.
- [ ] **7-qadam:** `venv/bin/python -m pytest tests/test_financial_reports.py tests/test_store_receipts.py -q`; kutilgan natija — kassa bilan foyda aralashmaydi, o'qish xatosi real balans sifatida ko'rinmaydi.

### Vazifa 10: Bot menyusi, token va ishga tushish — P1/P2

**Fayllar:**
- Yaratish: `bot_common/navigation.py`, `services/runtime.py`.
- O'zgartirish: `config.py:11`, `run_all.py`, har uch `main.py` va umumiy buyruq handlerlari; `main.py` test entrypointi.
- Sinov: `tests/test_navigation.py`, `tests/test_startup.py`.

- [ ] **1-qadam:** Bitta token, uchta token, qisman takrorlangan token, token yo'q va bo'sh alohida token uchun test yozish. Investor `/start` da `Balance`, Hisobchi kirim/chiqim/balans, Sotuvchi xarid/sotuv ko'rsin.
- [ ] **2-qadam:** Fallbackni `(os.getenv(key) or BOT_TOKEN).strip()` shaklida aniqlash; token formatini va kerakli boshqa qiymatlarni servis yaratishdan oldin tekshirish. Noto'g'ri konfiguratsiyada aniq xato bilan nol bo'lmagan chiqish kodi qaytsin.
- [ ] **3-qadam:** Bitta umumiy `/start`, bekor qilish, `/id`, `/status` va forward routeri yaratish. Funksional routerlar faqat o'z FSM oqimini yuritsin. Har bir token uchun faqat bitta polling task yaratilishi ta'minlansin; takrorlangan token shu token uchun zarur routerlarni birlashtirsin.
- [ ] **4-qadam:** Sheets/Drive xizmatlarini import paytida emas runtime ishga tushganda yaratish; konfiguratsiya tekshiruvi tugagach Google ulanishi sinovdan o'tsin. `ensure_worksheets` mavjud ishlab chiqarish schemasini jim o'zgartirmasin.
- [ ] **5-qadam:** Signalni runtime bir marta boshqarsin; alohida pollinglar `handle_signals=False` ishlatsin. Bir pollingning kritik xatosi yoki SIGTERM barcha tasklarni bekor qilib, barcha Bot sessiyalari va xizmatlarni `finally` ichida yopishi tekshirilsin.
- [ ] **6-qadam:** `drop_pending_updates=True` ni ishlab chiqarish uchun standart qilmaslik; eski update larni tashlash faqat alohida, aniq boshqariladigan ishga tushirish opsiyasi bo'lsin.
- [ ] **7-qadam:** `venv/bin/python -m pytest tests/test_navigation.py tests/test_startup.py -q`; kutilgan natija — Investor umumiy botda balansni ko'radi, bir tokenning ikki polling taski yo'q, xatoda ochiq sessiya qolmaydi.

### Vazifa 11: Event loop, FSM va diagnostika — P2

**Fayllar:**
- O'zgartirish: `services/runtime.py`, `services/google_sheets.py`, `services/google_drive.py`, `services/health_check.py`; handlerlar; `requirements.txt`, `config.py`, `.env.example`, `docker-compose.yml`.
- Sinov: `tests/test_async_runtime.py`, `tests/test_fsm_recovery.py`, `tests/test_health_check.py`.

- [ ] **1-qadam:** F19 ga o'xshash sekin Google chaqiruvi vaqtida boshqa foydalanuvchi update i bajarilishini test qilish.
- [ ] **2-qadam:** Google IO ni bitta maxsus worker thread orqali bajarish; navbat haddan oshsa chegara/timeout bilan boshqarish. `googleapiclient`/HTTP klientini bir nechta thread o'rtasida nazoratsiz ulashmaslik. Moliyaviy lock faqat yozuv atrofida emas, butun operatsiya atrofida bo'lsin.
- [ ] **3-qadam:** `redis` Python paketini tekshirilgan versiyada qo'shish; `FSM_STORAGE_URL` va `FSM_TTL_SECONDS=86400` orqali RedisStorage ni sozlash. Redis serverga AOF persistence va doimiy volume berish, internetga port ochmaslik. `DefaultKeyBuilder(with_bot_id=True)` va foydalanuvchi hodisalarini ketma-ket bajaruvchi Redis event isolation ishlatish. Bir foydalanuvchining ikkita botdagi holati aralashmasin. FSM tiklanishi moliyaviy operatsiya ID sini ham saqlasin; TTL tugashi bardoshli moliyaviy jurnalni o'chirmasin. Startupda tugallanmagan operatsiyalarni jurnaldan ko'rsatish/tiklash orqali yangi UUID bilan o'sha amalni takrorlashning oldi olinsin. Redis uzilsa yozuvchi oqimlar xotira storage ga jim o'tmasin.
- [ ] **4-qadam:** Diagnostikada klient obyekti borligini haqiqiy tayyorlik bilan tenglashtirmaslik; Sheets schema o'qilishi, Drive papka mavjudligi va zarur Telegram huquqlarini tegishli rejim uchun tekshirish. Tashqi so'rovga vaqt chegarasi, natijaga qisqa kesh, vaqtinchalik Bot sessiyasiga `finally` berish.
- [ ] **5-qadam:** Har bir `/start` da barcha Telegram va Google diagnostikasini takrorlamaslik. Oddiy foydalanuvchiga operatsion xabar, adminga maxfiy qiymatlarsiz batafsil holat berish.
- [ ] **6-qadam:** `venv/bin/python -m pytest tests/test_async_runtime.py tests/test_fsm_recovery.py tests/test_health_check.py -q`; kutilgan natija — sekin Google IO umumiy event loop ni bloklamaydi, restartdan keyin FSM va operatsiya ID si tiklanadi.

### Vazifa 12: Tekshiruv, deploy va hujjatlar — P2

**Fayllar:**
- Yaratish: `.github/workflows/checks.yml`, `requirements.lock`, `README.md`, `docs/DEPLOY_UZ.md`.
- O'zgartirish: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `docs/CLIENT_ONBOARDING_UZ.md`.
- Sinov: `tests/test_documented_commands.py` va butun regressiya to'plami.

- [ ] **1-qadam:** CI da Python 3.12, tarmoqsiz regressiya testlari va `ruff --select E9,F63,F7,F82` tekshiruvini qo'shish. Test uchun haqiqiy Telegram/Google secret talab qilinmasin.
- [ ] **2-qadam:** Sinovdan o'tgan barcha bog'liqliklarni tranzitiv versiyalar va hashlar bilan lock faylga mahkamlash. Docker faqat shu lockdan o'rnatsin; tekshirilmagan so'nggi versiyalarni deployda avtomatik tortmasin.
- [ ] **3-qadam:** Ishlab chiqarish Compose da `.:/app` mountini olib tashlash; image ichidagi kod ishlasin. Faqat zarur konfiguratsiya, credential, FSM va operatsiya jurnalining volume larini ulash. Ilova cheklangan OS foydalanuvchisi bilan ishlasin; OAuth token yangilanishi uchun zarur yozish huquqi saqlansin.
- [ ] **4-qadam:** `README.md` da real entrypoint va test/deploy buyruqlarini berish. Onboardingdagi yo'q skript va avtomatik xabar va'dasini olib tashlab, mavjud qo'lda sozlash yo'lini yozish. Hozirgi yettita varaq va Vazifa 8 dan keyingi `Amallar` bilan sakkizta varaqni yakuniy versiyaga mos ko'rsatish. Yangi onboarding avtomatizatsiyasini ushbu tuzatishlarga majburan qo'shmaslik.
- [ ] **5-qadam:** Quyidagi tekshiruvlarni bajarish; Docker Compose mavjud muhitda ishlatilsin. Kutilgan natija — barcha testlar o'tadi, kritik statik xato yo'q, konfiguratsiya to'g'ri, image yig'iladi.

```bash
venv/bin/python -m pytest tests -q
venv/bin/python -m ruff check . --exclude venv --select E9,F63,F7,F82
venv/bin/python -m pip check
docker compose config --quiet
docker compose build
git diff --check
```

- [ ] **6-qadam:** Alohida test botlari va nusxa Sheets bilan xarid → e'lon → sotuv → KPI to'lovi → hamkor to'lovi → balans oqimini tekshirish. Ikkita xodimning bir xil telefonni sotishga urinishini, Google/Telegram uzilishini va jarayon qayta boshlanishini tekshirish. Oldin/keyin qoldiqni yarashtirish.
- [ ] **7-qadam:** Ishlab chiqarish uchun ko'rib chiqiladigan deploy hujjatini tayyorlash: qaysi bot/token/jadval, schema qo'shimchalari, backup, restart, kutayotgan update lar, noaniq operatsiyalar, qaytarish tartibi. Ishlab chiqarishga qo'llash audit so'rovining tarkibiga kirmaydi.

## Tavsiya etilgan ketma-ketlik

| Bosqich | Vazifalar | Natija |
|---|---|---|
| 1. Zudlikdagi xatolar | 1–4 | Secret namunadan chiqariladi; remont ishlaydi; soxta saqlash xabari va noto'g'ri pul parse qilish to'xtaydi. |
| 2. Ma'lumotlar yaxlitligi | 5–8 | Qator/ustun/IMEI aniq; sotilgan telefon qayta ochilmaydi; ruxsatlar qayta tekshiriladi; takroriy moliyaviy amal nazorat qilinadi. |
| 3. Hisob va ish oqimi | 9–11 | Tasdiqlangan hisob qoidalari, to'liq hisobot, to'g'ri menyu/startup, bloklamaydigan IO va tiklanadigan FSM. Vazifa 10 ning fallback tuzatishi Vazifa 1 testini yakunlash uchun ertaroq olinishi mumkin. |
| 4. Yetkazish | 12 | Doimiy regressiya tekshiruvlari, qayta hosil qilinadigan image, real hujjatlar va nazoratli deploy paketi. |

Har bir vazifa alohida tekshiriladigan o'zgarish bo'lsin; bog'liq qismlar testdan o'tgach ko'rib chiqilsin. Commit faqat ijro topshirig'ida ruxsat berilganida yaratiladi va faqat tekshirilgan tegishli fayllarni oladi. @superpowers:systematic-debugging va @superpowers:verification-before-completion talablari bo'yicha har bir tuzatish dastlabki xato ssenariysi bilan tekshirilsin.

## Qabul mezonlari

- [ ] Tashqi yozuv xatosi foydalanuvchiga muvaffaqiyat deb ko'rsatilmaydi.
- [ ] Sotuv, qarz va KPI qisman yoki ikki marta moliyaviy ta'sir qilmaydi; noaniq natija alohida holatda tekshiriladi.
- [ ] IMEI to'liq mosligi va jismoniy qator/ustunlar to'g'ri ishlatiladi; e'lon moliyaviy holatni o'zgartirmaydi.
- [ ] Xato summa, ortiqcha to'lov, noto'g'ri turdagi xabar va ruxsati olib tashlangan foydalanuvchi yozuv kiritolmaydi.
- [ ] Kassa, foyda va qarzlar tasdiqlangan qoidalar bo'yicha yarashadi; qisman o'qilgan ma'lumot real balans sifatida berilmaydi.
- [ ] Bitta token va uchta token rejimi ishlaydi; polling, signal va sessiyalar boshqariladi.
- [ ] Restartdan keyin FSM va operatsiya ID si tiklanadi; Telegram xabari xatosi moliyaviy yozuvni qaytarmaydi.
- [ ] Test, kritik statik tekshiruv, Docker yig'ish va nusxa jadval bilan integratsiya natijalari qayd etilgan.

## Rasmiy texnik manbalar

- `callback_data` uchun 1–64 bayt chegarasi, `forward_origin` va HTML ekranlash qoidalari: [Telegram Bot API](https://core.telegram.org/bots/api#inlinekeyboardbutton).
- Bir batch ichidagi o'zgarishlarning birgalikda qo'llanishi va parallel tahrirlash cheklovi: [Google Sheets spreadsheets.batchUpdate](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate).
- Literal matn bilan foydalanuvchi kiritgan qiymatni parse qilish farqi: [Google Sheets ValueInputOption](https://developers.google.com/workspace/sheets/api/reference/rest/v4/ValueInputOption).
- MemoryStorage restartda saqlanmasligi va RedisStorage varianti: [aiogram FSM storages](https://docs.aiogram.dev/en/latest/dispatcher/finite_state_machine/storages.html).
