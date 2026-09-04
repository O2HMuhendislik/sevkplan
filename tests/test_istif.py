"""Araç içi yerleşim: ters rota sırası, zemin ölçüsü ve palet bölme."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.istif import (
    KAMYON,
    TIR,
    Durak,
    PaletTipi,
    istif_planla,
    paletleri_kur,
)


def tip(kod, palet_ici=16, en=80, boy=120, arac_palet=33, agirlik=0):
    return PaletTipi(
        urun_kodu=kod, urun_adi=f"{kod} ürünü", urun_grubu="PANEL",
        palet_ici_adet=palet_ici, en=en, boy=boy, yukseklik=160,
        agirlik=Decimal(str(agirlik)), arac_palet_sayisi=arac_palet,
    )


@pytest.mark.parametrize(
    "arac, en, boy, sirket_palet",
    [
        (TIR, 80, 120, 33), (TIR, 100, 120, 26),
        (KAMYON, 80, 120, 17), (KAMYON, 100, 120, 14),
    ],
)
def test_arac_zemini_sirketin_palet_sayisini_alir(arac, en, boy, sirket_palet):
    """Zemin, master datadaki 'tır/kamyon palet' sayısı kadar palet almalı.

    Araç ölçüleri tahmin değil: 1360x245 (tır) ve 700x245 (kamyon) zeminler,
    şirketin kendi palet sayılarını birebir veren ölçülerdir.
    """
    urun = tip("P", palet_ici=1, en=en, boy=boy, arac_palet=sirket_palet)
    paletler = paletleri_kur([(urun, Durak(1, "BAYİ", "IZMIR"), Decimal(sirket_palet))])
    plan = istif_planla(paletler, arac)

    assert plan.palet_sayisi == sirket_palet
    assert not plan.sigmayanlar
    # Tam sayıda palet zemini tam doldurur.
    assert plan.zemin_doluluk == Decimal(1)


def test_bir_palet_fazlasi_zemine_sigmaz():
    urun = tip("P", palet_ici=1, arac_palet=33)
    paletler = paletleri_kur([(urun, Durak(1, "BAYİ", "IZMIR"), Decimal(34))])
    plan = istif_planla(paletler, TIR)
    assert plan.palet_sayisi == 33
    assert len(plan.sigmayanlar) == 1


def test_son_durak_dibe_ilk_durak_kapiya_yuklenir():
    """Yükleme ters rota sırasıyla: 3. durak en dipte, 1. durak kapıda."""
    urun = tip("P", palet_ici=10, arac_palet=33)
    yukler = [
        (urun, Durak(1, "İLK", "BURSA"), Decimal(30)),
        (urun, Durak(2, "ORTA", "IZMIR"), Decimal(30)),
        (urun, Durak(3, "SON", "MUGLA"), Decimal(30)),
    ]
    plan = istif_planla(paletleri_kur(yukler), TIR)

    # Dipten kapıya doğru durak sırası tersine ilerler.
    sirali = sorted(plan.yerlesimler, key=lambda y: (y.x, y.y))
    duraklar = []
    for yerlesim in sirali:
        if not duraklar or duraklar[-1] != yerlesim.yuk.durak.sira:
            duraklar.append(yerlesim.yuk.durak.sira)
    assert duraklar == [3, 2, 1]

    # En dipteki palet (x=0) son durağın, en kapıdaki ilk durağın.
    assert sirali[0].yuk.durak.sira == 3
    assert sirali[-1].yuk.durak.sira == 1
    assert sirali[0].yukleme_sirasi == 1


def test_kirik_palet_ayri_palet_olur_ve_isaretlenir():
    urun = tip("P", palet_ici=16, arac_palet=33)
    paletler = paletleri_kur([(urun, Durak(1, "BAYİ", "IZMIR"), Decimal(35))])
    assert len(paletler) == 3                       # 16 + 16 + 3
    assert [int(p.adet) for p in paletler] == [16, 16, 3]
    assert [p.kirik_mi for p in paletler] == [False, False, True]


def test_kirik_palet_kapiya_yakin_kalir():
    """Aynı duraktaki tam paletler önce yüklenir, kırık olan en sona."""
    urun = tip("P", palet_ici=16, arac_palet=33)
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "BAYİ", "IZMIR"), Decimal(35))]), TIR
    )
    sirali = sorted(plan.yerlesimler, key=lambda y: (y.x, y.y))
    assert sirali[-1].yuk.kirik_mi is True


def test_agirlik_kirik_palette_oransal_hesaplanir():
    urun = tip("P", palet_ici=10, arac_palet=33, agirlik=100)   # tam palet 100 kg
    paletler = paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(15))])
    assert [p.agirlik for p in paletler] == [Decimal("100.0"), Decimal("50.0")]


def test_farkli_urunler_ayni_siraya_karismaz():
    """Depo bir sırayı tek ürün olarak topluyor; sırada iki ürün olmamalı."""
    a = tip("A", palet_ici=10, arac_palet=33)
    b = tip("B", palet_ici=10, arac_palet=33)
    durak = Durak(1, "BAYİ", "IZMIR")
    plan = istif_planla(
        paletleri_kur([(a, durak, Decimal(10)), (b, durak, Decimal(10))]), TIR
    )
    siralar: dict[int, set[str]] = {}
    for yerlesim in plan.yerlesimler:
        siralar.setdefault(yerlesim.yukleme_sirasi, set()).add(yerlesim.yuk.tip.urun_kodu)
    assert all(len(kodlar) == 1 for kodlar in siralar.values())


def test_agirlik_dagilimi_on_ve_arka_yariyi_ayirir():
    """Tek sıralı (araç enine bir palet) yükte ağırlık tam ortadan bölünür."""
    urun = tip("P", palet_ici=1, en=240, boy=240, arac_palet=10, agirlik=100)
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(10))]), TIR
    )
    assert plan.palet_sayisi == 10
    on, arka = plan.agirlik_dagilimi()
    assert on == arka == Decimal(500)


def test_olcusu_olmayan_urun_tek_palet_sayilir():
    urun = tip("X", palet_ici=0, en=0, boy=0, arac_palet=0)
    paletler = paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(7))])
    assert len(paletler) == 1
    plan = istif_planla(paletler, TIR)
    assert plan.palet_sayisi == 1


def test_zemine_sigmayan_palet_ustune_istiflenir():
    """Anahtar değeri dolu araçta palet gözü zeminden fazla olur; kalan üste konur."""
    urun = tip("P", palet_ici=1, arac_palet=33, agirlik=50)
    urun = PaletTipi(**{**urun.__dict__, "yukseklik": 120})   # 2 kat sığar (2x120<270)
    paletler = paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(36))])
    plan = istif_planla(paletler, TIR)

    assert plan.zemin_paleti == 33
    assert plan.istiflenen == 3
    assert plan.palet_sayisi == 36
    assert not plan.sigmayanlar
    # Ağırlık üsttekileri de sayar.
    assert plan.toplam_agirlik == Decimal(36 * 50)


def test_yuksek_palet_istiflenemez():
    """İki kat aracın iç yüksekliğini aşıyorsa istif önerilmez."""
    urun = tip("P", palet_ici=1, arac_palet=33)          # yükseklik 160, 2x160 > 270
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(34))]), TIR
    )
    assert plan.istiflenen == 0
    assert len(plan.sigmayanlar) == 1


def test_olcusu_bilinmeyen_palet_istiflenmez():
    """Yüksekliği tanımsız üründe istif önerilmez; bilinmeyen ölçüyle karar verilmez."""
    urun = PaletTipi(
        urun_kodu="X", urun_adi="X", urun_grubu="G", palet_ici_adet=1,
        en=80, boy=120, yukseklik=0, agirlik=Decimal(0), arac_palet_sayisi=33,
    )
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(34))]), TIR
    )
    assert plan.istiflenen == 0
    assert len(plan.sigmayanlar) == 1


def test_ustteki_palet_tabanindan_once_inmeli():
    """Alttaki mal önce inecekse üstündekini indirip tekrar yüklemek gerekir.

    Kural: üstteki paletin durak sırası tabanınkinden küçük ya da eşit olmalı
    (durak 1 ilk inen).
    """
    urun = PaletTipi(
        urun_kodu="P", urun_adi="P", urun_grubu="G", palet_ici_adet=1,
        en=80, boy=120, yukseklik=120, agirlik=Decimal(0), arac_palet_sayisi=33,
    )
    ilk = Durak(1, "İLK", "BURSA")      # önce iner, kapıya yakın
    son = Durak(2, "SON", "IZMIR")      # sonra iner, dipte
    # Zemin son durağın 33 paletiyle dolar; ilk durağın 2 paleti üste çıkar.
    plan = istif_planla(
        paletleri_kur([(urun, son, Decimal(33)), (urun, ilk, Decimal(2))]), TIR
    )
    assert plan.istiflenen == 2
    for yerlesim in plan.yerlesimler:
        for ustteki in yerlesim.ustundekiler:
            assert ustteki.durak.sira <= yerlesim.yuk.durak.sira
