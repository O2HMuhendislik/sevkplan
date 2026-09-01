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

# (stok kodu, ad, grup, palet içi adet, kamyon yükleme adeti, tır yükleme adeti)
URUNLER = [
    ("8000013403", "ademiX P 24/24 –AS/2 (H-TR)", "KOMBİ", 18, 234, 468),
    ("8000013404", "ademiX P 28/28 –AS/2 (H-TR)", "KOMBİ", 16, 208, 416),
    ("20268005", "Atık gaz borusu,DD 60/100", "AKSESUAR", 77, 1078, 2002),
    ("316181213", "22-600 180CMV010_B1A1G1 _13", "PANEL", 13, 195, 377),
    ("316101213", "22-600 100CMV010_B1A1G1 _13", "PANEL", 22, 330, 638),
    ("313151213", "25 DD S 22 300 1500 V0 A1 G1", "PANEL", 26, 390, 754),
    ("10016567", "T 7350 B Termosifon", "TERMOSİFON", 12, 144, 288),
    ("10047334", "aroTHERM pure VWL 65/7.2 AS", "ISI POMPASI", 1, 32, 64),
]


def ornek_dosyalar(hedef_dizin: Path) -> tuple[Path, Path]:
    hedef_dizin.mkdir(parents=True, exist_ok=True)

    urun_kitabi = Workbook()
    sayfa = urun_kitabi.active
    sayfa.title = "Ürünler"
    sayfa.append([
        "StokKodu", "StokAdi", "Ürün Grubu", "Palet içi adet",
        "Kamyon yükleme adeti", "Tır yükleme adeti",
    ])
    for satir in URUNLER:
        sayfa.append(list(satir))
    urun_dosyasi = hedef_dizin / "ornek_urunler.xlsx"
    urun_kitabi.save(urun_dosyasi)

    rastgele = random.Random(20260831)
    siparis_kitabi = Workbook()
    sayfa = siparis_kitabi.active
    sayfa.title = "Siparişler"
    sayfa.append([
        "SehirAdi", "Sipariş No", "Teslimat No", "Depo  Kodu", "StokKodu", "StokAdi",
        "Adet", "BayiAdi", "AliciFirma", "SevkAdresi", "Tarih", "Termin Tarihi",
    ])
    bugun = date(2026, 8, 31)
    for sayac in range(1, 81):
        urun = rastgele.choice(URUNLER)
        depo = "64" if sayac % 3 else "74"
        # Depo 64 palet, depo 74 anahtar ölçüsüyle planlandığı için miktarlar farklı
        # büyüklüklerde üretilir.
        # Tam palet katları üretilir; motorun palet birleştirmesi gözlenebilsin diye
        # bir kısmı kasten kırık palet bırakır.
        palet_adedi = rastgele.randint(1, 6)
        miktar = palet_adedi * urun[3]
        if rastgele.random() < 0.35 and urun[3] > 1:
            miktar -= rastgele.randint(1, urun[3] - 1)
        sayfa.append([
            "ESKİŞEHİR", 2010420000 + sayac, 2013620000 + sayac, depo,
            urun[0], urun[1], miktar,
            f"MOVUS DEPO-BAYİ {rastgele.randint(1, 40)}",
            "ORGANİZE SANAYİ BÖLGESİ 20. CAD. NO:36", "ODUNPAZARI",
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
        print("Ürünler   :", urun_sonucu.ozet())
        print("Siparişler:", siparis_sonucu.ozet())
        plan_sonucu = plan_servisi.tum_depolari_planla(db, plan_tarihi=date(2026, 8, 31))
        print("\nPlanlama :", plan_sonucu.ozet())
        for plan in plan_sonucu.planlar:
            israf = (
                "tam palet"
                if plan.kirik_palet_israfi == 0
                else f"{plan.kirik_palet_israfi} palet israf"
            )
            print(
                f"  {plan.sefer_no}  depo {plan.depo_kodu:<3} "
                f"{plan.planlama_anahtari:<12} {plan.birim_metni:>16}  "
                f"%{plan.doluluk_yuzdesi:>6}  {plan.toplam_palet:>3} palet  {israf}"
                + ("  MIX" if plan.mix_mi else "")
            )


if __name__ == "__main__":
    main()
