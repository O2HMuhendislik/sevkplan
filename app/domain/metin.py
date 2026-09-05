"""Türkçe metin yardımcıları.

Python'un `str.upper()` metodu Türkçe değildir: `'i'` harfini `'I'`, `'ı'` harfini
yine `'I'` yapar. Türkçede bunlar iki ayrı harftir — `i → İ`, `ı → I`. Ürün grubu
gibi alanlar bu yüzden ikiye bölünüyordu: dosyada "Klima" yazan kayıt `KLIMA`,
"KLİMA" yazan kayıt `KLİMA` olarak saklanıyor ve ekranda iki ayrı grup görünüyordu.
"""
from __future__ import annotations

_BUYUK = str.maketrans("iıçğöşü", "İIÇĞÖŞÜ")
_KUCUK = str.maketrans("IİÇĞÖŞÜ", "ıiçğöşü")


def buyuk_harf(deger: object) -> str:
    """Türkçe kurallarına göre büyük harfe çevirir: 'Klima' -> 'KLİMA'."""
    if deger is None:
        return ""
    return str(deger).strip().translate(_BUYUK).upper()


def kucuk_harf(deger: object) -> str:
    """Türkçe kurallarına göre küçük harfe çevirir: 'KLİMA' -> 'klima'."""
    if deger is None:
        return ""
    return str(deger).strip().translate(_KUCUK).lower()
