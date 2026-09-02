"""Müşteri master datasını veritabanına yükler.

Kullanım:
    python -m scripts.musteri_yukle [dosya.xlsx]

Dosya verilmezse `veri/ornek/ic_piyasa_masterdata.xlsx` kullanılır — bu dosya
`scripts/ic_piyasa_analiz.py` tarafından geçmiş sevk verilerinden üretilir.

Aynı işi Müşteriler ekranındaki "Excel'den yükle" düğmesi de yapar; bu betik ilk
kurulumda ekranı açmadan yüklemek içindir.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.db import OturumFabrikasi, semayi_olustur
from app.services import ice_aktarim

VARSAYILAN_DOSYA = Path("veri/ornek/ic_piyasa_masterdata.xlsx")


def main() -> int:
    dosya = Path(sys.argv[1]) if len(sys.argv) > 1 else VARSAYILAN_DOSYA
    if not dosya.exists():
        print(f"Dosya bulunamadı: {dosya}")
        print("Önce 'python -m scripts.ic_piyasa_analiz <sevk dosyaları>' çalıştırın.")
        return 1

    semayi_olustur()
    with OturumFabrikasi() as db:
        sonuc = ice_aktarim.musterileri_aktar(db, dosya, dosya.name, "kurulum")
        db.commit()
    print(sonuc.ozet())
    for uyari in sonuc.uyarilar[:10]:
        print(f"  uyarı — {uyari.anahtar}: {uyari.mesaj}")
    if len(sonuc.uyarilar) > 10:
        print(f"  ... ve {len(sonuc.uyarilar) - 10} uyarı daha")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
