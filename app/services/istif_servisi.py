"""Kaydedilmiş bir plandan araç içi yerleşim (istif) planı üretir.

Ekranın gördüğü veri buradan çıkar: hangi palet aracın neresinde, hangi sırayla
yüklenecek, ağırlık dengesi nasıl. Kurallar `app/domain/istif.py` içindedir; bu
katman yalnızca veritabanı kayıtlarını oraya taşır.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.istif import (
    Durak,
    IstifPlani,
    PaletTipi,
    arac_olcusu,
    istif_planla,
    paletleri_kur,
)
from app.models import SevkiyatPlani, Urun

VARSAYILAN_PALET_ICI = 1
"""Palet içi adedi tanımsız ürün tek palet sayılır; çizimde 'ölçüsü yok' işaretlenir."""


def _palet_tipi(urun: Urun | None, urun_kodu: str, urun_adi: str, arac_tipi: str) -> PaletTipi:
    kamyon = (arac_tipi or "").strip().upper() == "KAMYON"
    arac_palet = 0
    if urun is not None:
        arac_palet = int((urun.kamyon_palet if kamyon else urun.tir_palet) or 0)
    return PaletTipi(
        urun_kodu=urun_kodu,
        urun_adi=(urun.urun_adi if urun else "") or urun_adi or urun_kodu,
        urun_grubu=(urun.urun_grubu if urun else "") or "TANIMSIZ",
        palet_ici_adet=int(urun.palet_ici_adet or 0) if urun else 0,
        en=int(urun.palet_en or 0) if urun else 0,
        boy=int(urun.palet_boy or 0) if urun else 0,
        yukseklik=int(urun.palet_yukseklik or 0) if urun else 0,
        agirlik=(
            Decimal(urun.agirlik) * Decimal(urun.palet_ici_adet or 1)
            if urun is not None and urun.agirlik
            else Decimal(0)
        ),
        arac_palet_sayisi=arac_palet,
    )


def _durak_cozucu(db: Session, plan: SevkiyatPlani):
    """Sipariş satırını durağına bağlayan işlevi döner.

    Durak sırası plan detayındaki rota sırasının **aynısıdır**; iki ekran farklı sıra
    gösterirse depo hangi malı önce yükleyeceğini bilemez. Ring ve ihracat planları
    tek noktaya gittiği için hepsi 1. duraktır.
    """
    if not plan.ic_piyasa_mi:
        tek = Durak(sira=1, ad=plan.musteri_adi or plan.bolge_adi or "Araç", il="")
        return lambda satir: tek

    from app.services.ic_piyasa_servisi import _durak_anahtari, plan_musterileri

    duraklar = {
        k["anahtar"]: Durak(
            sira=k["sira"], ad=k["bayi_adi"], il=k["il"], ilce=k["ilce"]
        )
        for k in plan_musterileri(db, plan)
    }
    # plan_musterileri ile aynı anahtar kullanılır; eşleşmeyen satır olursa (ilçesi
    # sonradan değişmiş kayıt gibi) tek bir "bilinmeyen" durağa düşer, kaybolmaz.
    bilinmeyen = Durak(sira=len(duraklar) + 1, ad="(durak eşleşmedi)", il="")
    return lambda satir: duraklar.get(_durak_anahtari(satir), bilinmeyen)


def istif_plani(db: Session, plan: SevkiyatPlani) -> IstifPlani:
    """Planın araç içi yerleşimini kurar."""
    arac = arac_olcusu(plan.arac_tipi or ("KAMYON" if plan.ic_arac_adi == "Kamyon" else ""))

    kodlar = {s.urun_kodu for s in plan.satirlar}
    urunler = {
        u.urun_kodu: u
        for u in db.scalars(select(Urun).where(Urun.urun_kodu.in_(kodlar))).all()
    }
    durak_bul = _durak_cozucu(db, plan)

    tipler: dict[str, PaletTipi] = {}
    durak_haritasi: dict[int, Durak] = {}
    # Aynı ürünün aynı duraktaki satırları önce toplanır: iki teslimat da olsa depo
    # tek palet yapar, iki kırık palet değil.
    birlestirilmis: dict[tuple[str, int], Decimal] = {}
    for satir in plan.satirlar:
        tip = tipler.get(satir.urun_kodu)
        if tip is None:
            tip = _palet_tipi(
                urunler.get(satir.urun_kodu),
                satir.urun_kodu,
                satir.gosterilecek_urun_adi,
                plan.arac_tipi or "",
            )
            tipler[satir.urun_kodu] = tip
        durak = durak_bul(satir)
        durak_haritasi[durak.sira] = durak
        anahtar = (satir.urun_kodu, durak.sira)
        birlestirilmis[anahtar] = birlestirilmis.get(anahtar, Decimal(0)) + Decimal(
            satir.miktar
        )

    yukler = [
        (tipler[urun_kodu], durak_haritasi[durak_sira], miktar)
        for (urun_kodu, durak_sira), miktar in birlestirilmis.items()
    ]
    return istif_planla(paletleri_kur(yukler), arac)


def durak_ozeti(istif: IstifPlani) -> list[dict]:
    """Durak bazında yükleme özeti; ekrandaki lejant ve tablo bunu kullanır."""
    gruplar: dict[int, dict] = {}
    for yerlesim in istif.yerlesimler:
        durak = yerlesim.yuk.durak
        kayit = gruplar.setdefault(
            durak.sira,
            {
                "sira": durak.sira,
                "ad": durak.ad,
                "il": durak.il,
                "ilce": durak.ilce,
                "palet": 0,
                "adet": Decimal(0),
                "agirlik": Decimal(0),
                "urunler": {},
                "ilk_yukleme": yerlesim.yukleme_sirasi,
                "son_yukleme": yerlesim.yukleme_sirasi,
            },
        )
        kayit["palet"] += 1
        kayit["adet"] += yerlesim.yuk.adet
        kayit["agirlik"] += yerlesim.yuk.agirlik
        kayit["urunler"][yerlesim.yuk.tip.urun_kodu] = (
            kayit["urunler"].get(yerlesim.yuk.tip.urun_kodu, Decimal(0))
            + yerlesim.yuk.adet
        )
        kayit["ilk_yukleme"] = min(kayit["ilk_yukleme"], yerlesim.yukleme_sirasi)
        kayit["son_yukleme"] = max(kayit["son_yukleme"], yerlesim.yukleme_sirasi)

    # Üste istiflenen paletler kendi duraklarına yazılır; sıraları tabanlarınınkidir.
    for yerlesim in istif.yerlesimler:
        for ustteki in yerlesim.ustundekiler:
            durak = ustteki.durak
            kayit = gruplar.setdefault(
                durak.sira,
                {
                    "sira": durak.sira, "ad": durak.ad, "il": durak.il,
                    "ilce": durak.ilce, "palet": 0, "adet": Decimal(0),
                    "agirlik": Decimal(0), "urunler": {},
                    "ilk_yukleme": yerlesim.yukleme_sirasi,
                    "son_yukleme": yerlesim.yukleme_sirasi,
                },
            )
            kayit["palet"] += 1
            kayit["istif"] = kayit.get("istif", 0) + 1
            kayit["adet"] += ustteki.adet
            kayit["agirlik"] += ustteki.agirlik
            kayit["urunler"][ustteki.tip.urun_kodu] = (
                kayit["urunler"].get(ustteki.tip.urun_kodu, Decimal(0)) + ustteki.adet
            )
    for kayit in gruplar.values():
        kayit.setdefault("istif", 0)
    return sorted(gruplar.values(), key=lambda k: k["sira"])


DURAK_RENKLERI = (
    "#00887D",  # 01 Vaillant Group Green
    "#2A507C",  # 07 Dark Blue
    "#85225E",  # 04 Purple
    "#0087C0",  # 03 Light Blue
    "#85796B",  # 05 Beige
    "#4f9c95",  # yeşil %80
    "#a69c90",  # bej %70
    "#9b9b9b",  # 02 Grey
)
"""Durak renkleri — Vaillant Group kartelası (bkz. app/static/style.css).

