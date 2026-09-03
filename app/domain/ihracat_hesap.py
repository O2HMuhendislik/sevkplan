"""İhracat doluluk hesabı — şirketin `Hesaplama.xlsx` dosyasındaki modelin kodu.

Sahadaki hesap desi üzerinden değil **yükleme adeti** üzerinden yapılır. Her ürünün
bir tıra ve bir konteynere sığan adedi bellidir; aracın doluluğu kalemlerin
paylarının toplamıdır::

    DOLULUK  = Σ ( miktar / yükleme adeti )      1,00 = araç %100 dolu
    PALET    = Σ ( miktar / palet içi adet )
    DESİ     = Σ ( birim desi   × miktar )
    AĞIRLIK  = Σ ( birim ağırlık × miktar )

Ring'deki "anahtar değer" ile aynı mantıktır; farkı, ihracatta palete yuvarlama
yapılmaması ve tır/konteyner için iki ayrı yükleme adeti bulunmasıdır.

İki hesap sürümü yan yana yaşıyor ve **müşteriye göre** seçiliyor:

* **YENİ** — güncel sütunlar (`PALET İÇİ ADET`, `TIR`, `KONTEYNER`).
  Kaynak dosyadaki `Ürün Hesaplama-1` sayfası bunu kullanır.
* **ESKİ** — `-2` sütunları (`PALET İÇİ ADET-2`, `TIR-2`, `KONTEYNER-2`).
  Kaynak dosyadaki `Eski Detay Hesaplama` sayfası bunu kullanır. Müşteri master
  datasında notu "ESKİ HESAPLAMA" olanlar bu sürümle hesaplanır.

Bunun üzerine **palet yükseltme** gelir: paletler üst üste istiflendiğinde araca
%20 daha fazla yük girer, dosyadaki karşılığı `DOLULUK = Σ(...)/1,2` formülüdür.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.iller import yer_adi

PALET_YUKSELTME_KATSAYISI = Decimal("1.2")
"""Palet yükseltmeli yüklemede araca giren fazla yük: doluluk 1,2'ye bölünür."""

DESI_KAPASITELERI: dict[str, Decimal] = {
    "TIR": Decimal(21500),
    "KONTEYNER": Decimal(15300),
}
"""Yükleme adeti bilinmeyen ürünler için geri düşülen desi kapasitesi.

Master datada 2.862 üründen 205'inde tır, 314'ünde konteyner adedi boş. Bu ürünler
planlamayı durdurmasın diye desi payı üzerinden yaklaşık bir doluluk hesaplanır ve
kalem "ölçüsü eksik" olarak işaretlenir. Değerler 2025 sevklerinin %90'lık
dilimlerinden gelir.
"""


class HesaplamaTipi(str, enum.Enum):
    """Müşterinin hangi yükleme adeti setiyle hesaplanacağı."""

    YENI = "YENI"
    ESKI = "ESKI"

    @property
    def ad(self) -> str:
        return "Yeni hesaplama" if self is HesaplamaTipi.YENI else "Eski hesaplama"


@dataclass(frozen=True)
class YuklemeKurali:
    """Bir müşterinin yükleme biçimi: hangi hesap, hangi istif.

    `yukleme_tipi` ve `notlar` alanlarının ikisi de serbest metindir; kural bu iki
    metinden çözülür.
    """

    hesaplama: HesaplamaTipi = HesaplamaTipi.YENI
    palet_yukseltme: bool = False
    dokme: bool = False
    kosebent: bool = False
    etiket: bool = False
    tonaj_onemli: bool = False
    """Notta "TONAJ ÖNEMLİ" geçiyorsa ağırlık sınırı hacimden önce gelir."""

    @property
    def katsayi(self) -> Decimal:
        return PALET_YUKSELTME_KATSAYISI if self.palet_yukseltme else Decimal(1)

    @property
    def ad(self) -> str:
        parcalar = [self.hesaplama.ad]
        if self.palet_yukseltme:
            parcalar.append("palet yükseltmeli")
        if self.dokme:
            parcalar.append("dökme")
        if self.kosebent:
            parcalar.append("köşebentli")
        if self.etiket:
            parcalar.append("etiketli")
        return " · ".join(parcalar)


VARSAYILAN_KURAL = YuklemeKurali()


def yukleme_kurali_coz(yukleme_tipi: str = "", notlar: str = "") -> YuklemeKurali:
    """Müşteri master datasındaki serbest metinleri yükleme kuralına çevirir.

    Kaynak dosyada aynı şey birden çok yazımla geçiyor: "PALET YÜKSELTME",
    "PALET YÜKSETLME" (dosyadaki yazım hatası), "PALET YÜKSELTMELİ". Türkçe
    harfler sadeleştirilip ortak kök aranır.
    """
    metin = f"{yukleme_tipi or ''} {notlar or ''}"
    buyuk = yer_adi(metin)
    eski = "ESKI" in buyuk and "YENI" not in buyuk
    return YuklemeKurali(
        hesaplama=HesaplamaTipi.ESKI if eski else HesaplamaTipi.YENI,
        # "YUKSELTME" ve dosyadaki "YUKSETLME" yazımını birlikte yakalar.
        palet_yukseltme="PALET YUKS" in buyuk,
        dokme="DOKME" in buyuk,
        kosebent="KOSEBENT" in buyuk,
        etiket="ETIKET" in buyuk,
        tonaj_onemli="TONAJ ONEMLI" in buyuk,
    )


