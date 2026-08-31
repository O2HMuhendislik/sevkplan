"""Demo veri üretir: ürün master datası + sipariş Excel'i, ardından plan üretir.

Kullanım:  python -m scripts.ornek_veri
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

from app.config import VERI_DIZIN
from app.db import oturum, semayi_olustur
from app.services import ice_aktarim, plan_servisi

URUNLER = [
    ("KMB-24-ERP", "Kombi 24 kW ErP", "Kombi", 30, None, "H"),
    ("KMB-28-ERP", "Kombi 28 kW ErP", "Kombi", 30, None, "H"),
    ("KMB-BACA", "Kombi Baca Seti", "Kombi", 120, "HDR-KMB-24", "E"),
    ("KMB-24-HDR", "Kombi 24 kW (Header)", "Kombi", 30, "HDR-KMB-24", "H"),
    ("RAD-600-1000", "Panel Radyatör 600x1000", "Radyatör", 24, None, "H"),
    ("TRM-80", "Termosifon 80 lt", "Termosifon", 12, None, "H"),
    ("KLM-12000", "Klima 12000 BTU", "Klima", 18, None, "H"),
    ("ISP-8KW", "Isı Pompası 8 kW", "Isı Pompası", 6, None, "H"),
]


def ornek_dosyalar(hedef_dizin: Path) -> tuple[Path, Path]:
    hedef_dizin.mkdir(parents=True, exist_ok=True)

    urun_kitabi = Workbook()
    sayfa = urun_kitabi.active
    sayfa.title = "Ürünler"
    sayfa.append(["Ürün Kodu", "Ürün Adı", "Ürün Grubu", "Palet İçi Adet", "Header Kod", "Aksesuar mı"])
    for satir in URUNLER:
        sayfa.append(list(satir))
    urun_dosyasi = hedef_dizin / "ornek_urunler.xlsx"
    urun_kitabi.save(urun_dosyasi)

    rastgele = random.Random(20260831)
    siparis_kitabi = Workbook()
    sayfa = siparis_kitabi.active
    sayfa.title = "Siparişler"
    sayfa.append([
        "Sipariş No", "Sipariş Satır No", "Teslimat No", "Müşteri Kodu", "Müşteri Adı",
        "Ürün Kodu", "Miktar", "Depo Kodu", "Sipariş Tarihi", "Termin Tarihi",
    ])
    bugun = date(2026, 8, 31)
    for sayac in range(1, 61):
        urun = rastgele.choice(URUNLER)
        palet = rastgele.randint(2, 8)
        depo = "64" if sayac % 6 else "71"  # her 6 satırdan biri tır kapsamında
        sayfa.append([
            f"SIP-2026-{sayac:05d}", "10", f"TSL-88{sayac:05d}",
            f"M-{rastgele.randint(1000, 1099)}", f"Bayi {rastgele.randint(1, 40)}",
            urun[0], palet * urun[3], depo,
            (bugun - timedelta(days=rastgele.randint(1, 12))).strftime("%d.%m.%Y"),
            (bugun + timedelta(days=rastgele.randint(2, 20))).strftime("%d.%m.%Y"),
        ])
    siparis_dosyasi = hedef_dizin / "ornek_siparisler.xlsx"
    siparis_kitabi.save(siparis_dosyasi)
    return urun_dosyasi, siparis_dosyasi


def main() -> None:
    semayi_olustur()
    urun_dosyasi, siparis_dosyasi = ornek_dosyalar(VERI_DIZIN / "ornek")
    with oturum() as db:
        urun_sonucu = ice_aktarim.urunleri_aktar(db, urun_dosyasi, urun_dosyasi.name)
        siparis_sonucu = ice_aktarim.siparisleri_aktar(db, siparis_dosyasi, siparis_dosyasi.name)
        plan_sonucu = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))
        print("Ürünler   :", urun_sonucu.ozet())
        print("Siparişler:", siparis_sonucu.ozet())
        print("Planlama  :", plan_sonucu.ozet())
        for plan in plan_sonucu.planlar:
            print(
                f"  {plan.sefer_no}  {plan.urun_kodlari:<24} "
                f"{plan.toplam_palet:>2} palet  %{plan.doluluk_yuzdesi}  "
                f"{plan.teslimat_sayisi} teslimat"
            )


if __name__ == "__main__":
    main()
