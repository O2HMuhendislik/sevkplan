from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import Workbook

from app.models import SiparisDurumu, SiparisSatiri, Urun
from app.services import ice_aktarim
from app.services.excel import ExcelHatasi


def kitap(basliklar: list[str], satirlar: list[list]) -> BytesIO:
    calisma_kitabi = Workbook()
    sayfa = calisma_kitabi.active
    sayfa.append(basliklar)
    for satir in satirlar:
        sayfa.append(satir)
    tampon = BytesIO()
    calisma_kitabi.save(tampon)
    tampon.seek(0)
    return tampon


URUN_BASLIK = ["Ürün Kodu", "Ürün Adı", "Ürün Grubu", "Palet İçi Adet", "Header Kod", "Aksesuar mı"]
SIPARIS_BASLIK = [
    "Sipariş No", "Sipariş Satır No", "Teslimat No", "Ürün Kodu",
    "Miktar", "Depo Kodu", "Termin Tarihi",
]


def test_urun_masterdatasi_aktarilir(db):
    dosya = kitap(URUN_BASLIK, [
        ["KMB-24", "Kombi 24 kW", "Kombi", 30, None, "H"],
        ["KMB-AKS", "Kombi Baca Seti", "Kombi", 120, "HDR-KMB", "E"],
    ])
    sonuc = ice_aktarim.urunleri_aktar(db, dosya, "urunler.xlsx")
    assert (sonuc.eklenen, sonuc.hatali) == (2, 0)
    aksesuar = db.query(Urun).filter_by(urun_kodu="KMB-AKS").one()
    assert aksesuar.aksesuar_mi is True
    assert aksesuar.planlama_anahtari == "HDR-KMB"


def test_urun_tekrar_yuklenirse_guncellenir(db):
    ice_aktarim.urunleri_aktar(db, kitap(URUN_BASLIK, [["KMB-24", "Kombi", "Kombi", 30, None, "H"]]), "a.xlsx")
    sonuc = ice_aktarim.urunleri_aktar(
        db, kitap(URUN_BASLIK, [["KMB-24", "Kombi 24 kW ErP", "Kombi", 24, None, "H"]]), "b.xlsx"
    )
    assert (sonuc.eklenen, sonuc.guncellenen) == (0, 1)
    urun = db.query(Urun).one()
    assert urun.palet_ici_adet == 24 and urun.urun_adi == "Kombi 24 kW ErP"


def test_gecersiz_palet_ici_adet_hata_listesine_duser(db):
    sonuc = ice_aktarim.urunleri_aktar(
        db, kitap(URUN_BASLIK, [["KMB-24", "Kombi", "Kombi", 0, None, "H"]]), "a.xlsx"
    )
    assert sonuc.hatali == 1
    assert "sıfırdan büyük" in sonuc.hatalar[0].mesaj


def test_zorunlu_kolon_eksikse_dosya_reddedilir(db):
    with pytest.raises(ExcelHatasi, match="Palet İçi Adet"):
        ice_aktarim.urunleri_aktar(
            db, kitap(["Ürün Kodu", "Ürün Adı", "Ürün Grubu"], [["A", "B", "C"]]), "a.xlsx"
        )


def test_alternatif_kolon_basliklari_kabul_edilir(db):
    # Kaynak sistem "SKU / Malzeme Adı / Paletteki Adet" başlıklarıyla verse de okunur.
    dosya = kitap(
        ["SKU", "Malzeme Adı", "Mal Grubu", "Paletteki Adet"],
        [["KMB-24", "Kombi 24 kW", "Kombi", 30]],
    )
    sonuc = ice_aktarim.urunleri_aktar(db, dosya, "a.xlsx")
    assert sonuc.eklenen == 1


def test_siparisler_aktarilir(db):
    ice_aktarim.urunleri_aktar(db, kitap(URUN_BASLIK, [["KMB-24", "Kombi", "Kombi", 30, None, "H"]]), "u.xlsx")
    dosya = kitap(SIPARIS_BASLIK, [
        ["SIP-1", "10", "TSL-1", "KMB-24", 300, "64", "05.09.2026"],
        ["SIP-1", "20", "TSL-2", "KMB-24", 150, "64", "06.09.2026"],
    ])
    sonuc = ice_aktarim.siparisleri_aktar(db, dosya, "siparis.xlsx")
    assert (sonuc.eklenen, sonuc.hatali) == (2, 0)
    satir = db.query(SiparisSatiri).filter_by(siparis_satir_no="10").one()
    assert satir.durum == SiparisDurumu.BEKLEMEDE
    assert str(satir.termin_tarihi) == "2026-09-05"