Sarı kartelada var ama beyaz yazı üzerinde okunmadığı için dizide yok; palet
etiketleri beyaz basılıyor.
"""


def durak_rengi(sira: int) -> str:
    return DURAK_RENKLERI[(sira - 1) % len(DURAK_RENKLERI)]


def cizim_verisi(istif: IstifPlani, olcek: float = 0.9) -> dict:
    """Üç görünüşün de kullandığı tek koordinat kümesi.

    Paletler santimetre cinsinden yerleştirilir; çizime çevirmeyi burası yapar,
    şablonda hesap kalmaz. Her palet üç eksende ölçülür:

    * **x** — kabinden kapıya (araç uzunluğu). 0 = en dip, önce yüklenen.
    * **y** — sol duvardan sağa (araç genişliği).
    * **z** — zeminden yukarı. Üst kata konan paletler tabanlarının üstünde durur.

    Üstten görünüş x-y, yandan görünüş x-z düzlemidir; 3B görünüş üçünü birden
    kullanır. Aynı veriden çizildikleri için üçü hiçbir zaman çelişmez.
    """
    sol, ust = 40, 34
    zemin_g = istif.arac.uzunluk * olcek
    zemin_y = istif.arac.genislik * olcek
    yukseklik_px = istif.arac.yukseklik * olcek

    paletler: list[dict] = []
    siralar: dict[int, float] = {}
    for yerlesim in istif.yerlesimler:
        yigin = [(yerlesim.yuk, True)] + [(p, False) for p in yerlesim.ustundekiler]
        z = 0
        for yuk, zeminde in yigin:
            paletler.append(
                {
                    # cm cinsinden gerçek yerleşim: 3B görünüş bunları kullanır.
                    "cm_x": float(yerlesim.x),
                    "cm_y": float(yerlesim.y),
                    "cm_z": float(z),
                    "cm_uzunluk": float(yerlesim.derinlik),
                    "cm_genislik": float(yerlesim.genislik),
                    "cm_yukseklik": float(yuk.yukseklik or 20),
                    # üstten görünüş (x-y)
                    "x": round(sol + float(yerlesim.x) * olcek, 1),
                    "y": round(ust + float(yerlesim.y) * olcek, 1),
                    "w": round(float(yerlesim.derinlik) * olcek, 1),
                    "h": round(float(yerlesim.genislik) * olcek, 1),
                    # yandan görünüş (x-z): yükseklik yukarı doğru büyür, SVG'de aşağı
                    "yan_y": round(
                        ust + (istif.arac.yukseklik - z - (yuk.yukseklik or 20)) * olcek,
                        1,
                    ),
                    "yan_h": round(float(yuk.yukseklik or 20) * olcek, 1),
                    "renk": durak_rengi(yuk.durak.sira),
                    "kod": yuk.tip.urun_kodu,
                    "urun_adi": yuk.tip.urun_adi,
                    "adet": int(yuk.adet),
                    "kirik": yuk.kirik_mi,
                    "zeminde": zeminde,
                    "sira": yerlesim.yukleme_sirasi,
                    "durak": yuk.durak.sira,
                    "durak_adi": yuk.durak.ad,
                }
            )
            z += yuk.yukseklik or 20
        siralar.setdefault(
            yerlesim.yukleme_sirasi,
            round(sol + (float(yerlesim.x) + float(yerlesim.derinlik) / 2) * olcek, 1),
        )

    return {
        "olcek": olcek,
        "sol": sol,
        "ust": ust,
        "zemin_genislik": round(zemin_g, 1),
        "zemin_yukseklik": round(zemin_y, 1),
        "yan_yukseklik": round(yukseklik_px, 1),
        "genislik": round(sol * 2 + zemin_g, 1),
        "yukseklik": round(ust + zemin_y + 30, 1),
        "yan_toplam_yukseklik": round(ust + yukseklik_px + 30, 1),
        "arac_uzunluk": istif.arac.uzunluk,
        "arac_genislik": istif.arac.genislik,
        "arac_yukseklik": istif.arac.yukseklik,
        "paletler": paletler,
        "siralar": [{"no": no, "x": x} for no, x in sorted(siralar.items())],
    }


def yukleme_sirasi(istif: IstifPlani) -> list[dict]:
    """Yükleme sırası listesi: depo bunu okuyarak yükler.

    Sıra numarası çizimdeki numaranın aynısıdır. Aynı sırada birden fazla palet
    varsa tek satırda toplanır; depo o sırayı tek seferde alıp yükler.
    """
    gruplar: dict[int, dict] = {}
    for yerlesim in istif.yerlesimler:
        kayit = gruplar.setdefault(
            yerlesim.yukleme_sirasi,
            {
                "sira": yerlesim.yukleme_sirasi,
                "durak": yerlesim.yuk.durak,
                "kod": yerlesim.yuk.tip.urun_kodu,
                "urun_adi": yerlesim.yuk.tip.urun_adi,
                "palet": 0,
                "adet": Decimal(0),
                "kirik": 0,
                "ustundekiler": [],
                "renk": durak_rengi(yerlesim.yuk.durak.sira),
            },
        )
        kayit["palet"] += 1
        kayit["adet"] += yerlesim.yuk.adet
        kayit["kirik"] += 1 if yerlesim.yuk.kirik_mi else 0
        for ustteki in yerlesim.ustundekiler:
            kayit["ustundekiler"].append(
                {
                    "kod": ustteki.tip.urun_kodu,
                    "adet": int(ustteki.adet),
                    "durak_adi": ustteki.durak.ad,
                    "renk": durak_rengi(ustteki.durak.sira),
                }
            )
    return sorted(gruplar.values(), key=lambda k: k["sira"])
