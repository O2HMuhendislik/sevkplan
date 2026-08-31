from __future__ import annotations

from datetime import date

import pytest

from app.domain import sefer_no


def test_donemin_ilk_numarasi_1001_ile_baslar():
    numara = sefer_no.uret(date(2026, 8, 15), "D", None)
    assert str(numara) == "2608D1001"


def test_sayac_bir_artar():
    assert str(sefer_no.uret(date(2026, 8, 15), "D", 1001)) == "2608D1002"


def test_ay_degisince_sayac_sifirlanir():
    # Eylül ayının ilk planı, ağustos 1450'de bitmiş olsa da 1001'den başlar.
    eylul = sefer_no.uret(date(2026, 9, 1), "D", None)
    assert str(eylul) == "2609D1001"


def test_tek_haneli_ay_sifirla_yazilir():
    assert str(sefer_no.uret(date(2026, 1, 5), "D", None)) == "2601D1001"


def test_belge_kodu_plan_tipine_gore_degisir():
    assert str(sefer_no.uret(date(2026, 8, 1), "T", None)) == "2608T1001"


def test_sayac_tukenirse_hata_verir():
    with pytest.raises(ValueError, match="tükendi"):
        sefer_no.uret(date(2026, 8, 1), "D", 9999)


def test_coz_ile_geri_okunur():
    cozulmus = sefer_no.coz("2608D1042")
    assert (cozulmus.yil, cozulmus.ay, cozulmus.belge_kodu, cozulmus.sayac) == (
        2026,
        8,
        "D",
        1042,
    )


@pytest.mark.parametrize("gecersiz", ["2608D104", "26O8D1001", "2613D1001", ""])
def test_gecersiz_numaralar_reddedilir(gecersiz):
    with pytest.raises(ValueError):
        sefer_no.coz(gecersiz)
