from __future__ import annotations

from app.domain.istanbul import ANADOLU, AVRUPA, yaka


def test_bilinen_ilceler_dogru_yakaya_ayrilir():
    assert yaka("İSTANBUL", "Kadıköy") == ANADOLU
    assert yaka("İSTANBUL", "Beşiktaş") == AVRUPA
    assert yaka("İSTANBUL", "Adalar") == ANADOLU


def test_istanbul_disi_il_hep_none_doner():
    assert yaka("İZMİR", "Kadıköy") is None  # İzmir'de de bir Kadıköy ilçesi var
    assert yaka("KOCAELİ", "Gebze") is None


def test_tanimsiz_ilce_none_doner():
    assert yaka("İSTANBUL", "") is None
    assert yaka("İSTANBUL", None) is None
    assert yaka("İSTANBUL", "Uydurma Mahalle") is None


def test_mahalle_ekli_ilceler_dogru_cozulur():
    """Kaynak veride ilçe mahalleyle birleşmiş ya da il tekrarlanmış geliyor."""
    assert yaka("İSTANBUL", "Ümraniye-Yukarı Dudullu") == ANADOLU
    assert yaka("İSTANBUL", "Kartal / İstanbul") == ANADOLU
    assert yaka("İSTANBUL", "İçerenköy / Ataşehir") == ANADOLU
    assert yaka("İSTANBUL", "Halkalı-Küçükçekmece") == AVRUPA
    assert yaka("İSTANBUL", "Kurtköy-Pendik") == ANADOLU
    assert yaka("İSTANBUL", "Eyüpsultan / İstanbul") == AVRUPA


def test_eski_ve_hatali_yazimlar_taninir():
    assert yaka("İSTANBUL", "Eyüp") == AVRUPA
    assert yaka("İSTANBUL", "Beylükdüzü") == AVRUPA  # doğrusu Beylikdüzü
    assert yaka("İSTANBUL", "4.Levent") == AVRUPA


def test_ambigu_mahalle_hicbir_yakaya_baglanmaz():
    """Gürpınar hem Büyükçekmece'de hem Beykoz'da var; tahmin edilmez."""
    assert yaka("İSTANBUL", "Gürpınar") is None
