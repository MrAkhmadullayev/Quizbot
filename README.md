# Quiz Bot — Telegram + Django

Telegram quiz bot (Telegramning native quiz botiga o'xshash) + Django admin panel.
Adminlar test fayllarini yuklaydi, foydalanuvchilar Telegram bot orqali yakka yoki
guruhda test ishlaydi. Baza — loyiha yonida lokal SQLite fayl (`data/db.sqlite3`).

## Imkoniyatlar

- **Ro'yxatdan o'tish** — telefon raqami (inline "Kontakt yuborish" tugmasi), `tg_id`,
  username, telefon bazaga saqlanadi.
- **Asosiy menyu** — Profil / Test ishlash / Tarix.
- **Profil** — F.I.Sh, ID, telefon.
- **Test ishlash** — Test → Qism → Boshlash → (botda yakka | guruhda).
  Katta testlar (700 savol) avtomatik qismlarga bo'linadi.
- **Tarix** — ishlangan testlar, ball va sana.
- **Guruh rejimi** — native quiz poll, har bir foydalanuvchi javobi yoziladi,
  oxirida reyting. **Faqat boshlovchi** keyingi savolga o'tkaza/yakunlay oladi.
- **Admin yuklash oqimi** — fayl yuklash → tizim parse qilib savol/variant/to'g'ri
  javobni chiqaradi → admin to'g'ri javobni belgilaydi → **Saqlash**.
- **Ma'lumot yaxlitligi** — takroriy javob, eski tugma, boshqa foydalanuvchi
  sessiyasi va yopilgan poll javoblari bazada bloklanadi.
- **Redis talab qilinmaydi** — ro'yxatdan o'tish stateless, test holati SQLite'da.

## Loyiha tuzilishi

```
quizbot/
├── manage.py
├── requirements.txt
├── .env.example
├── config/                 # Django loyihasi (settings, urls)
├── data/                   # SQLite baza shu yerda (db.sqlite3)
├── quiz/                   # Django app: baza, admin, parserlar
│   ├── models.py
│   ├── admin.py            # yuklash + ko'rib chiqish (preview) oqimi
│   ├── services.py         # parse qilingan ma'lumotni saqlash, qismlarga bo'lish
│   ├── parsers/
│   │   ├── text_parser.py  # ???=savol  ==variant  +=to'g'ri  (PDF/TXT)
│   │   └── excel_parser.py # Test|SubTest|Question|Option1..4|Correct
│   ├── templates/admin/quiz/{upload,preview,test_changelist}.html
│   └── management/commands/{runbot,import_file,make_sample_excel}.py
└── bot/                    # Telegram bot (aiogram 3)
    ├── main.py             # Dispatcher, polling
    ├── db.py               # Django ORM bilan async ishlash (sync_to_async)
    ├── keyboards.py / texts.py
    └── handlers/{registration,menu,testing,group}.py
```

> Eslatma: siz aytgan "upload" fayl = `quiz/parsers/` + `quiz/services.py`,
> "bot" fayl = `bot/` katalogi. Loyiha to'g'ri Django strukturasiga moslab tashkil etilgan.

## O'rnatish

```bash
cd quizbot
python3.14 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # va .env ni to'ldiring (BOT_TOKEN, BOT_USERNAME)

python manage.py migrate
python manage.py createsuperuser      # admin panelga kirish uchun
```

## Ishga tushirish

Ikki jarayon (ikki terminal):

```bash
# 1) Admin panel (web)
python manage.py runserver
#    => http://127.0.0.1:8000/admin/

# 2) Telegram bot
python manage.py runbot
```

## Test yuklash

### Variant 1 — Admin panel (tavsiya etiladi)
1. `http://127.0.0.1:8000/admin/` → **Testlar** → **📤 Test faylini yuklash**.
2. Fayl tanlang:
   - **Excel (.xlsx)** — Test/Qism nomi faylning o'zida.
   - **PDF / TXT** — Test va Qism nomini formada kiriting.
3. Tizim parse qiladi va savollarni ko'rsatadi → **to'g'ri javobni belgilang**
   (PDF'da `+` bo'lmasa, sariq "Tekshirish kerak" belgisi ko'rinadi).
4. **✅ Saqlash**.

To'g'ri javobi belgilanmagan yoki variantlari noto'g'ri savollar botda
ko'rsatilmaydi. Admin panelda har savol uchun 2–10 ta variant va aynan bitta
to'g'ri javob talab qilinadi.

### Variant 2 — Buyruq qatori
```bash
python manage.py import_file fayl.pdf --test "Web 2025" --subtest "1-qism"
python manage.py import_file fayl.xlsx
```

## Fayl formatlari

**PDF / TXT:**
```
??? Savol matni?
= variant 1
= variant 2
+ variant 3        <- + belgisi = to'g'ri javob
= variant 4
```

**Excel:** ustunlar — `Test, SubTest, Question, Option1, Option2, Option3, Option4, Correct`
(`Correct` = to'g'ri variant raqami 1–4). Namuna: `python manage.py make_sample_excel`.

## Muhim eslatma (siz yuborgan PDF haqida)

Yuborilgan PDF'da **250 savol, 1000 variant bor, lekin `+` (to'g'ri javob) belgisi yo'q** —
barchasi `=`. Shuning uchun import paytida har bir savol "Tekshirish kerak" bo'lib
belgilanadi va admin panelда to'g'ri javobni qo'lda tanlash kerak. Agar kelajakda
fayllarda `+` belgisi bo'lsa, to'g'ri javob avtomatik aniqlanadi.

## Sozlamalar (.env)

| O'zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | @BotFather'dan olingan token |
| `BOT_USERNAME` | Bot username (guruhga qo'shish deep-link uchun) |
| `QUESTIONS_PER_PART` | Bitta qismdagi maksimal savol (default 50) — katta testlar shunga bo'linadi |

## Keyingi qadamlar (production uchun)

- Botni guruhga **admin** qilib qo'shish kerak (poll yuborish uchun).
- SQLite WAL rejimi va 30 soniyalik busy timeout bilan sozlangan. Bitta bot
  processi va kichik/o'rta yuklama uchun yetarli.
- Bir nechta bot worker yoki katta parallel trafik kerak bo'lsa, MongoDB emas,
  PostgreSQL'ga o'tish tavsiya qilinadi; Django ORM va admin to'liq saqlanadi.
- Production `.env` da `DEBUG=False`, domenlar `ALLOWED_HOSTS` da va yangi
  `BOT_TOKEN` bo'lishi kerak.
- Guruhda savollar orasida avtomatik timer qo'shish mumkin.
