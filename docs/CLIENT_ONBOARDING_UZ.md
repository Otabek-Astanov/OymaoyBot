# OymaoyBot: mijozni tizimga ulash

Mijozdan do'kon nomi, jadval/papka egasi bo'ladigan Google akkaunt, Telegram kanal va ikkita guruh, egasi/admin Telegram ID lari olinadi. Google paroli yoki secretni xabarda yuborish talab qilinmaydi. Integrator texnik sozlashni bajaradi; Google fayllariga egalik va ulashish qo'lda tekshiriladi.

## Integrator bajaradigan ishlar

1. BotFather orqali bitta umumiy bot yoki uchta alohida bot yarating. Tokenlarni `.env` ga kiriting. Loyihaning eski namunasi haqiqiy token ko'rinishidagi qiymatni o'z ichiga olgan: u ishlatilgan bo'lsa BotFather orqali revoke/regenerate qiling. Git tarixidagi eski tokenni olib tashlash uning bekor bo'lishini almashtirmaydi.
2. Google Cloud loyihasida Sheets/Drive API larini yoqing. Service Account yarating; credentialni lokal `credentials.json` yoki xavfsiz secret manziliga saqlang.
3. Google Sheets jadvalini va cheklangan ruxsatli Drive papkasini qo'lda yarating. Jadvalga Service Account elektron pochtasiga Editor huquqi bering. Papkaga kerakli ruxsatni bering. Ichki IMEI rasmiga ota papkadan `anyone` ruxsati meros bo'lsa yuklash rad etiladi; mavjud ruxsatlar avtomatik o'zgartirilmaydi. Drive yuklash uchun Shared Drive yoki yetarli quota/haqiqiy OAuth egasi kerak; papka mavjudligi upload quota borligini isbotlamaydi.
4. Yangi jadval uchun `prepare --bootstrap` ko'rib chiqish va `prepare --bootstrap --apply` qo'llashdan foydalaning. Mavjud jadval uchun avval nusxa yarating, `inspect`, keyin `prepare` ni ko'ring; tasdiqlangan nusxaga `prepare --apply` qo'llang.
5. Yettita varaqni tekshiring: `Xodimlar`, `Telefonlar`, `Chiqimlar`, `Kirimlar`, `Hamkorlar`, `Modellar`, `Shablonlar` (`Telefonlar` da `Telefon ID` ustuni bo'lsin). `Amallar` varag'i kerak emas: amallar jurnali serverdagi lokal SQLite da. Xodimning Telegram ID, roli va `Faol` holatini, modellar va kerakli shablonlarni to'ldiring.
6. Botni kanal/guruhlarga qo'shing. Xarid botiga kanal postlarini yozish/tahrirlash huquqi, tegishli guruhlar uchun xabar yozish huquqi bering. Kanal ID uchun xabarni botga forward qiling; mavjud `/id` buyrug'i chat ID ni ko'rsatadi. Yashirilgan forward jo'natuvchi ID si aniqlanmaydi. Bot yangi guruhga kirganda avtomatik ID xabari yuborishi va'da qilinmaydi.
7. Redis persistence, SQLite data volume va credential ruxsatlarini [deploy qo'llanmasi](DEPLOY_UZ.md) bo'yicha tayyorlang. `SPREADSHEET_ID`, `DRIVE_FOLDER_ID` va Telegram destination ID lari aynan shu mijozga tegishli bo'lsin.

```bash
venv/bin/python scripts/manage_data.py inspect
venv/bin/python scripts/manage_data.py prepare --bootstrap
venv/bin/python scripts/manage_data.py prepare --bootstrap --apply
venv/bin/python run_all.py
```

Bu buyruqlar konfiguratsiyadagi jadvalni ishlatadi. `--apply` tashqi jadvalga yozadi; avval jadval ID va ko'rib chiqilgan batchni tekshiring. Yangi mijoz uchun alohida konfiguratsiya va alohida doimiy volume ishlating.

## Xodim uchun kundalik oqim

Xaridda model, to'liq IMEI, xarid narxi va to'lov turi kiritiladi. Tasdiq faqat Google yozuvi tasdiqlangach muvaffaqiyat ko'rsatadi; bildirish muvaffaqiyatsizligi xaridni qayta kiritishga sabab bo'lmaydi. Kanalga e'lon berish alohida bosqichdir.

Sotuvda IMEI yoki oxirgi 6 raqam tanlanadi; bir nechta mos yozuv bo'lsa aniq Telefon ID tanlanadi. Narx, to'lov turi, xaridor/hamkor va KPI tekshiriladi. Sotilgan telefon uchun ikkinchi sotuv rad etiladi.

Hisobchi kirim, chiqim va qarz/KPI to'lovlarini yuritadi. Investor balansni o'qiydi. Egasi Admin `/status` orqali maxfiy qiymatlarsiz texnik tayyorlikni tekshiradi. Rol oqim davomida olib tashlansa yangi yozuv bloklanadi.

`Do'kondan` kirim va sotuvdan keyingi remont ma'nosi ishga tushirishdan oldin hisobchi bilan aniqlashtirilsin. Hozir aniqlanmagan telefon bilan bog'liq yozuvlar bloklangan; [hisob qoidalari](HISOB_QOIDALARI_UZ.md) ni o'qing.
