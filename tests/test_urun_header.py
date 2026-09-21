from __future__ import annotations

from app.domain.urun_header import HEADER_ESLESTIRME, header_olculerini_tamamla
from tests.conftest import urun_ekle


def _header_urun(db, kod="HDR-1"):
    """Ölçüsüz bir 'header' ürünü: SAP'in sipariş girişinde kullandığı ikinci kod."""
    return urun_ekle(
        db, kod, palet_ici_adet=None, kamyon_yukleme_adeti=None,
        tir_yukleme_adeti=None,
    )


def test_header_urunun_olcusu_gercek_urunden_kopyalanir(db, monkeypatch):
    header = _header_urun(db, "HDR-1")
    gercek = urun_ekle(
        db, "REAL-1", palet_ici_adet=18, kamyon_yukleme_adeti=234,
        tir_yukleme_adeti=468, agirlik=29,
    )
    monkeypatch.setattr(
        "app.domain.urun_header.HEADER_ESLESTIRME", {"HDR-1": "REAL-1"}
    )

    tamamlananlar = header_olculerini_tamamla({"HDR-1": header, "REAL-1": gercek})

    assert tamamlananlar == [("HDR-1", "REAL-1")]
    assert header.planlanabilir_mi is True
    assert header.tir_yukleme_adeti == 468
    assert header.kamyon_yukleme_adeti == 234
    assert header.agirlik == 29
    # Ad ve kod header'ın kendisinde kalır; ekranda hâlâ kendi adıyla görünür.
    assert header.urun_kodu == "HDR-1"


def test_header_kendi_olcusu_varsa_dokunulmaz(db, monkeypatch):
    """Kullanıcı header'ı elle doldurduysa `_doluyu_yaz` ilkesiyle tutarlı: ezilmez."""
    header = _header_urun(db, "HDR-1")
    header.tir_yukleme_adeti = 999
    gercek = urun_ekle(db, "REAL-1", tir_yukleme_adeti=468)
    monkeypatch.setattr(
        "app.domain.urun_header.HEADER_ESLESTIRME", {"HDR-1": "REAL-1"}
    )

    tamamlananlar = header_olculerini_tamamla({"HDR-1": header, "REAL-1": gercek})

    assert tamamlananlar == []
    assert header.tir_yukleme_adeti == 999


def test_gercek_urun_de_olcusuzse_hicbir_sey_yapilmaz(db, monkeypatch):
    header = _header_urun(db, "HDR-1")
    gercek = _header_urun(db, "REAL-1")
    monkeypatch.setattr(
        "app.domain.urun_header.HEADER_ESLESTIRME", {"HDR-1": "REAL-1"}
    )

    tamamlananlar = header_olculerini_tamamla({"HDR-1": header, "REAL-1": gercek})

    assert tamamlananlar == []
    assert header.planlanabilir_mi is False


def test_esleme_kodu_urun_sozlugunde_yoksa_atlanir(db, monkeypatch):
    header = _header_urun(db, "HDR-1")
    monkeypatch.setattr(
        "app.domain.urun_header.HEADER_ESLESTIRME", {"HDR-1": "YOK-KODU"}
    )

    tamamlananlar = header_olculerini_tamamla({"HDR-1": header})

    assert tamamlananlar == []


def test_gercekte_bos_olan_alan_headera_yazilmaz(db, monkeypatch):
    """Gerçek üründe m3 boşsa header'da da boş kalır; None ile üzerine yazılmaz."""
    header = _header_urun(db, "HDR-1")
    gercek = urun_ekle(db, "REAL-1", tir_yukleme_adeti=468)
    assert gercek.m3 is None
    monkeypatch.setattr(
        "app.domain.urun_header.HEADER_ESLESTIRME", {"HDR-1": "REAL-1"}
    )

    header_olculerini_tamamla({"HDR-1": header, "REAL-1": gercek})

    assert header.m3 is None
    assert header.tir_yukleme_adeti == 468


def test_gomulu_esleme_listesi_kendine_referans_vermiyor():
    """Sahadan gelen liste doğru biçimde kuruldu mu — her header kendinden farklı bir
    ürüne işaret etmeli, boş anahtar/değer olmamalı."""
    assert len(HEADER_ESLESTIRME) >= 31
    for header_kodu, gercek_kodu in HEADER_ESLESTIRME.items():
        assert header_kodu and gercek_kodu
        assert header_kodu != gercek_kodu
    assert len(set(HEADER_ESLESTIRME.values())) == len(HEADER_ESLESTIRME)
