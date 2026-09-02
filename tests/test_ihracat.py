"""İhracat planlama motorunun kuralları.

İhracatta araç **tek noktaya** gider ve kapasite iki boyutludur: hacim (desi) ve
ağırlık (kg). Tır 22.000 desi / 22.000 kg, konteyner 15.500 desi / 19.500 kg.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.domain.ihracat import (
    AGIRLIK_KAPASITELERI,
    AracTipi,
    MusteriYuku,
    arac_tipi_coz,
    planla,
)
from app.domain.iller import yer_adi
from app.domain.kapasite import IHRACAT_KONTEYNER, IHRACAT_TIR
from app.domain.planlama import Teslimat


def teslimat(no, desi, agirlik=0, depo="34", satir_id=None):
    return Teslimat(
        teslimat_no=no,
        depo_kodu=depo,
        planlama_anahtari="U1",
        urun_kodu="U1",
        urun_adi="U1",
        miktar=Decimal(10),
        birim=Decimal(str(desi)),
        anahtar=Decimal(str(desi)),
        agirlik=Decimal(str(agirlik)),
        oncelik_tarihi=date(2026, 9, 1),
        satir_idleri=(satir_id or int(no[-1]) if no[-1].isdigit() else 1,),
        depo_katkilari={depo: Decimal(str(desi))},
    )


def yuk(ad, desi, agirlik=0, tip=AracTipi.TIR, teslimatlar=None, azami=None, ulke="ALMANYA"):
    teslimatlar = teslimatlar or (teslimat(f"{ad}-1", desi, agirlik),)
    return MusteriYuku(
        anahtar=ad,
        musteri_adi=ad,
        ulke=ulke,
        ulke_kodu="DE",
        sevk_adresi="BERLIN",
        teslimatlar=tuple(teslimatlar),
        desi=Decimal(str(desi)),
        agirlik=Decimal(str(agirlik)),
        adet=sum((t.miktar for t in teslimatlar), Decimal(0)),
        arac_tipi=tip,
        azami_agirlik=Decimal(str(azami)) if azami else None,
    )


# ------------------------------------------------------------------- araç tipi


def test_konteyner_deniz_tir_kara_yoludur():
    """Taşıma modu araç tipinden çıkar: Şili konteyner (deniz), Romanya tır (kara)."""
    assert AracTipi.KONTEYNER.tasima_modu == "DENİZ"
    assert AracTipi.TIR.tasima_modu == "KARA"
    assert AracTipi.KONTEYNER.deniz_mi
    assert not AracTipi.TIR.deniz_mi


def test_arac_tipi_serbest_metinden_cozulur():
    """Sahada '1X40 DC', '1X40 HC', 'Konteyner' hepsi konteyner demek."""
    assert arac_tipi_coz("1X40 DC") is AracTipi.KONTEYNER
    assert arac_tipi_coz("1X40 HC") is AracTipi.KONTEYNER
    assert arac_tipi_coz("Konteyner") is AracTipi.KONTEYNER
    assert arac_tipi_coz("TIR") is AracTipi.TIR
    assert arac_tipi_coz("PARSİYEL") is AracTipi.PARSIYEL
    assert arac_tipi_coz("DHL") is AracTipi.KARGO
    assert arac_tipi_coz("") is AracTipi.TIR


def test_arac_tipine_gore_kapasite_degisir():
    assert IHRACAT_TIR.ust_limit == Decimal(22000)
    assert IHRACAT_KONTEYNER.ust_limit == Decimal(15500)
    assert AGIRLIK_KAPASITELERI[AracTipi.TIR] == Decimal(22000)
    assert AGIRLIK_KAPASITELERI[AracTipi.KONTEYNER] == Decimal(19500)


# ------------------------------------------------------------------- planlama


def test_her_musteri_kendi_aracina_yuklenir():
    """İhracat aracı tek noktaya gider: iki müşteri aynı araca binmez."""
    sonuc = planla([yuk("A", 20000, 15000), yuk("B", 19000, 14000)])
    assert len(sonuc.planlar) == 2
    assert {p.musteri.musteri_adi for p in sonuc.planlar} == {"A", "B"}


def test_araci_asan_musteri_birden_fazla_araca_bolunur():
    """Teslimat bölünmez; araç sayısını bölünmezlik belirler.

    12.000 desilik üç teslimat ikişer birleşemez (24.000 > 22.000), o yüzden üç araç
    çıkar ve hepsi yarım kalır. Bu kuralın ihlali değil, bölünmezliğin sonucudur —
    alt limit araç başına değil müşteri toplamına uygulanır.
    """
    teslimatlar = tuple(teslimat(f"T{i}", 12000, 8000, satir_id=i) for i in range(3))
    sonuc = planla([yuk("DEV", 36000, 24000, teslimatlar=teslimatlar)])
    assert len(sonuc.planlar) == 3
    assert all(p.desi <= IHRACAT_TIR.ust_limit for p in sonuc.planlar)
    assert sum(len(p.teslimatlar) for p in sonuc.planlar) == 3
    assert not any(p.alt_limit_esnetildi for p in sonuc.planlar)


def test_agirlik_sinira_takilirsa_hacim_dolmadan_arac_kapanir():
    """Ağır ama küçük hacimli yük: aracı ağırlık doldurur, desi değil."""
    teslimatlar = (
        teslimat("T1", 6000, 12000, satir_id=1),
        teslimat("T2", 6000, 12000, satir_id=2),
    )
    sonuc = planla([yuk("AĞIR", 12000, 24000, teslimatlar=teslimatlar)])
    assert len(sonuc.planlar) == 2
    for plan in sonuc.planlar:
        assert plan.agirlik <= Decimal(22000)
        assert plan.kisitlayan == "AĞIRLIK"


def test_musteriye_ozel_azami_tonaj_varsayilanin_onune_gecer():
    """Marka kılavuzundaki azami tonaj araç tipinin varsayılanını ezer."""
    teslimatlar = (
        teslimat("T1", 5000, 10000, satir_id=1),
        teslimat("T2", 5000, 10000, satir_id=2),
    )
    dusuk = yuk("SINIRLI", 10000, 20000, teslimatlar=teslimatlar, azami=19500)
    assert dusuk.agirlik_kapasitesi == Decimal(19500)
    sonuc = planla([dusuk])
    assert len(sonuc.planlar) == 2


def test_alt_limiti_dolduramayan_musteri_beklemede_kalir():
    """Alt limit müşteri toplamına bakar: bu müşteriye bugün araç kaldırmaya değer mi?"""
    sonuc = planla([yuk("KÜÇÜK", 5000, 3000)])
    assert sonuc.planlar == []
    assert "Yeterli hacim yok" in sonuc.bekleyenler[0].sebep
    assert "17000 desi" in sonuc.bekleyenler[0].sebep


def test_kalanlari_zorla_alt_limiti_atlar():
    sonuc = planla([yuk("KÜÇÜK", 5000, 3000)], kalanlari_zorla=True)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].alt_limit_esnetildi


def test_tek_basina_araci_asan_teslimat_istisna_olur():
    buyuk = yuk("DEV", 30000, 10000, teslimatlar=(teslimat("T1", 30000, 10000),))
    sonuc = planla([buyuk])
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].istisna_asim
    assert sonuc.planlar[0].doluluk_yuzdesi > 100


# --------------------------------------------------------------- servis katmanı


@pytest.fixture()
def ihracat_veri(db):
    from app.models import IhracatMusterisi

    db.add(
        IhracatMusterisi(
            anahtar=yer_adi("VAILLANT D.O.O."),
            musteri_adi="VAILLANT D.O.O.",
            ulke="HIRVATİSTAN",
            ulke_kodu="HR",
            arac_tipi="TIR",
            sefer_kodu="N",
            yukleme_tipi="PALET YÜKSELTME",
            aciklama="hava yastığı kullanılacak",
        )
    )
    db.add(
        IhracatMusterisi(
            anahtar=yer_adi("ANSAL REFRIGERACION SA"),
            musteri_adi="ANSAL REFRIGERACION SA",
            ulke="ARJANTİN",
            ulke_kodu="AR",
            arac_tipi="KONTEYNER",
            sefer_kodu="E",
            aciklama="silika jel",
        )
    )
    db.flush()
    return db


def _ihracat_satiri(db, siparis, teslimat_no, musteri, desi, kg, urun="U1", depo="34"):
    from app.models import SiparisSatiri

    satir = SiparisSatiri(
        siparis_no=siparis,
        siparis_satir_no=urun,
        teslimat_no=teslimat_no,
        urun_kodu=urun,
        urun_adi=f"{urun} ürünü",
        miktar=Decimal(10),
        depo_kodu=depo,
        bayi_adi=musteri,
        sehir="HIRVATİSTAN",
        ulke_kodu="HR",
        sevk_adresi="OSIJEK",
        desi=Decimal(str(desi)),
        agirlik=Decimal(str(kg)),
        modul="IHRACAT",
    )
    db.add(satir)
    db.flush()
    return satir


def test_sefer_numarasinin_belge_kodu_musteriden_gelir(ihracat_veri):
    """NSC müşterisi N, Export müşterisi E kodlu sefer alır."""
    from app.services import ihracat_servisi

    db = ihracat_veri
    _ihracat_satiri(db, "S1", "T1", "VAILLANT D.O.O.", 20000, 15000)
    _ihracat_satiri(db, "S2", "T2", "ANSAL REFRIGERACION SA", 14000, 12000, urun="U2")

    sonuc = ihracat_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), kullanici="test"
    )
    kodlar = {p.musteri_adi: p.sefer_no[4] for p in sonuc.planlar}
    assert kodlar["VAILLANT D.O.O."] == "N"
    assert kodlar["ANSAL REFRIGERACION SA"] == "E"


def test_musteri_master_datasi_arac_ve_notu_belirler(ihracat_veri):
    from app.services import ihracat_servisi

    db = ihracat_veri
    _ihracat_satiri(db, "S1", "T1", "ANSAL REFRIGERACION SA", 14000, 12000)

    sonuc = ihracat_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), kullanici="test"
    )
    plan = sonuc.planlar[0]
    assert plan.arac_tipi == "KONTEYNER"
    assert plan.tasima_modu == "DENİZ"
    assert plan.musteri_aciklamasi == "silika jel"
    assert plan.modul == "IHRACAT"
    # Konteyner kapasitesi tırdan küçüktür.
    assert plan.profil.ust_limit == Decimal(15500)


def test_master_datada_olmayan_musteri_tir_varsayilir(ihracat_veri):
    from app.services import ihracat_servisi

    db = ihracat_veri
    _ihracat_satiri(db, "S9", "T9", "YENİ MÜŞTERİ LTD", 20000, 15000)

    sonuc = ihracat_servisi.plan_uret(
        db, plan_tarihi=date(2026, 9, 1), kullanici="test"
    )
    assert "YENİ MÜŞTERİ LTD" in sonuc.tanimsiz_musteriler
    assert sonuc.planlar[0].arac_tipi == "TIR"
    assert "master datada yok" in sonuc.ozet()


def test_ihracat_formu_musteri_notunu_ve_arac_bloklarini_yazar(ihracat_veri, tmp_path):
    from openpyxl import load_workbook

    from app.services import ihracat_servisi, ihracat_yukleme_formu, plan_servisi

    db = ihracat_veri
    _ihracat_satiri(db, "S1", "T1", "VAILLANT D.O.O.", 20000, 15000)
    sonuc = ihracat_servisi.plan_uret(db, plan_tarihi=date(2026, 9, 1))
    plan = sonuc.planlar[0]
    plan_servisi.axata_no_gir(db, plan, "2735", "test")
    ihracat_servisi.arac_bilgisi_kaydet(
        db, plan, "OMSAN", "34 ABC 12", "MSCU1234567", "MÜHÜR-9", "Ali", "test"
    )

    hedef = ihracat_yukleme_formu.form_uret(plan, tmp_path / "form.xlsx")
    sayfa = load_workbook(hedef)["EXPORT"]
    metinler = [h.value for satir in sayfa.iter_rows() for h in satir if h.value]

    assert plan.sefer_no in metinler
    assert "hava yastığı kullanılacak" in metinler
    assert "DORSE/KONTEYNER NO" in metinler
    assert "MSCU1234567" in metinler
    assert "MÜHÜR NO" in metinler
    assert "PALET YÜKSELTME" in metinler
    assert "34-DEPO AXATA" in metinler
