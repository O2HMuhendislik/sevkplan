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
    # Birden fazla ana ürün grubu varsa teslimat geçersizdir; çağıran taraf raporlar.
    return " + ".join(sorted(anahtarlar))


def aksesuar_mi_hepsi(urunler: Iterable[Urun | None]) -> bool:
    tanimli = [urun for urun in urunler if urun is not None]
    return bool(tanimli) and all(
        (urun.urun_grubu or "").strip().upper() in AKSESUAR_GRUPLARI for urun in tanimli
    )
