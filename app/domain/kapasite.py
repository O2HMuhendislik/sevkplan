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


# Depo 64 ring planı: 20 palet gözü, 18 palet alt limit.
RING_PALET = KapasiteProfili(
    kod="RING_PALET",
    ad="Ring — 20 palet (depo 64)",
    belge_kodu="D",
    olcu=Olcu.PALET,
    arac_tipi=AracTipi.KAMYON,
    ust_limit=Decimal(20),
    alt_limit=Decimal(18),
)

# Depo 74 ring planı: tır anahtar değeri 1.0 = %100 dolu.
RING_ANAHTAR = KapasiteProfili(
    kod="RING_ANAHTAR",
    ad="Ring — anahtar değer %100 (depo 74)",
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

PROFILLER = {profil.kod: profil for profil in (RING_PALET, RING_ANAHTAR, TIR)}


def profil_getir(kod: str) -> KapasiteProfili:
    try:
        return PROFILLER[kod]
    except KeyError as hata:
        raise ValueError(f"Tanımsız kapasite profili: {kod}") from hata
