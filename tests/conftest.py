from __future__ import annotations

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


def urun_ekle(db, urun_kodu, palet_ici_adet=10, header_kod=None, grup="Kombi", aktif=True):
    urun = models.Urun(
        urun_kodu=urun_kodu,
        urun_adi=f"{urun_kodu} ürünü",
        urun_grubu=grup,
        palet_ici_adet=palet_ici_adet,
        header_kod=header_kod,
        aktif=aktif,
    )
    db.add(urun)
    db.flush()
    return urun


def satir_ekle(db, teslimat_no, urun_kodu, miktar, depo_kodu="64", termin=None, siparis_no=None):
    from datetime import date

    sayac = db.query(models.SiparisSatiri).count() + 1
    satir = models.SiparisSatiri(
        siparis_no=siparis_no or f"SIP-{sayac:04d}",
        siparis_satir_no="10",
        teslimat_no=teslimat_no,
        urun_kodu=urun_kodu,
        miktar=miktar,
        depo_kodu=depo_kodu,
        termin_tarihi=termin or date(2026, 9, 1),
    )
    db.add(satir)
    db.flush()
    return satir
