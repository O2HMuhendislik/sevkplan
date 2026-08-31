"""Program güncellendiğinde mevcut veritabanının uyarlanması."""
from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

from app import models


def _motorla(yol, islev, *args):
    """app.db modülünü geçici bir veritabanına yönlendirip çalıştırır."""
    from app import db as db_modulu

    eski = db_modulu.motor
    db_modulu.motor = create_engine(f"sqlite:///{yol}", future=True)
    try:
        return islev(*args)
    finally:
        db_modulu.motor.dispose()
        db_modulu.motor = eski


def test_yeni_kolonlar_otomatik_eklenir(tmp_path):
    from app.db import semayi_olustur

    yol = tmp_path / "eski.db"
    _motorla(yol, semayi_olustur)

    baglanti = sqlite3.connect(yol)
    baglanti.execute("ALTER TABLE sevkiyat_planlari DROP COLUMN alt_limit_esnetildi")
    baglanti.commit()
    baglanti.close()

    _motorla(yol, semayi_olustur)

    motor = create_engine(f"sqlite:///{yol}", future=True)
    kolonlar = {k["name"] for k in inspect(motor).get_columns("sevkiyat_planlari")}
    assert "alt_limit_esnetildi" in kolonlar


def test_uyumsuz_kalinti_kolon_anlasilir_hata_verir(tmp_path):
    from app.db import SemaUyumsuzlugu, semayi_olustur

    yol = tmp_path / "uyumsuz.db"
    _motorla(yol, semayi_olustur)

    baglanti = sqlite3.connect(yol)
    baglanti.execute(
        "ALTER TABLE siparis_satirlari ADD COLUMN eski_alan VARCHAR(10) NOT NULL DEFAULT ''"
    )
    # DEFAULT'u olmayan NOT NULL kalıntı ancak tablo yeniden yazılarak oluşur;
    # burada doğrudan sistem tablosunu düzenleyerek o durumu taklit ediyoruz.
    baglanti.execute("PRAGMA writable_schema=ON")
    baglanti.execute(
        "UPDATE sqlite_master SET sql=REPLACE(sql, \"eski_alan VARCHAR(10) NOT NULL "
        "DEFAULT ''\", 'eski_alan VARCHAR(10) NOT NULL') WHERE name='siparis_satirlari'"
    )
    baglanti.commit()
    baglanti.close()

    with pytest.raises(SemaUyumsuzlugu, match="veritabani_sifirla|uyumlu değil"):
        _motorla(yol, semayi_olustur)


def test_bos_veritabani_sorunsuz_olusur(tmp_path):
    from app.db import semayi_olustur

    yol = tmp_path / "yeni.db"
    _motorla(yol, semayi_olustur)
    motor = create_engine(f"sqlite:///{yol}", future=True)
    tablolar = set(inspect(motor).get_table_names())
    assert {"urunler", "siparis_satirlari", "sevkiyat_planlari"} <= tablolar
    with motor.connect() as baglanti:
        assert baglanti.execute(text("SELECT COUNT(*) FROM urunler")).scalar() == 0
