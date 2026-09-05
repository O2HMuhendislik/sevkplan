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
    "arac, en, boy, sira_adedi, sira_sayisi",
    [
        # 80x120: eni 245'e üç kez sığar, derinlik 120 -> 1360/120 = 11 sıra
        (TIR, 80, 120, 3, 11),
        # 100x120: çevrilir, 120 eni ikiye sığar, derinlik 100 -> 13 sıra
        (TIR, 100, 120, 2, 13),
        (KAMYON, 80, 120, 3, 5),
        (KAMYON, 100, 120, 2, 7),
    ],
)
def test_paletler_gercek_olculeriyle_zemine_dizilir(arac, en, boy, sira_adedi, sira_sayisi):
    """Her palet master datadaki eni/boyu kadar yer kaplar.

    Palet iki yönde de denenir; aracın enine daha çok sığan yön seçilir. Çizim bir
    zemin planıdır: kapasite kararı anahtar değerindir, burada geometri konuşur.
    """
    urun = tip("P", palet_ici=1, en=en, boy=boy, arac_palet=0)
    hedef = sira_adedi * sira_sayisi
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "BAYİ", "IZMIR"), Decimal(hedef))]), arac
    )

    assert plan.zemin_paleti == hedef
    assert not plan.sigmayanlar
    # Her palet gerçek ölçüsünde; sıradaki paletler yan yana dizilir.
    ilk_sira = [y for y in plan.yerlesimler if y.yukleme_sirasi == 1]
    assert len(ilk_sira) == sira_adedi
    enler = {int(y.genislik) for y in ilk_sira}
    assert len(enler) == 1 and enler.pop() * sira_adedi <= arac.genislik
    assert len({y.y for y in ilk_sira}) == sira_adedi      # farklı konumlarda


def test_zemin_dolunca_kalan_paletler_ustune_konur():
    """Bir sıra fazlası zemine sığmaz; istiflenebiliyorsa üste çıkar."""
    urun = tip("P", palet_ici=1, arac_palet=0)          # 80x120, yükseklik 160
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "BAYİ", "IZMIR"), Decimal(34))]), TIR
    )
    assert plan.zemin_paleti == 33
    # 2 x 160 cm > 270 cm iç yükseklik: istiflenemez.
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


def test_agirlik_dagilimi_on_ve_arka_yariyi_ayirir():
    """Zemine eşit dağılan yükte ağırlık ön ve arka yarıda eşit olur."""
    # 80x120 palet: 3 yan yana, 11 sıra = 33 palet, 1320 cm. Ortadaki 6. sıra
    # (600-720 cm) tam ortada; ilk 5 sıra önde, son 5 sıra arkada kalır.
    urun = tip("P", palet_ici=1, arac_palet=0, agirlik=100)
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(33))]), TIR
    )
    on, arka = plan.agirlik_dagilimi()
    assert on + arka == Decimal(3300)
    assert on > arka          # yük dipten başlar, ön yarı daha dolu


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


def test_ayni_duragin_farkli_urunleri_ayni_sirayi_paylasir():
    """Tek paletlik kalemler sıranın kalanını boş bırakmaz; depo yan yana koyar."""
    a = tip("A", palet_ici=1, arac_palet=0)
    b = tip("B", palet_ici=1, arac_palet=0)
    durak = Durak(1, "BAYİ", "IZMIR")
    plan = istif_planla(
        paletleri_kur([(a, durak, Decimal(1)), (b, durak, Decimal(1))]), TIR
    )
    assert len({y.yukleme_sirasi for y in plan.yerlesimler}) == 1   # tek sıra
    assert {y.yuk.tip.urun_kodu for y in plan.yerlesimler} == {"A", "B"}
    assert len({y.y for y in plan.yerlesimler}) == 2                # yan yana


