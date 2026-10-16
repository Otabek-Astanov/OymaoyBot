# OymaoyBot

Telefon do'koni uchun xarid, sotuv, kirim/chiqim, qarz va KPI botlari. Python 3.12, aiogram 3, Google Sheets, Google Drive va Redis ishlatiladi. Bir token barcha funksiyalarni yoki turli tokenlar tegishli funksiyalarni bajaradi; qisman takrorlangan tokenlar ham bitta polling jarayoniga birlashtiriladi.

Moliyaviy yozuvlar bitta boshqariladigan yozuvchi orqali bajariladi. Har amal UUID oladi; SQLite jurnaliga saqlanadi va Google Sheets `batchUpdate` orqali tegishli qoldiqlar bilan birga yoziladi. Telegram bildirishlari tasdiqlangan yozuvdan keyin yuboriladi. Natijasi noaniq Google so'rovi avtomatik qayta yuborilmaydi.

## Mahalliy tayyorlash

```bash
python3.12 -m venv venv
venv/bin/python -m pip install --require-hashes -r requirements.lock
venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

`.env` ichida tokenlar, admin ID, `SPREADSHEET_ID`, credential manzili va `FSM_STORAGE_URL` ni kiriting. Mahalliy ishga tushishda fayl manzillarini `/app/...` o'rniga mavjud mahalliy manzilga almashtiring. Masalan, `OPERATION_DB_PATH=data/operations.sqlite`, `GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json`, `GOOGLE_OAUTH_TOKEN_FILE=token.json`, `MEDIA_DIR=media`. Redis majburiy: ulanmasa bot ishga tushmaydi, xotiradagi FSM ga yashirin o'tish yo'q. Faqat lokal sinov uchun `FSM_STORAGE_URL=memory://` yozish mumkin; bunda boshlangan oqimlar restartda yo'qoladi. Token va kalitlarni Gitga kiritmang.

Google servislar import vaqtida tarmoqqa chiqmaydi. Runtime avval konfiguratsiyani tekshiradi, keyin Redis va Google schemasining haqiqiy tayyorligini tekshiradi. Mavjud schema ishga tushishda avtomatik o'zgartirilmaydi.

## Google jadvalini tayyorlash

Yettita varaq kerak: `Xodimlar`, `Telefonlar`, `Chiqimlar`, `Kirimlar`, `Hamkorlar`, `Modellar`, `Shablonlar`. Amallar jurnali lokal SQLite da (`OPERATION_DB_PATH`) turadi; `prepare` `Amallar` varag'ini yaratmaydi, eski jadvalda u bo'lsa yozuvlar unga ham qo'shiladi. Ustunlar `config.DEFAULT_HEADERS` da berilgan. `Telefon ID` majburiy: qayta xarid qilingan IMEI har safar alohida ID oladi. Ustun yo'q bo'lsa bot ishga tushmaydi; mavjud jadvalga uni `prepare` qo'shadi va bo'sh ID larni to'ldiradi. E'lon uchun `Elon narxi ($)` ixtiyoriy ustun. IMEI matn sifatida saqlanadi.

Avval ishlab chiqarish jadvalining nusxasida tekshiring:

```bash
venv/bin/python scripts/manage_data.py inspect
venv/bin/python scripts/manage_data.py prepare
venv/bin/python scripts/manage_data.py prepare --apply
venv/bin/python scripts/manage_data.py reconcile
```

Yangi, bo'sh jadval uchun oldin `prepare --bootstrap` orqali ko'rib chiqing; tasdiqlangan nusxaga `prepare --bootstrap --apply` qo'llanadi. `--apply` Google jadvaliga yozadi. Oddiy runtime buni bajarmaydi. Migratsiya moliyaviy tarixni qayta yozmaydi.

## Ishga tushirish

```bash
venv/bin/python run_all.py
```

`main.py` ham shu umumiy runtime ga yo'naltirilgan. Faqat alohida funksiya kerak bo'lsa `venv/bin/python -m bot_harid.main`, `-m bot_sotuv.main` yoki `-m bot_harajat.main` ishlatiladi. Bular ham ayni jurnal va yagona yozuvchi qulfidan foydalanadi; bir bazaga bir vaqtda alohida entrypointlarni yurgizmang. Konfiguratsiya yoki startup tekshiruvi xato bo'lsa chiqish kodi `1`.

`BOT_TOKEN` umumiy token; bo'sh `HARID_BOT_TOKEN`, `SOTUV_BOT_TOKEN`, `HARAJAT_BOT_TOKEN` shu tokendan foydalanadi. `run_all.py` uchun yoqilgan funksiyalarning tokeni yoki umumiy token kerak. Bo'sh token funksiyani o'chirmaydi; funksiyani o'chirish uchun `ENABLED_FEATURES` ishlatiladi (masalan, `ENABLED_FEATURES=harid,sotuv` harajat botini, ya'ni Kirim/Chiqim'ni ishga tushirmaydi). Bo'sh qiymat uchala funksiyani yoqadi. `DROP_PENDING_UPDATES=false` standart: navbatdagi update lar o'chirilmaydi.

## Tekshiruv

```bash
venv/bin/python -m pytest tests -q
venv/bin/python -m ruff check .
venv/bin/python -m pip check
git diff --check
```

Testlar `.env`, haqiqiy credential, Telegram yoki Google yozuvlarini ishlatmaydi; tarmoq chaqiruvlari bloklangan. CI Python 3.12 da shu tekshiruvlarni va Docker image yig'ishni bajaradi. Dependency lockni yangilash: `venv/bin/python -m piptools compile --generate-hashes --no-emit-index-url --no-emit-trusted-host --output-file requirements.lock requirements.txt`; yangilangan versiyalarni qayta tekshiring.

## Hisob va joylashtirish

[Hisob qoidalari](docs/HISOB_QOIDALARI_UZ.md), [deploy, backup va tiklash](docs/DEPLOY_UZ.md), [mijozni ulash](docs/CLIENT_ONBOARDING_UZ.md).

Sheets birgalikdagi batchni qo'llaydi, lekin qo'lda parallel tahrir yoki boshqa host yozuvini izolyatsiya qilmaydi. Shu sababli moliyaviy ustunlarni boshqa yozuvchidan tahrirlamang, qatorlarni sort/delete qilmang; filtr ko'rinishidan foydalaning. Ko'p host/replica kerak bo'lsa asosiy tranzaksion bazani alohida loyihalash kerak.

Telegram yetkazish mutlaq bir martalik emas: xabar yuborilib, yetkazish holati saqlanmasdan jarayon uzilsa holat noaniq bo'ladi. Tekshirishsiz qayta yuborish yoki moliyaviy amalni qayta kiritish bu noaniqlikni hal qilmaydi.

E'lon ma'lumoti avval saqlanadi, keyin navbatdan kanalga yuboriladi. Qayta e'lon mavjud `Kanal post ID` ni tahrirlaydi; ID yo'q bo'lsa yangi post yaratadi. Eski, kuzatilmaydigan kanal postlari uchun qo'lda audit kerak.
