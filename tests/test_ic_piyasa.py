"""İç piyasa planlama motorunun kuralları.

Ölçek (bkz. conftest.urun_ekle): bir tıra 100 adet, bir palete 10 adet sığar.
Yani 100 adet = tam tır = 10 palet; 30 adet = 3 palet = %30 tır.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.domain.bolgeler import bolge_adi, il_bolgesi
from app.domain.ic_piyasa import (
    Kurallar,
    MusteriSiparisi,
    RotaPlani,
    SevkiyatTipi,
    aktarma_notu,
    musteriyi_bol,
    planla,
    tip_belirle,
    yukleme_deposu,
)
from app.domain.kapasite import (
    AracTipi,
    IC_EXW,
    IC_FTL,
    IC_FTL_KAMYON,
    IC_KARGO,
    IC_RUTIN,
    IC_RUTIN_KAMYON,
)
from app.domain.planlama import Teslimat
from app.services import ic_piyasa_servisi
from tests.conftest import satir_ekle, urun_ekle


def teslimat(no, birim, depo="64", miktar=None, palet=None):
    miktar = Decimal(str(miktar if miktar is not None else birim * 100))
    return Teslimat(
        teslimat_no=no,
        depo_kodu=depo,
        planlama_anahtari="U1",
        urun_kodu="U1",
        urun_adi="U1 ürünü",
        miktar=miktar,
        birim=Decimal(str(birim)),
        oncelik_tarihi=date(2026, 9, 1),
        sku_miktarlari={"U1": miktar},
        depo_katkilari={depo: Decimal(str(birim))},
        palet=Decimal(str(palet if palet is not None else birim * 10)),
        anahtar=Decimal(str(birim)),
    )


def musteri(
    ad, il, birim, ilce="MERKEZ", palet=None, desi=0, incoterms="CIF",
    tir="?", depo="64", teslimatlar=None,
):
    teslimatlar = teslimatlar or (teslimat(f"{ad}-1", birim, depo),)
    return MusteriSiparisi(
        anahtar=f"{ad}|{il}|{ilce}",
        bayi_adi=ad,
        il=il,
        ilce=ilce,
        teslimatlar=tuple(teslimatlar),
        palet=Decimal(str(palet if palet is not None else birim * 10)),
        birim=Decimal(str(birim)),
        desi=Decimal(str(desi)),
        adet=sum((t.miktar for t in teslimatlar), Decimal(0)),
        agirlik=Decimal(0),
        incoterms=incoterms,
        tir_girisi=tir,
    )


# ------------------------------------------------------------------ sevkiyat tipi


def test_exw_musterisi_kendi_tipine_gider():
    """Taşımayı müşteri üstleniyorsa hacmi ne olursa olsun araç planlanmaz.

    EXW kargo **değildir**: kargoya verdiğimiz malın navlununu biz öderiz, EXW malı
    müşterinin aracına yüklenir. İkisi tek listede toplanınca günlük kargo listesi
    2025 verisinde 9,7 tırlık EXW yüküyle şişiyordu.
    """
    tip, gerekce = tip_belirle(musteri("BÜYÜK BAYİ", "IZMIR", 0.9, incoterms="EXW"))
    assert tip is SevkiyatTipi.EXW
    assert tip.aracsiz_mi
    assert "EXW" in gerekce


def test_exw_kargo_listesine_karismaz():
    """EXW ve kargo ayrı listelerde toplanır; sefer numaraları da ayrıdır."""
    from app.domain.ic_piyasa import EXW_KODU, GUNLUK_KARGO_KODU

    exw = planla(
        [musteri("EXW BAYİ", "IZMIR", 0.9, incoterms="EXW")],
        SevkiyatTipi.EXW, IC_EXW,
    )
    kargo = planla(
        [musteri("KÜÇÜK", "IZMIR", Decimal("0.001"), desi=7)],
        SevkiyatTipi.KARGO, IC_KARGO,
    )
    assert [p.bolge_kodu for p in exw.planlar] == [EXW_KODU]
    assert [p.bolge_kodu for p in kargo.planlar] == [GUNLUK_KARGO_KODU]
    assert SevkiyatTipi.EXW.belge_kodu == "X"


def test_aracsiz_listede_doluluk_olculmez():
    """Kargo/EXW listesinde araç yoktur; 9,8 tırlık liste %980 doluluk göstermemeli."""
    sonuc = planla(
        [musteri("TOPTANCI", "IZMIR", 9, incoterms="EXW")],
        SevkiyatTipi.EXW, IC_EXW,
    )
    plan = sonuc.planlar[0]
    assert plan.toplam_birim == Decimal(9)
    assert plan.doluluk_yuzdesi == Decimal(0)


def test_on_desinin_altindaki_musteri_kargoya_gider():
    tip, _ = tip_belirle(musteri("KÜÇÜK", "IZMIR", 0.02, desi=7))
    assert tip is SevkiyatTipi.KARGO


def test_on_desi_ve_uzeri_kargoya_gitmez():
    """Eşik tam 10 desi: 10 desi kargoya değil, hacmine göre rutine/FTL'e düşer."""
    tip, _ = tip_belirle(musteri("ORTA", "IZMIR", 0.02, palet=2, desi=10))
    assert tip is SevkiyatTipi.RUTIN


def test_uc_palete_kadar_rutin():
    tip, gerekce = tip_belirle(musteri("BAYİ", "IZMIR", 0.3, palet=3, desi=500))
    assert tip is SevkiyatTipi.RUTIN
    assert "3 palet" in gerekce


def test_uc_paletten_buyuk_musteri_ftl_olur():
    tip, _ = tip_belirle(musteri("BAYİ", "IZMIR", 0.4, palet=4, desi=500))
    assert tip is SevkiyatTipi.FTL


def test_palet_kurali_musterinin_tumunu_kapsar():
    """Üç palet sınırı tek teslimata değil, müşterinin o günkü toplamına bakar."""
    iki_teslimat = (teslimat("T1", 0.2, palet=2), teslimat("T2", 0.2, palet=2))
    tip, _ = tip_belirle(
        musteri("BAYİ", "IZMIR", 0.4, palet=4, desi=500, teslimatlar=iki_teslimat)
    )
    assert tip is SevkiyatTipi.FTL


# ------------------------------------------------------------------- FTL kuralları


def test_ftl_araca_en_fazla_bes_durak_konur():
    musteriler = [
        musteri(f"BAYİ{sira}", "ISTANBUL", 0.15, ilce=f"ILCE{sira}") for sira in range(8)
    ]
    sonuc = planla(musteriler, SevkiyatTipi.FTL, IC_FTL, Kurallar())
    for plan in sonuc.planlar:
        assert plan.durak_sayisi <= 5


def test_son_ugrak_yuzde_onbesin_altindaysa_aractan_cikarilir():
    """Uzak ildeki küçük müşteri için o mesafeye araç göndermek navlunu bozar.

    İki il aynı bölgede (B05) olmasa zaten aynı araca binmezlerdi; kuralın tek başına
    çalıştığını görmek için aynı bölgeden, aynı güzergâhta yakın/uzak bir çift
    seçildi (Kayseri üzerinden Van'a sapma 14 km, rota kuralına takılmaz).
    """
    yakin = musteri("YAKIN", "KAYSERI", 0.9)
    uzak = musteri("UZAK", "VAN", 0.05)
    assert il_bolgesi("KAYSERI") == il_bolgesi("VAN")

    sonuc = planla([yakin, uzak], SevkiyatTipi.FTL, IC_FTL)

    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].son_ugrak == "KAYSERI"
    assert [b.musteri.bayi_adi for b in sonuc.bekleyenler] == ["UZAK"]
    assert "Son uğrak" in sonuc.bekleyenler[0].sebep


