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


def test_kirik_palet_arac_kapasitesinde_tam_palet_yeri_kaplar(db):
    """Sahadaki durum: kombi + baca çiftleri, 305 adet değil 300 adet planlanmalı.

    Kombi palet içi 15, tır yükleme adeti 360 (= 24 tam palet).
    305 adet ham oranla 305/360 = 0,847 görünür ama 21 palet gözü kaplar (0,875).
    Baca ile birlikte toplam 1,029 eder ve araca sığmaz; motor 300 adetlik
    (20 tam palet) bileşimi seçmelidir.
    """
    urun_ekle(db, "KMB-P24", palet_ici_adet=15, tir_yukleme_adeti=360, grup="KOMBİ")
    urun_ekle(db, "BACA-60", palet_ici_adet=77, tir_yukleme_adeti=2002, grup="AKSESUAR")
    for i in range(61):  # 61 x 5 = 305 adet
        satir_ekle(db, f"T{i:02d}", "KMB-P24", 5, siparis_no=f"SK{i}")
        satir_ekle(db, f"T{i:02d}", "BACA-60", 5, siparis_no=f"SB{i}")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    kombi_adedi = sum(s.miktar for s in plan.satirlar if s.urun_kodu == "KMB-P24")
    assert kombi_adedi == 300              # 20 tam palet, 305 değil
    assert plan.toplam_palet == 24         # 20 kombi + 4 baca paleti
    assert plan.toplam_birim <= 1
    assert len(sonuc.bekleyenler) == 1     # artan çift beklemede


def test_tam_palet_katindaki_miktar_araci_doldurur(db):
    urun_ekle(db, "KMB-P24", palet_ici_adet=15, tir_yukleme_adeti=360, grup="KOMBİ")
    for i in range(24):
        satir_ekle(db, f"T{i:02d}", "KMB-P24", 15, siparis_no=f"S{i}")

    plan = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu="64"
    ).planlar[0]
    assert plan.toplam_palet == 24
    assert plan.toplam_birim == 1
    assert plan.kirik_palet_israfi == 0


def test_anahtar_birimi_kirik_paleti_tam_palet_sayar():
    """Ham oran ile işgal edilen yer arasındaki farkı doğrudan ölçer."""
    from app.domain.planlama import AnahtarBirimi, Teslimat

    hesapla = AnahtarBirimi({"KMB": 15}, {"KMB": 360})

    def teslimat(miktar):
        return Teslimat(
            teslimat_no="T",
            depo_kodu="64",
            planlama_anahtari="KMB",
            urun_kodu="KMB",
            urun_adi="KMB",
            miktar=Decimal(miktar),
            birim=Decimal("0.1"),
            oncelik_tarihi=date(2026, 12, 1),
            sku_miktarlari={"KMB": Decimal(miktar)},
        )

    # 5 adet ham oranla 0,0139 eder ama bir palet gözü kaplar: 15/360 = 0,0417.
    assert hesapla([teslimat(5)]) == Decimal(15) / Decimal(360)
    # 305 adet -> 21 palet -> 315/360
    assert hesapla([teslimat(305)]) == Decimal(315) / Decimal(360)
    # 300 adet -> 20 tam palet -> ham oranla aynı
    assert hesapla([teslimat(300)]) == Decimal(300) / Decimal(360)
