from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models


@pytest.fixture()
def db() -> Session:
    motor = create_engine("sqlite:///:memory:", future=True)
    models.Temel.metadata.create_all(motor)
    oturum = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)()
    try:
        yield oturum
    finally:
        oturum.close()


def urun_ekle(
    db,
    urun_kodu,
    palet_ici_adet=10,
    grup="KOMBİ",
    header_kod=None,
    kamyon_yukleme_adeti=None,
    tir_yukleme_adeti=100,
    agirlik=None,
    aktif=True,
):
    """Varsayılan ürün: bir tıra 100 adet, bir palete 10 adet sığar.

    Yani tam tır = 100 adet = 10 palet; %10 doluluk = 1 palet. Testlerdeki sayılar
    bu ölçeğe göre okunmalıdır.
    """
    urun = models.Urun(
        urun_kodu=urun_kodu,
        urun_adi=f"{urun_kodu} ürünü",
        urun_grubu=grup,
        palet_ici_adet=palet_ici_adet,
        kamyon_yukleme_adeti=kamyon_yukleme_adeti,
        tir_yukleme_adeti=tir_yukleme_adeti,
        agirlik=Decimal(str(agirlik)) if agirlik is not None else None,
        header_kod=header_kod,
        aktif=aktif,
    )
    db.add(urun)
    db.flush()
    return urun


def satir_ekle(
    db, teslimat_no, urun_kodu, miktar, depo_kodu="64", termin=None, siparis_no=None,
    modul="RING",
):
    sayac = db.query(models.SiparisSatiri).count() + 1
    satir = models.SiparisSatiri(
        siparis_no=siparis_no or f"SIP-{sayac:04d}",
        siparis_satir_no=urun_kodu,
        teslimat_no=teslimat_no,
        urun_kodu=urun_kodu,
        miktar=Decimal(str(miktar)),
        depo_kodu=depo_kodu,
        modul=modul,
        sehir="ESKİŞEHİR",
        bayi_adi="TEST BAYİ",
        # Varsayılan termin uzak bırakılır ki alt limit esnetmesi kendiliğinden
        # devreye girip testleri etkilemesin; esnetme testleri terminini kendi verir.
        termin_tarihi=termin or date(2026, 12, 1),
    )
    db.add(satir)
    db.flush()
    return satir
