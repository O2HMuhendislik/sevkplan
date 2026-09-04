"""İç piyasa planlama motorunun kuralları.

Ölçek (bkz. conftest.urun_ekle): bir tıra 100 adet, bir palete 10 adet sığar.
Yani 100 adet = tam tır = 10 palet; 30 adet = 3 palet = %30 tır.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

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
    IC_FTL,
    IC_FTL_KAMYON,
    IC_KARGO,
    IC_RUTIN,
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
        ham_anahtar=Decimal(str(birim)),
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
        ham_birim=Decimal(str(birim)),
        desi=Decimal(str(desi)),
        adet=sum((t.miktar for t in teslimatlar), Decimal(0)),
        agirlik=Decimal(0),
        incoterms=incoterms,
        tir_girisi=tir,
    )


# ------------------------------------------------------------------ sevkiyat tipi


def test_exw_musterisi_kargoya_gider():
    """Taşımayı müşteri üstleniyorsa hacmi ne olursa olsun araç planlanmaz."""
    tip, gerekce = tip_belirle(musteri("BÜYÜK BAYİ", "IZMIR", 0.9, incoterms="EXW"))
    assert tip is SevkiyatTipi.KARGO
    assert "EXW" in gerekce


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
    çalıştığını görmek için aynı bölgeden yakın/uzak bir çift seçildi.
    """
    yakin = musteri("YAKIN", "ADANA", 0.9)
    uzak = musteri("UZAK", "VAN", 0.05)
    assert il_bolgesi("ADANA") == il_bolgesi("VAN")

    sonuc = planla([yakin, uzak], SevkiyatTipi.FTL, IC_FTL)

    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].son_ugrak == "ADANA"
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


def test_gunluk_arac_siniri_asilan_hacim_bekler():
    musteriler = [
        musteri(f"BAYİ{sira}", "ISTANBUL", 0.95, ilce=f"ILCE{sira}") for sira in range(5)
    ]
    sonuc = planla(musteriler, SevkiyatTipi.FTL, IC_FTL, gunluk_sinir=2)
    assert len(sonuc.planlar) == 2
    assert len(sonuc.bekleyenler) == 3
    assert "sonraki güne" in sonuc.bekleyenler[0].sebep


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


def test_rutin_olcusu_palete_yuvarlanmaz():
    """Parsiyel araçta paletler karışık istiflenir; kırık palet tam palet sayılmaz."""
    kucuk = musteri("BAYİ", "IZMIR", 0.30, palet=3)
    yuvarlanmis = kucuk.birim
    ham = kucuk.olcu(SevkiyatTipi.RUTIN)
    assert kucuk.olcu(SevkiyatTipi.FTL) == yuvarlanmis
    assert ham == kucuk.ham_birim


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
    # İkisi de 3 paletten büyük olmalı ki FTL kovasına düşsünler.
    _siparis(db, "T1", 60, "BAYİ A", "IZMIR", depo="64")
    _siparis(db, "T2", 40, "BAYİ B", "IZMIR", depo="74", ilce="BORNOVA")
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


def test_gunluk_sinir_daha_once_uretilen_planlari_sayar(ic_veri):
    """Aynı gün ikinci kez çalıştırıldığında sınır sıfırdan başlamaz."""
    db = ic_veri
    kurallar = Kurallar(gunluk_ftl_siniri=1)
    for sira in range(3):
        _siparis(db, f"T{sira}", 95, f"BAYİ {sira}", "IZMIR", ilce=f"ILCE{sira}")
    db.flush()

    ilk = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL],
        kurallar=kurallar, kullanici="test",
    )
    assert len(ilk.planlar) == 1

    ikinci = ic_piyasa_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), tipler=[SevkiyatTipi.FTL],
        kurallar=kurallar, kullanici="test",
    )
    assert ikinci.planlar == []


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
        ham_anahtar=Decimal(miktar) / 100,
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


def test_bolunemeyen_depoda_teslimat_kesilmez():
    """64 ve 74 depolarında teslimat bölünmez; olduğu gibi kalır."""
    from app.domain.ic_piyasa import teslimati_bol

    t = replace(bolunebilir_teslimat("T-1", 1000, [1]), depo_kodu="64", bolunebilir_mi=False)
    assert teslimati_bol(t, Decimal(1), SevkiyatTipi.FTL, PALET_ICI, YUKLEME) == [t]


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
    assert len(sonuc.planlar) == 10
    assert not any(plan.istisna_asim for plan in sonuc.planlar)
    assert all(plan.doluluk_yuzdesi <= 100 for plan in sonuc.planlar)


def test_kesilen_satirin_kalani_ayni_teslimatla_beklemede_kalir(ic_veri):
    """Araca sığmayan miktar aynı teslimat numarasıyla beklemede kalır."""
    from app.models import SiparisDurumu, SiparisSatiri

    db = ic_veri
    # 100 adet = tam tır; 250 adetlik tek satırlık bir bayi depo siparişi.
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
    assert [Decimal(s.miktar) for s in bekleyen] == [Decimal(50)]
    # Bölünen parçalar aynı teslimat ve sipariş numarasını taşır.
    assert len({s.siparis_no for s in satirlar}) == 1


# ------------------------------------------------------------- kamyon / tır ayrımı


def _kamyonlu_musteri(ad, il, tir, kamyon, kamyon_uygun=True):
    """Aynı yükün tır ve kamyon anahtar değerini birlikte taşıyan müşteri."""
    t = replace(
        teslimat(f"{ad}-1", float(tir)),
        kamyon_anahtar=Decimal(str(kamyon)),
        kamyon_ham_anahtar=Decimal(str(kamyon)),
        kamyon_olculebilir=kamyon_uygun,
    )
    return replace(
        musteri(ad, il, float(tir), teslimatlar=(t,)),
        kamyon_birim=Decimal(str(kamyon)),
        kamyon_ham_birim=Decimal(str(kamyon)),
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