def test_son_ugrak_kurali_tek_durakli_aracta_aranmaz():
    plan = RotaPlani("B01", SevkiyatTipi.FTL, IC_FTL, [musteri("TEK", "VAN", 0.9)])
    assert plan.son_ugrak_uygun_mu(Kurallar())


def test_duraklar_yakindan_uzaga_siralanir():
    plan = RotaPlani(
        "B01",
        SevkiyatTipi.FTL,
        IC_FTL,
        [musteri("A", "VAN", 0.3), musteri("B", "BURSA", 0.3), musteri("C", "ANKARA", 0.3)],
    )
    assert plan.iller == ["BURSA", "ANKARA", "VAN"]
    assert plan.son_ugrak == "VAN"


def test_motor_hacmin_gerektirdigi_butun_araclari_uretir():
    """Günlük sınır motorun işi değil: hacim kaç araç gerektiriyorsa o kadar üretilir.

    Aracın hangi güne düşeceğine takvimi bilen servis karar verir; motor araçları
    en dolu olan başta olacak şekilde sıralar.
    """
    musteriler = [
        musteri(f"BAYİ{sira}", "ISTANBUL", Decimal("0.95") - sira * Decimal("0.02"),
                ilce=f"ILCE{sira}")
        for sira in range(5)
    ]
    sonuc = planla(musteriler, SevkiyatTipi.FTL, IC_FTL)
    assert len(sonuc.planlar) == 5
    assert not sonuc.bekleyenler
    birimler = [p.toplam_birim for p in sonuc.planlar]
    assert birimler == sorted(birimler, reverse=True)


def test_her_durak_icin_yuzde_bir_pay_birakilir():
    """Beş duraklı tır %95'te kapatılır: her durak için elleçleme boşluğu gerekir.

    Kâğıt üzerinde %100 dolu görünen çok duraklı araca mal fiziken sığmıyor; yük
    kapıda boşaltılacak sırayla istifleniyor ve her durak için pay bırakılıyor.
    """
    musteriler = [
        musteri(f"BAYİ{sira}", "ISTANBUL", 0.20, ilce=f"ILCE{sira}")
        for sira in range(5)
    ]
    sonuc = planla(musteriler, SevkiyatTipi.FTL, IC_FTL, kalanlari_zorla=True)
    # 5 x 0,20 = 1,00; beş duraklı araca 0,95 sığar, biri dışarıda kalır.
    dolu = max(sonuc.planlar, key=lambda p: p.toplam_birim)
    assert dolu.durak_sayisi == 4
    assert dolu.toplam_birim == Decimal("0.80")
    assert dolu.kapasite() == Decimal("0.96")


def test_tek_durakli_arac_yuzde_99da_kapatilir():
    musteriler = [musteri("TEK", "ISTANBUL", 0.99)]
    plan = planla(musteriler, SevkiyatTipi.FTL, IC_FTL).planlar[0]
    assert plan.kapasite() == Decimal("0.99")
    assert plan.bos_alan == Decimal(0)
    assert not plan.sigar_mi(musteri("EK", "ISTANBUL", 0.001, ilce="X"), Kurallar())


def test_durak_payi_kapatilabilir():
    """Pay ayardan gelir; sıfırlanınca eski davranış (tam kapasite) geri döner."""
    kurallar = Kurallar(durak_payi=Decimal(0))
    musteriler = [
        musteri(f"BAYİ{sira}", "ISTANBUL", 0.20, ilce=f"ILCE{sira}")
        for sira in range(5)
    ]
    sonuc = planla(musteriler, SevkiyatTipi.FTL, IC_FTL, kurallar)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].toplam_birim == Decimal("1.00")


def test_farkli_bolgeler_ayni_araca_binmez():
    sonuc = planla(
        [musteri("EGE", "IZMIR", 0.5), musteri("MARMARA", "ISTANBUL", 0.5)],
        SevkiyatTipi.FTL,
        IC_FTL,
        kalanlari_zorla=True,
    )
    assert len(sonuc.planlar) == 2
    assert {p.bolge_kodu for p in sonuc.planlar} == {
        il_bolgesi("IZMIR"),
        il_bolgesi("ISTANBUL"),
    }


def test_alt_limiti_dolduramayan_arac_acilmaz():
    sonuc = planla([musteri("KÜÇÜK", "IZMIR", 0.4)], SevkiyatTipi.FTL, IC_FTL)
    assert sonuc.planlar == []
    assert "alt limitini doldurmuyor" in sonuc.bekleyenler[0].sebep


def test_kalanlari_zorla_alt_limiti_atlar():
    sonuc = planla(
        [musteri("KÜÇÜK", "IZMIR", 0.4)], SevkiyatTipi.FTL, IC_FTL, kalanlari_zorla=True
    )
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].alt_limit_esnetildi


# --------------------------------------------------------------- müşteriyi bölme


def test_bir_araci_asan_musteri_araclara_bolunur():
    """Bölünmez olan teslimattır; 2,5 araçlık sipariş veren bayiye üç araç gider."""
    teslimatlar = tuple(teslimat(f"T{sira}", 0.5) for sira in range(5))
    buyuk = musteri("DEV BAYİ", "IZMIR", 2.5, teslimatlar=teslimatlar)
    parcalar = musteriyi_bol(buyuk, SevkiyatTipi.FTL, Decimal(1))

    assert len(parcalar) == 3
    assert all(p.birim <= 1 for p in parcalar)
    assert sum(len(p.teslimatlar) for p in parcalar) == 5


def test_tek_basina_araci_asan_teslimat_istisna_planina_gider():
    buyuk = musteri("DEV", "IZMIR", 1.6, teslimatlar=(teslimat("T1", 1.6),))
    sonuc = planla([buyuk], SevkiyatTipi.FTL, IC_FTL)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].istisna_asim
    assert sonuc.planlar[0].doluluk_yuzdesi > 100


# --------------------------------------------------------------- rutin ve kargo


def test_rutin_arac_yuzde_altmista_birakilir():
    """Rutinde üst limit tırın %60'ı: karışık palet ve çok durak olduğu için dolmaz."""
    assert IC_RUTIN.ust_limit == Decimal("0.60")
    musteriler = [
        musteri(f"BAYİ{sira}", "ISTANBUL", 0.1, ilce=f"ILCE{sira}", palet=1)
        for sira in range(9)
    ]
    sonuc = planla(musteriler, SevkiyatTipi.RUTIN, IC_RUTIN)
    assert all(plan.toplam_birim <= Decimal("0.60") for plan in sonuc.planlar)


def test_rutin_aracta_durak_siniri_yoktur():
    """FTL'deki 5 durak kuralı rutinde geçerli değil; rutin 25-30 durak yapıyor."""
    musteriler = [
        musteri(f"BAYİ{sira}", "ISTANBUL", 0.05, ilce=f"ILCE{sira}", palet=1)
        for sira in range(12)
    ]
    sonuc = planla(musteriler, SevkiyatTipi.RUTIN, IC_RUTIN)
    assert max(plan.durak_sayisi for plan in sonuc.planlar) > 5


