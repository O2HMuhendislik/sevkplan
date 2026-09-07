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


# ------------------------------------------------------------- marka ayrımı
@pytest.fixture()
def marka_kurulumu(kurulum):
    """Karma araç: yarısı Vaillant (64-V), yarısı DemirDöküm (64) deposundan."""
    db = kurulum
    plan = _plan(db, "2603S100", "FTL", "TIR", "IZMIR")
    _satir(db, plan, "P1", 100, "IZMIR", "A BAYİ", "T1")          # 200 desi · DEMİRDÖKÜM
    db.query(SiparisSatiri).filter_by(teslimat_no="T1").one().depo_kodu = "64"
    _satir(db, plan, "P1", 300, "IZMIR", "B BAYİ", "T2")          # 600 desi · VAİLLANT
    db.query(SiparisSatiri).filter_by(teslimat_no="T2").one().depo_kodu = "64-V"
    db.commit()
    db.expire_all()
    return db


def test_marka_maliyeti_desi_payina_gore_bolunur(marka_kurulumu):
    """Karma araçta navlun markalara taşınan yer payına göre dağılır."""
    db = marka_kurulumu
    ozet = {s["marka"]: s["tutar"] for s in ms.marka_ozeti(ms.plan_maliyetleri(db))}
    assert ozet["DEMİRDÖKÜM"] == Decimal("10000.00")   # 200/800 × 40.000
    assert ozet["VAİLLANT"] == Decimal("30000.00")     # 600/800
    assert sum(ozet.values()) == Decimal("40000.00")


def test_markaya_indirgeme_yalnizca_o_markanin_satirlarini_birakir(marka_kurulumu):
    db = marka_kurulumu
    tumu = ms.plan_maliyetleri(db)
    vaillant = ms.markaya_indirge(tumu, "VAİLLANT")
    assert len(vaillant) == 1
    assert {s.musteri for s in vaillant[0].satirlar} == {"B BAYİ"}
    assert vaillant[0].gerceklesen == Decimal("30000.00")
    # Markaların toplamı bütünü vermeli.
    toplam = sum(
        (m.gerceklesen for marka in ("DEMİRDÖKÜM", "VAİLLANT")
         for m in ms.markaya_indirge(tumu, marka)),
        Decimal(0),
    )
    assert toplam == tumu[0].gerceklesen


def test_marka_kirilimi_ekranda_ayni_toplami_verir(marka_kurulumu):
    db = marka_kurulumu
    satirlar = ms.kirilim(ms.plan_maliyetleri(db), "MARKA")
    assert {s["anahtar"] for s in satirlar} == {"DEMİRDÖKÜM", "VAİLLANT"}
    assert sum(s["tutar"] for s in satirlar) == Decimal("40000.00")


def test_butce_marka_bazinda_okunur(marka_kurulumu):
    db = marka_kurulumu
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 12000, marka="DEMİRDÖKÜM")
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 25000, marka="VAİLLANT")
    db.commit()

    hepsi = ms.butce_karsilastirmasi(db, 2026, bugun=date(2026, 3, 31))
    # Marka toplamı girilmediyse markaların satırları toplanır.
    assert hepsi["satirlar"][2]["butce"] == Decimal("37000")
    assert hepsi["satirlar"][2]["gerceklesen"] == Decimal("40000.00")

    vaillant = ms.butce_karsilastirmasi(
        db, 2026, bugun=date(2026, 3, 31), marka="VAİLLANT"
    )
    assert vaillant["satirlar"][2]["butce"] == Decimal("25000")
    assert vaillant["satirlar"][2]["gerceklesen"] == Decimal("30000.00")


def test_marka_toplami_girilirse_kirilimi_ezer(marka_kurulumu):
    """İki kırılım boyutunda da kural aynı: boş bırakılan satır toplamdır."""
    db = marka_kurulumu
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 12000, marka="DEMİRDÖKÜM")
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 25000, marka="VAİLLANT")
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 35000)   # ay toplamı
    db.commit()
    sonuc = ms.butce_karsilastirmasi(db, 2026, bugun=date(2026, 3, 31))
    assert sonuc["satirlar"][2]["butce"] == Decimal("35000")


# --------------------------------------------------------- sapma açıklaması
def test_sapma_bilesenleri_farkin_tamamini_acikliyor(kurulum):
    """Hacim + birim maliyet + fatura farkı, sapmanın tamamına eşit olmalı."""
    db = kurulum
    plan = _plan(db, "2603S200", "FTL", "TIR", "IZMIR")
    _satir(db, plan, "P1", 100, "IZMIR", "A BAYİ", "T1")   # 200 desi
    db.commit()
    ms.fiili_maliyet_kaydet(db, plan.id, "43000")          # tarife 40.000
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 36000, desi=180)
    db.commit()
    db.expire_all()

    sonuc = ms.butce_karsilastirmasi(db, 2026, bugun=date(2026, 3, 31))
    aciklama = sonuc["satirlar"][2]["aciklama"]
    assert aciklama["fark"] == Decimal("7000.00")          # 43.000 − 36.000
    assert aciklama["aciklanan"] == aciklama["fark"]

    adlar = {b["ad"]: b["tutar"] for b in aciklama["bilesenler"]}
    # 20 desi fazla × 200 TL/desi bütçe birimi = 4.000
    assert adlar["Hacim etkisi"] == Decimal("4000.00")
    assert adlar["Fatura farkı"] == Decimal("3000.00")
    assert adlar["Birim maliyet etkisi"] == Decimal("0.00")


