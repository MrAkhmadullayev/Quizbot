#!/usr/bin/env bash
# =============================================================
#  SQLite bazani tiklash skripti (macOS uchun)
#  "database disk image is malformed" xatosidan keyin ishlatiladi.
#
#  ISHLATISHDAN OLDIN: bazaga tegadigan BARCHA jarayonlarni to'xtating!
#    - Telegram bot:        python manage.py runbot   -> Ctrl+C
#    - Django server:       python manage.py runserver -> Ctrl+C
#    - Ochiq admin/dashboard sahifalarini yoping
#
#  Ishga tushirish:
#    cd "~/Desktop/Quiz bot/quizbot"
#    bash recover_db.sh
# =============================================================
set -euo pipefail

DB="data/db.sqlite3"
TS=$(date +%Y%m%d_%H%M%S)
BKP="data/backup_$TS"

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "❌ sqlite3 topilmadi. macOS'da odatda mavjud bo'ladi."
  exit 1
fi

if [ ! -f "$DB" ]; then
  echo "❌ $DB topilmadi. Loyiha papkasida turibsizmi?"
  exit 1
fi

echo "1) Zaxira: $BKP"
mkdir -p "$BKP"
cp -v "$DB" "$BKP/" 2>/dev/null || true
[ -f "$DB-wal" ] && cp -v "$DB-wal" "$BKP/" || true
[ -f "$DB-shm" ] && cp -v "$DB-shm" "$BKP/" || true

echo "2) Butunlik tekshiruvi (oldin):"
sqlite3 "$DB" "PRAGMA integrity_check;" || true

echo "3) .recover orqali yangi bazaga tiklash..."
RECOVERED="data/db_recovered_$TS.sqlite3"
if sqlite3 "$DB" ".recover" | sqlite3 "$RECOVERED"; then
  echo "   Tiklandi -> $RECOVERED"
else
  echo "   ⚠️ .recover qisman ishladi (ba'zi qatorlar yo'qolgan bo'lishi mumkin)."
fi

echo "4) Tiklangan bazani tekshirish:"
if sqlite3 "$RECOVERED" "PRAGMA integrity_check;" | grep -q "^ok$"; then
  echo "   ✅ Tiklangan baza SOG'LOM."
  echo "5) Eski WAL/SHM o'chiriladi va baza almashtiriladi."
  rm -f "$DB-wal" "$DB-shm"
  mv "$DB" "$BKP/db.sqlite3.corrupt"
  mv "$RECOVERED" "$DB"
  echo "   ✅ Tayyor. Yangi sog'lom baza: $DB"
  echo "   Eski buzilgan nusxa: $BKP/db.sqlite3.corrupt"
else
  echo "   ❌ Tiklangan baza ham sog'lom emas. Quyidagini ko'ring:"
  echo "      - Zaxira: $BKP"
  echo "      - Agar tiklab bo'lmasa, yangi baza yarating (pastdagi izohga qarang)."
fi

echo ""
echo "Agar tiklab bo'lmasa, bo'sh yangi baza (ma'lumot yo'qoladi):"
echo "   rm -f data/db.sqlite3 data/db.sqlite3-wal data/db.sqlite3-shm"
echo "   python manage.py migrate"
echo "   python manage.py createsuperuser"