def test_olcu_sevkiyat_tipine_gore_degismez():
    """FTL, rutin ve kargo aynı ham anahtar değeri kullanır.

    Bir dönem FTL'de miktar palete yukarı yuvarlanıyordu; gerçek araçlarda
    doğrulanmadığı için kaldırıldı (bkz. AnahtarBirimi).
    """
    kucuk = musteri("BAYİ", "IZMIR", 0.30, palet=3)
    assert kucuk.olcu(SevkiyatTipi.FTL) == kucuk.birim
    assert kucuk.olcu(SevkiyatTipi.RUTIN) == kucuk.birim
    assert kucuk.olcu(SevkiyatTipi.KARGO) == kucuk.birim


def test_kargoda_kapasite_ve_durak_kurali_aranmaz():
    musteriler = [
        musteri(f"BAYİ{sira}", "ISTANBUL", 0.01, ilce=f"ILCE{sira}", desi=5)
        for sira in range(9)
    ]
    sonuc = planla(musteriler, SevkiyatTipi.KARGO, IC_KARGO)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].durak_sayisi == 9
    assert sonuc.bekleyenler == []


# ------------------------------------------------------------------ ortak yükleme


def test_yukleme_deposu_en_cok_hacmi_olan_depodur():
    plan = RotaPlani(
        "B01",
        SevkiyatTipi.FTL,
        IC_FTL,
        [
            musteri("A", "IZMIR", 0.6, depo="64"),
            musteri("B", "IZMIR", 0.3, ilce="BORNOVA", depo="74"),
        ],
    )
    assert yukleme_deposu(plan) == "64"


def test_aktarma_notu_yalnizca_baska_depodaki_mala_yazilir():
    assert aktarma_notu("74", "64") == "64 depoya gönderilmelidir"
    assert aktarma_notu("64", "64") == ""


# ------------------------------------------------------------------- bölge tablosu


def test_bolge_tablosu_illeri_dogru_esler():
    assert il_bolgesi("İZMİR") == il_bolgesi("IZMIR")
    assert bolge_adi(il_bolgesi("IZMIR")) == "Ege"
    assert il_bolgesi("MANISA") == il_bolgesi("IZMIR")


def test_tanimsiz_il_kendi_basina_bolge_olur():
    """Tanımsız ili başka illerle aynı torbaya atmak yanlış rota kurar."""
    kod = il_bolgesi("BİLİNMEYEN")
    assert kod.startswith("IL:")
    assert kod != il_bolgesi("BAŞKA İL")


# ---------------------------------------------------------------- servis katmanı


@pytest.fixture()
def ic_veri(db):
    urun_ekle(db, "U1", palet_ici_adet=10, tir_yukleme_adeti=100)
    return db


def _siparis(db, teslimat_no, miktar, bayi, sehir, depo="64", ilce="MERKEZ"):
    """İç piyasa havuzuna sipariş satırı ekler (modül = ROTA)."""
    satir = satir_ekle(db, teslimat_no, "U1", miktar, depo_kodu=depo, modul="ROTA")
    satir.bayi_adi = bayi
    satir.sehir = sehir
    satir.ilce = ilce
    db.flush()
    return satir


def test_ayni_bayinin_farkli_illerdeki_subeleri_ayri_duraktir(ic_veri):
    """Bayi kodu gelmediği için şubeler tek adla geliyor; il/ilçe ayrımı şart.

    Ayrılmazsa Samsun ve Trabzon'daki iki şube tek durak sayılır; araç tek duraklı
    görünür, son uğrak ve yükleme formundaki "Yer Miktarı" yanlış çıkar.
    """
    from app.models import SiparisSatiri

    db = ic_veri
    _siparis(db, "T1", 40, "SÜHA MAKİNA", "SAMSUN")
    _siparis(db, "T2", 40, "SÜHA MAKİNA", "TRABZON")
    db.flush()

    satirlar = list(db.query(SiparisSatiri).all())
    musteriler, _ = ic_piyasa_servisi.musterileri_topla(db, satirlar)
    assert {m.il for m in musteriler} == {"SAMSUN", "TRABZON"}
    assert all(m.bayi_adi == "SÜHA MAKİNA" for m in musteriler)


def test_plan_uretimi_tipleri_ayirir(ic_veri):
    db = ic_veri
    from app.models import SiparisSatiri

    _siparis(db, "FTL-1", 90, "BÜYÜK BAYİ", "IZMIR")
    _siparis(db, "RUT-1", 20, "KÜÇÜK BAYİ", "IZMIR", ilce="BORNOVA")
    db.flush()

    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), kullanici="test"
    )
    tipler = {plan.sevkiyat_tipi for plan in sonuc.planlar}
    assert "FTL" in tipler
    assert all(plan.modul == "ROTA" for plan in sonuc.planlar)
    assert all(plan.sefer_no[4] in "SRK" for plan in sonuc.planlar)
    assert db.query(SiparisSatiri).filter_by(teslimat_no="FTL-1").one().plan_id


def test_ortak_yukleme_notu_plana_islenir(ic_veri):
    """64 + 74 aynı araca yüklenince az olan depodaki mal diğerine getirilir."""
    db = ic_veri
    # İkisi de 3 paletten büyük olmalı ki FTL kovasına düşsünler. Toplam 0,98:
    # iki duraklı araçta durak payı (%1 x 2) düşülünce kalan kapasite tam budur.
    _siparis(db, "T1", 60, "BAYİ A", "IZMIR", depo="64")
    _siparis(db, "T2", 38, "BAYİ B", "IZMIR", depo="74", ilce="BORNOVA")
    db.flush()

    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL], kullanici="test"
    )
    plan = sonuc.planlar[0]
    assert plan.yukleme_deposu == "64"
    yetmis_dort = next(s for s in plan.satirlar if s.depo_kodu == "74")
    altmis_dort = next(s for s in plan.satirlar if s.depo_kodu == "64")
    assert plan.aktarma_notu(yetmis_dort) == "64 depoya gönderilmelidir"
    assert plan.aktarma_notu(altmis_dort) == ""


def test_gunluk_sinir_dolunca_ertesi_gune_planlanir(ic_veri):
    """Günlük sınıra takılan hacim beklemez, sonraki çalışma gününe kayar."""
    db = ic_veri
    kurallar = Kurallar(gunluk_ftl_siniri=1)
    for sira in range(3):
        _siparis(db, f"T{sira}", 95, f"BAYİ {sira}", "IZMIR", ilce=f"ILCE{sira}")
    db.flush()

    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL],
        kurallar=kurallar, kullanici="test",
    )
    assert len(sonuc.planlar) == 3
    assert not sonuc.bekleyenler
    assert [p.plan_tarihi for p in sonuc.planlar] == [
        date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)
    ]
    assert "3 iş gününe dağıtıldı" in sonuc.ozet()


def test_pazar_gunune_plan_uretilmez(ic_veri):
    """Sevkiyat pazar günü yapılmaz; o güne düşen araç pazartesiye kayar."""
    db = ic_veri
    kurallar = Kurallar(gunluk_ftl_siniri=1)
    for sira in range(2):
        _siparis(db, f"P{sira}", 95, f"BAYİ {sira}", "IZMIR", ilce=f"ILCE{sira}")
    db.flush()

    # 5 Eylül 2026 cumartesi, 6 Eylül pazar, 7 Eylül pazartesi.
    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 5), tipler=[SevkiyatTipi.FTL],
        kurallar=kurallar, kullanici="test",
    )
    assert [p.plan_tarihi for p in sonuc.planlar] == [
        date(2026, 9, 5), date(2026, 9, 7)
    ]


