"""Anahtar değer ölçüsüyle planlama (depo 74) ve planlama anahtarı seviyeleri."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.config import depo_profili
from app.domain.kapasite import RING_ANAHTAR, RING_PALET, Olcu
from app.services import plan_servisi
from tests.conftest import satir_ekle, urun_ekle


def test_depo_profilleri_dogru_olcuyu_secer():
    assert depo_profili("64").olcu is Olcu.PALET
    assert depo_profili("74").olcu is Olcu.ANAHTAR
    assert depo_profili("99") is None


def test_anahtar_degeri_yukleme_adetinden_hesaplanir(db):
    # Tır yükleme adeti 468 olan üründen 468 adet = 1.000 anahtar = %100 dolu.
    urun_ekle(db, "KMB-24", palet_ici_adet=18, tir_yukleme_adeti=468)
    satir_ekle(db, "TSL-1", "KMB-24", 468, depo_kodu="74")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="74")
    plan = sonuc.planlar[0]
    assert plan.olcu == "ANAHTAR"
    assert round(float(plan.toplam_anahtar), 4) == 1.0
    assert float(plan.doluluk_yuzdesi) == 100.0
    assert plan.toplam_palet == 26  # 468 / 18, bilgi amaçlı yine hesaplanır


def test_anahtar_altinda_kalan_teslimatlar_beklemede_kalir(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=18, tir_yukleme_adeti=468)
    satir_ekle(db, "TSL-1", "KMB-24", 200, depo_kodu="74")  # 0.427 anahtar

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="74")
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 1


def test_ayni_gruptaki_farkli_skular_tek_planda_birlesir(db):
    """2025 planlarının davranışı: farklı ölçülerdeki paneller aynı plandadır."""
    urun_ekle(db, "PNL-600", palet_ici_adet=10, grup="PANEL")
    urun_ekle(db, "PNL-400", palet_ici_adet=10, grup="PANEL")
    satir_ekle(db, "TSL-1", "PNL-600", 100, siparis_no="S1")
    satir_ekle(db, "TSL-2", "PNL-400", 100, siparis_no="S2")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.planlama_anahtari == "PANEL"
    assert plan.urun_kodlari == "PNL-400, PNL-600"


def test_farkli_gruplar_ayni_plana_girmez(db):
    urun_ekle(db, "PNL-600", palet_ici_adet=10, grup="PANEL")
    urun_ekle(db, "KMB-24", palet_ici_adet=10, grup="KOMBİ")
    satir_ekle(db, "P1", "PNL-600", 100, siparis_no="S1")
    satir_ekle(db, "P2", "PNL-600", 100, siparis_no="S2")
    satir_ekle(db, "K1", "KMB-24", 100, siparis_no="S3")
    satir_ekle(db, "K2", "KMB-24", 100, siparis_no="S4")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert {p.planlama_anahtari for p in sonuc.planlar} == {"PANEL", "KOMBİ"}


def test_aksesuar_ana_urunun_planina_yazilir(db):
    """Aksesuar tek başına plan açmaz; teslimattaki ana ürünün grubuna yazılır."""
    urun_ekle(db, "KMB-24", palet_ici_adet=18, grup="KOMBİ")
    urun_ekle(db, "BACA-60", palet_ici_adet=77, grup="AKSESUAR")
    satir_ekle(db, "TSL-1", "KMB-24", 180, siparis_no="S1")   # 10 palet
    satir_ekle(db, "TSL-1", "BACA-60", 77, siparis_no="S2")   # 1 palet
    satir_ekle(db, "TSL-2", "KMB-24", 162, siparis_no="S3")   # 9 palet

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.planlama_anahtari == "KOMBİ"
    assert plan.toplam_birim == 20
    assert "BACA-60" in plan.urun_kodlari


def test_sku_seviyesinde_ayni_grup_bile_ayrisir(db, monkeypatch):
    monkeypatch.setattr("app.config.PLANLAMA_SEVIYESI", "SKU")
    urun_ekle(db, "PNL-600", palet_ici_adet=10, grup="PANEL")
    urun_ekle(db, "PNL-400", palet_ici_adet=10, grup="PANEL")
    satir_ekle(db, "TSL-1", "PNL-600", 100, siparis_no="S1")
    satir_ekle(db, "TSL-2", "PNL-400", 100, siparis_no="S2")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    # Tek başına 10 palet, 18 palet alt limitini dolduramaz; ikisi de beklemede kalır.
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 2


def test_agirlik_ve_adet_toplamlari_plana_yazilir(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=10, agirlik=29)
    for i in range(4):
        satir_ekle(db, f"TSL-{i}", "KMB-24", 50, siparis_no=f"S{i}")
    plan = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="64"
    ).planlar[0]
    assert plan.toplam_adet == 200
    assert plan.toplam_agirlik == Decimal("5800.000")
