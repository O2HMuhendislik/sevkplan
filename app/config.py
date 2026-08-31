"""Uygulama genelindeki sabitler ve ayarlar."""
from __future__ import annotations

import os
from pathlib import Path

from app.domain.kapasite import RING_ANAHTAR, RING_PALET, KapasiteProfili

KOK_DIZIN = Path(__file__).resolve().parent.parent
VERI_DIZIN = Path(os.environ.get("SEVKPLAN_VERI_DIZIN", KOK_DIZIN / "veri"))
YUKLEME_DIZIN = VERI_DIZIN / "yuklemeler"
CIKTI_DIZIN = VERI_DIZIN / "ciktilar"

VERITABANI_URL = os.environ.get(
    "SEVKPLAN_DB_URL", f"sqlite:///{VERI_DIZIN / 'sevkplan.db'}"
)

# ---------------------------------------------------------------- planlama ayarları

PLANLAMA_SEVIYESI = os.environ.get("SEVKPLAN_PLANLAMA_SEVIYESI", "URUN_GRUBU")
"""Bir planın içinde neyin aynı olacağını belirler.

  URUN_GRUBU : Aynı ürün grubundaki farklı SKU'lar tek planda birleşebilir
               (ör. farklı ölçülerdeki paneller). 2025 planlarının davranışı budur.
  SKU        : Planda tek bir ürün kodu bulunur.

Değiştirmek için bu satırı düzenleyin ya da SEVKPLAN_PLANLAMA_SEVIYESI ortam
değişkenini kullanın.
"""

from app.models import AKSESUAR_GRUPLARI  # noqa: E402,F401  (tek tanım models.py'de)

# Depo kodu -> kapasite profili. Listede olmayan depolar planlamaya girmez.
DEPO_PROFILLERI: dict[str, KapasiteProfili] = {
    "64": RING_PALET,
    "64-D": RING_PALET,
    "64-V": RING_PALET,
    "64-P": RING_PALET,
    "74": RING_ANAHTAR,
    "74-V": RING_ANAHTAR,
}

RING_DEPO_KODU = "64"
"""Arayüzde varsayılan olarak seçili gelen depo."""


def depo_profili(depo_kodu: str) -> KapasiteProfili | None:
    return DEPO_PROFILLERI.get((depo_kodu or "").strip().upper())


for _dizin in (VERI_DIZIN, YUKLEME_DIZIN, CIKTI_DIZIN):
    _dizin.mkdir(parents=True, exist_ok=True)
