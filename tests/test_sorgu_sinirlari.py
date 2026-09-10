"""Hiçbir sorgu SQLite'ın değişken sınırını aşmamalı.

Sahadaki Windows kurulumunda SQLite `SQLITE_MAX_VARIABLE_NUMBER=999` ile
derlenmiş; geliştirme makinesinde sınır pratikte yok. Bu yüzden "bende çalışıyor"
demek bir şey ifade etmiyordu: 139 bin satırlık bir sipariş dosyası 132 bin
teslimat numarası üretiyor ve tek `IN (...)` sorgusuna konunca kullanıcıda
`too many SQL variables` ile düşüyordu.

Test sınırı taklit etmez — **çalışan her sorgunun** kaç değişken bağladığını
sayar. Böylece hangi SQLite sürümünde çalışırsa çalışsın, sınırı aşan yeni bir
sorgu eklenirse yakalanır.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, select

from app.models import SevkiyatPlani, SiparisDurumu, SiparisSatiri, Urun
from app.domain.kapasite import profil_getir
from app.services import ice_aktarim, plan_servisi, temizleme


SQLITE_DEGISKEN_SINIRI = 999
"""Sahadaki kurulumun gerçek sınırı.

Eşik programın kendi ayarından (`app.db.SORGU_PARCA_BOYU`) **okunmaz**: ayarı
okusaydık ayar bozulduğunda test de onunla birlikte gevşer ve hiçbir şeyi
korumazdı. Burada sabit, dışarıdan dayatılan sınır yazılı.
"""


@pytest.fixture()
def sayac(db):
    """Çalıştırılan sorgulardaki en büyük değişken sayısını kaydeder."""
    kayit = {"en_fazla": 0, "sorgu": ""}

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _olc(_conn, _cursor, ifade, parametreler, *_args):
        adet = len(parametreler) if parametreler else 0
        if isinstance(parametreler, (list, tuple)) and parametreler:
            if isinstance(parametreler[0], (list, tuple)):
                adet = max(len(p) for p in parametreler)  # executemany
        if adet > kayit["en_fazla"]:
            kayit["en_fazla"] = adet
            kayit["sorgu"] = ifade[:200]

    yield kayit


def _cok_teslimatli_veri(db, adet: int = 2500) -> list[str]:
    """Tek bir `IN` sorgusuna sığmayacak kadar çok teslimat üretir."""
    db.add(Urun(urun_kodu="PN1", urun_adi="Panel", urun_grubu="PANEL",
                palet_ici_adet=10, tir_yukleme_adeti=100, desi=Decimal(2)))
    teslimatlar = []
    for sira in range(adet):
        no = f"T{sira:06d}"
        teslimatlar.append(no)
        db.add(SiparisSatiri(
            siparis_no=f"S{sira:06d}", siparis_satir_no="1", teslimat_no=no,
            urun_kodu="PN1", urun_adi="Panel", miktar=Decimal(10), depo_kodu="64",
            sehir="IZMIR", bayi_adi=f"BAYİ {sira}", modul="ROTA",
            durum=SiparisDurumu.BEKLEMEDE,
        ))
    db.commit()
    return teslimatlar


def test_teslimat_dogrulamasi_sinira_takilmaz(db, sayac):
    """İçe aktarımın teslimat doğrulaması binlerce numarayı parçalayarak sormalı."""
    teslimatlar = _cok_teslimatli_veri(db)
    ice_aktarim._teslimatlari_dogrula(db, set(teslimatlar))
    assert sayac["en_fazla"] <= SQLITE_DEGISKEN_SINIRI, (
        f"{sayac['en_fazla']} değişken bağlandı: {sayac['sorgu']}"
    )


def test_mevcut_siparis_satirlari_sinira_takilmaz(db, sayac):
    teslimatlar = _cok_teslimatli_veri(db)
    kayitlar = [{"siparis_no": f"S{sira:06d}"} for sira in range(len(teslimatlar))]
    mevcutlar = ice_aktarim._mevcut_siparis_satirlari(db, kayitlar)
    assert len(mevcutlar) == len(teslimatlar)
    assert sayac["en_fazla"] <= SQLITE_DEGISKEN_SINIRI, (
        f"{sayac['en_fazla']} değişken bağlandı: {sayac['sorgu']}"
    )


def test_plan_uretimi_sinira_takilmaz(db, sayac):
    """Binlerce teslimatla plan üretimi de sınırı aşmamalı."""
    _cok_teslimatli_veri(db)
    satirlar = list(db.scalars(select(SiparisSatiri)).all())
    plan_servisi.teslimatlari_hazirla(
        db, satirlar, profil_getir("RING_ANAHTAR"), "SKU"
    )
    assert sayac["en_fazla"] <= SQLITE_DEGISKEN_SINIRI, (
        f"{sayac['en_fazla']} değişken bağlandı: {sayac['sorgu']}"
    )


def test_plan_silme_sinira_takilmaz(db, sayac):
    """Binlerce plan silinirken `IN` listesi parçalanmalı."""
    for sira in range(2000):
        db.add(SevkiyatPlani(
            sefer_no=f"2601D{sira:05d}", donem="2601", depo_kodu="64",
            planlama_anahtari="PANEL", urun_kodlari="PN1",
            toplam_birim=Decimal(1), doluluk_yuzdesi=Decimal(100),
            plan_tipi="RING_ANAHTAR", plan_tarihi=date(2026, 1, 5),
        ))
    db.commit()
    planlar = list(db.scalars(select(SevkiyatPlani)).all())
    silinen = temizleme._planlari_sil(db, planlar)
    db.commit()
    assert silinen == 2000
    assert db.query(SevkiyatPlani).count() == 0
    assert sayac["en_fazla"] <= SQLITE_DEGISKEN_SINIRI, (
        f"{sayac['en_fazla']} değişken bağlandı: {sayac['sorgu']}"
    )
