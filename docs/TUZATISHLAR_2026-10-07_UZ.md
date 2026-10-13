# OymaoyBot tuzatishlari va tekshiruv natijasi

2026-10-07. Audit rejasidagi kod tuzatishlari lokal ishchi nusxada bajarildi. Boshlang'ich commit: `cc5109d`. O'zgarishlar commit yoki deploy qilinmagan. Haqiqiy Telegram xabari yuborilmadi, Google jadvali/rasm ruxsatlari va ishlab chiqarish konfiguratsiyasi o'zgartirilmadi.

## Audit muammolari bo'yicha natija

| Audit ID | Bajarilgan tuzatish | Asosiy dalil |
|---|---|---|
| A01 | Namunadagi token o'rinbosarga almashtirildi; secret fayllar build/Gitdan chiqarildi. Eski tokenni bekor qilish tartibi hujjatlashtirildi. | `tests/test_secrets.py`, `docs/DEPLOY_UZ.md` |
| A02–A06 | Soxta saqlash muvaffaqiyati olib tashlandi. Bog'liq moliyaviy yozuvlar va `Amallar` bir batchda bajariladi; kesh tasdiqlanmagan yozuvni aks ettirmaydi. | `tests/test_write_failures.py`, `tests/test_operations.py`, `tests/test_phone_cache.py` |
| A05 | UUID, ma'lumot hash'i, SQLite WAL/FULL jurnal, yagona IO worker va jarayon qulfi qo'shildi. Takroriy tasdiq ikkinchi moliyaviy ta'sir yaratmaydi. | `tests/test_idempotency.py`, `tests/test_journal_recovery.py`, `tests/test_async_runtime.py` |
| A07–A09 | Jismoniy qator va sarlavhaga mos ustun ishlatiladi; IMEI literal matn sifatida saqlanadi. To'liq IMEI aniq topiladi, noaniq qisqa qidiruv tanlov chiqaradi. | `tests/test_sheet_rows.py`, `tests/test_sheet_schema.py`, `tests/test_literal_text.py`, `tests/test_imei_lookup.py` |
| A10–A11 | Bitta qat'iy pul parseri, Decimal/sent hisobi va xizmat darajasidagi to'lov chegaralari kiritildi. | `tests/test_money.py`, `tests/test_payment_limits.py` |
| A12 | Remont handleri bitta atomic xizmatga o'tkazildi. Eski 5 va yangi 10 remont 100 xarid tannarxini 115 ga oshiradi. | `tests/test_handler_contracts.py`, `tests/test_review_regressions.py` |
| A13 | E'lon narxi sotuv narxidan ajratildi. Sotilgan telefon qayta ochilmaydi; mavjud kanal posti tahrirlanadi. | `tests/test_channel_state.py`, `tests/test_notifications.py` |
| A14–A15 | Token uchun yagona navigatsiya va rolga mos menyu bor. Moliyaviy update hamda commit oldida joriy ruxsat tekshiriladi. | `tests/test_navigation.py`, `tests/test_permissions.py`, `tests/test_write_failures.py` |
| A16 | Kassa, sotuv marjasi, operatsion foyda va qarzlar ajratildi. O'qish yoki formula xatosida qisman/nol balans chiqarilmaydi. | `tests/test_financial_reports.py`, `tests/test_store_receipts.py` |
| A17, A19 | Foydalanuvchi matni literal yoziladi va HTML ekranlanadi. Callbacklar qisqa ID ishlatadi; zamonaviy forward turlari qo'llanadi. Ichki IMEI fotosi ommaviy qilinmaydi. | `tests/test_literal_text.py`, `tests/test_telegram_inputs.py`, `tests/test_photo_permissions.py` |
| A18, A20–A21 | Google chaqiruvlari event loopdan chiqarildi. Takrorlangan tokenlar bitta pollingga yig'iladi; shutdown sessiyalarni yopadi. Redis FSM, bot ID bo'yicha isolation, AOF va persistent volume qo'shildi. | `tests/test_async_runtime.py`, `tests/test_startup.py`, `tests/test_fsm_recovery.py` |
| A22–A23 | Offline regressiya testlari, CI, 44 paketli hash lock, cheklangan container foydalanuvchisi va real onboarding/deploy buyruqlari qo'shildi. | `.github/workflows/checks.yml`, `tests/test_documented_commands.py`, `README.md` |

Rejadagi vaqtinchalik `clean_num` import tuzatishi o'rniga remont to'g'ridan-to'g'ri umumiy pul parseri va atomic xizmatga o'tkazildi. Ayrim rejalashtirilgan test fayllari umumiy handler va domen testlariga birlashtirildi; quyidagi to'liq test buyrug'i amaldagi to'plamni tekshiradi.

## Yakuniy ko'rikdagi qo'shimcha tuzatishlar