def test_pazara_verilen_plan_tarihi_pazartesiye_alinir(ic_veri):
    db = ic_veri
    _siparis(db, "PZ-1", 95, "BAYİ", "IZMIR")
    db.flush()
    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 6), tipler=[SevkiyatTipi.FTL], kullanici="test"
    )
    assert [p.plan_tarihi for p in sonuc.planlar] == [date(2026, 9, 7)]


def test_gunluk_sinir_daha_once_uretilen_planlari_sayar(ic_veri):
    """Aynı gün ikinci kez çalıştırıldığında sınır sıfırdan başlamaz."""
    db = ic_veri
    kurallar = Kurallar(gunluk_ftl_siniri=1)
    _siparis(db, "T0", 95, "BAYİ 0", "IZMIR")
    db.flush()
    ilk = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL],
        kurallar=kurallar, kullanici="test",
    )
    assert [p.plan_tarihi for p in ilk.planlar] == [date(2026, 9, 1)]

    _siparis(db, "T1", 95, "BAYİ 1", "IZMIR", ilce="BORNOVA")
    db.flush()
    ikinci = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL],
        kurallar=kurallar, kullanici="test",
    )
    assert [p.plan_tarihi for p in ikinci.planlar] == [date(2026, 9, 2)]


def test_planlama_ufkuna_sigmayan_hacim_beklemede_kalir(ic_veri):
    """Ufuk sonsuz değil: bir yıllık havuz tek çalıştırmada 100 günlük araç üretmemeli."""
    db = ic_veri
    kurallar = Kurallar(gunluk_ftl_siniri=1, planlama_ufku_gun=2)
    for sira in range(4):
        _siparis(db, f"U{sira}", 95, f"BAYİ {sira}", "IZMIR", ilce=f"ILCE{sira}")
    db.flush()

    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL],
        kurallar=kurallar, kullanici="test",
    )
    assert len(sonuc.planlar) == 2
    assert len(sonuc.bekleyenler) == 2
    assert "planlama ufkuna sığmadı" in sonuc.bekleyenler[0].sebep


def test_marka_sonekli_depolar_ayni_depodur():
    """64-V'deki mal 64'e "gönderilmez", zaten oradadır; sonek markayı gösterir."""
    plan = RotaPlani(
        "B01",
        SevkiyatTipi.FTL,
        IC_FTL,
        [
            musteri("A", "IZMIR", 0.3, depo="64"),
            musteri("B", "IZMIR", 0.4, ilce="BORNOVA", depo="64-V"),
            musteri("C", "IZMIR", 0.2, ilce="KARSIYAKA", depo="74"),
        ],
    )
    assert yukleme_deposu(plan) == "64"
    assert aktarma_notu("64-V", "64") == ""
    assert aktarma_notu("74-V", "64") == "64 depoya gönderilmelidir"
    assert aktarma_notu("64-P", "74-V") == "74 depoya gönderilmelidir"


def test_ilce_alanina_sayi_yazilmaz():
    """`Not` ve `SevkAdresi` sütunlarında ilçe yerine kod geldiğinde alan boş kalır."""
    from app.services.veri_formatlari import not_alanini_coz, yer_alanlarini_coz

    assert not_alanini_coz("CIF - 45796") == ("CIF", "")
    assert not_alanini_coz(" - MERKEZ") == ("", "MERKEZ")

    firma, adres, ilce, incoterms = yer_alanlarini_coz(
        "PAZAR MH. M.ENGİZLİ SOKAK.NO:2/A", "45796", "CIF"
    )
    assert adres == "PAZAR MH. M.ENGİZLİ SOKAK.NO:2/A"
    assert ilce == ""
    assert incoterms == "CIF"


def test_sutun_duzeni_icerikten_cozulur():
    """AliciFirma/SevkAdresi sütunlarının anlamı satır tipine göre kayıyor."""
    from app.services.veri_formatlari import yer_alanlarini_coz

    # Bayi siparişi: adres AliciFirma sütununda, ilçe SevkAdresi sütununda.
    assert yer_alanlarini_coz(
        "KORDON BOYU MAH.TURGUT ÖZAL BULV. NO:61/1", "KARTAL", "CIF"
    ) == ("", "KORDON BOYU MAH.TURGUT ÖZAL BULV. NO:61/1", "KARTAL", "CIF")

    # Bayi ortak deposu siparişi: firma yerinde firma, adres SevkAdresi'nde, ilçe Not'ta.
    assert yer_alanlarini_coz(
        "ANKA CORP İNŞAAT LİMİTED ŞİRKETİ", "GÜMÜŞÇEŞME MAH. 184 SOK. NO:13/B", " - MERKEZ"
    ) == (
        "ANKA CORP İNŞAAT LİMİTED ŞİRKETİ",
        "GÜMÜŞÇEŞME MAH. 184 SOK. NO:13/B",
        "MERKEZ",
        "",
    )


# ------------------------------------------- bayi ortak deposu (-1) teslimat bölme


def bolunebilir_teslimat(no, miktar, satirlar):
    """`-1` deposundan gelen, miktarı kesilebilen teslimat.

    Ölçek: palete 10, tıra 100 adet. Yani 100 adet = tam tır.
    """
    return Teslimat(
        teslimat_no=no,
        depo_kodu="-1",
        planlama_anahtari="U1",
        urun_kodu="U1",
        urun_adi="U1 ürünü",
        miktar=Decimal(miktar),
        birim=Decimal(miktar) / 100,
        oncelik_tarihi=date(2026, 9, 1),
        satir_idleri=tuple(satirlar),
        sku_kodlari=("U1",),
        sku_miktarlari={"U1": Decimal(miktar)},
        satir_miktarlari={
            sid: ("U1", Decimal(miktar) / len(satirlar)) for sid in satirlar
        },
        bolunebilir_mi=True,
        depo_katkilari={"-1": Decimal(miktar) / 100},
        palet=Decimal(miktar) / 10,
        anahtar=Decimal(miktar) / 100,
    )


PALET_ICI = {"U1": 10}
YUKLEME = {"U1": 100}


def test_bayi_depo_teslimati_arac_kapasitesine_gore_kesilir():
    """1000 adetlik sipariş, 100 adetlik araçlara tam palet sınırında bölünür."""
    from app.domain.ic_piyasa import teslimati_bol

    t = bolunebilir_teslimat("BD-1", 1000, [1])
    parcalar = teslimati_bol(t, Decimal(1), SevkiyatTipi.FTL, PALET_ICI, YUKLEME)

    assert len(parcalar) == 10
    assert all(p.birim <= 1 for p in parcalar)
    assert sum(p.miktar for p in parcalar) == 1000
    # Her parça tam palet: 100 adet = 10 palet
    assert all(p.miktar % 10 == 0 for p in parcalar)


def test_kesim_tam_palet_sinirinda_yapilir():
    """Araca 85 adet sığsa bile 80 alınır: kırık palet yüklenmez."""
    from app.domain.ic_piyasa import teslimati_bol

    t = bolunebilir_teslimat("BD-2", 200, [1])
    parcalar = teslimati_bol(
        t, Decimal("0.85"), SevkiyatTipi.FTL, PALET_ICI, YUKLEME
    )
    assert [p.miktar for p in parcalar] == [Decimal(80), Decimal(80), Decimal(40)]


def test_araca_sigan_teslimat_hicbir_depoda_kesilmez():
    """Aracı aşmayan teslimat bölünmez — bölünebilir depoda bile."""
    from app.domain.ic_piyasa import teslimati_bol

    t = replace(bolunebilir_teslimat("T-1", 100, [1]), depo_kodu="64", bolunebilir_mi=False)
    assert teslimati_bol(t, Decimal(1), SevkiyatTipi.FTL, PALET_ICI, YUKLEME) == [t]


