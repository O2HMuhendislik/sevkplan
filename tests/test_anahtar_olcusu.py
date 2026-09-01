"""Servis seviyesinde planlama kuralları: anahtar değer, iki fazlı gruplama, depolar.

Ölçek: `urun_ekle` varsayılanıyla bir tıra 100 adet, bir palete 10 adet sığar.
Yani 100 adet = 1,000 anahtar = tam araç = 10 palet.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.config import DEPO_PROFILLERI, depo_profili
from app.domain.kapasite import Olcu
from app.services import plan_servisi
from tests.conftest import satir_ekle, urun_ekle


def test_butun_depolar_anahtar_olcusuyle_planlanir():
    for depo in ("64", "64-V", "64-P", "74", "74-V", "3", "03", "34", "36", "44"):
        profil = depo_profili(depo)
        assert profil is not None, depo
        assert profil.olcu is Olcu.ANAHTAR, depo
    assert depo_profili("99") is None


def test_anahtar_degeri_yukleme_adetinden_hesaplanir(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=18, tir_yukleme_adeti=468)
    satir_ekle(db, "TSL-1", "KMB-24", 468, depo_kodu="74")

    plan = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="74"
    ).planlar[0]
    assert plan.olcu == "ANAHTAR"
    assert round(float(plan.toplam_anahtar), 4) == 1.0
    assert float(plan.doluluk_yuzdesi) == 100.0
    assert plan.toplam_palet == 26  # 468 / 18, bilgi amaçlı


def test_alt_limitin_altinda_kalan_beklemede_kalir(db):
    urun_ekle(db, "KMB-24")
    satir_ekle(db, "TSL-1", "KMB-24", 40, depo_kodu="74")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="74")
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 1


def test_faz1_once_saf_plan_kurar(db):
    """Tek ürün kodu aracı doldurabiliyorsa karışık plana gerek kalmaz."""
    urun_ekle(db, "PNL-600", grup="PANEL")
    urun_ekle(db, "PNL-400", grup="PANEL")
    satir_ekle(db, "A1", "PNL-600", 50, siparis_no="S1")
    satir_ekle(db, "A2", "PNL-600", 50, siparis_no="S2")
    satir_ekle(db, "B1", "PNL-400", 30, siparis_no="S3")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.urun_kodlari == "PNL-600"
    assert plan.mix_mi is False
    assert [b.teslimat.teslimat_no for b in sonuc.bekleyenler] == ["B1"]


def test_faz2_dolmayan_artiklari_grup_icinde_birlestirir(db):
    urun_ekle(db, "PNL-600", grup="PANEL")
    urun_ekle(db, "PNL-400", grup="PANEL")
    satir_ekle(db, "A1", "PNL-600", 50, siparis_no="S1")
    satir_ekle(db, "B1", "PNL-400", 50, siparis_no="S2")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.urun_kodlari == "PNL-400, PNL-600"
    assert plan.planlama_anahtari == "PANEL"
    assert plan.mix_mi is True


def test_grup_ici_mix_kapatilinca_artiklar_beklemede_kalir(db):
    urun_ekle(db, "PNL-600", grup="PANEL")
    urun_ekle(db, "PNL-400", grup="PANEL")
    satir_ekle(db, "A1", "PNL-600", 50, siparis_no="S1")
    satir_ekle(db, "B1", "PNL-400", 50, siparis_no="S2")

    sonuc = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="64", grup_ici_mix=False
    )
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 2


def test_farkli_gruplar_otomatik_birlesmez(db):
    urun_ekle(db, "PNL-600", grup="PANEL")
    urun_ekle(db, "KMB-24", grup="KOMBİ")
    satir_ekle(db, "A1", "PNL-600", 50, siparis_no="S1")
    satir_ekle(db, "B1", "KMB-24", 50, siparis_no="S2")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 2


def test_aksesuar_ana_urunun_planina_yazilir(db):
    """Aksesuar tek başına plan açmaz; teslimattaki ana ürünün anahtarına yazılır."""
    urun_ekle(db, "KMB-24", palet_ici_adet=18, grup="KOMBİ")
    urun_ekle(db, "BACA-60", palet_ici_adet=77, tir_yukleme_adeti=1000, grup="AKSESUAR")
    satir_ekle(db, "TSL-1", "KMB-24", 50, siparis_no="S1")    # 0,50 anahtar
    satir_ekle(db, "TSL-1", "BACA-60", 100, siparis_no="S2")  # 0,10 anahtar
    satir_ekle(db, "TSL-2", "KMB-24", 40, siparis_no="S3")    # 0,40 anahtar

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.planlama_anahtari == "KMB-24"
    assert plan.toplam_birim == 1
    assert "BACA-60" in plan.urun_kodlari


def test_kalanlari_zorla_alt_limiti_hic_uygulamaz(db):
    urun_ekle(db, "KMB-24")
    satir_ekle(db, "TSL-1", "KMB-24", 30, siparis_no="S1")

    normal = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert normal.planlar == []

    zorlanan = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="64", kalanlari_zorla=True
    )
    assert len(zorlanan.planlar) == 1
    assert zorlanan.planlar[0].alt_limit_esnetildi is True
    assert zorlanan.esnetilen_plan_sayisi == 1


def test_dolu_planlar_esnetildi_isaretlenmez(db):
    urun_ekle(db, "KMB-24")
    for i in range(4):
        satir_ekle(db, f"TSL-{i}", "KMB-24", 25, siparis_no=f"S{i}")
    sonuc = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="64", kalanlari_zorla=True
    )
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].alt_limit_esnetildi is False


def test_agirlik_ve_adet_toplamlari_plana_yazilir(db):
    urun_ekle(db, "KMB-24", agirlik=29)
    for i in range(4):
        satir_ekle(db, f"TSL-{i}", "KMB-24", 25, siparis_no=f"S{i}")
    plan = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="64"
    ).planlar[0]
    assert plan.toplam_adet == 100
    assert plan.toplam_agirlik == Decimal("2900.000")


def test_tum_depolar_tek_seferde_planlanir(db):
    """"Tüm depolar" seçeneği her depoyu planlar, sefer numarası ortak sayaçtandır."""
    urun_ekle(db, "KMB-24")
    for i in range(4):
        satir_ekle(db, f"A-{i}", "KMB-24", 25, depo_kodu="64", siparis_no=f"S64{i}")
    for i in range(4):
        satir_ekle(db, f"B-{i}", "KMB-24", 25, depo_kodu="74", siparis_no=f"S74{i}")

    sonuc = plan_servisi.tum_depolari_planla(db, plan_tarihi=date(2026, 8, 31))
    assert {p.depo_kodu for p in sonuc.planlar} == {"64", "74"}
    assert all(p.toplam_birim == 1 for p in sonuc.planlar)
    assert sorted(p.sefer_no for p in sonuc.planlar) == ["2608D1001", "2608D1002"]