def test_butcelenen_desi_yoksa_sapma_tek_parca_kalir(kurulum):
    db = kurulum
    plan = _plan(db, "2603S201", "FTL", "TIR", "IZMIR")
    _satir(db, plan, "P1", 100, "IZMIR", "A BAYİ", "T1")
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 36000)
    db.commit()
    db.expire_all()

    aciklama = ms.butce_karsilastirmasi(
        db, 2026, bugun=date(2026, 3, 31)
    )["satirlar"][2]["aciklama"]
    adlar = [b["ad"] for b in aciklama["bilesenler"]]
    assert adlar == ["Tarife maliyeti sapması"]
    assert aciklama["aciklanan"] == aciklama["fark"]
    assert "desi" in aciklama["bilesenler"][0]["aciklama"]


def test_sapma_katkilari_nereye_gittigini_gosterir(kurulum):
    db = kurulum
    plan = _plan(db, "2603S202", "FTL", "TIR", "IZMIR")
    _satir(db, plan, "P1", 100, "IZMIR", "A BAYİ", "T1")
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 36000)
    db.commit()
    db.expire_all()

    aciklama = ms.butce_karsilastirmasi(
        db, 2026, bugun=date(2026, 3, 31)
    )["satirlar"][2]["aciklama"]
    assert aciklama["katkilar"]["Sevkiyat tipi"][0]["ad"] == "FTL"
    assert aciklama["katkilar"]["İl"][0]["ad"] == "IZMIR"
    assert aciklama["katkilar"]["Marka"][0]["ad"] == "DEMİRDÖKÜM"


def test_eksik_tarife_sapma_aciklamasinda_uyari_cikarir(kurulum):
    """Tarifesi eksik plan gerçekleşeni düşük gösterir; sapma yanıltıcı olur."""
    db = kurulum
    plan = _plan(db, "2603S203", "FTL", "TIR", "VAN")
    _satir(db, plan, "P1", 100, "VAN", "VAN BAYİ", "T1")
    ms.butce_kaydet(db, 2026, 3, "BUTCE", 36000)
    db.commit()
    db.expire_all()

    aciklama = ms.butce_karsilastirmasi(
        db, 2026, bugun=date(2026, 3, 31)
    )["satirlar"][2]["aciklama"]
    assert any("tarifesi eksik" in u for u in aciklama["uyarilar"])
    # Tarifesi olmasa da hacim görünmeli: satırlar sıfır tutarla üretiliyor.
    assert aciklama["desi"] == Decimal("200.000")


def test_marka_ozeti_ile_marka_kirilimi_ayni_sayiyi_verir(marka_kurulumu):
    """İki ekran aynı satır maliyetlerinden hesaplar; kuruşu kuruşuna tutmalı."""
    db = marka_kurulumu
    maliyetler = ms.plan_maliyetleri(db)
    ozetten = {s["marka"]: s["tutar"] for s in ms.marka_ozeti(maliyetler)}
    kirilimdan = {s["anahtar"]: s["tutar"] for s in ms.kirilim(maliyetler, "MARKA")}
    assert ozetten == kirilimdan


def test_faturali_karma_aracta_marka_toplami_faturayi_tutar(marka_kurulumu):
    db = marka_kurulumu
    plan = db.query(SevkiyatPlani).filter_by(sefer_no="2603S100").one()
    ms.fiili_maliyet_kaydet(db, plan.id, "44000")
    db.commit()
    db.expire_all()
    ozetten = ms.marka_ozeti(ms.plan_maliyetleri(db))
    assert sum(s["tutar"] for s in ozetten) == Decimal("44000.00")


def test_marka_gorunumunde_ust_metrik_ile_kirilim_kurusu_kurusuna_tutar(marka_kurulumu):
    """Ekranın üst metriği, marka özeti ve kırılım aynı sayıyı göstermeli.

    Üçü ayrı yoldan hesaplansaydı yuvarlama yüzünden birkaç kuruş ayrışır ve
    "toplamlar birbirini tutar" iddiası çökerdi.
    """
    db = marka_kurulumu
    plan = db.query(SevkiyatPlani).filter_by(sefer_no="2603S100").one()
    ms.fiili_maliyet_kaydet(db, plan.id, "43333.33")
    db.commit()
    db.expire_all()

    tumu = ms.plan_maliyetleri(db)
    for marka in ("DEMİRDÖKÜM", "VAİLLANT"):
        indirgenmis = ms.markaya_indirge(tumu, marka)
        ust_metrik = ms.ozet(indirgenmis)["gerceklesen"]
        marka_ozetinden = next(
            s["tutar"] for s in ms.marka_ozeti(tumu) if s["marka"] == marka
        )
        kirilimdan = sum(s["tutar"] for s in ms.kirilim(indirgenmis, "MUSTERI"))
        assert ust_metrik == marka_ozetinden == kirilimdan, marka
