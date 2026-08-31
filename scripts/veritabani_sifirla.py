"""Veritabanını yedekleyip sıfırdan oluşturur.

Program güncellendiğinde eski veritabanı çoğu zaman olduğu gibi çalışmaya devam eder;
yeni kolonlar otomatik eklenir. Yalnızca "veritabanı uyumlu değil" hatası alındığında
ya da baştan temiz başlamak istendiğinde bu komut kullanılır.

Kullanım:
    python -m scripts.veritabani_sifirla
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from app.config import VERITABANI_URL
from app.db import semayi_olustur


def dosya_yolu() -> Path | None:
    if not VERITABANI_URL.startswith("sqlite:///"):
        return None
    return Path(VERITABANI_URL.removeprefix("sqlite:///"))


def main() -> None:
    hedef = dosya_yolu()
    if hedef is None:
        print("Bu komut yalnızca SQLite veritabanı için çalışır.")
        raise SystemExit(1)

    if hedef.exists():
        yedek = hedef.with_name(
            f"{hedef.stem}_yedek_{datetime.now():%Y%m%d_%H%M%S}{hedef.suffix}"
        )
        shutil.copy2(hedef, yedek)
        hedef.unlink()
        print(f"Mevcut veritabanı yedeklendi: {yedek}")
    else:
        print("Mevcut veritabanı bulunamadı, yenisi oluşturulacak.")

    semayi_olustur()
    print(f"Boş veritabanı hazır: {hedef}")
    print("Sırada: Master Data ve Siparişler ekranlarından Excel dosyalarını yükleyin.")


if __name__ == "__main__":
    main()
