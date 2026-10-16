# Nazoratli deploy, backup va tiklash

Bu hujjat ko'rib chiqish uchun deploy tartibidir. Lokal kod tuzatishlari ishlab chiqarish botlarini qayta boshlatgani, tokenni bekor qilgani yoki Google schemasini o'zgartirgani degani emas.

## Doira va old shartlar

Qaysi bot tokenlari, Telegram kanal/guruhlar, `SPREADSHEET_ID`, Drive papka, admin ID, eski image va data volume lar ishlatilishini yozib oling. Secret qiymatlarni log yoki PRga qo'ymang. Eski `.env.example` tokeni faol bo'lsa BotFather orqali bekor qilishni egasi bajarishi kerak.

Python 3.12 va Docker Compose v2 kerak. Alohida test botlari, nusxa Sheets va alohida data volume bilan to'liq oqimni tekshiring: xarid → e'lon → sotuv → KPI to'lovi → hamkor to'lovi → balans. Bir telefon uchun parallel tasdiq, Google/Telegram uzilishi va restart ham tekshirilsin. Faqat offline test o'tishi haqiqiy API huquqi/quota tasdig'i emas.

## Schema va konfiguratsiya

Runtime schema qo'shmaydi. Mavjud jadvalga `Telefon ID` (majburiy) va `Elon narxi ($)` kerak; `Telefon ID` siz yangi kod ishga tushmaydi. `Amallar` varag'i yaratilmaydi, jurnal lokal SQLite da. Avval jadval nusxasida:

```bash
venv/bin/python scripts/manage_data.py inspect
venv/bin/python scripts/manage_data.py prepare
venv/bin/python scripts/manage_data.py prepare --apply
venv/bin/python scripts/manage_data.py reconcile
```

`prepare` taklif qilingan batchni ko'rsatadi. Faqat tekshirilgan target, yozuvchi bot to'xtatilishi va backupdan keyin `--apply` ishlatiladi. Yangi bo'sh jadvalga `prepare --bootstrap` kerak. Moliyaviy tarixni avtomatik qayta yozish migratsiyaga kirmaydi. Sheets moliyaviy ustunlarini boshqa botlar/qo'lda tahrirlashni, qatorlarni sort/delete qilishni to'xtating; filtr ko'rinishidan foydalaning.

`.env` ni `.env.example` dan tayyorlang. Compose Google credentialni read-only, OAuth tokenni `/app/data/token.json` orqali yoziladigan volume dan oladi. Bot UID/GID `10001:10001` bilan ishlaydi; `credentials.json` shu UID o'qiy oladigan qilib sozlanishi kerak. Faylni ommaga o'qiladigan qilish o'rniga hostdagi guruh/ACL orqali aniq o'qish huquqi bering. OAuth ishlatilsa lokal `authorize_drive.py` ni yurgizishdan oldin `GOOGLE_OAUTH_TOKEN_FILE` ni yozish mumkin bo'lgan lokal manzilga, masalan `token.json` ga sozlang. U tokenni shu sozlangan manzilga atomar tarzda saqlaydi. Hosil qilingan tokenni persistent volume ga joylang; quyidagi host manzilini o'zingizdagi token manziliga moslang:

```bash
docker compose run --rm --no-deps -v ./token.json:/seed/token.json:ro bot python -c "import shutil; shutil.copyfile('/seed/token.json', '/app/data/token.json')"
```

Bu maxfiy token faylini ko'chiradi, uning qiymatini chiqarmaydi. Jarayon egasi refreshni yozish huquqiga ega bo'lishi kerak. Bir martalik authorize vositasi interaktiv Google ruxsatini talab qiladi; runtime avtomatik qayta authorize qilmaydi. Ichki IMEI rasmlari uchun papka va uning ota papkalarida `anyone` ruxsati bo'lmasin: meros ruxsati aniqlansa yuklash rad etiladi. Mavjud ruxsatlar avtomatik o'zgartirilmaydi. Drive ishlatilmasa `DRIVE_FOLDER_ID` bo'sh qoldiriladi. [Google Drive ruxsat hujjati](https://developers.google.com/workspace/drive/api/guides/manage-sharing).