def test_cok_urunlu_teslimat_hataliya_duser(db):
    ice_aktarim.urunleri_aktar(db, kitap(URUN_BASLIK, [
        ["KMB-24", "Kombi", "Kombi", 30, None, "H"],
        ["RAD-600", "Radyatör", "Radyatör", 20, None, "H"],
    ]), "u.xlsx")
    dosya = kitap(SIPARIS_BASLIK, [
        ["SIP-1", "10", "TSL-1", "KMB-24", 300, "64", "05.09.2026"],
        ["SIP-1", "20", "TSL-1", "RAD-600", 100, "64", "05.09.2026"],
    ])
    sonuc = ice_aktarim.siparisleri_aktar(db, dosya, "siparis.xlsx")
    assert sonuc.hatali == 1
    assert "birden fazla ürün" in sonuc.hatalar[0].mesaj
    assert all(s.durum == SiparisDurumu.HATALI for s in db.query(SiparisSatiri).all())


def test_header_kodlu_teslimat_cok_urunlu_sayilmaz(db):
    # Ana ürün + aksesuarı aynı teslimatta olabilir: planlama anahtarları aynı.
    ice_aktarim.urunleri_aktar(db, kitap(URUN_BASLIK, [
        ["KMB-24", "Kombi", "Kombi", 30, "HDR-KMB", "H"],
        ["KMB-AKS", "Baca Seti", "Kombi", 120, "HDR-KMB", "E"],
    ]), "u.xlsx")
    dosya = kitap(SIPARIS_BASLIK, [
        ["SIP-1", "10", "TSL-1", "KMB-24", 300, "64", "05.09.2026"],
        ["SIP-1", "20", "TSL-1", "KMB-AKS", 60, "64", "05.09.2026"],
    ])
    sonuc = ice_aktarim.siparisleri_aktar(db, dosya, "siparis.xlsx")
    assert sonuc.hatali == 0
    assert all(s.durum == SiparisDurumu.BEKLEMEDE for s in db.query(SiparisSatiri).all())


def test_ayni_dosya_iki_kez_yuklenirse_mukerrer_kayit_olusmaz(db):
    ice_aktarim.urunleri_aktar(db, kitap(URUN_BASLIK, [["KMB-24", "Kombi", "Kombi", 30, None, "H"]]), "u.xlsx")
    satirlar = [["SIP-1", "10", "TSL-1", "KMB-24", 300, "64", "05.09.2026"]]
    ice_aktarim.siparisleri_aktar(db, kitap(SIPARIS_BASLIK, satirlar), "s.xlsx")
    ikinci = ice_aktarim.siparisleri_aktar(db, kitap(SIPARIS_BASLIK, satirlar), "s.xlsx")
    assert ikinci.eklenen == 0 and ikinci.guncellenen == 1
    assert db.query(SiparisSatiri).count() == 1


def test_planlanmis_satir_yeniden_yuklemeyle_bozulmaz(db):
    from datetime import date
    from app.services import plan_servisi

    ice_aktarim.urunleri_aktar(db, kitap(URUN_BASLIK, [["KMB-24", "Kombi", "Kombi", 10, None, "H"]]), "u.xlsx")
    satirlar = [
        [f"SIP-{i}", "10", f"TSL-{i}", "KMB-24", 50, "64", "05.09.2026"] for i in range(4)
    ]
    ice_aktarim.siparisleri_aktar(db, kitap(SIPARIS_BASLIK, satirlar), "s.xlsx")
    plan_servisi.plan_uret(db, plan_tarihi=date(2026, 8, 31))

    tekrar = ice_aktarim.siparisleri_aktar(db, kitap(SIPARIS_BASLIK, satirlar), "s.xlsx")
    assert tekrar.atlanan == 4
    assert all(s.durum == SiparisDurumu.PLANLANDI for s in db.query(SiparisSatiri).all())


def test_negatif_miktar_reddedilir(db):
    ice_aktarim.urunleri_aktar(db, kitap(URUN_BASLIK, [["KMB-24", "Kombi", "Kombi", 30, None, "H"]]), "u.xlsx")
    sonuc = ice_aktarim.siparisleri_aktar(
        db, kitap(SIPARIS_BASLIK, [["SIP-1", "10", "TSL-1", "KMB-24", -5, "64", "05.09.2026"]]), "s.xlsx"
    )
    assert sonuc.hatali == 1 and "sıfırdan büyük" in sonuc.hatalar[0].mesaj
