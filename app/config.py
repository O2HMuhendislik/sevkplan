"""Uygulama genelindeki sabitler ve ayarlar."""
from __future__ import annotations

import os
from pathlib import Path

KOK_DIZIN = Path(__file__).resolve().parent.parent
VERI_DIZIN = Path(os.environ.get("SEVKPLAN_VERI_DIZIN", KOK_DIZIN / "veri"))
YUKLEME_DIZIN = VERI_DIZIN / "yuklemeler"
CIKTI_DIZIN = VERI_DIZIN / "ciktilar"

VERITABANI_URL = os.environ.get(
    "SEVKPLAN_DB_URL", f"sqlite:///{VERI_DIZIN / 'sevkplan.db'}"
)

# Ring planlamasının geçerli olduğu depo kodu. Diğer depolar Faz 2 (tır) kapsamındadır.
RING_DEPO_KODU = "64"

for _dizin in (VERI_DIZIN, YUKLEME_DIZIN, CIKTI_DIZIN):
    _dizin.mkdir(parents=True, exist_ok=True)