def test_araci_asan_teslimat_bolunemeyen_depoda_da_bolunur():
    """Bir araç bir araçtan fazlasını taşıyamaz: 64 deposunda da bölünür.

    Sahadan gelen örnek: TÜZÜNLER ENERJİ'nin 0060774085 teslimatı tek başına 1,56
    tır. Eskiden "teslimat bölünmez" kuralı yüzünden tek araca konuyor ve plan
    %155,87 dolulukla görünüyordu; o araç sahada yüklenemez.
    """
    from app.domain.ic_piyasa import teslimati_bol

    t = replace(bolunebilir_teslimat("T-1", 156, [1]), depo_kodu="64", bolunebilir_mi=False)
    parcalar = teslimati_bol(t, Decimal(1), SevkiyatTipi.FTL, PALET_ICI, YUKLEME)

    assert len(parcalar) == 2
    assert sum(p.miktar for p in parcalar) == Decimal(156)
    assert all(p.birim <= 1 for p in parcalar)
    assert [(p.parca_no, p.parca_adedi) for p in parcalar] == [(1, 2), (2, 2)]


def test_bayi_depo_musterisi_istisna_plani_uretmez():
    """Bölünebilir teslimatta artık %100'ü aşan araç kalmaz."""
    dev = musteri(
        "BAYİ DEPO MÜŞTERİSİ", "IZMIR", 10,
        teslimatlar=(bolunebilir_teslimat("BD-3", 1000, [1]),),
    )
    sonuc = planla(
        [dev], SevkiyatTipi.FTL, IC_FTL,
        palet_ici=PALET_ICI, yukleme_adeti=YUKLEME,
    )
    # Tek duraklı araç 0,99'da kapatıldığı için 10 tırlık yük 11 araca çıkar.
    assert len(sonuc.planlar) == 11
    assert not any(plan.istisna_asim for plan in sonuc.planlar)
    assert all(plan.doluluk_yuzdesi <= 99 for plan in sonuc.planlar)


def test_hicbir_plan_araci_asmaz():
    """Aracı aşan teslimat 64/74 deposunda da bölünür; hiçbir plan %100'ü aşmaz.

    Sahadan gelen defekt: 2025 havuzunda üretilen 118 planın 88'i %100'ün üzerinde
    doluluk gösteriyordu — en büyüğü %980 (kargo listesi), araçlılar arasında en
    büyüğü %214. Sebep, tek başına aracı aşan teslimatların bölünmeden tek araca
    konmasıydı.
    """
    dev = musteri(
        "BÖLÜNEMEYEN DEPO", "IZMIR", Decimal("2.56"),
        teslimatlar=(
            replace(
                bolunebilir_teslimat("T-256", 256, [1, 2, 3]),
                depo_kodu="64", bolunebilir_mi=False,
                depo_katkilari={"64": Decimal("2.56")},
            ),
        ),
    )
    sonuc = planla(
        [dev], SevkiyatTipi.FTL, IC_FTL,
        palet_ici=PALET_ICI, yukleme_adeti=YUKLEME, kalanlari_zorla=True,
    )
    assert sum(p.toplam_birim for p in sonuc.planlar) == Decimal("2.56")
    assert all(plan.doluluk_yuzdesi <= 100 for plan in sonuc.planlar)
    assert not any(plan.istisna_asim for plan in sonuc.planlar)


def test_palet_alti_kalem_araci_tasirmaz():
    """Bir paletin altında kalan kalem bölünmez ama aracı da aşırmaz.

    Küçük kalemler "aksesuar ana ürününden kopmasın" diye bütün hâlde ilk araca
    konuyordu; birikince parça kapasiteyi aşıyor ve plan %101,80 çıkıyordu.
    """
    from app.domain.ic_piyasa import teslimati_bol

    t = replace(
        bolunebilir_teslimat("T-KUCUK", 105, [1, 2, 3, 4, 5, 6, 7]),
        depo_kodu="74", bolunebilir_mi=False,
    )
    parcalar = teslimati_bol(t, Decimal(1), SevkiyatTipi.FTL, PALET_ICI, YUKLEME)

    assert sum(p.miktar for p in parcalar) == Decimal(105)
    assert all(p.birim <= 1 for p in parcalar)


def test_bekleme_sebebi_siparis_satirina_yazilir(ic_veri):
    """Plana giremeyen satır, gerekçesini ekranda gösterebilmeli.

    Gerekçe eskiden yalnızca çalıştırma özetinde duruyordu; Bekleyenler ekranı bütün
    satırlara ayrımsız "Hacim bekliyor" yazıyordu. Oysa satır günlük araç sınırına
    da takılmış olabilir, son uğrak kuralına da.
    """
    from app.models import SiparisSatiri

    db = ic_veri
    # 5 palet: rutin sınırının üstünde ama tırın alt limitini dolduramıyor.
    _siparis(db, "KUCUK-1", 50, "KÜÇÜK BAYİ", "IZMIR")
    db.flush()

    ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL], kullanici="test"
    )
    satir = db.scalars(
        select(SiparisSatiri).where(SiparisSatiri.teslimat_no == "KUCUK-1")
    ).first()
    assert satir.plan_id is None
    assert "Yeterli hacim yok" in satir.bekleme_sebebi
    assert satir.bekleme_gerekcesi == satir.bekleme_sebebi


def test_plana_giren_satirin_bekleme_sebebi_silinir(ic_veri):
    """Satır plana girince eski gerekçesi ekranda kalmamalı."""
    from app.models import SiparisSatiri

    db = ic_veri
    _siparis(db, "BUYUR-1", 50, "BÜYÜYEN BAYİ", "IZMIR")
    db.flush()
    ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL], kullanici="test"
    )
    _siparis(db, "BUYUR-2", 45, "BÜYÜYEN BAYİ", "IZMIR")
    db.flush()
    ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 2), tipler=[SevkiyatTipi.FTL], kullanici="test"
    )

    satirlar = db.scalars(
        select(SiparisSatiri).where(SiparisSatiri.teslimat_no.in_(["BUYUR-1", "BUYUR-2"]))
    ).all()
    assert all(s.plan_id is not None for s in satirlar)
    assert all(s.bekleme_sebebi is None for s in satirlar)


def test_kesilen_satirin_kalani_ayni_teslimatla_beklemede_kalir(ic_veri):
    """Araca sığmayan miktar aynı teslimat numarasıyla beklemede kalır."""
    from app.models import SiparisDurumu, SiparisSatiri

    db = ic_veri
    # 100 adet = tam tır ama tek duraklı araç 0,99'da kapatılır: araca 99 adet
    # girer, palete indirilince 90. 250 adetlik tek satırlık bayi depo siparişi.
    _siparis(db, "BD-100", 250, "BAYİ DEPO", "IZMIR", depo="-1")
    db.flush()

    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL], kullanici="test"
    )
    assert len(sonuc.planlar) == 2
    assert all(p.doluluk_yuzdesi <= 100 for p in sonuc.planlar)

    satirlar = db.query(SiparisSatiri).filter_by(teslimat_no="BD-100").all()
    assert sum(Decimal(s.miktar) for s in satirlar) == 250
    bekleyen = [s for s in satirlar if s.durum is SiparisDurumu.BEKLEMEDE]
    assert [Decimal(s.miktar) for s in bekleyen] == [Decimal(70)]
    # Bölünen parçalar aynı teslimat ve sipariş numarasını taşır.
    assert len({s.siparis_no for s in satirlar}) == 1


