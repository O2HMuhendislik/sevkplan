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


def test_kucuk_kalemler_arac_kapasitesini_sismez(db):
    """61 x 5 adetlik kombi + baca: ham ölçüyle araca tam sığar.

    Kombi palet içi 15, tır yükleme adeti 360. 305 adet = 305/360 = 0,847;
    baca 305/2002 = 0,152 — toplam 0,9995, tek araç.

    Eski ölçüde her 5'lik teslimat bir tam palet sayılıyordu: 61 kombi paleti +
    61 baca paleti = 2,88 anahtar, yani aynı yük üç araç görünüyordu.
    """
    urun_ekle(db, "KMB-P24", palet_ici_adet=15, tir_yukleme_adeti=360, grup="KOMBİ")
    urun_ekle(db, "BACA-60", palet_ici_adet=77, tir_yukleme_adeti=2002, grup="AKSESUAR")
    for i in range(61):  # 61 x 5 = 305 adet
        satir_ekle(db, f"T{i:02d}", "KMB-P24", 5, siparis_no=f"SK{i}")
        satir_ekle(db, f"T{i:02d}", "BACA-60", 5, siparis_no=f"SB{i}")

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert sum(s.miktar for s in plan.satirlar if s.urun_kodu == "KMB-P24") == 305
    assert Decimal("0.99") < plan.toplam_birim <= 1
    assert not sonuc.bekleyenler
    # Palet sayısı bilgi olarak hesaplanmaya devam eder; kapasiteye girmez.
    assert plan.toplam_palet == 25         # 21 kombi + 4 baca paleti


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


def test_anahtar_birimi_palete_yuvarlamaz():
    """Kapasite ölçüsü ham orandır: Σ miktar / yükleme adeti.

    Gerekçesi AnahtarBirimi'nde: 2025'in 2.048 gerçek tırında ham ölçünün medyanı
    1,000, palete yuvarlanmış ölçününki 1,263 çıkıyor.
    """
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

    assert hesapla([teslimat(5)]) == Decimal(5) / Decimal(360)
    assert hesapla([teslimat(305)]) == Decimal(305) / Decimal(360)
    assert hesapla([teslimat(300)]) == Decimal(300) / Decimal(360)


def test_bayi_deposu_yuku_gercek_doluluguyla_olculur(db):
    """Sahadan gelen 2609S1026 planı: sistem %98 diyordu, araç %36 doluydu.

    Bayi ortak deposu (-1) siparişleri tek tek küçük kalemler hâlinde geliyor ve her
    satır kendi teslimatı oluyor. Eski ölçüde her satır ayrı bir tam palet sayılıyordu:
    28 adet atık gaz borusu 4 x 77 = 308 adet gibi ölçülüyor, 18 SKU'luk yük %98,43
    çıkıyordu. Gerçek ölçüsü 0,357.
    """
    urunler = {
        # kod: (palet içi, tır yükleme adeti)
        "315061213": (64, 1408), "315091213": (32, 896), "315101213": (32, 768),
        "315111213": (32, 768), "315121213": (32, 704), "315131213": (16, 560),
        "315141213": (16, 544), "315151213": (16, 528), "315161213": (16, 528),
        "315181213": (16, 512), "315201213": (14, 350), "8000021394": (1, 92),
        "8000021402": (8, 176), "10047150": (8, 208), "20268005": (77, 2002),
        "10019471": (15, 360), "3003202922": (77, 2002), "8000013403": (18, 468),
    }
    for kod, (ici, tir) in urunler.items():
        urun_ekle(db, kod, palet_ici_adet=ici, tir_yukleme_adeti=tir, grup="KARMA")

    # Formdaki 25 satır: her sipariş kendi teslimatı (bayi ortak deposu düzeni).
    satirlar = [
        ("315061213", 5), ("315091213", 1), ("315101213", 10), ("315111213", 10),
        ("315121213", 10), ("315131213", 10), ("315141213", 10), ("315151213", 3),
        ("315161213", 1), ("315181213", 6), ("315201213", 5), ("8000021394", 3),
        ("8000021402", 3), ("10047150", 15), ("20268005", 15), ("10019471", 15),
        ("3003202922", 15), ("10047150", 3), ("20268005", 3), ("10047150", 2),
        ("20268005", 2), ("10019471", 5), ("3003202922", 5), ("8000013403", 8),
        ("20268005", 8),
    ]
    for sira, (kod, adet) in enumerate(satirlar):
        satir_ekle(db, f"T{sira:02d}", kod, adet, siparis_no=f"S{sira:02d}")

    # Doğru ölçüyle bu yük bir tırı dolduramaz: alt limit (0,75) altında kaldığı için
    # tam araç açılmaz, beklemede kalır. Eskiden %98,43 ile dolu araç sanılıyordu.
    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 9, 4), depo_kodu="64")
    assert not sonuc.planlar

    # Zorlanırsa tek araç çıkar ve gerçek doluluğunu yazar.
    zorlanmis = plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 4), depo_kodu="64", kalanlari_zorla=True
    )
    assert len(zorlanmis.planlar) == 1
    plan = zorlanmis.planlar[0]
    assert sum(s.miktar for s in plan.satirlar) == 173
    assert Decimal("0.35") < plan.toplam_birim < Decimal("0.37")   # eski ölçü: 0,984