def test_farkli_duraklar_ayni_sirayi_paylasmaz():
    """Sıra bir bütün olarak iner; dipteki sıraya öndekiler boşaltılmadan ulaşılmaz."""
    urun = tip("P", palet_ici=1, arac_palet=0)
    plan = istif_planla(
        paletleri_kur(
            [
                (urun, Durak(1, "İLK", "BURSA"), Decimal(1)),
                (urun, Durak(2, "SON", "IZMIR"), Decimal(1)),
            ]
        ),
        TIR,
    )
    siralar: dict[int, set[int]] = {}
    for yerlesim in plan.yerlesimler:
        siralar.setdefault(yerlesim.yukleme_sirasi, set()).add(yerlesim.yuk.durak.sira)
    assert all(len(duraklar) == 1 for duraklar in siralar.values())


def test_olcusuz_urun_standart_palet_sayilir():
    """Ölçüsü tanımsız ürün için Euro palet varsayılır; palet yine çizilir."""
    from app.domain.istif import VARSAYILAN_PALET_BOY, VARSAYILAN_PALET_EN

    urun = PaletTipi(
        urun_kodu="X", urun_adi="X", urun_grubu="G", palet_ici_adet=1,
        en=0, boy=0, yukseklik=120, agirlik=Decimal(0), arac_palet_sayisi=0,
    )
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(3))]), TIR
    )
    assert plan.zemin_paleti == 3
    assert all(int(y.genislik) == VARSAYILAN_PALET_EN for y in plan.yerlesimler)
    assert all(int(y.derinlik) == VARSAYILAN_PALET_BOY for y in plan.yerlesimler)


def test_cizim_verisi_ust_kati_ayri_kutu_olarak_verir(db):
    """3B ve yandan görünüş için her palet kendi x/y/z kutusunu alır."""
    from app.services.istif_servisi import cizim_verisi

    urun = PaletTipi(
        urun_kodu="P", urun_adi="P", urun_grubu="G", palet_ici_adet=1,
        en=80, boy=120, yukseklik=120, agirlik=Decimal(0), arac_palet_sayisi=33,
    )
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(35))]), TIR
    )
    cizim = cizim_verisi(plan)

    assert len(cizim["paletler"]) == plan.palet_sayisi == 35
    zemin = [p for p in cizim["paletler"] if p["zeminde"]]
    ustteki = [p for p in cizim["paletler"] if not p["zeminde"]]
    assert len(zemin) == 33 and len(ustteki) == 2
    # Üst kattaki palet tabanının tam üstünde durur.
    assert all(p["cm_z"] == 120 for p in ustteki)
    assert all(p["cm_z"] == 0 for p in zemin)
    # Yandan görünüşte üsttekiler daha yukarıda (SVG'de y küçülür).
    assert min(p["yan_y"] for p in ustteki) < min(p["yan_y"] for p in zemin)


def test_yukleme_sirasi_listesi_dipten_kapiya(db):
    """Ekrandaki liste çizimdeki numaralarla aynı sırayı verir."""
    from app.services.istif_servisi import yukleme_sirasi

    urun = tip("P", palet_ici=10, arac_palet=33)
    plan = istif_planla(
        paletleri_kur(
            [
                (urun, Durak(1, "İLK", "BURSA"), Decimal(30)),
                (urun, Durak(2, "SON", "IZMIR"), Decimal(30)),
            ]
        ),
        TIR,
    )
    liste = yukleme_sirasi(plan)
    assert [k["sira"] for k in liste] == sorted(k["sira"] for k in liste)
    # 1 numara son durağın malı: en dibe konur.
    assert liste[0]["durak"].sira == 2
    assert liste[-1]["durak"].sira == 1


def test_zemin_kaplama_bos_sirayi_sayar():
    """Kullanılan uzunluk ile kaplanan alan farklıdır; eksik sıra boşluk bırakır."""
    urun = tip("P", palet_ici=1, arac_palet=0)          # 80x120 -> 3 yan yana
    plan = istif_planla(
        paletleri_kur([(urun, Durak(1, "B", "IZMIR"), Decimal(1))]), TIR
    )
    # Tek palet bir sıra açar: uzunlukça 120/1360, alanca 80x120 / (1360x245).
    assert plan.kullanilan_uzunluk == Decimal(120)
    assert plan.zemin_doluluk == Decimal("0.0882")
    assert plan.zemin_kaplama == Decimal("0.0288")
