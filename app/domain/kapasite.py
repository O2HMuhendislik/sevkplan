"""Plan tipi ve kapasite tanımları.

Faz 1 (Ring) palet sayar, Faz 2 (Tır) "anahtar değer" yüzdesi sayar. Planlama motoru
hangi ölçüyle çalıştığını bilmez; sadece aşağıdaki profilden gelen sayısal birimlerle
işlem yapar. Yeni bir plan tipi eklemek için buraya bir profil eklemek yeterlidir.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class KapasiteProfili:
    kod: str
    ad: str
    belge_kodu: str
    """Sefer numarasındaki tek harfli belge kodu (Ring için 'D')."""
    olcu_adi: str
    """Kullanıcıya gösterilen birim adı: 'palet', 'anahtar değer' vb."""
    ust_limit: Decimal
    """Bir planın alabileceği azami birim."""
    alt_limit: Decimal
    """Bir planın geçerli sayılması için gereken asgari birim."""

    def gecerli_dolu(self, birim: Decimal) -> bool:
        return self.alt_limit <= birim <= self.ust_limit

    def doluluk_yuzdesi(self, birim: Decimal) -> Decimal:
        if self.ust_limit == 0:
            return Decimal(0)
        return (birim / self.ust_limit * 100).quantize(Decimal("0.01"))


RING = KapasiteProfili(
    kod="RING",
    ad="Ring (20 palet)",
    belge_kodu="D",
    olcu_adi="palet",
    ust_limit=Decimal(20),
    alt_limit=Decimal(18),
)

# Faz 2 taslağı: tır planlamasında ölçü anahtar değerdir, %100 = tam dolu tır.
# Belge kodu ve alt limit netleştiğinde güncellenecek.
TIR = KapasiteProfili(
    kod="TIR",
    ad="Tır (anahtar değer %100)",
    belge_kodu="T",
    olcu_adi="anahtar değer",
    ust_limit=Decimal(100),
    alt_limit=Decimal(90),
)

PROFILLER = {profil.kod: profil for profil in (RING, TIR)}


def profil_getir(kod: str) -> KapasiteProfili:
    try:
        return PROFILLER[kod]
    except KeyError as hata:
        raise ValueError(f"Tanımsız kapasite profili: {kod}") from hata
