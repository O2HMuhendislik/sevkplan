"""Uygulama genelindeki sabitler ve ayarlar."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from app.domain.kapasite import RING_ANAHTAR, KapasiteProfili

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

# Depo kodu -> kapasite profili.
#
# Sahadaki güncel kural: bütün ring planlamaları tır bazında, anahtar değerle yapılır.
# Anahtar değer = miktar / tır yükleme adeti; toplam 1,00 olunca araç %100 doludur.
# Palet, kapasite kısıtı değil ama planlamanın birincil kalite ölçüsüdür: motor kırık
# palet israfını en aza indirecek şekilde yerleştirir.
#
# (Yükleme formundaki "64-D DEPO" satırı ayrı bir depo değil, depo 64'ün form
#  üzerindeki adıdır; "64-V" ise gerçekten ayrı bir depo kodudur.)
DEPO_PROFILLERI: dict[str, KapasiteProfili] = {
    depo: RING_ANAHTAR
    for depo in ("64", "64-V", "64-P", "74", "74-V", "3", "03", "34", "36", "44")
}

RING_DEPO_KODU = "64"
"""Arayüzde varsayılan olarak seçili gelen depo."""

# ------------------------------------------------------- karışık plan ve alt limit

GRUP_ICI_MIX = os.environ.get("SEVKPLAN_GRUP_ICI_MIX", "1") not in {"0", "false", "False"}
"""Faz 2'nin varsayılan durumu.

Planlama önce ürün kodu bazında yapılır. Aracı dolduramayan artıklar, bu ayar açıkken
aynı ürün grubu içinde birleştirilerek yeniden paketlenir (ör. farklı ölçülerdeki
paneller). Kapalıyken artıklar beklemede kalır. Planlama ekranındaki kutu ile her
çalıştırmada ayrıca seçilebilir.
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


# ------------------------------------------------------------------------ oturum

OTURUM_SURESI_DAKIKA = int(os.environ.get("SEVKPLAN_OTURUM_SURESI", "480"))
"""Hareketsiz oturumun kapanma süresi (dakika). Varsayılan 8 saat."""


def oturum_anahtari() -> str:
    """Oturum çerezlerini imzalayan gizli anahtar.

    Öncelik `SEVKPLAN_OTURUM_ANAHTARI` ortam değişkenindedir — sunucuya kurulumda
    bunun verilmesi önerilir. Verilmezse veri klasöründe bir anahtar üretilip saklanır;
    böylece program yeniden başladığında oturumlar düşmez.
    """
    ortamdan = os.environ.get("SEVKPLAN_OTURUM_ANAHTARI")
    if ortamdan:
        return ortamdan
    dosya = VERI_DIZIN / ".oturum_anahtari"
    if not dosya.exists():
        import secrets

        dosya.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            dosya.chmod(0o600)
        except OSError:
            pass  # Windows'ta chmod desteklenmeyebilir
    return dosya.read_text(encoding="utf-8").strip()