# ------------------------------------------------------------- kamyon / tır ayrımı


def _kamyonlu_musteri(ad, il, tir, kamyon, kamyon_uygun=True):
    """Aynı yükün tır ve kamyon anahtar değerini birlikte taşıyan müşteri."""
    t = replace(
        teslimat(f"{ad}-1", float(tir)),
        kamyon_anahtar=Decimal(str(kamyon)),
        kamyon_olculebilir=kamyon_uygun,
    )
    return replace(
        musteri(ad, il, float(tir), teslimatlar=(t,)),
        kamyon_birim=Decimal(str(kamyon)),
        kamyon_uygun=kamyon_uygun,
    )


def test_yarim_kalan_tir_dolu_bir_kamyondur():
    """Tırın %50'sini dolduran yük kamyonun %93'ünü doldurur; araç kamyona iner.

    Kamyon seçeneği olmadan bu yük "alt limiti dolduramadı" diye beklemede kalırdı.
    """
    yarim = _kamyonlu_musteri("YARIM", "IZMIR", "0.50", "0.93")

    beklemede = planla([yarim], SevkiyatTipi.FTL, IC_FTL)
    assert beklemede.planlar == []

    sonuc = planla([yarim], SevkiyatTipi.FTL, IC_FTL, kamyon_profili=IC_FTL_KAMYON)
    plan = sonuc.planlar[0]
    assert plan.arac_tipi is AracTipi.KAMYON
    assert plan.secili_profil is IC_FTL_KAMYON
    # Doluluk kamyon kapasitesine göre ölçülür, tıra göre değil.
    assert plan.doluluk_yuzdesi == Decimal("93.00")


def test_kamyona_sigmayan_yuk_tirla_gider():
    tam = _kamyonlu_musteri("TAM", "IZMIR", "0.95", "1.77")
    plan = planla(
        [tam], SevkiyatTipi.FTL, IC_FTL, kamyon_profili=IC_FTL_KAMYON
    ).planlar[0]
    assert plan.arac_tipi is AracTipi.TIR
    assert plan.doluluk_yuzdesi == Decimal("95.00")


def test_kamyon_olcusu_olmayan_urun_kamyona_yuklenmez():
    """Bir SKU'nun kamyon yükleme adeti tanımsızsa o yük kamyona verilemez."""
    olcusuz = _kamyonlu_musteri("ÖLÇÜSÜZ", "IZMIR", "0.90", "0", kamyon_uygun=False)
    plan = planla(
        [olcusuz], SevkiyatTipi.FTL, IC_FTL, kamyon_profili=IC_FTL_KAMYON
    ).planlar[0]
    assert plan.arac_tipi is AracTipi.TIR


def test_tir_giremeyen_musteri_tira_binmez():
    """Adrese tır giremiyorsa FTL aracı kesinlikle tır olmaz — esneme yok.

    Tam araç bayinin kapısına gider. Tır giremeyen bir adrese tır planlamak sahada
    boşaltılamayan bir sevkiyattır; hacim yetse de tır kurulamaz.
    """
    giremez = replace(
        _kamyonlu_musteri("TIR GİREMEZ", "IZMIR", "0.95", "0.90"), tir_girisi="H"
    )
    sonuc = planla(
        [giremez], SevkiyatTipi.FTL, IC_FTL, kamyon_profili=IC_FTL_KAMYON,
        kamyon_yukleme_adeti=YUKLEME,
    )
    assert [p.arac_tipi for p in sonuc.planlar] == [AracTipi.KAMYON]


def test_tir_giremeyen_musteri_tir_girenle_ayni_araca_binmez():
    """İki müşteri hacim olarak sığsa bile aynı araca konmaz: araç tıra çıkardı."""
    # İkisi birlikte tam bir tır (0,50 + 0,50); eskiden aynı araca binip tıra
    # çıkıyorlardı. Her biri tek başına da dolu bir kamyondur.
    giremez = replace(
        _kamyonlu_musteri("GİREMEZ", "IZMIR", "0.50", "0.93"), tir_girisi="H"
    )
    girer = replace(_kamyonlu_musteri("GİRER", "IZMIR", "0.50", "0.93"), tir_girisi="E")
    sonuc = planla(
        [giremez, girer], SevkiyatTipi.FTL, IC_FTL, kamyon_profili=IC_FTL_KAMYON,
        kamyon_yukleme_adeti=YUKLEME,
    )
    assert len(sonuc.planlar) == 2
    for plan in sonuc.planlar:
        assert len(plan.musteriler) == 1
        if plan.musteriler[0].tir_girisi == "H":
            assert plan.arac_tipi is AracTipi.KAMYON


def test_tir_giremeyen_musteri_kamyon_olcusu_yoksa_planlanmaz():
    """Kamyon ölçüsü hesaplanamıyorsa tıra bindirmek yerine beklemede kalır.

    Eskiden bu müşteri "kamyona verilemez" diye serbest havuza düşüyor ve tıra
    biniyordu; sahada araç kapıya giremiyordu.
    """
    olcusuz = replace(
        _kamyonlu_musteri("ÖLÇÜSÜZ", "IZMIR", "0.90", "0", kamyon_uygun=False),
        tir_girisi="H",
    )
    sonuc = planla(
        [olcusuz], SevkiyatTipi.FTL, IC_FTL, kamyon_profili=IC_FTL_KAMYON
    )
    assert sonuc.planlar == []
    assert "tır giremiyor" in sonuc.bekleyenler[0].sebep.lower()


def test_tir_giremeyen_musteri_parsiyele_binebilir():
    """Parsiyelde araç bayiye uğramaz, yük aktarma merkezine iner; kural aranmaz."""
    olcusuz = replace(
        _kamyonlu_musteri("ÖLÇÜSÜZ", "IZMIR", "0.55", "0", kamyon_uygun=False),
        tir_girisi="H",
    )
    sonuc = planla(
        [olcusuz], SevkiyatTipi.RUTIN, IC_RUTIN, kamyon_profili=IC_RUTIN_KAMYON
    )
    assert len(sonuc.planlar) == 1


def test_ayni_teslimat_numarasi_iki_bayiye_aitse_ayrilir(db):
    """Kaynak dosyada aynı teslimat numarası iki farklı bayiye ait olabiliyor.

    2025 verisinde 82.258 teslimatın 49'u böyle. Yalnızca numaraya göre gruplayınca
    ikinci bayinin malı birincinin adresine ve aracına biniyordu; tır giremeyen bir
    bayinin malı böyle bir tıra binmişti.
    """
    from app.models import SiparisSatiri

    urun_ekle(db, "U1", palet_ici_adet=1, tir_yukleme_adeti=100)
    _siparis(db, "ORTAK", 50, "BAYİ A", "IZMIR", ilce="BORNOVA")
    _siparis(db, "ORTAK", 40, "BAYİ B", "ISTANBUL", ilce="KADIKOY")
    db.flush()

    musteriler, _ = ic_piyasa_servisi.musterileri_topla(
        db, db.query(SiparisSatiri).all()
    )
    assert len(musteriler) == 2
    assert {m.bayi_adi for m in musteriler} == {"BAYİ A", "BAYİ B"}
    assert all(len(m.teslimatlar) == 1 for m in musteriler)
    assert all(t.teslimat_no == "ORTAK" for m in musteriler for t in m.teslimatlar)


# ------------------------------------------------------------------------ marka