## Yig'ish va ishga tushirish

```bash
venv/bin/python -m pytest tests -q
venv/bin/python -m ruff check .
venv/bin/python -m pip check
docker compose config --quiet
docker compose build
```

Compose kodni hostdan mount qilmaydi. Image dagi kod va hash bilan mahkamlangan production paketlar ishlaydi. Bot filesystemi read-only; faqat `/app/data`, `/app/media` va vaqtinchalik `/tmp` yoziladi. Redis AOF va alohida persistent volume ishlatadi, host/internet porti ochilmaydi.

Ishlab chiqarish restarti barcha botlar uchun bitta runtime ni to'xtatib, qayta ishga tushiradi. Bitta token uchun bitta polling bor. Navbatdagi Telegram update lar standartda saqlanadi (`DROP_PENDING_UPDATES=false`). `DROP_PENDING_UPDATES=true` faqat kutayotgan update larni ongli tashlash qarori uchun.

```bash
docker compose up -d
docker compose logs --tail=100 bot
```

Konfiguratsiya, Redis, Sheets schema yoki sozlangan Drive tayyor bo'lmasa runtime chiqish kodi `1` bilan to'xtaydi. `/status` texnik tayyorlik uchun; yangi moliyaviy sinovlar faqat oldindan kelishilgan test targetlarda bajariladi.

## Backup

1. Botni to'xtating: `docker compose stop bot`. Worker yuborilgan so'rov tugashini kutadi; 90 soniyadan keyingi majburiy uzilish natijani noaniq qoldirishi mumkin. Jurnal buni qayta ishga tushishda tekshiradi.
2. Google Sheets nusxasini, foydalanilayotgan image/tagni va secret konfiguratsiyasini xavfsiz saqlang.
3. `/app/data` dagi SQLite DB, WAL, SHM va OAuth tokenning bir xil vaqt nusxasini oling. SQLite ning `backup()` usuli yaxlit DB nusxasini beradi; nusxa kerak bo'lsa yozuvchi to'xtatilgan holda data volume ichida yaratish mumkin:

```bash
docker compose run --rm --no-deps bot python -c "import sqlite3; src=sqlite3.connect('/app/data/operations.sqlite'); dst=sqlite3.connect('/app/data/operations.backup.sqlite'); src.backup(dst); dst.close(); src.close()"
```

4. Redis ni to'xtatib, `redis_data` volume ning to'liq AOF directory nusxasini oling; Redis 7 AOF bir nechta fayl va manifestdan iborat bo'lishi mumkin. `bot_data`, `bot_media`, `redis_data` uchun tanlangan Compose project/volume nomlarini qayd eting. Secret backup ruxsatlari cheklangan bo'lsin. `docker compose down -v` ma'lumotlarni o'chiradi va bu tartibda ishlatilmaydi.

## Noaniq amallar va tiklash

Mahalliy `Yuborilmoqda` amallar restartda `Noaniq` bo'ladi. Yozilgan qiymatlar (eski jadvalda `Amallar` varag'i bo'lsa, undagi ayni UUID ham) qayta o'qilib tasdiqlansa yakunlangan natija tiklanadi. UUID yo'qligi o'z-o'zidan so'rov hech qachon qo'llanmaganini isbotlamaydi; bot avtomatik qayta commit qilmaydi. Noaniq yozuvga zid moliyaviy amal bloklangan bo'ladi.

```bash
venv/bin/python scripts/manage_data.py reconcile
```

Operator Sheets, original batch, local jurnal, tarix va tegishli qoldiqlarni tekshirib natijani aniq bilganidan keyingina qo'lda belgilaydi:

