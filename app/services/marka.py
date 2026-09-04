"""Kurumsal logo yönetimi.

Resmî Vaillant Group logosu markadır; depoda yalnızca bir **yer tutucu** durur
(`app/static/logo.svg`). Gerçek logo ekrandan yüklenir ve `veri/` altına yazılır —
program klasörüne değil. Böylece yeni sürüm kurulduğunda (klasörün üzerine yeni zip
açıldığında) yüklenen logo silinmez.
"""
from __future__ import annotations

from pathlib import Path

from app.config import VERI_DIZIN

KOK = Path(__file__).resolve().parent.parent
YEDEK_LOGO = KOK / "static" / "logo.svg"
"""Logo yüklenmemişse gösterilen yer tutucu."""

LOGO_DIZINI = VERI_DIZIN / "marka"

UZANTI_TURLERI = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
"""Kabul edilen logo dosyaları. SVG en iyisidir: her ekranda net görünür."""

AZAMI_BOYUT = 2 * 1024 * 1024
"""2 MB. Logo başlıkta 34 piksel yüksekliğinde gösteriliyor; daha büyüğü gereksiz."""


class LogoHatasi(Exception):
    """Yüklenen dosya logo olarak kullanılamaz; kullanıcıya gösterilir."""


def yuklenen_logo() -> Path | None:
    """Yüklenmiş logo dosyası (varsa)."""
    if not LOGO_DIZINI.exists():
        return None
    for uzanti in UZANTI_TURLERI:
        aday = LOGO_DIZINI / f"logo{uzanti}"
        if aday.exists():
            return aday
    return None


def logo_yolu() -> Path:
    """Gösterilecek logo: yüklenmişse o, yoksa yer tutucu."""
    return yuklenen_logo() or YEDEK_LOGO


def icerik_turu(yol: Path) -> str:
    return UZANTI_TURLERI.get(yol.suffix.lower(), "application/octet-stream")


def surum() -> int:
    """Dosyanın değişme zamanı; tarayıcının eski logoyu önbellekten sunmasını önler."""
    yol = logo_yolu()
    return int(yol.stat().st_mtime) if yol.exists() else 0


def logo_kaydet(icerik: bytes, dosya_adi: str) -> Path:
    """Yüklenen logoyu kaydeder; öncekini siler.

    Tek bir logo tutulur: iki farklı uzantı bir arada kalırsa hangisinin geçerli
    olduğu belirsizleşir.
    """
    uzanti = Path(dosya_adi or "").suffix.lower()
    if uzanti not in UZANTI_TURLERI:
        kabul = ", ".join(sorted(UZANTI_TURLERI))
        raise LogoHatasi(f"Desteklenmeyen dosya türü ({uzanti or 'uzantısız'}). Kabul edilenler: {kabul}")
    if not icerik:
        raise LogoHatasi("Dosya boş.")
    if len(icerik) > AZAMI_BOYUT:
        raise LogoHatasi(
            f"Dosya çok büyük ({len(icerik) / 1024 / 1024:.1f} MB); en fazla 2 MB olmalı."
        )
    if uzanti == ".svg" and b"<svg" not in icerik[:2048].lower():
        raise LogoHatasi("SVG dosyası tanınmadı.")

    LOGO_DIZINI.mkdir(parents=True, exist_ok=True)
    for eski in LOGO_DIZINI.glob("logo.*"):
        eski.unlink()
    hedef = LOGO_DIZINI / f"logo{uzanti}"
    hedef.write_bytes(icerik)
    return hedef


def logo_sil() -> bool:
    """Yüklenen logoyu kaldırır; yer tutucuya dönülür."""
    mevcut = yuklenen_logo()
    if mevcut is None:
        return False
    mevcut.unlink()
    return True
