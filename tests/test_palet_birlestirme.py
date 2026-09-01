"""Tam palet hedefi: kırık paletlerin birleştirilmesi ve israfın ölçülmesi."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services import plan_servisi
from tests.conftest import satir_ekle, urun_ekle


def test_ayni_urunun_kirik_paletleri_tek_palete_iner(db):
    """Palet içi 16 olan üründen 13 + 3 adet, iki kırık palet değil tek dolu palettir."""
    urun_ekle(db, "PNL-600", palet_ici_adet=16, tir_yukleme_adeti=100, grup="PANEL")
    satir_ekle(db, "TSL-DOLU", "PNL-600", 64, siparis_no="S0")  # 4 tam palet
    satir_ekle(db, "TSL-13", "PNL-600", 13, siparis_no="S1")
    satir_ekle(db, "TSL-3", "PNL-600", 3, siparis_no="S2")
    satir_ekle(db, "TSL-DOLU2", "PNL-600", 16, siparis_no="S3")  # 1 tam palet

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    # 64 + 13 + 3 + 16 = 96 adet -> 6 tam palet, kırık palet yok.
    assert plan.toplam_palet == 6
    assert plan.kirik_palet_israfi == 0


def test_kirik_paleti_tamamlayan_teslimat_ayni_plana_konur(db):
    """13 adetlik siparişin yanına 3 adetlik sipariş eklenmeli."""
    urun_ekle(db, "PNL-600", palet_ici_adet=16, tir_yukleme_adeti=100, grup="PANEL")
    satir_ekle(db, "T-13", "PNL-600", 60, siparis_no="S1")   # 0,60 anahtar
    satir_ekle(db, "T-DOLU", "PNL-600", 55, siparis_no="S2")  # 0,55 anahtar
    satir_ekle(db, "T-3", "PNL-600", 30, siparis_no="S3")     # 0,30 anahtar

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    # 60 + 30 = 90 adet tek araca sığar; 55'lik teslimat sığmadığı için beklemede.
    assert {s.teslimat_no for s in plan.satirlar} == {"T-13", "T-3"}
    assert plan.toplam_palet == 6  # ceil(90/16)


def test_israf_plana_yazilir(db):
    urun_ekle(db, "PNL-600", palet_ici_adet=16, tir_yukleme_adeti=100, grup="PANEL")
    satir_ekle(db, "T1", "PNL-600", 95, siparis_no="S1")

    plan = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="64"
    ).planlar[0]
    # 95 adet -> 6 palet gözü, 96 olsaydı tam olurdu: 1/16 = 0,0625 palet israf.
    assert plan.toplam_palet == 6
    assert plan.kirik_palet_israfi == Decimal("0.063")


def test_palet_verisi_olmayan_urunde_israf_sifirdir(db):
    """Palet içi adedi tanımsız ürün planlamayı engellemez, israf ölçülmez."""
    urun_ekle(db, "KLM-12", palet_ici_adet=None, tir_yukleme_adeti=100, grup="KLİMA")
    for i in range(4):
        satir_ekle(db, f"T{i}", "KLM-12", 25, siparis_no=f"S{i}")

    plan = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="64"
    ).planlar[0]
    assert plan.toplam_palet == 0
    assert plan.kirik_palet_israfi == 0