def test_teslimat_numarasi_markayi_belirler():
    """Normal depolarda 006/6 ile başlayan teslimat Vaillant, 2013 DemirDöküm."""
    from app.domain.marka import marka

    assert marka("64", "0060774085", "TÜZÜNLER ENERJİ") == "VAİLLANT"
    assert marka("64", "60774085", "TÜZÜNLER ENERJİ") == "VAİLLANT"
    assert marka("64", "2013552918", "DİMAŞ-DOĞU") == "DEMİRDÖKÜM"
    assert marka("74", "2720818162", "MÜMİN KORKMAZ") == "DEMİRDÖKÜM"


def test_bayi_ortak_deposunda_marka_bayi_adindan_okunur():
    """-1 deposunda teslimat numarası marka taşımaz; P- ile başlayan bayi Vaillant'tır."""
    from app.domain.marka import marka

    assert marka("-1", "278484", "P- Hüner Teknik - Nazik Doğan") == "VAİLLANT"
    assert marka("-1", "278114", "ANKA CORP İNŞAAT") == "DEMİRDÖKÜM"
    # Teslimat numarası orada yanıltıcı olabilir; bayi adı kazanır.
    assert marka("-1", "0060000001", "ANKA CORP İNŞAAT") == "DEMİRDÖKÜM"


def test_depo_soneki_teslimat_numarasini_ezer():
    """Mal zaten o markanın deposundan çıkıyorsa sonek en kesin bilgidir."""
    from app.domain.marka import marka

    assert marka("64-V", "2013552918", "X") == "VAİLLANT"
    assert marka("64-P", "0060774085", "X") == "PROTHERM"


def test_marka_payi_teslimat_numarasindan_hesaplanir(db):
    """Aynı depodan çıkan iki markanın payı plana ayrı ayrı yazılır."""
    urun_ekle(db, "U1", palet_ici_adet=1, tir_yukleme_adeti=100)
    # 64 deposundan yarı yarıya Vaillant (006…) ve DemirDöküm (2013…) yükü.
    _siparis(db, "0060000001", 45, "BAYİ A", "IZMIR")
    _siparis(db, "2013000001", 45, "BAYİ A", "IZMIR")
    db.flush()

    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL], kullanici="test"
    )
    plan = sonuc.planlar[0]
    from app.domain.marka import paylari_coz

    paylar = paylari_coz(plan.marka_paylari_metni)
    assert paylar == {"DEMİRDÖKÜM": Decimal("0.5000"), "VAİLLANT": Decimal("0.5000")}


def test_plan_kamyon_tir_ayrimini_kaydeder(db):
    """Servis katmanı: ürün master datasındaki iki yükleme adeti plana yansımalı."""
    from app.models import SevkiyatPlani

    # Tıra 100, kamyona 54 adet giren ürün: 50 adet tırın yarısı, kamyonun %93'ü.
    urun_ekle(db, "U1", palet_ici_adet=1, tir_yukleme_adeti=100,
              kamyon_yukleme_adeti=54)
    _siparis(db, "T1", 50, "BAYİ A", "IZMIR")

    sonuc = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL], kullanici="test"
    )
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.arac_tipi == "KAMYON"
    assert plan.plan_tipi == "IC_FTL_KAMYON"
    assert plan.ic_arac_adi == "Kamyon"
    # Listelerde "FTL" değil aracın adı yazar.
    assert plan.sevkiyat_tipi_adi == "Kamyon (tam araç)"
    assert db.get(SevkiyatPlani, plan.id).doluluk_yuzdesi > 90


def test_buyuk_siparis_tirla_planlanir(db):
    urun_ekle(db, "U1", palet_ici_adet=1, tir_yukleme_adeti=100,
              kamyon_yukleme_adeti=54)
    _siparis(db, "T1", 95, "BAYİ A", "IZMIR")

    plan = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL], kullanici="test"
    ).planlar[0]
    assert plan.arac_tipi == "TIR"
    assert plan.sevkiyat_tipi_adi == "Tır (tam araç)"


# ------------------------------------------------- yükleme tesisi ve parsiyel depo


def _depolu_musteri(ad, il, birim, depolar, ilce="MERKEZ"):
    """Malı verilen depolara dağılmış müşteri."""
    pay = birim / len(depolar)
    teslimatlar = tuple(
        teslimat(f"{ad}-{sira}", pay, depo=depo)
        for sira, depo in enumerate(depolar, start=1)
    )
    return musteri(ad, il, birim, ilce=ilce, teslimatlar=teslimatlar)


def test_64_ve_bayi_deposu_ayni_araca_yuklenir():
    """64 ile bayi ortak deposu (-1) aynı tesistedir; birlikte yüklenmeleri önceliktir."""
    sonuc = planla(
        [_depolu_musteri("BAYİ", "IZMIR", 0.9, ("64", "-1"))],
        SevkiyatTipi.FTL,
        IC_FTL,
    )
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].yukleme_tesisleri == ["ESKİŞEHİR"]
    assert not sonuc.planlar[0].ortak_yukleme_mi


def test_74_deposu_ayri_sehirde_oldugu_icin_once_kendi_aracina_binmeye_calisir():
    """64 (Eskişehir) ile 74 (Bozüyük) ayrı şehirdir; ikisi de kendi aracını doldurabiliyorsa
    aynı araca konmaz — yoksa depo malı iki şehirden toplamak zorunda kalır."""
    sonuc = planla(
        [
            _depolu_musteri("ESK", "IZMIR", 0.9, ("64",)),
            _depolu_musteri("BOZ", "IZMIR", 0.9, ("74",), ilce="BORNOVA"),
        ],
        SevkiyatTipi.FTL,
        IC_FTL,
    )
    assert len(sonuc.planlar) == 2
    assert all(not p.ortak_yukleme_mi for p in sonuc.planlar)
    assert {p.yukleme_tesisleri[0] for p in sonuc.planlar} == {"ESKİŞEHİR", "BOZÜYÜK"}


def test_tek_tesisten_dolmayan_yukler_ortak_araca_biner():
    """İkinci öncelik: kendi tesisinden araç dolduramayan yükler birleşebilir."""
    sonuc = planla(
        [
            _depolu_musteri("ESK", "IZMIR", 0.45, ("64",)),
            _depolu_musteri("BOZ", "IZMIR", 0.45, ("74",), ilce="BORNOVA"),
        ],
        SevkiyatTipi.FTL,
        IC_FTL,
    )
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.ortak_yukleme_mi
    assert plan.yukleme_tesisleri == ["BOZÜYÜK", "ESKİŞEHİR"]


# --------------------------------------------------------------- parsiyel kuralları


def test_parsiyelde_74_ile_64_ayni_araca_binmez():
    """Parsiyelde 64/-1 birlikte gider; 74 kendi aracıyla gider."""
    sonuc = planla(
        [
            _depolu_musteri("A", "IZMIR", 0.2, ("64", "-1")),
            _depolu_musteri("B", "IZMIR", 0.2, ("74",), ilce="BORNOVA"),
        ],
        SevkiyatTipi.RUTIN,
        IC_RUTIN,
        kalanlari_zorla=True,
    )
    assert len(sonuc.planlar) == 2
    depo_gruplari = [sorted(p.depolar) for p in sonuc.planlar]
    assert ["-1", "64"] in depo_gruplari
    assert ["74"] in depo_gruplari


def test_parsiyel_yalnizca_uc_depodan_yapilir():
    """34, 44 gibi depoların malı parsiyel araca yüklenmez; gerekçesiyle bekler."""
    sonuc = planla(
        [_depolu_musteri("A", "IZMIR", 0.2, ("34",))],
        SevkiyatTipi.RUTIN,
        IC_RUTIN,
        kalanlari_zorla=True,
    )
    assert sonuc.planlar == []
    assert "yalnızca 64, -1 ve 74" in sonuc.bekleyenler[0].sebep


