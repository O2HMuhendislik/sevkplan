"""Nakliye maliyeti: tarife, dağıtım, kırılım ve bütçe karşılaştırması."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models import (
    ButceSenaryosu,
    MaliyetBirimi,
    PlanDurumu,
    SevkiyatPlani,
    SiparisDurumu,
    SiparisSatiri,
    Urun,
)
from app.services import maliyet_servisi as ms


@pytest.fixture()
def kurulum(db):
    """İzmir'e giden bir FTL ve Manisa/İzmir'e uğrayan bir parsiyel."""
    db.add(Urun(urun_kodu="P1", urun_adi="Panel 600", urun_grubu="PANEL", desi=Decimal(2)))
    db.add(Urun(urun_kodu="P2", urun_adi="Panel 900", urun_grubu="PANEL", desi=Decimal(3)))
    # FTL: İZMİR tır seferi 40.000
    ms.tarife_kaydet(db, "FTL", "IZMIR", 40000, date(2026, 1, 1), arac_tipi="TIR")
    ms.tarife_kaydet(db, "FTL", "IZMIR", 30000, date(2026, 1, 1), arac_tipi="KAMYON")
    # Parsiyel: desi başı İZMİR 12, MANİSA 15
    ms.tarife_kaydet(db, "RUTIN", "IZMIR", 12, date(2026, 1, 1))
    ms.tarife_kaydet(db, "RUTIN", "MANISA", 15, date(2026, 1, 1))
    db.commit()
    return db


def _plan(db, sefer, tip, arac, iller, tarih=date(2026, 3, 10)):
    plan = SevkiyatPlani(
        sefer_no=sefer, donem="2603", depo_kodu="64", planlama_anahtari="PANEL",
        urun_kodlari="P1", toplam_birim=Decimal(1), doluluk_yuzdesi=Decimal(100),
        modul="ROTA", plan_tipi="IC_FTL", plan_tarihi=tarih,
        sevkiyat_tipi=tip, arac_tipi=arac, iller_metni=iller,
        son_ugrak=iller.split(",")[-1].strip(),
    )
    db.add(plan)
    db.flush()
    return plan


def _satir(db, plan, urun, miktar, sehir, bayi, teslimat, siparis="S1"):
    # plan.satirlar'a burada dokunulmaz: oturum expire_on_commit=False ile
    # çalıştığı için koleksiyon bir kez yüklenirse bayatlar ve sonradan eklenen
    # satırlar görünmez olur.
    db.add(SiparisSatiri(
        siparis_no=siparis, siparis_satir_no=teslimat,
        teslimat_no=teslimat, urun_kodu=urun, urun_adi=urun, miktar=Decimal(miktar),
        depo_kodu="64", sehir=sehir, bayi_adi=bayi, modul="ROTA",
        plan_id=plan.id, durum=SiparisDurumu.PLANLANDI,
    ))
    db.flush()


def test_ftl_sefer_bedeli_en_uzak_ilden_okunur(kurulum):
    db = kurulum
    plan = _plan(db, "2603S001", "FTL", "TIR", "MANISA, IZMIR")
    _satir(db, plan, "P1", 100, "MANISA", "EGE ISITMA", "T1")
    _satir(db, plan, "P2", 100, "IZMIR", "IZMIR ISI", "T2")
    db.commit()

    db.expire_all()
    maliyetler = ms.plan_maliyetleri(db)
    assert len(maliyetler) == 1
    maliyet = maliyetler[0]
    # İller yakından uzağa yazılır; sonuncusu (IZMIR) en uzaktır.
    assert maliyet.fiyat_ili == "IZMIR"
    assert maliyet.birim is MaliyetBirimi.SEFER
    assert maliyet.tarife_maliyeti == Decimal("40000.00")
    assert not maliyet.eksikler


def test_ftl_sefer_bedeli_satirlara_desi_payina_gore_dagilir(kurulum):
    db = kurulum
    plan = _plan(db, "2603S002", "FTL", "TIR", "IZMIR")
    _satir(db, plan, "P1", 100, "IZMIR", "A BAYİ", "T1")   # 200 desi
    _satir(db, plan, "P2", 200, "IZMIR", "B BAYİ", "T2")   # 600 desi
    db.commit()

    db.expire_all()
    maliyet = ms.plan_maliyetleri(db)[0]
    paylar = {s.musteri: s.tutar for s in maliyet.satirlar}
    assert paylar["A BAYİ"] == Decimal("10000.00")   # 200/800
    assert paylar["B BAYİ"] == Decimal("30000.00")   # 600/800
    # Parçaların toplamı sefer bedeline eşit olmalı, yoksa kırılım planı tutmaz.
    assert sum(paylar.values()) == maliyet.tarife_maliyeti


def test_parsiyel_her_durak_kendi_ilinin_desi_fiyatiyla_hesaplanir(kurulum):
    db = kurulum
    plan = _plan(db, "2603R001", "RUTIN", "KAMYON", "MANISA, IZMIR")
    _satir(db, plan, "P1", 10, "MANISA", "MANİSA BAYİ", "T1")   # 20 desi × 15
    _satir(db, plan, "P1", 10, "IZMIR", "İZMİR BAYİ", "T2")     # 20 desi × 12
    db.commit()

    db.expire_all()
    maliyet = ms.plan_maliyetleri(db)[0]
    assert maliyet.birim is MaliyetBirimi.DESI
    paylar = {s.musteri: s.tutar for s in maliyet.satirlar}
    assert paylar["MANİSA BAYİ"] == Decimal("300.00")
    assert paylar["İZMİR BAYİ"] == Decimal("240.00")
    assert maliyet.tarife_maliyeti == Decimal("540.00")


def test_tarifesi_olmayan_il_maliyeti_sifir_saymaz_uyarir(kurulum):
    db = kurulum
    plan = _plan(db, "2603S003", "FTL", "TIR", "VAN")
    _satir(db, plan, "P1", 10, "VAN", "VAN BAYİ", "T1")
    db.commit()

    db.expire_all()
    maliyet = ms.plan_maliyetleri(db)[0]
    assert maliyet.eksik_mi
    assert "VAN" in maliyet.eksikler[0]
    assert maliyet.tarife_maliyeti == Decimal("0.00")


def test_plan_tarihinde_gecerli_tarife_kullanilir(kurulum):
    """Tarife yıl içinde yenileniyor; plan kendi tarihinin fiyatıyla maliyetlenir."""
    db = kurulum
    ms.tarife_kaydet(db, "FTL", "IZMIR", 52000, date(2026, 7, 1), arac_tipi="TIR")
    eski = _plan(db, "2603S010", "FTL", "TIR", "IZMIR", tarih=date(2026, 3, 10))
    _satir(db, eski, "P1", 10, "IZMIR", "A", "T1")
    yeni = _plan(db, "2608S011", "FTL", "TIR", "IZMIR", tarih=date(2026, 8, 10))
    _satir(db, yeni, "P1", 10, "IZMIR", "A", "T2")
    db.commit()

    db.expire_all()
    tutarlar = {m.plan.sefer_no: m.tarife_maliyeti for m in ms.plan_maliyetleri(db)}
    assert tutarlar["2603S010"] == Decimal("40000.00")
    assert tutarlar["2608S011"] == Decimal("52000.00")


def test_fatura_girilince_gerceklesen_fatura_olur(kurulum):
    db = kurulum
    plan = _plan(db, "2603S004", "FTL", "TIR", "IZMIR")
    _satir(db, plan, "P1", 10, "IZMIR", "A BAYİ", "T1")
    db.commit()

    ms.fiili_maliyet_kaydet(db, plan.id, "46500", "FTR-2026-1")
    db.commit()

    db.expire_all()
    maliyet = ms.plan_maliyetleri(db)[0]
    assert maliyet.tarife_maliyeti == Decimal("40000.00")
    assert maliyet.gerceklesen == Decimal("46500")
    assert maliyet.fark == Decimal("6500")
    # Kırılım da faturaya göre ölçeklenmeli, yoksa toplamlar tutmaz.
    kirilim = ms.kirilim([maliyet], "MUSTERI")
    assert kirilim[0]["tutar"] == Decimal("46500.00")


def test_ring_plani_maliyete_girmez(kurulum):
    """Ring kendi deposundan çıkar; nakliyeciye sefer bedeli ödenmez."""
    db = kurulum
    plan = _plan(db, "2603D001", "FTL", "TIR", "IZMIR")
    plan.modul = "RING"
    plan.sevkiyat_tipi = None
    _satir(db, plan, "P1", 10, "IZMIR", "A", "T1")
    db.commit()
    db.expire_all()
    assert ms.plan_maliyetleri(db) == []


def test_iptal_plani_maliyete_girmez(kurulum):
    db = kurulum
    plan = _plan(db, "2603S005", "FTL", "TIR", "IZMIR")
    plan.durum = PlanDurumu.IPTAL
    _satir(db, plan, "P1", 10, "IZMIR", "A", "T1")
    db.commit()
    db.expire_all()
    assert ms.plan_maliyetleri(db) == []


def test_kirilim_boyutlari_ayni_toplami_verir(kurulum):
    """Beş kırılım aynı satır maliyetlerinden çıkar; toplamları eşit olmalı."""
    db = kurulum
    plan = _plan(db, "2603S006", "FTL", "TIR", "IZMIR")
    _satir(db, plan, "P1", 100, "IZMIR", "A BAYİ", "T1", siparis="S10")
    _satir(db, plan, "P2", 50, "IZMIR", "B BAYİ", "T2", siparis="S11")
    db.commit()

    db.expire_all()
    maliyetler = ms.plan_maliyetleri(db)
    toplamlar = {
        boyut: sum(s["tutar"] for s in ms.kirilim(maliyetler, boyut))
        for boyut in ms.BOYUTLAR
    }
    assert len(set(toplamlar.values())) == 1
    assert next(iter(toplamlar.values())) == Decimal("40000.00")


def test_ftl_il_kurali_degistirilebilir(kurulum):
    """Sözleşme en uzak il yerine baskın ile göre çalışıyorsa kural değişebilmeli."""
    db = kurulum
    ms.tarife_kaydet(db, "FTL", "MANISA", 25000, date(2026, 1, 1), arac_tipi="TIR")
    plan = _plan(db, "2603S007", "FTL", "TIR", "MANISA, IZMIR")
    _satir(db, plan, "P1", 500, "MANISA", "MANİSA BAYİ", "T1")  # baskın
    _satir(db, plan, "P1", 10, "IZMIR", "İZMİR BAYİ", "T2")
    db.commit()

    db.expire_all()
    assert ms.plan_maliyetleri(db)[0].tarife_maliyeti == Decimal("40000.00")
    ms.ftl_il_kurali_kaydet(db, "BASKIN")
    db.commit()
    db.expire_all()
    maliyet = ms.plan_maliyetleri(db)[0]
    assert maliyet.fiyat_ili == "MANISA"
    assert maliyet.tarife_maliyeti == Decimal("25000.00")


def test_butce_karsilastirmasi_ytd_gelecek_aylari_saymaz(kurulum):
    db = kurulum
    for ay in range(1, 13):
        ms.butce_kaydet(db, 2026, ay, "BUTCE", 100000)
        ms.butce_kaydet(db, 2026, ay, "FC", 110000, surum="FC1")
    plan = _plan(db, "2603S008", "FTL", "TIR", "IZMIR", tarih=date(2026, 3, 5))
    _satir(db, plan, "P1", 10, "IZMIR", "A", "T1")
    db.commit()

    db.expire_all()
    sonuc = ms.butce_karsilastirmasi(db, 2026, "FC1", bugun=date(2026, 5, 20))
    assert sonuc["ytd"]["butce"] == Decimal("500000")     # Ocak–Mayıs
    assert sonuc["ytd"]["fc"] == Decimal("550000")
    assert sonuc["ytd"]["gerceklesen"] == Decimal("40000.00")
    assert sonuc["yillik"]["butce"] == Decimal("1200000")
    mart = sonuc["satirlar"][2]
    assert mart["gerceklesen"] == Decimal("40000.00")
    assert mart["butce_farki"] == Decimal("-60000.00")


def test_ay_toplami_varsa_kirilim_satirlari_iki_kez_sayilmaz(kurulum):
    db = kurulum
    ms.butce_kaydet(db, 2026, 1, "BUTCE", 100000)
    ms.butce_kaydet(db, 2026, 1, "BUTCE", 60000, sevkiyat_tipi="FTL")
    ms.butce_kaydet(db, 2026, 2, "BUTCE", 40000, sevkiyat_tipi="FTL")
    ms.butce_kaydet(db, 2026, 2, "BUTCE", 20000, sevkiyat_tipi="RUTIN")
    db.commit()

    sonuc = ms.butce_karsilastirmasi(db, 2026, bugun=date(2026, 12, 31))
    assert sonuc["satirlar"][0]["butce"] == Decimal("100000")  # toplam kazandı
    assert sonuc["satirlar"][1]["butce"] == Decimal("60000")   # kırılım toplandı


def test_parsiyel_tarifesinde_arac_tipi_tasinmaz(kurulum):
    """Fiyat araca değil desiye bağlı; araç tipi yazılırsa tarife bulunamaz olurdu."""
    db = kurulum
    tarife = ms.tarife_kaydet(db, "KARGO", "BURSA", 9, date(2026, 1, 1), arac_tipi="TIR")
    db.commit()
    assert tarife.arac_tipi is None
    assert tarife.birim is MaliyetBirimi.DESI


def test_ftl_tarifesi_arac_tipi_ister(kurulum):
    with pytest.raises(ms.MaliyetHatasi, match="araç tipi"):
        ms.tarife_kaydet(kurulum, "FTL", "BURSA", 30000, date(2026, 1, 1))


def test_fc_surumsuz_kaydedilemez(kurulum):
    with pytest.raises(ms.MaliyetHatasi, match="sürüm"):
        ms.butce_kaydet(kurulum, 2026, 1, "FC", 100000)
