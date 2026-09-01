"""Planlama motorunun saf iş kuralları.

Ölçek: tam araç = 1.000 anahtar. Testlerde bir teslimatın anahtar değeri doğrudan
verilir; 0.25 anahtar, aracın dörtte biri demektir.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.domain.kapasite import RING_ANAHTAR as RING
from app.domain.planlama import (
    EsnetmeKurali,
    PaletBirimi,
    PaletIsrafi,
    Teslimat,
    palet_hesapla,
    planla,
)


def teslimat(no, anahtar, sku="KMB-24", grup="KOMBİ", miktar=None, depo="64"):
    anahtar = Decimal(str(anahtar))
    miktar = Decimal(str(miktar)) if miktar is not None else anahtar * 100
    return Teslimat(
        teslimat_no=no,
        depo_kodu=depo,
        planlama_anahtari=sku,
        urun_kodu=sku,
        urun_adi=sku,
        miktar=miktar,
        birim=anahtar,
        oncelik_tarihi=date(2026, 12, 1),
        sku_kodlari=(sku,),
        sku_miktarlari={sku: miktar},
        urun_grubu=grup,
        anahtar=anahtar,
    )


def test_kirik_palet_tam_palet_sayilir():
    assert palet_hesapla(Decimal(300), 30) == 10       # tam bölünüyor
    assert palet_hesapla(Decimal(301), 30) == 11       # 10,03 -> 11 palet gözü
    assert palet_hesapla(Decimal(1), 30) == 1          # tek adet de bir palet kaplar


def test_tam_dolu_arac():
    sonuc = planla([teslimat(f"T{i}", "0.25") for i in range(4)], RING)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].toplam_birim == Decimal("1.00")
    assert sonuc.planlar[0].doluluk_yuzdesi == Decimal("100.00")
    assert not sonuc.bekleyenler


def test_alt_limitin_altinda_plan_uretilmez():
    sonuc = planla([teslimat("T1", "0.45"), teslimat("T2", "0.40")], RING)
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 2
    assert "alt limitini doldurmuyor" in sonuc.bekleyenler[0].sebep


def test_alt_limit_tam_tutan_plan_gecerlidir():
    sonuc = planla([teslimat("T1", "0.45"), teslimat("T2", "0.45")], RING)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].toplam_birim == Decimal("0.90")


def test_teslimat_bolunmez():
    # 0,6 + 0,6: ikisi tek araca sığmaz, bölünmek yerine ayrı kalırlar.
    sonuc = planla([teslimat("T1", "0.6"), teslimat("T2", "0.6")], RING)
    assert sonuc.planlar == []
    assert {b.teslimat.teslimat_no for b in sonuc.bekleyenler} == {"T1", "T2"}


def test_farkli_urun_kodlari_faz1de_ayrisir():
    """Faz 1 saf çalışır: her ürün kodu kendi aracını doldurur."""
    teslimatlar = [
        *(teslimat(f"A{i}", "0.5", sku="KMB-24") for i in range(2)),
        *(teslimat(f"B{i}", "0.5", sku="KMB-28") for i in range(2)),
    ]
    sonuc = planla(teslimatlar, RING)
    assert len(sonuc.planlar) == 2
    for plan in sonuc.planlar:
        assert len(plan.urun_kodlari) == 1
        assert not plan.grup_ici_mix


def test_dolmayan_artiklar_ayni_grupta_birlestirilir():
    """Faz 2: tek başına aracı dolduramayan ürün kodları grup içinde birleşir."""
    teslimatlar = [
        teslimat("A1", "0.5", sku="PNL-600", grup="PANEL"),
        teslimat("B1", "0.5", sku="PNL-400", grup="PANEL"),
    ]
    sonuc = planla(teslimatlar, RING)
    assert len(sonuc.planlar) == 1
    plan = sonuc.planlar[0]
    assert plan.urun_kodlari == ["PNL-400", "PNL-600"]
    assert plan.grup_ici_mix is True
    assert plan.planlama_anahtari == "PANEL"


def test_grup_ici_mix_kapatilabilir():
    teslimatlar = [
        teslimat("A1", "0.5", sku="PNL-600", grup="PANEL"),
        teslimat("B1", "0.5", sku="PNL-400", grup="PANEL"),
    ]
    sonuc = planla(teslimatlar, RING, grup_ici_mix=False)
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 2


def test_farkli_gruplar_faz2de_bile_birlesmez():
    teslimatlar = [
        teslimat("A1", "0.5", sku="PNL-600", grup="PANEL"),
        teslimat("B1", "0.5", sku="KMB-24", grup="KOMBİ"),
    ]
    sonuc = planla(teslimatlar, RING)
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 2


def test_saf_plan_kurulabiliyorsa_karisik_plana_gerek_kalmaz():
    """PNL-600 kendi başına aracı dolduruyor; PNL-400 ile karıştırılmamalı."""
    teslimatlar = [
        *(teslimat(f"A{i}", "0.5", sku="PNL-600", grup="PANEL") for i in range(2)),
        teslimat("B1", "0.3", sku="PNL-400", grup="PANEL"),
    ]
    sonuc = planla(teslimatlar, RING)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].urun_kodlari == ["PNL-600"]
    assert [b.teslimat.teslimat_no for b in sonuc.bekleyenler] == ["B1"]


def test_ust_limiti_asan_teslimat_kendi_istisna_planina_gider():
    sonuc = planla(
        [teslimat("BUYUK", "1.3"), teslimat("T1", "0.5"), teslimat("T2", "0.45")], RING
    )
    istisna = [p for p in sonuc.planlar if p.istisna_asim]
    assert len(istisna) == 1
    assert istisna[0].toplam_birim == Decimal("1.3")
    assert len(istisna[0].teslimatlar) == 1
    normal = [p for p in sonuc.planlar if not p.istisna_asim]
    assert len(normal) == 1 and normal[0].toplam_birim == Decimal("0.95")


def test_farkli_depolar_ayni_plana_girmez():
    teslimatlar = [
        *(teslimat(f"D{i}", "0.5", depo="64") for i in range(2)),
        *(teslimat(f"E{i}", "0.5", depo="74") for i in range(2)),
    ]
    sonuc = planla(teslimatlar, RING)
    assert len(sonuc.planlar) == 2
    assert {p.depo_kodu for p in sonuc.planlar} == {"64", "74"}


def test_kalanlari_zorla_alt_limiti_devre_disi_birakir():
    teslimatlar = [teslimat("T1", "0.2"), teslimat("T2", "0.1")]
    assert planla(teslimatlar, RING).planlar == []

    sonuc = planla(teslimatlar, RING, EsnetmeKurali(zorla=True))
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].alt_limit_esnetildi is True
    assert sonuc.bekleyenler == []


def test_zorlamada_asgari_oranin_altindaki_kalinti_beklemede_kalir():
    teslimatlar = [teslimat("T1", "0.05")]
    esnetme = EsnetmeKurali(zorla=True, asgari_oran=Decimal("0.25"))
    sonuc = planla(teslimatlar, RING, esnetme)
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 1


def test_sifir_buyuklukteki_teslimat_reddedilir():
    with pytest.raises(ValueError, match="negatif olamaz"):
        teslimat("T0", "0")


# ----------------------------------------------------------------- tam palet hedefi

def paletli(no, sku, miktar, anahtar, grup="PANEL"):
    return Teslimat(
        teslimat_no=no,
        depo_kodu="64",
        planlama_anahtari=sku,
        urun_kodu=sku,
        urun_adi=sku,
        miktar=Decimal(miktar),
        birim=Decimal(str(anahtar)),
        oncelik_tarihi=date(2026, 12, 1),
        sku_kodlari=(sku,),
        sku_miktarlari={sku: Decimal(miktar)},
        urun_grubu=grup,
        anahtar=Decimal(str(anahtar)),
    )


def test_palet_israfi_kirik_palet_payini_olcer():
    israf = PaletIsrafi({"PNL": 16})
    assert israf([paletli("T1", "PNL", 16, "0.1")]) == 0            # tam palet
    assert israf([paletli("T1", "PNL", 13, "0.1")]) == Decimal("3") / 16
    # 13 + 3 birlikte tam palet olur, israf sıfıra iner.
    assert israf([paletli("T1", "PNL", 13, "0.1"), paletli("T2", "PNL", 3, "0.1")]) == 0


def test_yerlestirme_kirik_paleti_tamamlayan_plani_secer():
    """3 adetlik teslimat, 13 adetliğin yanına giderek paleti tamamlamalı."""
    israf = PaletIsrafi({"PNL": 16})
    # İki ayrı araç oluşur: 13 adetlik (kırık palet) ve 32 adetlik (tam 2 palet).
    # 3 adetlik teslimat ikisine de sığar; kırık paleti tamamladığı için ilkine gitmeli.
    teslimatlar = [
        paletli("T-13", "PNL", 13, "0.60"),
        paletli("T-DOLU", "PNL", 32, "0.55"),
        paletli("T-3", "PNL", 3, "0.30"),
    ]
    sonuc = planla(teslimatlar, RING, israf_hesaplayici=israf)
    hedef = next(
        p for p in sonuc.planlar if any(t.teslimat_no == "T-3" for t in p.teslimatlar)
    )
    assert {t.teslimat_no for t in hedef.teslimatlar} == {"T-13", "T-3"}
    assert hedef.israf == 0


def test_palet_olcusu_plan_bazinda_toplanir():
    hesaplayici = PaletBirimi({"PNL": 16})
    ts = [paletli("T1", "PNL", 13, "0.1"), paletli("T2", "PNL", 3, "0.1")]
    assert hesaplayici(ts) == 1
    assert hesaplayici([ts[0]]) + hesaplayici([ts[1]]) == 2