def test_parsiyel_musterisi_depo_grubuna_gore_bolunur():
    """Malı hem 64 hem 74'te olan müşteri iki parsiyel aracına ayrılır."""
    sonuc = planla(
        [_depolu_musteri("A", "IZMIR", 0.4, ("64", "74"))],
        SevkiyatTipi.RUTIN,
        IC_RUTIN,
        kalanlari_zorla=True,
    )
    assert len(sonuc.planlar) == 2
    assert sorted(sorted(p.depolar) for p in sonuc.planlar) == [["64"], ["74"]]


@pytest.mark.parametrize(
    "il,merkez",
    [
        ("KOCAELI", "ISTANBUL"), ("TEKIRDAG", "ISTANBUL"), ("ZONGULDAK", "ISTANBUL"),
        ("IZMIR", "BURSA"), ("ANTALYA", "BURSA"), ("BALIKESIR", "BURSA"),
        ("KONYA", "ANKARA"), ("TRABZON", "ANKARA"), ("GAZIANTEP", "ANKARA"),
    ],
)
def test_parsiyelin_son_noktasi_aktarma_merkezidir(il, merkez):
    """Parsiyel yük müşteriye değil merkeze iner; aracın son noktası merkez ilidir."""
    plan = planla(
        [_depolu_musteri("A", il, 0.5, ("64",))],
        SevkiyatTipi.RUTIN,
        IC_RUTIN,
        kalanlari_zorla=True,
    ).planlar[0]
    assert plan.aktarma_merkezi == merkez
    assert plan.son_ugrak == merkez
    # Aracın tamamı merkeze iniyor.
    assert plan.son_ugrak_orani == Decimal(1)
    # Gerçek varış ili bilgi olarak durur.
    assert plan.iller == [il]


def test_farkli_aktarma_merkezleri_ayni_araca_binmez():
    sonuc = planla(
        [
            _depolu_musteri("EGE", "IZMIR", 0.2, ("64",)),
            _depolu_musteri("DOGU", "TRABZON", 0.2, ("64",)),
        ],
        SevkiyatTipi.RUTIN,
        IC_RUTIN,
        kalanlari_zorla=True,
    )
    assert len(sonuc.planlar) == 2
    assert {p.aktarma_merkezi for p in sonuc.planlar} == {"BURSA", "ANKARA"}


def test_bolunen_teslimatta_aksesuar_ana_urunden_ayrilmaz():
    """Şofben bir araca, bacası başka araca düşmemeli.

    Ürün master datasında header kod boş olduğu için aksesuarı ana ürüne bağlayan
    bir alan yok; bölme oransal yapılarak bağ korunur.
    """
    from app.domain.ic_piyasa import teslimati_bol

    # 600 şofben (palet içi 10, tıra 100) + 600 baca (palet içi 20, tıra 200).
    palet_ici = {"SOFBEN": 10, "BACA": 20}
    yukleme = {"SOFBEN": 100, "BACA": 200}
    t = replace(
        teslimat("BD-MIX", 9, depo="-1", miktar=1200),
        bolunebilir_mi=True,
        sku_miktarlari={"SOFBEN": Decimal(600), "BACA": Decimal(600)},
        sku_kodlari=("BACA", "SOFBEN"),
        satir_miktarlari={1: ("SOFBEN", Decimal(600)), 2: ("BACA", Decimal(600))},
    )

    parcalar = teslimati_bol(t, Decimal(1), SevkiyatTipi.FTL, palet_ici, yukleme)

    assert len(parcalar) > 1
    for parca in parcalar:
        kodlar = {sku for sku, _ in parca.satir_miktarlari.values()}
        assert kodlar == {"SOFBEN", "BACA"}, "aksesuar ana üründen koptu"
    assert sum(p.sku_miktarlari["SOFBEN"] for p in parcalar) == 600
    assert sum(p.sku_miktarlari["BACA"] for p in parcalar) == 600


def test_zikzak_rota_ayni_araca_binmez():
    """Adana, Hatay, Elazığ, Mardin uzaklığa göre sıralandığında araç dolaşıyor.

    Rota 1.530 km, doğrudan Mardin'e gidiş 1.162 km — 368 km sapma. Kural: rota
    doğrudan gidişten en fazla 100 km uzun olabilir.
    """
    musteriler = [
        musteri("A", "ADANA", 0.25),
        musteri("B", "HATAY", 0.25, ilce="ISKENDERUN"),
        musteri("C", "ELAZIG", 0.25, ilce="MERKEZ"),
        musteri("D", "MARDIN", 0.25, ilce="MIDYAT"),
    ]
    sonuc = planla(musteriler, SevkiyatTipi.FTL, IC_FTL, kalanlari_zorla=True)

    assert len(sonuc.planlar) > 1, "hepsi tek araca binmemeli"
    for plan in sonuc.planlar:
        assert plan.sapma_km is None or plan.sapma_km <= 100


def test_ayni_guzergahtaki_duraklar_birlikte_gider():
    """Kayseri ve Van aynı yolun üzerinde: sapma 14 km, tek araca binerler."""
    sonuc = planla(
        [musteri("A", "KAYSERI", 0.5), musteri("B", "VAN", 0.45, ilce="IPEKYOLU")],
        SevkiyatTipi.FTL,
        IC_FTL,
    )
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].durak_sayisi == 2
    assert sonuc.planlar[0].sapma_km <= 100


def test_parsiyelde_rota_sapmasi_aranmaz():
    """Parsiyel araç tek noktaya (aktarma merkezine) gider; zikzak kuralı işlemez."""
    sonuc = planla(
        [
            _depolu_musteri("A", "ADANA", 0.2, ("64",)),
            _depolu_musteri("B", "MARDIN", 0.2, ("64",), ilce="MIDYAT"),
        ],
        SevkiyatTipi.RUTIN,
        IC_RUTIN,
        kalanlari_zorla=True,
    )
    # İkisi de Ankara aktarmasına bağlı; tek araca binerler.
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].aktarma_merkezi == "ANKARA"


def test_kargo_gunde_tek_plandir():
    """10 desi altındaki siparişler için her müşteriye ayrı sefer numarası açılmaz."""
    musteriler = [
        musteri("A", "IZMIR", 0.01, desi=5),
        musteri("B", "TRABZON", 0.01, desi=5, ilce="ORTAHISAR"),
        musteri("C", "ISTANBUL", 0.01, desi=5, ilce="KADIKOY"),
    ]
    sonuc = planla(musteriler, SevkiyatTipi.KARGO, IC_KARGO)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].durak_sayisi == 3
    assert bolge_adi(sonuc.planlar[0].bolge_kodu) == "Günlük kargo listesi"


def test_64_ile_bayi_deposu_arasinda_aktarma_notu_yazilmaz():
    """64 ile -1 aynı lokasyonda; aralarında mal gönderme diye bir şey yok."""
    from app.domain.ic_piyasa import aktarma_notu

    assert aktarma_notu("-1", "64") == ""
    assert aktarma_notu("64", "-1") == ""
    assert aktarma_notu("64-V", "-1") == ""
    # Bozüyük ile Eskişehir arasında not yazılır.
    assert aktarma_notu("74", "64") == "64 depoya gönderilmelidir"
    assert aktarma_notu("64", "74") == "74 depoya gönderilmelidir"
