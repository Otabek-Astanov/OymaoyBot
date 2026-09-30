# 📱 OymaoyBot — Yangi Mijozni Tizimga Ulash Qo'llanmasi (Onboarding Guide)

Ushbu qo'llanma telefon do'koni egalariga (hatto Google Sheets yoki Drive nima ekanini bilmaydigan oddiy mijozlarga) bot tizimini noldan sozlab, ishga tushirib berish tartibini o'rgatadi.

---

## 📌 Asosiy Qoida: "Mijozni murakkab texnik ishlarga aralashtirmaslik"
Do'kon egasidan hech qachon Google Cloud, API, Service Account yoki JSON kalitlar so'ralmaydi. 
Barcha texnik ishlarni siz (dasturchi/integrator) bajarasiz. Mijozdan esa faqat **4 ta oddiy ma'lumot** olinadi.

---

## 1-QADAM: Mijozga Yuboriladigan Tayyor Xabar (Telegram Shabloni)

*(Quyidagi matnni to'g'ridan-to'g'ri nusxalab, mijozga Telegram orqali yuboring)*

```text
Assalomu alaykum, hurmatli do'kon egasi!

Do'koningizda savdo, haridlar va hisob-kitoblarni to'liq avtomatlashtiruvchi bot tizimini ishga tushirish uchun sizdan atigi 4 ta ma'lumot kerak bo'ladi:

1. 🏪 Do'koningiz nomi (Masalan: "SmartPhone Chorsu" yoki "Apple Market").
2. 📧 Bitta Gmail pochta manzili (Telefoningizda ochilgan va parolini biladigan @gmail.com manzilingiz. Barcha hisobot jadvallari va telefon rasmlari avtomatik shu pochtangizga biriktiriladi).
3. 💬 Telegramda 1 ta Kanal va 2 ta Guruh:
   • 📢 Vitrina Kanal (Sotuvdagi telefonlar rasmi va narxi avtomatik e'lon bo'lib chiqadi).
   • 📥 Haridlar guruhi (Yangi qabul qilingan telefonlar hisoboti tushadi).
   • 📤 Sotuvlar guruhi (Sotilgan telefonlar va xodimlar KPI si tushadi).
4. 🆔 Do'kon egasi va asosiy adminning Telegram raqami/ID si.

Qolgan barcha murakkab ishlarni (botlarni ulash, elektron jadvallarni sozlash va tizimni ishga tushirishni) o'zimiz to'liq qilib beramiz!
```

---

## 2-QADAM: Mijoz Uchun Oddiy Yo'riqnoma (Agar tushunmasa)

### 1. Gmail pochtani qayerdan topadi?
- Android telefonda: **Gmail** yoki **Google Play Market** ilovasiga kiriladi. O'ng tepa burchakdagi rasm/harf bosiladi. O'sha yerda yozilgan `misol@gmail.com` manzili olinadi.
- iPhone telefonda: **Sozlamalar (Settings)** -> **Pochta (Mail)** bo'limida ko'rish mumkin.

### 2. Telegramda Kanal va Guruhlar ochish:
1. **Vitrina Kanal:** Telegramda "Yangi kanal" ochiladi (Masalan: *“Ideal Mobile - Vitrina”*).
2. **Haridlar guruhi:** Telegramda "Yangi guruh" ochiladi (Masalan: *“Ideal Mobile - Haridlar”*).
3. **Sotuvlar guruhi:** Telegramda "Yangi guruh" ochiladi (Masalan: *“Ideal Mobile - Sotuvlar”*).

### 3. Botlarni admin qilish:
- Botlar guruh va kanalga oddiy a'zo kabi qo'shiladi va ularga **"Admin"** huquqi beriladi (Xabar yozish va xabarlarni tahrirlash huquqi bo'lsa yetarli).

### 4. Telegram ID raqamini aniqlash:
- Mijozga rasmiy xavfsiz `@userinfobot` havolasi beriladi.
- Botga kirib `/start` bosiladi va chiqqan `Id: 123456789` raqami olinadi.

---

## 3-QADAM: Dasturchi / Integrator (Siz) Qiladigan Ishlar

### 1. BotFather'dan botlarni olish
Mijoz uchun 3 ta bot ochiladi (yoki bitta bot):
- `@falonchi_harid_bot`
- `@falonchi_sotuv_bot`
- `@falonchi_harajat_bot`

### 2. Avtomatlashtirilgan o'rnatish skriptini yurgizish:
Loyihada quyidagi buyruqni bajarasiz:
```bash
python scripts/setup_new_client.py
```
Ushbu skript:
1. Do'kon nomini va mijozning Gmail pochtasini kiritishingizni so'raydi.
2. Google Drive'da avtomatik tarzda: `{Do'kon Nomi} - Rasmlar` nomli papka yaratadi.
3. Google Sheets'da avtomatik tarzda: `{Do'kon Nomi} - Baza` nomli yangi jadval yaratadi va 6 ta varaqni (`Xodimlar`, `Telefonlar`, `Chiqimlar`, `Kirimlar`, `Hamkorlar`, `Modellar`) barcha ustunlari bilan to'ldiradi.
4. Ushbu jadval va papkaga mijozning Gmail pochtasiga **Editor (Tahrirlovchi)** qilib avtomatik ruxsat ulashadi.
5. Yangi mijoz uchun tayyor `.env` faylini generatsiya qilib beradi!

### 3. Guruh va Kanal ID larini aniqlash:
- Botni yangi guruhga qo'shishingiz bilan bot avtomatik ravishda:
  > *"✅ Bot guruhga ulandi! Guruh ID raqami: `-100xxxxxxxxxx`"* deb chiqarib beradi.
- Yoki guruhda admin bo'lib turib `/id` buyrug'ini yuboring.

---

## 4-QADAM: Do'konda Kundalik Ish Tartibi (Xodimlar uchun)

1. **Yangi telefon olinganda (@...harid_bot):**
   - Xodim "📥 Yangi telefon qabul qilish" tugmasini bosadi;
   - IMEI, model, holat va xarid narxini kiritadi;
   - Telefon rasmini yuboradi;
   - Ma'lumot Sheets ga saqlanadi, harid guruhiga hisobot boradi va vitrina kanalga e'lon chiqadi.

2. **Telefon sotilganda (@...sotuv_bot):**
   - "📱 Telefon sotish" -> IMEI oxirgi 6 raqamini kiritish;
   - Narx, to'lov turi va sotuvchi kiritiladi;
   - Sotuv guruhiga tabrik boradi, kanaldagi e'lon esa "🔴 SOTILDI ❌" ga o'zgaradi.

3. **Xarajat va Balans nazorati (@...harajat_bot):**
   - Kunlik tushlik, arenda, oylik to'lovlar kiritiladi;
   - Do'kon egasi "📊 Balans va Hisobot" tugmasi orqali jonli kassa qoldig'i va sof foydani ko'rib turadi.
