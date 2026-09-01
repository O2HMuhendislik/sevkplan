"""Veri temizleme kuralları."""
from __future__ import annotations

from datetime import date

from app.models import PlanDurumu, SevkiyatPlani, SiparisDurumu, SiparisSatiri, Urun
from app.services import plan_servisi, temizleme
from tests.conftest import satir_ekle, urun_ekle


def _plan_kur(db, depo="64", onek="TSL"):
    urun_ekle(db, "KMB-24") if not db.query(Urun).count() else None
    for i in range(4):
        satir_ekle(db, f"{onek}-{i}", "KMB-24", 25, depo_kodu=depo, siparis_no=f"S{onek}{i}")
    return plan_servisi.plan_uret(
        db, plan_tarihi=date(2026, 8, 31), depo_kodu=depo
    ).planlar[0]


def test_bekleyen_siparisleri_sil_plani_bozmaz(db):
    plan = _plan_kur(db)
    satir_ekle(db, "BEKLEYEN-1", "KMB-24", 5, siparis_no="SB1")
    satir_ekle(db, "BEKLEYEN-2", "KMB-24", 5, siparis_no="SB2")

    sonuc = temizleme.bekleyen_siparisleri_sil(db)
    assert sonuc.siparis == 2
    assert db.query(SevkiyatPlani).count() == 1
    assert db.query(SiparisSatiri).count() == 4
    assert all(s.plan_id == plan.id for s in db.query(SiparisSatiri).all())


def test_hatali_satirlar_da_silinir(db):
    satir_ekle(db, "TSL-X", "TANIMSIZ", 10)
    plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31), depo_kodu="64")
    assert db.query(SiparisSatiri).one().durum == SiparisDurumu.HATALI

    assert temizleme.bekleyen_siparisleri_sil(db).siparis == 1
    assert db.query(SiparisSatiri).count() == 0


def test_plan_silinince_siparisler_beklemeye_doner(db):
    _plan_kur(db)
    sonuc = temizleme.planlari_sil(db)
    assert sonuc.plan == 1 and sonuc.siparis == 0
    assert db.query(SevkiyatPlani).count() == 0
    satirlar = db.query(SiparisSatiri).all()
    assert len(satirlar) == 4
    assert all(s.durum == SiparisDurumu.BEKLEMEDE and s.plan_id is None for s in satirlar)


def test_plan_silerken_siparisler_de_silinebilir(db):
    _plan_kur(db)
    sonuc = temizleme.planlari_sil(db, siparisleri_de_sil=True)
    assert sonuc.plan == 1 and sonuc.siparis == 4
    assert db.query(SiparisSatiri).count() == 0


def test_tamamlanmis_planlar_varsayilan_olarak_korunur(db):
    plan = _plan_kur(db)
    plan_servisi.axata_no_gir(db, plan, "AX-1")
    plan_servisi.plan_tamamla(db, plan)

    assert temizleme.planlari_sil(db).plan == 0
    assert db.query(SevkiyatPlani).count() == 1

    assert temizleme.planlari_sil(db, tamamlananlar_dahil=True).plan == 1
    assert db.query(SevkiyatPlani).count() == 0


def test_tarih_araligi_disindaki_planlar_kalir(db):
    _plan_kur(db, onek="A")
    sonuc = temizleme.planlari_sil(db, baslangic=date(2026, 9, 1))
    assert sonuc.plan == 0
    assert db.query(SevkiyatPlani).count() == 1


def test_siparis_ve_planlari_sil_urunlere_dokunmaz(db):
    _plan_kur(db)
    sonuc = temizleme.siparis_ve_planlari_sil(db)
    assert sonuc.plan == 1 and sonuc.siparis == 4
    assert db.query(SiparisSatiri).count() == 0
    assert db.query(SevkiyatPlani).count() == 0
    assert db.query(Urun).count() == 1


def test_sayac_sifirlanirsa_numara_bastan_baslar(db):
    _plan_kur(db)
    temizleme.siparis_ve_planlari_sil(db, sayaci_sifirla=True)
    yeni = _plan_kur(db, onek="B")
    assert yeni.sefer_no == "2608D1001"


def test_sayac_sifirlanmazsa_numara_kaldigi_yerden_devam_eder(db):
    _plan_kur(db)
    temizleme.siparis_ve_planlari_sil(db)
    yeni = _plan_kur(db, onek="B")
    assert yeni.sefer_no == "2608D1002"


def test_her_seyi_sil_bos_sistem_birakir(db):
    _plan_kur(db)
    sonuc = temizleme.her_seyi_sil(db)
    assert sonuc.urun == 1 and sonuc.plan == 1
    assert db.query(Urun).count() == 0
    assert db.query(SiparisSatiri).count() == 0
    assert db.query(SevkiyatPlani).count() == 0


def test_sayimlar_ekrandaki_degerleri_verir(db):
    _plan_kur(db)
    satir_ekle(db, "BEKLEYEN", "KMB-24", 5, siparis_no="SB")
    sayim = temizleme.sayimlar(db)
    assert sayim["urun"] == 1
    assert sayim["siparis"] == 5
    assert sayim["bekleyen"] == 1
    assert sayim["plan"] == 1
    assert sayim["tamamlanan_plan"] == 0