- Sheets raqamli formulasidagi `0.30 - 0.10` kabi binary qoldiq sent sifatida to'g'ri o'qiladi. Yangi KPI va hamkor formulalari `ROUND(..., 2)` ishlatadi; foydalanuvchining uch kasrli matni rad etiladi.
- KPI qoldig'i yoki hamkor qarzi tarixiy manbalarga mos bo'lmasa yangi bog'liq amal bloklanadi. Remont nomuvofiq tarixiy tannarxni jim qayta hisoblamaydi. Yozilgan raqamlar va moliyaviy formula natijalari qayta o'qiladi.
- E'lonni qayta tasdiqlashda birinchi ma'lumotlar FSMda saqlanadi. Sheets yozib, javob yo'qolsa ayni UUID bilan qayta urinish birinchi intentni yarashtiradi; ikkinchi batch yuborilmaydi.
- Telefonda tugallanmagan e'lon bo'lsa yangi UUID bilan boshqa e'lon navbatga olinmaydi. Telegram javobidan keyingi metadata xatosida post ID diagnostikada qoladi. Qo'lda tiklashda yetkazilgan e'lonning post ID sini yozish majburiy.
- Kanalga yuborish oldidan joriy rol qayta tekshiriladi. Sotuv e'lon bilan bir paytda amalga oshsa yangi post `SOTILDI` bilan tahrirlanadi. Sotuv botining diagnostikasi kanal tahrir huquqini ham tekshiradi.
- SQLite jurnali ayni Google jadvaliga bog'lanadi; boshqa jadval uchun shu jurnalni qayta ishlatish rad etiladi. Drive token manzili runtime konfiguratsiyasidan olinadi.
- Balansda xaridor va tashqi hamkor qarzi ajratildi. Tasniflanmagan tarixiy chiqim bo'lsa uning operatsion foydaga kiritilmagani ko'rsatiladi.

## Bajarilgan tekshiruvlar

| Tekshiruv | Natija |
|---|---|
| `venv/bin/python -m pytest tests -q` | **178 passed, 20 subtests passed** |
| Ruff: `E9,F63,F7,F82,F401,F811,F841` | Xatosiz |
| `venv/bin/python -m pip check` | `No broken requirements found` |
| O'rnatilgan production paketlar va `requirements.lock` | 44 ta paket tekshirildi, versiya farqi 0 |
| `/opt/homebrew/bin/docker-compose config --quiet` | Chiqish kodi 0 |
| `git diff --check` | Xatosiz |

Haqiqiy aiogram Dispatcher/router/FSM orqali xarid → naqd sotuv → KPI to'lovi → balans sinovi o'tdi. Domen va outbox sinovlari qarz, remont, hamkor to'lovi, e'lon, parallel sotuv tasdig'i, Google/Telegram uzilishi va jurnal tiklanishini qamrab oladi. Barcha tashqi xizmatlar sun'iy obyektlar bilan almashtirilgan; tarmoq chaqiruvlari testlarda bloklangan. FSM sinovi RedisStorage serializer va bot ID ajratilishini tekshiradi; haqiqiy Redis serveri/volume restarti bu lokal sinovga kirmaydi.

## Tashqi muhitda bajarilishi kerak bo'lgan ishlar

1. Eski namunaviy token ishlaydigan token bo'lsa, egasi uni BotFather orqali bekor qilib yangisini olishi kerak. Git tarixidagi avvalgi qiymat bu kod tuzatishi bilan yo'qolmagan; tarix qayta yozilmadi.
2. Docker daemon mavjud muhitda image yig'ish kerak. Bu kompyuterda daemon ishlamaydi; image build muvaffaqiyati tasdiqlanmagan. CIga build tekshiruvi qo'shilgan, CI hali yurgizilmadi.
3. Alohida test botlari, nusxa Sheets, cheklangan Drive papkasi va alohida data volume bilan real API oqimlari, Redis AOF restarti, ruxsatlar va qoldiqlar tekshirilsin. Haqiqiy jadval schemasiga `Telefon ID`, `Elon narxi ($)` va `Amallar` qo'shish bu ishda bajarilmadi.
4. `Kirim → Do'kondan` ning iqtisodiy ma'nosi, avans/qaytim va sotuvdan keyingi remont qoidalari hisobchi tomonidan tasdiqlanishi kerak. Hozir noaniq bog'liq amal yoki ortiqcha to'lov bloklangan; tarixiy balanslar qayta yozilmagan.

Sheets uchun bitta yozuvchi va bitta jurnal ishlashi shart. Boshqa hostdan yozish yoki qatorlarni qo'lda sort/delete qilish tranzaksion himoya doirasiga kirmaydi. Ko'p yozuvchi kerak bo'lsa asosiy tranzaksiyalarni alohida bazaga ko'chirish loyihasi kerak.

[Hisob qoidalari](HISOB_QOIDALARI_UZ.md) · [Deploy, backup va tiklash](DEPLOY_UZ.md) · [Ishga tushirish va testlar](../README.md)
