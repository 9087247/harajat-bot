# Boshliq xabarlari boti

Telegram'da boshliqdan kelgan xabarni shu botga yo'naltirasiz, u esa xabarni bazaga saqlaydi va oylik Word hujjatga qo'shadi.

| Xabar turi | Hujjatga nima yoziladi |
|---|---|
| Matn | Aynan o'zi, AI'ga yuborilmaydi |
| Ovozli xabar, audio, video | Gemini yozib bergan matn (asl fayl `media/` da qoladi) |
| Rasm | Rasmning o'zi, undagi matn va qisqa tavsif |
| PDF | Fayldagi matn |
| Word, Excel va boshqa fayllar | Faqat fayl nomi va manzili, ichi o'qilmaydi |

Hujjatlar `hujjatlar/Boshliq-xabarlari-YYYY-MM.docx` nomi bilan saqlanadi. Xabarlar asl yuborilgan vaqti bo'yicha tartiblanadi.

## Birinchi sozlash

`.env` faylini oching va quyidagilarni to'ldiring:

1. `TELEGRAM_BOT_TOKEN`: Telegram'da @BotFather → `/newbot`.
2. `GEMINI_API_KEY`: https://aistudio.google.com/apikey
3. `ishga_tushirish.bat` ni ishga tushiring va botga `/start` yozing. Bot Telegram ID raqamingizni aytadi.
4. Uni `OWNER_TELEGRAM_ID` ga yozing va botni qayta ishga tushiring. Shundan keyin bot faqat sizning xabarlaringizni qabul qiladi.

## Buyruqlar

- `/bugun`, `/hafta`, `/oy`, `/oy 2026-10`: hujjatni Telegram'ga yuboradi
- `/holat`: tayyor, navbatdagi va o'qilmagan xabarlar soni
- `/qayta`: o'qilmagan xabarlarni qayta urinadi

## Railway'ga joylash

1. Railway'da **New Project → Deploy from GitHub repo** ni tanlang va shu repositoryni ulang.
2. Loyihaga **Database → PostgreSQL** qo'shing.
3. Bot xizmatining **Variables** bo'limiga `.env.example` dagi qiymatlarni yozing. `DATABASE_URL` uchun `${{Postgres.DATABASE_URL}}` deb yozing.
4. Bot xizmatiga **Volume** qo'shing va uni `/data` ga ulang. Volume bo'lmasa, ovoz va rasm fayllari har deploy'da o'chadi.
5. Kompyuterdagi botni to'xtating. Bitta token bilan ikkita bot bir vaqtda ishlay olmaydi.

## Bilish kerak

- Bot faqat kompyuter yoqiq va `ishga_tushirish.bat` oynasi ochiq paytda ishlaydi. O'chiq paytda yuborilgan xabarlarni Telegram taxminan 24 soat saqlaydi va bot yonganda oladi.
- Gemini ishlamay qolsa, bot 5 martagacha qayta urinadi. Xabar bazada saqlangan bo'ladi.
- Telegram botga 20 MB dan katta faylni yuklab olishga ruxsat bermaydi. Bunday xabar hujjatda alohida belgilanadi.
- Oylik hujjat Word'da ochiq bo'lsa, yangilanmaydi. Yopilgach, keyingi xabarda yoki `/oy` buyrug'ida yangilanadi.
- PostgreSQL 5433-portda ishlaydi, chunki 5432-portni kompyuterdagi `nakladnoy-bot` ishlatadi.
- `.env` faylida maxfiy kalitlar bor, uni hech kimga bermang. Zaxira nusxa uchun `media/` papkasi va `boshliq_bot` bazasini saqlang.
