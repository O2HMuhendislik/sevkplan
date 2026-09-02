"""Sistemdeki modüllerin tanımı.

Her modül ayrı bir ekran grubudur ve kullanıcılara ayrı ayrı yetkilendirilir. Yeni bir
modül eklerken buraya bir kayıt eklemek yeterlidir: modül seçim ekranında kartı çıkar,
kullanıcı yönetiminde yetki satırı açılır.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Modul:
    kod: str
    ad: str
    aciklama: str
    yol: str
    simge: str
    hazir: bool = True
    """Hazır olmayan modüller seçim ekranında 'yakında' olarak gösterilir."""


MODULLER: tuple[Modul, ...] = (
    Modul(
        kod="RING",
        ad="Ring Planlama",
        aciklama=(
            "Depo çıkışlı ring sevkiyatlarının araç bazında planlanması, sefer "
            "numarası atanması ve yükleme formunun hazırlanması."
        ),
        yol="/ring",
        simge="🚚",
    ),
    Modul(
        kod="ROTA",
        ad="İç Piyasa Sevkiyat Planlama",
        aciklama=(
            "FTL, rutin/parsiyel ve kargo sevkiyatlarının müşteri ve bölge bazında "
            "planlanması; durak sırası, son uğrak kuralı ve ortak yükleme."
        ),
        yol="/rota",
        simge="🗺️",
    ),
    Modul(
        kod="IHRACAT",
        ad="İhracat Planlama",
        aciklama="Yurt dışı sevkiyatların konteyner ve araç planlaması.",
        yol="/ihracat",
        simge="🌍",
        hazir=False,
    ),
    Modul(
        kod="ARAC_TALEP",
        ad="Araç Talep ve Tedarik",
        aciklama=(
            "Planlanan seferler için araç talebi açma, sözleşmeli nakliyecilerin "
            "araç bildirmesi ve atama."
        ),
        yol="/arac-talep",
        simge="📋",
        hazir=False,
    ),
    Modul(
        kod="RAPORLAMA",
        ad="Raporlama",
        aciklama=(
            "Bütün modüllerin siparişleri tek ekranda; modüle göre filtrelenir. "
            "Siparişin plana alınma süresi (KPI) burada izlenir."
        ),
        yol="/raporlama",
        simge="📊",
    ),
    Modul(
        kod="MASTERDATA",
        ad="Master Data",
        aciklama="Ürün tanımları, palet ve araç kapasite bilgileri. Modüllerin ortak verisi.",
        yol="/urunler",
        simge="📦",
    ),
    Modul(
        kod="YONETIM",
        ad="Sistem Yönetimi",
        aciklama="Kullanıcılar, yetkiler ve veri yönetimi.",
        yol="/yonetim/kullanicilar",
        simge="⚙️",
    ),
)

MODUL_HARITASI = {modul.kod: modul for modul in MODULLER}


def modul(kod: str) -> Modul:
    return MODUL_HARITASI[kod]
