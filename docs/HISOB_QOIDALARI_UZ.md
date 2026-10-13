# Hisob qoidalari va aniqlashtirilmagan holatlar

Pul hisoblari Decimal yoki butun sent bilan yuritiladi. Manfiy summa, noto'g'ri ajratgich, ortiqcha kasr va qarz/qoldiqdan ortiq to'lov rad etiladi. Moliyaviy hisobot uchun barcha zarur varaqlar o'qilishi kerak; o'qish xatosi yoki `#REF!` kabi katak xatosi nol sifatida ko'rsatilmaydi.

KPI va hamkor formulalari `ROUND(..., 2)` bilan sentgacha hisoblanadi. Eski Sheets raqamli katagidagi `0.30 − 0.10 = 0.19999999999999998` kabi juda kichik binary qoldiq o'qishda sentga moslashtiriladi; haqiqiy uch kasrli summa yoki foydalanuvchi matni yumshatilmaydi. Bu moslashtirish tarixiy kataklarni qayta yozmaydi.

## Kassa va foyda

Kassa qoldig'i haqiqiy naqd kirim va chiqimni aks ettiradi: xarid naqd qismi, sotuv naqd qismi/boshlang'ich to'lov, alohida qarz qaytishi va alohida to'lovlar. Kapital kirimi kassani oshiradi, savdo foydasini oshirmaydi. Rahbariyat pul olishi pul chiqimidir; uning dividend, avans yoki boshqa ma'nosi tasdiqlanmaguncha operatsion xarajat sifatida talqin qilinmaydi.

Sotuv marjasi = sotuv narxi − xarid narxi − telefon tannarxiga kiritilgan remont − hisoblangan KPI. Operatsion foyda = sotuv marjasi − tasdiqlangan operatsion xarajatlar (`Abed`, `Arenda`). KPI keyin to'langanda foyda yana kamaymaydi; to'lov faqat kassa va KPI qoldig'iga ta'sir qiladi. Remont tannarxda sanalgan bo'lsa sof foydadan ikkinchi marta ayrilmaydi.

Misol: 100 xarid + 20 remont, 150 sotuv, 10 hisoblangan KPI → sotuv marjasi 20. Alohida 5 operatsion xarajat → operatsion foyda 15. KPI ning 10 to'lovi marjani qaytadan kamaytirmaydi. Naqd to'lovlar amalga oshgan sanada kassa o'zgaradi.

## Qarz va KPI

- Xarid qarzi — do'konning telefon egasiga qarzi. Uni `Chiqim → Telefon qarzi` to'lovi kamaytiradi.
- Sotuv/hamkor qarzi — do'konga to'lanishi kerak bo'lgan summa. Uni tegishli hamkor kirimi kamaytiradi.
- KPI qoldig'i — hisoblangan KPI minus to'langan KPI. To'lov barqaror Telegram ID orqali xodimga bog'lanadi.
- Qarz/KPI to'lovi qoldiqdan oshmaydi. Bir UUID bilan takroriy tasdiq yangi moliyaviy ta'sir yaratmaydi.

`Kirim → Do'kondan` ma'nosi hali biznes tomonidan tasdiqlanmagan. IMEI bilan xarid qarzini kirim orqali kamaytirish bloklangan. Bu xaridor to'lovi bo'lsa sotuv qarziga bog'lanishi kerak; kassalar o'tkazmasi bo'lsa manba va qabul qiluvchi kassa alohida kerak. Tasdiq bo'lmaguncha tarixiy yozuvlar avtomatik qayta talqin qilinmaydi. Telefon bilan bog'lanmagan kirimning iqtisodiy ma'nosini ham hisobchi tekshirishi kerak.

## Telefon holati va e'lon

Xarid `Sotuvda`, sotuv `Sotuvda → Sotildi`. Sotuv tasdiqlanganda tannarx va holat yangidan o'qiladi. Sotilgan telefonni qayta sotish yoki e'lon bilan omborga qaytarish mumkin emas. Qayta xarid alohida Telefon ID bilan yangi yozuvdir. To'liq IMEI faqat aniq mos yozuvni topadi; oxirgi 6 raqam bir nechta yozuvga mos bo'lsa aniq tanlov kerak.

E'lon narxi `Elon narxi ($)` da, haqiqiy sotuv narxi `Sotuv narxi ($)` da saqlanadi. E'lon ma'lumoti saqlanib, yuborish navbatiga qo'yiladi; bu xabar hali kanalga chiqdi degani emas. `Kanal post ID` bo'lsa qayta e'lon ayni postni tahrirlaydi; yangi post faqat ID yo'q bo'lsa yaratiladi. Oldingi metadata operatsiya tarixida saqlanadi, mavjud post o'chirilmaydi. Tuzatishdan avval yaratilgan, ID si yo'qolgan eski postlarni bot ishonchli topolmaydi; kanal bo'yicha qo'lda audit kerak. E'lon moliyaviy holatni o'zgartirmaydi. Ichki IMEI fotosi Drive da ommaviy ruxsat olmaydi.

Sotilgan telefon uchun keyingi remontning kimga va qaysi davrga tegishliligi aniqlanmagan; bunday remont hozir bloklangan. Egasi/hisobchi kafolat xarajati yoki eski tannarx tuzatishini alohida tasdiqlashi kerak. Bir xaridda boshlang'ich qisman to'lov kiritish oqimi hozir mavjud emas: to'lov turi naqd yoki to'liq qarz.

## Tarixiy ma'lumot va nazorat

`inspect` va `reconcile` o'qish orqali schema, summa va qarzlarni tekshiradi. Aniqlanmagan tarixiy xatolar yoki formula qoldiqlari jim tuzatilmaydi. Har tuzatish uchun boshlang'ich qoldiq, sabab, hisobchi tasdig'i va yakuniy qoldiq kerak. Bot moliyaviy jurnalini qo'lda sort/delete qilish yoki boshqa yozuvchi bilan parallel tahrirlash qo'llab-quvvatlanmaydi.

Hamkorning eski raqamli qarz qoldig'i telefonlardagi sotuv qarzi minus qayd etilgan hamkor to'lovlari bilan mos bo'lishi kerak. Farq bo'lsa yangi hamkor sotuv/to'lovi bloklanib, read-only yarashtirish hisobotida ko'rsatiladi. Eski son jim formula bilan almashtirilmaydi; boshlang'ich qarz o'ylab topilmaydi. Hamkor to'lovlarini faollashtirishdan oldin tarixiy qoldiqni hisobchi tekshirsin.
