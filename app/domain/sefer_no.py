"""Sefer numarası üretimi.

Format: YY + AA + <belge kodu> + <4 haneli sayaç>   ->  2608D1001
  YY  : yılın son iki hanesi
  AA  : ay (01-12)
  D   : belge kodu (Ring = D, Faz 2 tır = T)
  #### : sayaç, her ay 1001'den başlar

İptal edilen planın numarası geri kullanılmaz; numara akışındaki boşluk normaldir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

BASLANGIC_SAYAC = 1001
SON_SAYAC = 9999

SEFER_NO_DESENI = re.compile(r"^(\d{2})(\d{2})([A-Z])(\d{4})$")


@dataclass(frozen=True)
class SeferNo:
    yil: int
    ay: int
    belge_kodu: str
    sayac: int

    @property
    def donem(self) -> str:
        """Sayacın sıfırlandığı dönem anahtarı: '2608'."""
        return f"{self.yil % 100:02d}{self.ay:02d}"

    def __str__(self) -> str:
        return f"{self.donem}{self.belge_kodu}{self.sayac:04d}"


def donem_anahtari(tarih: date) -> str:
    return f"{tarih.year % 100:02d}{tarih.month:02d}"


def uret(tarih: date, belge_kodu: str, onceki_sayac: int | None) -> SeferNo:
    """Verilen dönem için bir sonraki sefer numarasını üretir.

    `onceki_sayac` o döneme ait en son kullanılan sayaç; dönemin ilk planı için None.
    """
    if len(belge_kodu) != 1 or not belge_kodu.isalpha():
        raise ValueError(f"Belge kodu tek harf olmalı: {belge_kodu!r}")
    sayac = BASLANGIC_SAYAC if onceki_sayac is None else onceki_sayac + 1
    if sayac > SON_SAYAC:
        raise ValueError(
            f"{donem_anahtari(tarih)} döneminde sefer numarası tükendi "
            f"(üst sınır {SON_SAYAC}). Sayaç hane sayısı artırılmalı."
        )
    return SeferNo(
        yil=tarih.year, ay=tarih.month, belge_kodu=belge_kodu.upper(), sayac=sayac
    )


def coz(sefer_no: str) -> SeferNo:
    """Metin halindeki sefer numarasını parçalarına ayırır."""
    eslesme = SEFER_NO_DESENI.match(sefer_no.strip().upper())
    if not eslesme:
        raise ValueError(f"Geçersiz sefer numarası: {sefer_no!r}")
    yy, aa, kod, sayac = eslesme.groups()
    ay = int(aa)
    if not 1 <= ay <= 12:
        raise ValueError(f"Geçersiz ay: {sefer_no!r}")
    return SeferNo(yil=2000 + int(yy), ay=ay, belge_kodu=kod, sayac=int(sayac))
