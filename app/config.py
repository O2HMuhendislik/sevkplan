"""Uygulama genelindeki sabitler ve ayarlar."""
from __future__ import annotations

import os
from decimal import Decimal
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

# Planlama varsayılan olarak SKU bazlıdır: bir planda tek ürün kodu bulunur.
# Planlama ekranındaki "Mix plan yap" kutusu işaretlendiğinde seviye ürün grubuna
# çıkar ve aynı gruptaki farklı ürün kodları tek planda birleşebilir.

from app.models import AKSESUAR_GRUPLARI  # noqa: E402,F401  (tek tanım models.py'de)

# Depo kodu -> kapasite profili. Listede olmayan depolar planlamaya girmez.
#
# Ölçüler 2025 verisinden doğrulandı:
#   64 / 64-V / 64-P  -> anahtar medyanı 0,15-0,38 · palet dağılımının tepesi 20 → PALET
#     (Yükleme formundaki "64-D DEPO" satırı ayrı bir depo değil, depo 64'ün form
#      üzerindeki adıdır; "64-V DEPO" ise gerçekten ayrı bir depo kodudur.)
#   74 / 3 / 03       -> planların %91-95'i anahtar 1,0 civarında            → ANAHTAR
#   34 / 36 / 44      -> 2025'te örnek az; Ağustos 2026'da anahtar ~1,0 civarı olduğu
#                        için ANAHTAR kabul edildi. Palet ölçüsüne geçmesi gerekiyorsa
#                        aşağıdaki satırı RING_PALET yapmak yeterli.
DEPO_PROFILLERI: dict[str, KapasiteProfili] = {
    "64": RING_PALET,
    "64-V": RING_PALET,
    "64-P": RING_PALET,
    "74": RING_ANAHTAR,
    "74-V": RING_ANAHTAR,
    "3": RING_ANAHTAR,
    "03": RING_ANAHTAR,
    "34": RING_ANAHTAR,
    "36": RING_ANAHTAR,
    "44": RING_ANAHTAR,
}

RING_DEPO_KODU = "64"
"""Arayüzde varsayılan olarak seçili gelen depo."""

# ------------------------------------------------------------- alt limit esnetmesi

ESNETME_GUN_ESIGI = int(os.environ.get("SEVKPLAN_ESNETME_GUN_ESIGI", "3"))
"""Alt limitin kendiliğinden esneyeceği aciliyet eşiği (gün).

Alt limiti dolduramayan teslimatlar normalde beklemede kalır. Ancak aralarında termin
tarihine bu kadar veya daha az gün kalan (ya da termini geçmiş) bir teslimat varsa,
kalanlar alt limite bakılmadan planlanır ve plan "alt limit esnetildi" olarak
işaretlenir. 0 verilirse yalnızca termini gelmiş/geçmiş teslimatlar esnetir.
"""

ESNETME_ASGARI_ORAN = Decimal(os.environ.get("SEVKPLAN_ESNETME_ASGARI_ORAN", "0"))
"""Esnetme yapılsa bile bu doluluk oranının altındaki planlar açılmaz (0 = sınır yok).

Örnek: 0.25 verilirse depo 64'te 5 paletin (20 x 0,25) altındaki kalıntılar
beklemeye devam eder.
"""


TUM_DEPOLAR = "TUMU"
"""Planlama ekranında "Tüm depolar" seçeneğinin değeri."""


def depo_profili(depo_kodu: str) -> KapasiteProfili | None:
    return DEPO_PROFILLERI.get((depo_kodu or "").strip().upper())


for _dizin in (VERI_DIZIN, YUKLEME_DIZIN, CIKTI_DIZIN):
    _dizin.mkdir(parents=True, exist_ok=True)
