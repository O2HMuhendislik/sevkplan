from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models import PlanDurumu, SiparisDurumu
from app.services import plan_servisi
from app.services.plan_servisi import PlanHatasi
from tests.conftest import satir_ekle, urun_ekle


def test_plan_uretimi_sefer_numarasi_atar(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=10)
    for i in range(4):
        satir_ekle(db, f"TSL-{i}", "KMB-24", Decimal(25))  # 5'er palet
    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))

    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.sefer_no == "2608D1001"
    assert plan.durum == PlanDurumu.TASLAK
    assert plan.teslimat_sayisi == 4
    assert all(s.durum == SiparisDurumu.PLANLANDI for s in plan.satirlar)


def test_ardisik_planlar_sayaci_ilerletir(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=10)
    for i in range(8):
        satir_ekle(db, f"TSL-{i}", "KMB-24", Decimal(25))
    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))
    assert sorted(p.sefer_no for p in sonuc.planlar) == ["2608D1001", "2608D1002"]

    # Sonraki ay sayaç sıfırlanır.
    for i in range(4):
        satir_ekle(db, f"EYL-{i}", "KMB-24", Decimal(25))
    eylul = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 9, 2))
    assert eylul.planlar[0].sefer_no == "2609D1001"


def test_sadece_secilen_depo_planlanir(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=10)
    for i in range(4):
        satir_ekle(db, f"TSL-{i}", "KMB-24", Decimal(25), depo_kodu="64")
    for i in range(4):
        satir_ekle(db, f"TIR-{i}", "KMB-24", Decimal(25), depo_kodu="71")
    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))
    assert len(sonuc.planlar) == 1
    assert {s.teslimat_no for s in sonuc.planlar[0].satirlar} == {
        "TSL-0", "TSL-1", "TSL-2", "TSL-3"
    }


def test_masterdatasi_olmayan_urun_hataliya_dusar(db):
    satir_ekle(db, "TSL-X", "TANIMSIZ", Decimal(50))
    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))
    assert sonuc.planlar == []
    assert sonuc.hatali_teslimatlar[0][0] == "TSL-X"
    from app.models import SiparisSatiri

    satir = db.query(SiparisSatiri).one()
    assert satir.durum == SiparisDurumu.HATALI
    assert "master datada tanımlı değil" in satir.hata_aciklamasi


def test_header_code_ana_urun_ve_aksesuar_ayni_planda(db):
    """Header kodlu ana ürün ve aksesuarı aynı teslimatta gelir, birlikte planlanır."""
    urun_ekle(db, "KMB-24", palet_ici_adet=10, tir_yukleme_adeti=100, header_kod="HDR-1")
    urun_ekle(
        db, "KMB-AKS", palet_ici_adet=100, tir_yukleme_adeti=1000,
        header_kod="HDR-1", grup="AKSESUAR",
    )
    satir_ekle(db, "TSL-1", "KMB-24", Decimal(50), siparis_no="S1")   # 0,50 anahtar
    satir_ekle(db, "TSL-1", "KMB-AKS", Decimal(100), siparis_no="S2")  # 0,10 anahtar
    satir_ekle(db, "TSL-2", "KMB-24", Decimal(40), siparis_no="S3")   # 0,40 anahtar

    sonuc = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.toplam_birim == 1
    assert plan.planlama_anahtari == "HDR-1"
    assert "KMB-AKS" in plan.urun_kodlari


def test_axata_numarasi_olmadan_mail_gonderilemez(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=10)
    for i in range(4):
        satir_ekle(db, f"TSL-{i}", "KMB-24", Decimal(25))
    plan = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31)).planlar[0]

    with pytest.raises(PlanHatasi, match="Axata"):
        plan_servisi.mail_gonderildi_isaretle(db, plan)

    plan_servisi.axata_no_gir(db, plan, "AX-99001")
    assert plan.durum == PlanDurumu.AXATA_BEKLIYOR
    plan_servisi.mail_gonderildi_isaretle(db, plan)
    assert plan.durum == PlanDurumu.MAIL_GONDERILDI
    assert plan.mail_gonderim_tarihi is not None


def test_iptal_edilen_planin_siparisleri_beklemeye_doner(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=10)
    for i in range(4):
        satir_ekle(db, f"TSL-{i}", "KMB-24", Decimal(25))
    plan = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31)).planlar[0]
    plan_servisi.plan_iptal(db, plan, "Depo talebiyle iptal")

    assert plan.durum == PlanDurumu.IPTAL
    from app.models import SiparisSatiri

    assert all(
        s.durum == SiparisDurumu.BEKLEMEDE for s in db.query(SiparisSatiri).all()
    )

    # İptal edilen numara geri kullanılmaz: yeni plan 1002 alır.
    yeni = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))
    assert yeni.planlar[0].sefer_no == "2608D1002"


def test_tamamlanan_plan_siparisleri_tamamlandi_yapar(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=10)
    for i in range(4):
        satir_ekle(db, f"TSL-{i}", "KMB-24", Decimal(25))
    plan = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31)).planlar[0]
    plan_servisi.axata_no_gir(db, plan, "AX-1")
    plan_servisi.mail_gonderildi_isaretle(db, plan)
    plan_servisi.plan_tamamla(db, plan)
    assert plan.durum == PlanDurumu.TAMAMLANDI
    assert all(s.durum == SiparisDurumu.TAMAMLANDI for s in plan.satirlar)


def test_mix_plan_manuel_olusturulur(db):
    """Farklı ürün grupları yalnızca elle seçilerek tek plana konabilir."""
    urun_ekle(db, "KMB-24", palet_ici_adet=10, grup="KOMBİ")
    urun_ekle(db, "PNL-600", palet_ici_adet=10, grup="PANEL")
    satir_ekle(db, "M1", "KMB-24", Decimal(50), siparis_no="S1")    # 5 palet -> 0,50
    satir_ekle(db, "M2", "PNL-600", Decimal(40), siparis_no="S2")   # 4 palet -> 0,40

    # Otomatik motor farklı grupları birleştirmez.
    otomatik = plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))
    assert otomatik.planlar == []

    plan = plan_servisi.mix_plan_olustur(db, ["M1", "M2"], plan_tarihi=date(2026, 8, 31))
    assert plan.mix_mi is True
    assert plan.toplam_birim == Decimal("0.90")
    assert plan.urun_kodlari == "KMB-24, PNL-600"


def test_mix_plan_ust_limiti_asamaz(db):
    urun_ekle(db, "KMB-24", palet_ici_adet=10, grup="KOMBİ")
    urun_ekle(db, "PNL-600", palet_ici_adet=10, grup="PANEL")
    satir_ekle(db, "M1", "KMB-24", Decimal(80), siparis_no="S1")
    satir_ekle(db, "M2", "PNL-600", Decimal(80), siparis_no="S2")
    with pytest.raises(PlanHatasi, match="üst limit"):
        plan_servisi.mix_plan_olustur(db, ["M1", "M2"], plan_tarihi=date(2026, 8, 31))
