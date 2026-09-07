"""Geçmiş sevk planlarının sisteme alınması ve maliyetlenmesi."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.models import PlanDurumu, SevkiyatPlani, SiparisSatiri, Urun
from app.services import gerceklesen_sevk as gs
from app.services import maliyet_servisi as ms

BASLIKLAR = [
    "İsim", "Plaka", "Telefon", "Araç Tipi", "SehIrAdI", "Sipariş No", "Belge No",
    "Depo  Kodu", "StokKodu", "StokAdi", "Adet", "BayiAdi", "AliciFirma",
    "SevkAdresi", "Not", "Tarih", "Not", "Teslimat No", "PLANLAMA TARİHİ",
    "Dağıtım Yapacak Firma", "Desi",
]


def _dosya(satirlar: list[dict]) -> BytesIO:
    """Sahadaki sevk dosyasının kolon yerleşimiyle bir kitap üretir."""
    kitap = Workbook()
    sayfa = kitap.active
    sayfa.append(BASLIKLAR)
    for satir in satirlar:
        hucreler = [None] * len(BASLIKLAR)
        hucreler[3] = satir.get("arac", "TIR")
        hucreler[4] = satir.get("sehir", "IZMIR")
        hucreler[5] = satir.get("siparis", "S1")
        hucreler[6] = satir["belge"]
        hucreler[7] = satir.get("depo", "64")
        hucreler[8] = satir.get("urun", "P1")
        hucreler[9] = satir.get("urun_adi", "Panel")
        hucreler[10] = satir.get("adet", 10)
        hucreler[11] = satir.get("bayi", "EGE ISITMA")
        hucreler[14] = satir.get("ilce", "")
        hucreler[17] = satir.get("teslimat", "T1")
        hucreler[18] = satir.get("plan_tarihi", datetime(2026, 3, 10))
        hucreler[19] = satir.get("nakliyeci", "OMSAN")
        hucreler[20] = satir.get("desi", 100)
        sayfa.append(hucreler)
    tampon = BytesIO()
    kitap.save(tampon)
    tampon.seek(0)
    return tampon


@pytest.fixture()
def tarifeli(db):
    from datetime import date

    from app.models import Depo

    db.add(Urun(urun_kodu="P1", urun_adi="Panel", urun_grubu="PANEL", desi=Decimal(2)))
    db.add(Depo(kod="64", ad="Eskişehir", tesis="ESKİŞEHİR"))
    ms.tarife_kaydet(db, "FTL", "IZMIR", 40000, date(2026, 1, 1),
                     arac_tipi="TIR", cikis_noktasi="ESKİŞEHİR", nakliyeci="OMSAN")
    ms.tarife_kaydet(db, "RUTIN", "IZMIR", 10, date(2026, 1, 1),
                     cikis_noktasi="ESKİŞEHİR", nakliyeci="OMSAN")
    db.commit()
    return db


def test_ring_seferleri_alinmaz(tarifeli):
    """Ring kendi deposundan çıkar; nakliyeciye sefer bedeli ödenmez."""
    db = tarifeli
    ozet = gs.aktar(db, _dosya([
        {"belge": "2603D2001", "sehir": "ESKİŞEHİR"},
        {"belge": "2603S2001"},
    ]))
    db.commit()
    assert ozet.plan == 1
    assert ozet.ring_atlanan == 1
    seferler = {p.sefer_no for p in db.query(SevkiyatPlani).all()}
    assert seferler == {"2603S2001"}


def test_belge_kodu_sevkiyat_tipini_belirler(tarifeli):
    db = tarifeli
    gs.aktar(db, _dosya([
        {"belge": "2603S2001"}, {"belge": "2603R2001"},
        {"belge": "2603K2001"}, {"belge": "2603B2001"},
    ]))
    db.commit()
    tipler = {p.sefer_no: p.sevkiyat_tipi for p in db.query(SevkiyatPlani).all()}
    assert tipler["2603S2001"] == "FTL"
    assert tipler["2603R2001"] == "RUTIN"
    assert tipler["2603K2001"] == "KARGO"
    assert tipler["2603B2001"] == "FTL"   # bayi dağıtım deposu da tam araç


def test_maliyetsiz_hareketler_tarifesi_eksik_sayilmaz(tarifeli):
    """Bedeli olmayan sevk ile fiyatı bilinmeyen sevk ayrı şeylerdir.

    Alıcı vasıtası ve sistemsel hareket için navlun ödenmiyor; bunları "tarife
    yok" diye işaretlemek raporu yanıltırdı.
    """
    db = tarifeli
    gs.aktar(db, _dosya([
        {"belge": "2603A2001", "arac": "ALICI VASITASI", "nakliyeci": "ALICI VASITASI"},
        {"belge": "2603T2001", "arac": "SİSTEMSEL", "nakliyeci": "SİSTEMSEL"},
        {"belge": "2603ST2001", "arac": "STOK AKTARIM", "nakliyeci": "STOK AKTARIM"},
    ]))
    db.commit()
    maliyetler = ms.plan_maliyetleri(db)
    assert len(maliyetler) == 3
    for maliyet in maliyetler:
        assert maliyet.gerceklesen == Decimal("0.00")
        assert not maliyet.eksik_mi, maliyet.plan.sefer_no
        assert maliyet.plan.maliyet_notu


def test_alinan_sefer_tarifeden_maliyetlenir(tarifeli):
    db = tarifeli
    gs.aktar(db, _dosya([
        {"belge": "2603S2001", "sehir": "IZMIR", "adet": 100, "desi": 200},
    ]))
    db.commit()
    maliyet = ms.plan_maliyetleri(db)[0]
    assert maliyet.plan.durum is PlanDurumu.TAMAMLANDI
    assert maliyet.tarife_maliyeti == Decimal("40000.00")
    assert maliyet.cikis_noktasi == "ESKISEHIR"


def test_ayni_dosya_tekrar_yuklenince_maliyet_iki_kez_sayilmaz(tarifeli):
    db = tarifeli
    satirlar = [{"belge": "2603S2001", "teslimat": "T1"},
                {"belge": "2603S2001", "teslimat": "T2", "siparis": "S2"}]
    gs.aktar(db, _dosya(satirlar))
    db.commit()
    ilk = ms.ozet(ms.plan_maliyetleri(db))["gerceklesen"]

    ozet = gs.aktar(db, _dosya(satirlar))
    db.commit()
    assert ozet.guncellenen == 1
    assert db.query(SevkiyatPlani).count() == 1
    assert db.query(SiparisSatiri).count() == 2
    assert ms.ozet(ms.plan_maliyetleri(db))["gerceklesen"] == ilk


def test_bayi_deposu_satirinda_teslimat_anahtari_siparisten_kurulur(tarifeli):
    """-1 deposunda Teslimat No sütunu 'BAYİ DEPO' etiketi taşıyor."""
    db = tarifeli
    gs.aktar(db, _dosya([
        {"belge": "2603S2001", "siparis": "321445", "teslimat": "BAYİ DEPO", "depo": "-1"},
        {"belge": "2603S2002", "siparis": "321446", "teslimat": "BAYİ DEPO", "depo": "-1"},
    ]))
    db.commit()
    anahtarlar = {s.teslimat_no for s in db.query(SiparisSatiri).all()}
    assert anahtarlar == {"321445-BAYI DEPO", "321446-BAYI DEPO"}


def test_bozuk_desi_hucresi_aktarimi_durdurmaz(tarifeli):
    """Kaynak dosyada formül artığı #REF! hücreleri var."""
    db = tarifeli
    ozet = gs.aktar(db, _dosya([
        {"belge": "2603S2001", "desi": "#REF!"},
        {"belge": "2603S2001", "desi": 100, "teslimat": "T2", "siparis": "S2"},
    ]))
    db.commit()
    assert ozet.bozuk_desi == 1
    assert ozet.plan == 1
    assert db.query(SevkiyatPlani).one().toplam_desi == Decimal(100)


