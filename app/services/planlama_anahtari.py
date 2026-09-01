"""Bir teslimatın hangi plana ait olduğunu belirleyen anahtarın hesabı.

Kurallar:
  * Header kodu tanımlı bir ürün varsa anahtar odur (ana ürün + aksesuar bir arada).
  * Aksesuar nitelikli gruplar (AKSESUAR, BACA, DİRSEK) tek başına plan açmaz;
    teslimatta ana ürün varsa anahtar ana ürünün grubudur.
  * Varsayılan seviye SKU'dur: planda tek ürün kodu bulunur.
  * Mix plan seçildiğinde seviye ürün grubudur: aynı gruptaki farklı ürün kodları
    tek planda birleşebilir.
"""
from __future__ import annotations

from collections.abc import Iterable

from app.models import AKSESUAR_GRUPLARI, Urun


VARSAYILAN_SEVIYE = "SKU"


def teslimat_anahtari(
    urunler: Iterable[Urun | None], seviye: str | None = None
) -> str | None:
    seviye = seviye or VARSAYILAN_SEVIYE
    tanimli = [urun for urun in urunler if urun is not None]
    if not tanimli:
        return None

    for urun in tanimli:
        if urun.header_kod:
            return urun.header_kod

    ana_urunler = [urun for urun in tanimli if not urun.aksesuar_mi]
    secilenler = ana_urunler or tanimli
    anahtarlar = {urun.planlama_anahtari(seviye) for urun in secilenler}
    if len(anahtarlar) == 1:
        return next(iter(anahtarlar))
    # Çok ürünlü teslimat hata değildir; tek ürünlü ("saf") plana giremez, karma plana
    # yazılır. Çağıran taraf None görünce teslimatı karma olarak işaretler.
    return None


def urun_grubu(urunler: Iterable[Urun | None], sku_miktarlari: dict | None = None) -> str:
    """Teslimatın ait olduğu ürün grubu.

    Birden fazla grup varsa **baskın grup** seçilir: miktar verildiyse en çok adede
    sahip olan, verilmediyse alfabetik ilk grup. Teslimat böylece kendi ana grubunun
    karma planına katılır.
    """
    tanimli = [urun for urun in urunler if urun is not None]
    ana_urunler = [urun for urun in tanimli if not urun.aksesuar_mi] or tanimli
    if not ana_urunler:
        return ""
    if sku_miktarlari:
        agirliklar: dict[str, float] = {}
        for urun in ana_urunler:
            grup = (urun.urun_grubu or urun.urun_kodu).upper()
            agirliklar[grup] = agirliklar.get(grup, 0) + float(
                sku_miktarlari.get(urun.urun_kodu, 0)
            )
        if agirliklar:
            return max(agirliklar.items(), key=lambda ikili: (ikili[1], ikili[0]))[0]
    return sorted((urun.urun_grubu or urun.urun_kodu).upper() for urun in ana_urunler)[0]


def aksesuar_mi_hepsi(urunler: Iterable[Urun | None]) -> bool:
    tanimli = [urun for urun in urunler if urun is not None]
    return bool(tanimli) and all(
        (urun.urun_grubu or "").strip().upper() in AKSESUAR_GRUPLARI for urun in tanimli
    )