```bash
venv/bin/python scripts/manage_data.py resolve --operation-id UUID --actor-id ADMIN_TELEGRAM_ID --outcome not-applied --acknowledge-verified-outcome
venv/bin/python scripts/manage_data.py resolve --operation-id UUID --actor-id ADMIN_TELEGRAM_ID --outcome notification-sent --notification-index 0 --acknowledge-verified-outcome
venv/bin/python scripts/manage_data.py resolve --operation-id UUID --actor-id ADMIN_TELEGRAM_ID --outcome notification-not-sent --notification-index 0 --acknowledge-verified-outcome
```

Yozuvchi botni to'xtatib, konfiguratsiyani ayni persistent jurnalga yo'naltiring. `not-applied` faqat batch qo'llanmagani isbotlangan holatga tegishli. Telegram `sending/unknown` uchun chat tarixini va jurnalning tegishli bildirish indeksini tekshiring; `--notification-index` uchun to'g'ri indeksni tanlang. `--acknowledge-verified-outcome` operator shu tekshiruvni bajarganini aniq bildiradi. Xabar yuborish va holatini saqlash orasidagi uzilish takroriy yetkazishga sabab bo'lishi mumkin; moliyaviy yozuv bu sababli qayta yuborilmaydi. Yangi UUID bilan ayni amalni qayta kiritib karantinni chetlab o'tmang.

`--actor-id` uchun joriy faol `Admin` yoki `Hisobchi` ID kerak. Yetkazilgan `publish_channel` e'loni uchun yuqoridagi `notification-sent` buyrug'iga **`--channel-post-id TEKSHIRILGAN_POST_ID`** ham qo'shiladi. Bu post aynan shu telefon va kanalga tegishli ekanini chat tarixi orqali tekshiring. Post ID avval Sheets ga yozilib tasdiqlanadi, keyin bildirish yakunlanadi; shu vaqtda telefon sotilgan bo'lsa `SOTILDI` tahriri alohida navbatga olinadi. ID siz e'lonni yetkazilgan deb belgilab yangi nusxa yaratishga yo'l berilmaydi.

Bir telefonning oldingi e'loni `pending`, `sending` yoki `unknown` bo'lsa boshqa UUID bilan yangi e'lon navbatga olinmaydi. `notification-not-sent` faqat hech qanday xabar yetkazilmagani tekshirilgach ishlatiladi; u eski moliyaviy commitga tegmasdan, ayni bildirish uchun cheklangan urinishlar hisobini yangilaydi. `reconcile` chiqishidagi bildirish holati, telefon ID va xavfsiz `post_id` diagnostikasi shu tekshiruvga yordam beradi.

## Qaytarish

Yangi botni to'xtating; noaniq amallarni tekshiring. Google da yangi commitlar mavjud bo'lsa eski SQLite/FSM backupini ko'r-ko'rona tiklash deduplikatsiya ma'lumotini yo'qotishi mumkin. Avval yangi jurnal va Google ledgerni yarashtiring, yangi snapshotni saqlang. Oldingi imagega o'tish faqat yangi schema/jurnal bilan mosligi tekshirilgach amalga oshiriladi. Google ga yozilgan moliyaviy natijalar image rollback bilan bekor bo'lmaydi; ularni hisobchi tasdiqlagan alohida tuzatish amali hal qiladi.

Bir xil SPREADSHEET_ID uchun bitta runtime va bitta umumiy jurnal volume ishlasin. Lokal `flock` boshqa host yoki boshqa volume dagi yozuvchini to'xtatmaydi. Ko'p replica ishlatishdan oldin tranzaksion baza arxitekturasi kerak.

SQLite jurnaliga jadval ID si bog'lanadi. Test nusxasi, boshqa mijoz yoki boshqa `SPREADSHEET_ID` uchun **alohida data volume va jurnal** kerak; eski jurnalni boshqa jadvalga yo'naltirish startupda rad etiladi. Backupni tiklashda ayni jadval va unga tegishli jurnalni birga yarashtiring.