def test_arac_tipi_serbest_metinden_cozulur(tarifeli):
    """Alan sahada elle doldurulmuş: 'RUTİN KAMYON', 'FTL KAMYON' gibi."""
    db = tarifeli
    gs.aktar(db, _dosya([
        {"belge": "2603S2001", "arac": "RUTİN KAMYON"},
        {"belge": "2603S2002", "arac": "FTL TIR"},
        {"belge": "2603S2003", "arac": "CEVA"},
    ]))
    db.commit()
    araclar = {p.sefer_no: p.arac_tipi for p in db.query(SevkiyatPlani).all()}
    assert araclar["2603S2001"] == "KAMYON"
    assert araclar["2603S2002"] == "TIR"
    assert araclar["2603S2003"] is None


def test_marka_paylari_depo_kodundan_hesaplanir(tarifeli):
    db = tarifeli
    from app.models import Depo

    db.add(Depo(kod="64-V", ad="Eskişehir Vaillant", tesis="ESKİŞEHİR"))
    db.commit()
    gs.aktar(db, _dosya([
        {"belge": "2603S2001", "depo": "64", "desi": 300, "teslimat": "T1"},
        {"belge": "2603S2001", "depo": "64-V", "desi": 100, "teslimat": "T2",
         "siparis": "S2"},
    ]))
    db.commit()
    plan = db.query(SevkiyatPlani).one()
    paylar = plan.marka_paylari
    assert paylar["DEMİRDÖKÜM"] == Decimal("0.7500")
    assert paylar["VAİLLANT"] == Decimal("0.2500")


def test_nakliyecinin_tarifesi_yoksa_vekil_kullanilir_ve_not_dusulur(tarifeli):
    """Sıfır maliyet yazmaktansa eldeki tarife kullanılır; ama bu görünmeli."""
    db = tarifeli
    gs.aktar(db, _dosya([{"belge": "2603S2001", "nakliyeci": "CEVA"}]))
    db.commit()
    maliyet = ms.plan_maliyetleri(db)[0]
    assert maliyet.tarife_maliyeti == Decimal("40000.00")
    assert maliyet.notlar
    assert "CEVA tarifesi yok" in maliyet.notlar[0]
    assert not maliyet.eksik_mi   # tutar var, eksik değil


def test_bos_dosya_anlasilir_hata_verir(tarifeli):
    with pytest.raises(gs.SevkAktarimHatasi, match="ring dışı sefer bulunamadı"):
        gs.aktar(tarifeli, _dosya([{"belge": "2603D2001"}]))
