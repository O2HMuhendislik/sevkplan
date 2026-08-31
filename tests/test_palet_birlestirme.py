"""Paletin plan bazında hesaplanması — depodaki elleçlemeyi azaltan kural."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.domain.kapasite import RING_PALET
from app.domain.planlama import PaletBirimi, Teslimat, planla
from app.services import plan_servisi
from tests.conftest import satir_ekle, urun_ekle


def teslimat(no, sku, miktar, palet_ici, gun=1):
    from app.domain.planlama import palet_hesapla

    return Teslimat(
        teslimat_no=no,
        depo_kodu="64",
        planlama_anahtari=sku,
        urun_kodu=sku,
        urun_adi=sku,
        miktar=Decimal(miktar),
        birim=palet_hesapla(Decimal(miktar), palet_ici),
        oncelik_tarihi=date(2026, 12, gun),
        sku_miktarlari={sku: Decimal(miktar)},
    )


def test_ayni_urunun_kirik_paletleri_birlestirilir():
    """Palet içi 16 olan üründen 13 + 3 adet, iki kırık palet değil tek dolu palettir."""
    hesaplayici = PaletBirimi({"PNL": 16})
    ts = [teslimat("T1", "PNL", 13, 16), teslimat("T2", "PNL", 3, 16)]
    assert hesaplayici(ts) == 1
    assert hesaplayici([ts[0]]) + hesaplayici([ts[1]]) == 2


def test_kirik_paleti_tamamlayan_teslimat_ayni_plana_konur(db):
    """13 adetlik siparişin yanına 3 adetlik sipariş eklenmeli."""
    urun_ekle(db, "PNL-600", palet_ici_adet=16, grup="PANEL")
    # 19 dolu palet (304 adet) + 13 adet + 3 adet: son ikisi tek paleti paylaşır.
    satir_ekle(db, "TSL-DOLU", "PNL-600", 304, siparis_no="S0")
    satir_ekle(db, "TSL-13", "PNL-600", 13, siparis_no="S1")
    satir_ekle(db, "TSL-3", "PNL-600", 3, siparis_no="S2")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.toplam_birim == 20  # 19 + (13+3)/16 = 20, 21 değil
    assert {s.teslimat_no for s in plan.satirlar} == {"TSL-DOLU", "TSL-13", "TSL-3"}
    assert sonuc.bekleyenler == []


def test_plan_paleti_teslimat_paletlerinin_toplamindan_kucuk_olabilir(db):
    urun_ekle(db, "PNL-600", palet_ici_adet=16, grup="PANEL")
    for i in range(20):
        satir_ekle(db, f"TSL-{i:02d}", "PNL-600", 16 * 15 // 20 + 4, siparis_no=f"S{i}")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    for plan in sonuc.planlar:
        teslimat_paletleri = sum(
            (Decimal(s.miktar) / 16).to_integral_value(rounding="ROUND_CEILING")
            for s in plan.satirlar
        )
        assert plan.toplam_palet <= teslimat_paletleri
        assert plan.toplam_palet <= 20


def test_anahtar_olcusu_toplanabilir_kalir(db):
    """Anahtar değer ölçüsünde birleştirme yoktur; değerler doğrudan toplanır."""
    urun_ekle(db, "KMB-24", palet_ici_adet=18, tir_yukleme_adeti=468, grup="KOMBİ")
    satir_ekle(db, "TSL-1", "KMB-24", 234, depo_kodu="74", siparis_no="S1")
    satir_ekle(db, "TSL-2", "KMB-24", 234, depo_kodu="74", siparis_no="S2")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="74")
    assert round(float(sonuc.planlar[0].toplam_anahtar), 4) == 1.0


def test_ust_limit_birlestirmeden_sonra_kontrol_edilir():
    """Birleşince sığan teslimat, ayrı ayrı sığmıyor görünse de plana alınır."""
    hesaplayici = PaletBirimi({"PNL": 10})
    # 10 x 19 adet: ayrı ayrı 20 palet, birleşince 19 palet.
    ts = [teslimat(f"T{i}", "PNL", 19, 10, gun=i + 1) for i in range(10)]
    sonuc = planla(ts, RING_PALET, hesaplayici=hesaplayici)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].toplam_birim == 19
    assert len(sonuc.planlar[0].teslimatlar) == 10
