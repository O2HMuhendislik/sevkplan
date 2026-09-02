"""Plan tipi ve kapasite tanımları.

Sahadaki iki farklı ölçü tek soyutlamada toplanır:

* **PALET** — bir planın alabileceği palet gözü sayısı (depo 64 ring: 20 palet).
* **ANAHTAR** — aracın doluluk oranı. Her ürünün "yükleme adeti" kadarı bir aracı
  doldurur; anahtar değer = miktar / yükleme adeti. Toplam 1.0 olunca araç %100 dolu
  demektir (depo 74 ring ve tır planlaması bu ölçüyü kullanır).

Planlama motoru ölçünün ne olduğunu bilmez; profilden gelen sayısal birimle çalışır.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal


class Olcu(str, enum.Enum):
    PALET = "PALET"
    ANAHTAR = "ANAHTAR"


class AracTipi(str, enum.Enum):
    """Anahtar değerin hangi araç kapasitesine göre hesaplanacağı."""

    KAMYON = "KAMYON"
    TIR = "TIR"


@dataclass(frozen=True)
class KapasiteProfili:
    kod: str
    ad: str
    belge_kodu: str
    """Sefer numarasındaki tek harfli belge kodu (Ring = D)."""
    olcu: Olcu
    arac_tipi: AracTipi
    """Anahtar ölçüsünde hangi sütunun kullanılacağı; palet ölçüsünde raporlama içindir."""
    ust_limit: Decimal
    alt_limit: Decimal

    @property
    def olcu_adi(self) -> str:
        return "palet" if self.olcu is Olcu.PALET else "anahtar değer"

    def gecerli_dolu(self, birim: Decimal) -> bool:
        return self.alt_limit <= birim <= self.ust_limit

    def doluluk_yuzdesi(self, birim: Decimal) -> Decimal:
        if self.ust_limit == 0:
            return Decimal(0)
        return (Decimal(birim) / self.ust_limit * 100).quantize(Decimal("0.01"))

    def bicimle(self, birim: Decimal) -> str:
        if self.olcu is Olcu.PALET:
            return f"{Decimal(birim).quantize(Decimal(1))} palet"
        return f"{Decimal(birim).quantize(Decimal('0.001'))} anahtar"


# Palet ölçüsüyle planlama profili. Şu an hiçbir depo bunu kullanmıyor; bir depo palet
# bazına dönerse app/config.py içindeki DEPO_PROFILLERI'ne eklenmesi yeterli.
RING_PALET = KapasiteProfili(
    kod="RING_PALET",
    ad="Ring — 20 palet",
    belge_kodu="D",
    olcu=Olcu.PALET,
    arac_tipi=AracTipi.KAMYON,
    ust_limit=Decimal(20),
    alt_limit=Decimal(18),
)

# Ring planlaması: tır anahtar değeri 1,00 = %100 dolu. Bütün depolar bunu kullanır.
RING_ANAHTAR = KapasiteProfili(
    kod="RING_ANAHTAR",
    ad="Ring — tır / anahtar değer",
    belge_kodu="D",
    olcu=Olcu.ANAHTAR,
    arac_tipi=AracTipi.TIR,
    ust_limit=Decimal(1),
    alt_limit=Decimal("0.90"),
)

# Faz 2: tır planlaması. Belge kodu netleşince güncellenecek.
TIR = KapasiteProfili(
    kod="TIR",
    ad="Tır — anahtar değer %100",
    belge_kodu="T",
    olcu=Olcu.ANAHTAR,
    arac_tipi=AracTipi.TIR,
    ust_limit=Decimal(1),
    alt_limit=Decimal("0.90"),
)

# ----------------------------------------------------------------- iç piyasa
#
# Üç sevkiyat tipinin her biri ayrı belge kodu ve ayrı doluluk hedefiyle çalışır.
# Sefer numarası bu belge kodundan üretilir: 2609S1001, 2609R1001, 2609K1001.

IC_FTL = KapasiteProfili(
    kod="IC_FTL",
    ad="İç piyasa — FTL (tam araç)",
    belge_kodu="S",
    olcu=Olcu.ANAHTAR,
    arac_tipi=AracTipi.TIR,
    ust_limit=Decimal(1),
    alt_limit=Decimal("0.85"),
)
"""Geçmiş FTL planlarının medyan doluluğu %94,4; alt limit 0,85 ile gerçeğe yakın."""

IC_RUTIN = KapasiteProfili(
    kod="IC_RUTIN",
    ad="İç piyasa — Rutin / parsiyel",
    belge_kodu="R",
    olcu=Olcu.ANAHTAR,
    arac_tipi=AracTipi.TIR,
    ust_limit=Decimal("0.60"),
    alt_limit=Decimal("0.50"),
)
"""Rutin araç %100 doldurulmaz: karışık palet ve çok durak olduğu için %50-60'ta bırakılır.

Üst limit 0,60 olduğu için doluluk yüzdesi de bu hedefe göre hesaplanır: %100 gösterimi
"araç tıka basa dolu" değil, "rutin hedefinin üst ucunda" demektir.
"""

IC_KARGO = KapasiteProfili(
    kod="IC_KARGO",
    ad="İç piyasa — Kargo",
    belge_kodu="K",
    olcu=Olcu.ANAHTAR,
    arac_tipi=AracTipi.TIR,
    ust_limit=Decimal(1),
    alt_limit=Decimal(0),
)
"""Kargoda araç kapasitesi yoktur; profil yalnızca belge kodu ve raporlama içindir."""

PROFILLER = {
    profil.kod: profil
    for profil in (RING_PALET, RING_ANAHTAR, TIR, IC_FTL, IC_RUTIN, IC_KARGO)
}


def profil_getir(kod: str) -> KapasiteProfili:
    try:
        return PROFILLER[kod]
    except KeyError as hata:
        raise ValueError(f"Tanımsız kapasite profili: {kod}") from hata
