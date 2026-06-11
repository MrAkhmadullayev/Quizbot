"""Bazani XAVFSIZ zaxiralash (SQLite online backup API).

Oddiy fayl nusxalash (cp) ishlab turgan bazani buzishi mumkin. Bu buyruq
SQLite'ning rasmiy backup API'sidan foydalanadi — baza ochiq/ishlatilayotgan
bo'lsa ham izchil (consistent) nusxa oladi.

Misol:
    python manage.py backupdb
    python manage.py backupdb --dir /Users/mrakhmadullayev/quizbot-backups
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "SQLite bazadan xavfsiz, izchil zaxira nusxa oladi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default="",
            help="Zaxira papkasi (bo'sh bo'lsa: baza yonidagi backups/).",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=20,
            help="Saqlanadigan oxirgi nusxalar soni (eskilari o'chiriladi).",
        )

    def handle(self, *args, **options):
        db_path = settings.DATABASES["default"]["NAME"]
        if not os.path.exists(db_path):
            raise CommandError(f"Baza topilmadi: {db_path}")

        out_dir = Path(options["dir"]) if options["dir"] else Path(db_path).parent / "backups"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = out_dir / f"db_{ts}.sqlite3"

        # Online backup API — ishlab turgan baza uchun ham xavfsiz
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(str(dest))
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        # Butunlikni tekshirish
        check = sqlite3.connect(str(dest))
        try:
            ok = check.execute("PRAGMA integrity_check;").fetchone()[0]
        finally:
            check.close()

        if ok != "ok":
            dest.unlink(missing_ok=True)
            raise CommandError(f"Zaxira butunlik tekshiruvidan o'tmadi: {ok}")

        # Eskilarini tozalash
        backups = sorted(out_dir.glob("db_*.sqlite3"))
        keep = max(1, options["keep"])
        for old in backups[:-keep]:
            old.unlink(missing_ok=True)

        size_kb = dest.stat().st_size // 1024
        self.stdout.write(
            self.style.SUCCESS(f"✅ Zaxira tayyor: {dest} ({size_kb} KB, integrity: ok)")
        )
