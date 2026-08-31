from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.domain.kapasite import RING
from app.domain.planlama import Teslimat, palet_hesapla, planla


def teslimat(no, palet, anahtar="KMB-24", urun=None, gun=1, depo="64"):
    return Teslimat(
        teslimat_no=no,
        depo_kodu=depo,
        planlama_anahtari=anahtar,
        urun_kodu=urun or anahtar,
        urun_adi="Test ürünü",
        miktar=Decimal(palet) * 10,
        birim=Decimal(palet),
        oncelik_tarihi=date(2026, 9, gun),
    )


def test_kirik_palet_tam_palet_sayilir():
    assert palet_hesapla(Decimal(300), 30) == 10       # tam bölünüyor
    assert palet_hesapla(Decimal(301), 30) == 11       # 10,03 -> 11 palet gözü
    assert palet_hesapla(Decimal(1), 30) == 1          # tek adet de bir palet kaplar


def test_tam_dolu_plan_20_palet():
    sonuc = planla([teslimat(f"T{i}", 5) for i in range(4)], RING)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].toplam_birim == 20
    assert sonuc.planlar[0].doluluk_yuzdesi == Decimal("100.00")
    assert not sonuc.bekleyenler


def test_alt_limit_18_altinda_plan_uretilmez():
    # 17 palet: alt limitin altında kaldığı için plan açılmaz.
    sonuc = planla([teslimat("T1", 9), teslimat("T2", 8)], RING)
    assert sonuc.planlar == []
    assert len(sonuc.bekleyenler) == 2
    assert "alt limitini doldurmuyor" in sonuc.bekleyenler[0].sebep


def test_18_palet_gecerli_plandir():
    sonuc = planla([teslimat("T1", 9), teslimat("T2", 9)], RING)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].toplam_birim == 18


def test_teslimat_bolunmez():
    # 12 + 12 palet: ikisi tek plana sığmaz, bölünmek yerine ayrı kalırlar.
    sonuc = planla([teslimat("T1", 12), teslimat("T2", 12)], RING)
    assert sonuc.planlar == []
    assert {b.teslimat.teslimat_no for b in sonuc.bekleyenler} == {"T1", "T2"}


def test_farkli_sku_ayni_plana_girmez():
    teslimatlar = [
        teslimat("A1", 10, anahtar="KMB-24"),
        teslimat("A2", 10, anahtar="KMB-24"),
        teslimat("B1", 10, anahtar="RAD-600"),
        teslimat("B2", 10, anahtar="RAD-600"),
    ]
    sonuc = planla(teslimatlar, RING)
    assert len(sonuc.planlar) == 2
    for plan in sonuc.planlar:
        assert len(set(plan.planlama_anahtari)) >= 1
        assert len({t.planlama_anahtari for t in plan.teslimatlar}) == 1


def test_header_code_ana_urun_ve_aksesuari_ayni_planda():
    # Ana ürün ve aksesuarı farklı SKU ama aynı header code -> aynı planda.
    teslimatlar = [
        teslimat("H1", 10, anahtar="HDR-KMB", urun="KMB-24"),
        teslimat("H2", 10, anahtar="HDR-KMB", urun="KMB-AKS"),
    ]
    sonuc = planla(teslimatlar, RING)
    assert len(sonuc.planlar) == 1
    assert sonuc.planlar[0].urun_kodlari == ["KMB-24", "KMB-AKS"]


def test_ust_limiti_asan_teslimat_kendi_istisna_planina_gider():
    sonuc = planla([teslimat("BUYUK", 26), teslimat("T1", 10), teslimat("T2", 9)], RING)
    istisna = [p for p in sonuc.planlar if p.istisna_asim]
    assert len(istisna) == 1
    assert istisna[0].toplam_birim == 26
    assert len(istisna[0].teslimatlar) == 1
    # Kalan 19 palet normal plan olarak açılır.
    normal = [p for p in sonuc.planlar if not p.istisna_asim]
    assert len(normal) == 1 and normal[0].toplam_birim == 19


def test_farkli_depolar_ayni_plana_girmez():
    teslimatlar = [
        teslimat("D1", 10, depo="64"),
        teslimat("D2", 10, depo="64"),
        teslimat("E1", 10, depo="71"),
        teslimat("E2", 10, depo="71"),
    ]
    sonuc = planla(teslimatlar, RING)
    assert len(sonuc.planlar) == 2
    assert {p.depo_kodu for p in sonuc.planlar} == {"64", "71"}


def test_cok_sayida_teslimat_verimli_paketlenir():
    # 10 x 6 palet = 60 palet -> 3 x 18 palet plan, artan yok.
    sonuc = planla([teslimat(f"T{i:02d}", 6) for i in range(10)], RING)
    toplam_planli = sum(p.toplam_birim for p in sonuc.planlar)
    assert len(sonuc.planlar) == 3
    assert toplam_planli == 54
    assert len(sonuc.bekleyenler) == 1


def test_eski_termin_yeniye_tercih_edilir():
    # Beşinci teslimat plana sığmaz; sığmayanın en yeni tarihli olması beklenir.
    teslimatlar = [teslimat(f"T{i}", 5, gun=10 - i) for i in range(5)]
    sonuc = planla(teslimatlar, RING)
    assert len(sonuc.planlar) == 1
    bekleyen = sonuc.bekleyenler[0].teslimat
    en_yeni = max(teslimatlar, key=lambda t: t.oncelik_tarihi)
    assert bekleyen.teslimat_no == en_yeni.teslimat_no


def test_sifir_paletli_teslimat_reddedilir():
    with pytest.raises(ValueError, match="negatif olamaz"):
        teslimat("T0", 0)
