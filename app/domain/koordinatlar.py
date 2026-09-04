"""İl merkezlerinin koordinatları ve iller arası yaklaşık karayolu mesafesi.

Rota kurarken tek başına "Eskişehir'e uzaklık" yetmiyor: Adana, Hatay, Elazığ ve
Mardin uzaklığa göre sıralandığında araç bir aşağı bir yukarı gidiyor. Sapmayı
ölçebilmek için **iller arası** mesafe gerekiyor, o da koordinat ister.

Mesafe büyük daire (haversine) uzaklığının **1,25** ile çarpımıdır; karayolu kuş
uçuşundan bu oranda uzundur. Tahmin, sahadan derlenen `ESKISEHIR_MESAFELERI`
tablosunun 80 ilini medyan **%6** hatayla yeniden üretiyor — 100 km'lik sapma
kuralı için yeterli hassasiyet.
"""
from __future__ import annotations

import math

from app.domain.iller import yer_adi

KARAYOLU_KATSAYISI = 1.25
"""Kuş uçuşu mesafeyi karayoluna çeviren çarpan (bkz. modül açıklaması)."""

KOORDINATLAR: dict[str, tuple[float, float]] = {
    "ADANA": (37.0, 35.32),
    "ADIYAMAN": (37.76, 38.28),
    "AFYONKARAHISAR": (38.76, 30.54),
    "AGRI": (39.72, 43.05),
    "AKSARAY": (38.37, 34.03),
    "AMASYA": (40.65, 35.83),
    "ANKARA": (39.93, 32.86),
    "ANTALYA": (36.9, 30.7),
    "ARDAHAN": (41.11, 42.7),
    "ARTVIN": (41.18, 41.82),
    "AYDIN": (37.85, 27.84),
    "BALIKESIR": (39.65, 27.88),
    "BARTIN": (41.64, 32.34),
    "BATMAN": (37.89, 41.13),
    "BAYBURT": (40.26, 40.23),
    "BILECIK": (40.15, 29.98),
    "BINGOL": (38.88, 40.5),
    "BITLIS": (38.4, 42.11),
    "BOLU": (40.74, 31.61),
    "BURDUR": (37.72, 30.29),
    "BURSA": (40.19, 29.06),
    "CANAKKALE": (40.15, 26.41),
    "CANKIRI": (40.6, 33.62),
    "CORUM": (40.55, 34.95),
    "DENIZLI": (37.78, 29.09),
    "DIYARBAKIR": (37.91, 40.24),
    "DUZCE": (40.84, 31.16),
    "EDIRNE": (41.68, 26.56),
    "ELAZIG": (38.68, 39.22),
    "ERZINCAN": (39.75, 39.49),
    "ERZURUM": (39.9, 41.27),
    "ESKISEHIR": (39.78, 30.52),
    "GAZIANTEP": (37.07, 37.38),
    "GIRESUN": (40.91, 38.39),
    "GUMUSHANE": (40.46, 39.48),
    "HAKKARI": (37.58, 43.74),
    "HATAY": (36.2, 36.16),
    "IGDIR": (39.92, 44.04),
    "ISPARTA": (37.76, 30.55),
    "ISTANBUL": (41.01, 28.98),
    "IZMIR": (38.42, 27.14),
    "KAHRAMANMARAS": (37.58, 36.93),
    "KARABUK": (41.2, 32.63),
    "KARAMAN": (37.18, 33.22),
    "KARS": (40.6, 43.09),
    "KASTAMONU": (41.39, 33.78),
    "KAYSERI": (38.73, 35.49),
    "KILIS": (36.72, 37.12),
    "KIRIKKALE": (39.85, 33.51),
    "KIRKLARELI": (41.74, 27.22),
    "KIRSEHIR": (39.15, 34.16),
    "KOCAELI": (40.77, 29.92),
    "KONYA": (37.87, 32.48),
    "KUTAHYA": (39.42, 29.98),
    "MALATYA": (38.35, 38.31),
    "MANISA": (38.62, 27.43),
    "MARDIN": (37.31, 40.74),
    "MERSIN": (36.81, 34.64),
    "MUGLA": (37.22, 28.36),
    "MUS": (38.73, 41.49),
    "NEVSEHIR": (38.62, 34.71),
    "NIGDE": (37.97, 34.68),
    "ORDU": (40.98, 37.88),
    "OSMANIYE": (37.07, 36.25),
    "RIZE": (41.02, 40.52),
    "SAKARYA": (40.78, 30.4),
    "SAMSUN": (41.29, 36.33),
    "SANLIURFA": (37.16, 38.8),
    "SIIRT": (37.93, 41.94),
    "SINOP": (42.03, 35.15),
    "SIRNAK": (37.52, 42.46),
    "SIVAS": (39.75, 37.02),
    "TEKIRDAG": (40.98, 27.51),
    "TOKAT": (40.31, 36.55),
    "TRABZON": (41.0, 39.72),
    "TUNCELI": (39.11, 39.55),
    "USAK": (38.68, 29.41),
    "VAN": (38.49, 43.38),
    "YALOVA": (40.66, 29.28),
    "YOZGAT": (39.82, 34.81),
    "ZONGULDAK": (41.46, 31.79),
}
"""İl merkezi enlem/boylam. 81 ilin tamamı tanımlı."""


def _haversine(bir: tuple[float, float], iki: tuple[float, float]) -> float:
    enlem1, boylam1 = map(math.radians, bir)
    enlem2, boylam2 = map(math.radians, iki)
    pay = (
        math.sin((enlem2 - enlem1) / 2) ** 2
        + math.cos(enlem1) * math.cos(enlem2) * math.sin((boylam2 - boylam1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(pay))


def mesafe_km(bir_il: str, iki_il: str) -> int | None:
    """İki il merkezi arasındaki yaklaşık karayolu mesafesi. Tanımsız il için None."""
    bir = KOORDINATLAR.get(yer_adi(bir_il))
    iki = KOORDINATLAR.get(yer_adi(iki_il))
    if bir is None or iki is None:
        return None
    return round(_haversine(bir, iki) * KARAYOLU_KATSAYISI)


def rota_km(baslangic: str, duraklar: list[str]) -> int | None:
    """Başlangıçtan sırayla bütün duraklara giden rotanın toplam uzunluğu."""
    noktalar = [baslangic, *duraklar]
    toplam = 0
    for onceki, sonraki in zip(noktalar, noktalar[1:]):
        adim = mesafe_km(onceki, sonraki)
        if adim is None:
            return None
        toplam += adim
    return toplam