@dataclass(frozen=True)
class UrunOlcusu:
    """Bir ihracat ürününün yükleme ölçüleri (`Hesaplama.xlsx` → `Ürün` sayfası)."""

    urun_kodu: str
    urun_adi: str = ""
    urun_grubu: str = ""
    palet_ici_adet: Decimal | None = None
    tir_yukleme_adeti: Decimal | None = None
    konteyner_yukleme_adeti: Decimal | None = None
    palet_ici_adet_eski: Decimal | None = None
    tir_yukleme_adeti_eski: Decimal | None = None
    konteyner_yukleme_adeti_eski: Decimal | None = None
    desi: Decimal | None = None
    agirlik: Decimal | None = None
    dokme_adeti: Decimal | None = None

    def yukleme_adeti(
        self, arac_tipi: str, hesaplama: HesaplamaTipi = HesaplamaTipi.YENI
    ) -> Decimal | None:
        """Aracı dolduran adet. Eski hesapta `-2` sütunu yoksa yeniye düşülür."""
        konteyner = arac_tipi == "KONTEYNER"
        if hesaplama is HesaplamaTipi.ESKI:
            eski = (
                self.konteyner_yukleme_adeti_eski
                if konteyner
                else self.tir_yukleme_adeti_eski
            )
            if eski:
                return eski
        return self.konteyner_yukleme_adeti if konteyner else self.tir_yukleme_adeti

    def palet_adeti(self, hesaplama: HesaplamaTipi = HesaplamaTipi.YENI) -> Decimal | None:
        if hesaplama is HesaplamaTipi.ESKI and self.palet_ici_adet_eski:
            return self.palet_ici_adet_eski
        return self.palet_ici_adet

    @property
    def olculebilir_mi(self) -> bool:
        return bool(self.tir_yukleme_adeti or self.konteyner_yukleme_adeti or self.desi)


@dataclass
class Doluluk:
    """Bir kalem kümesinin araç karşılığı."""

    doluluk: Decimal = Decimal(0)
    """1,00 = araç %100 dolu. Palet yükseltme katsayısı uygulanmış hâlidir."""
    palet: Decimal = Decimal(0)
    desi: Decimal = Decimal(0)
    agirlik: Decimal = Decimal(0)
    olcusuz_kodlar: tuple[str, ...] = ()
    """Yükleme adeti master datada olmayan ürünler; desiden yaklaşık hesaplandı."""

    @property
    def yuzde(self) -> Decimal:
        return (self.doluluk * 100).quantize(Decimal("0.01"))


@dataclass
class Kalem:
    urun_kodu: str
    miktar: Decimal
    olcu: UrunOlcusu | None = None
    desi: Decimal | None = None
    """Dosyadan gelen satır desisi; master datada ölçü yoksa buna düşülür."""
    agirlik: Decimal | None = None


def kalem_dolulugu(
    kalem: Kalem, arac_tipi: str, kural: YuklemeKurali = VARSAYILAN_KURAL
) -> tuple[Decimal, bool]:
    """Tek kalemin araç payı. İkinci değer: ölçü master datadan mı geldi?

    Yükleme adeti bilinmiyorsa kalemin desisi araç tipinin desi kapasitesine
    bölünür — kaba ama planlamayı durdurmayan bir yaklaşım.
    """
    olcu = kalem.olcu
    adet = olcu.yukleme_adeti(arac_tipi, kural.hesaplama) if olcu else None
    if adet:
        return (Decimal(kalem.miktar) / Decimal(adet)) / kural.katsayi, True

    desi = _kalem_desisi(kalem)
    kapasite = DESI_KAPASITELERI.get(arac_tipi, DESI_KAPASITELERI["TIR"])
    return (desi / kapasite) / kural.katsayi, False


def hesapla(
    kalemler: list[Kalem], arac_tipi: str, kural: YuklemeKurali = VARSAYILAN_KURAL
) -> Doluluk:
    """`Hesaplama.xlsx`'in özet bloğunun karşılığı: doluluk, palet, desi, ağırlık."""
    sonuc = Doluluk()
    olcusuzler: list[str] = []
    for kalem in kalemler:
        pay, master_datadan = kalem_dolulugu(kalem, arac_tipi, kural)
        sonuc.doluluk += pay
        if not master_datadan and kalem.urun_kodu:
            olcusuzler.append(kalem.urun_kodu)

        olcu = kalem.olcu
        palet_ici = olcu.palet_adeti(kural.hesaplama) if olcu else None
        if palet_ici:
            sonuc.palet += Decimal(kalem.miktar) / Decimal(palet_ici)
        sonuc.desi += _kalem_desisi(kalem)
        sonuc.agirlik += _kalem_agirligi(kalem)
    sonuc.olcusuz_kodlar = tuple(dict.fromkeys(olcusuzler))
    return sonuc


def _kalem_desisi(kalem: Kalem) -> Decimal:
    if kalem.olcu is not None and kalem.olcu.desi:
        return Decimal(kalem.olcu.desi) * Decimal(kalem.miktar)
    return Decimal(kalem.desi or 0)


def _kalem_agirligi(kalem: Kalem) -> Decimal:
    if kalem.olcu is not None and kalem.olcu.agirlik:
        return Decimal(kalem.olcu.agirlik) * Decimal(kalem.miktar)
    return Decimal(kalem.agirlik or 0)
