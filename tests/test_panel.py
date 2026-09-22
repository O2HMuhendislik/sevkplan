from __future__ import annotations

from dataclasses import dataclass

from app.domain.panel import bonus_haritasi, bonus_uygun_mu, panel_ailesi, panel_uzunlugu


@dataclass
class _Urun:
    urun_adi: str


def test_panel_uzunlugu_taninir():
    assert panel_uzunlugu("22-600 100CMV010_B1A1G1 _13") == "100"
    assert panel_uzunlugu("22-600 120CMV010_B1A1G1 _13") == "120"
    assert panel_uzunlugu("22-600 140CMV010_B1A1G1 _13") is None
    assert panel_uzunlugu("SOFBEN 20 LT") is None
    assert panel_uzunlugu(None) is None


def test_panel_ailesi_uzunluk_haric_ayni_olan_urunleri_esler():
    assert panel_ailesi("22-600 100CMV010_B1A1G1 _13") == panel_ailesi(
        "22-600 120CMV010_B1A1G1 _13"
    )
    assert panel_ailesi("22-500 100CMV010_B1A1G1 _13") != panel_ailesi(
        "22-600 100CMV010_B1A1G1 _13"
    )
    assert panel_ailesi("SOFBEN 20 LT") is None


def test_bonus_haritasi_yalnizca_100_120_panel_skularini_alir():
    urunler = {
        "P100": _Urun("22-600 100CMV010_B1A1G1 _13"),
        "P120": _Urun("22-600 120CMV010_B1A1G1 _13"),
        "P140": _Urun("22-600 140CMV010_B1A1G1 _13"),
        "BACA": _Urun("BACA SETI"),
    }
    harita = bonus_haritasi(urunler)
    assert set(harita) == {"P100", "P120"}
    assert harita["P100"][0] == harita["P120"][0]
    assert harita["P100"][1] == "100"
    assert harita["P120"][1] == "120"


def test_bonus_uygun_mu_saf_100_120_yuklemede_true():
    harita = {"P100": ("AILE_A", "100"), "P120": ("AILE_A", "120")}
    assert bonus_uygun_mu(["P100", "P120"], harita) is True
    assert bonus_uygun_mu(["P100", "P100", "P120"], harita) is True


def test_bonus_uygun_mu_tek_uzunlukta_false():
    harita = {"P100": ("AILE_A", "100"), "P120": ("AILE_A", "120")}
    assert bonus_uygun_mu(["P100"], harita) is False
    assert bonus_uygun_mu(["P120"], harita) is False


def test_bonus_uygun_mu_farkli_aile_karisinca_false():
    harita = {
        "P100": ("AILE_A", "100"),
        "P120": ("AILE_A", "120"),
        "Q120": ("AILE_B", "120"),
    }
    assert bonus_uygun_mu(["P100", "Q120"], harita) is False


def test_bonus_uygun_mu_panel_disi_urun_karisinca_false():
    harita = {"P100": ("AILE_A", "100"), "P120": ("AILE_A", "120")}
    assert bonus_uygun_mu(["P100", "P120", "BACA"], harita) is False


def test_bonus_uygun_mu_bos_kume_false():
    assert bonus_uygun_mu([], {"P100": ("AILE_A", "100")}) is False
