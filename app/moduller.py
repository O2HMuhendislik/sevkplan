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
    """`simgeler.html` içindeki çizim adı — kart üstünde SVG olarak çizilir."""
    renk: str
    """Kurumsal palet adı (`style.css` içindeki `.modul-kart[data-renk=...]`).

    Her modülün kendi rengi var; kullanıcı kartı okumadan hangi modül olduğunu
    renginden tanısın diye. Renkler Vaillant Group kartelasından seçildi.
    """
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
        simge="kamyon",
        renk="yesil",
    ),
    Modul(
        kod="ROTA",
        ad="İç Piyasa Sevkiyat Planlama",
        aciklama=(
            "FTL, rutin/parsiyel ve kargo sevkiyatlarının müşteri ve bölge bazında "
            "planlanması; durak sırası, son uğrak kuralı ve ortak yükleme."
        ),
        yol="/rota",
        simge="rota",
        renk="lacivert",
    ),
    Modul(
        kod="IHRACAT",
        ad="İhracat Planlama",
        aciklama=(
            "Yurt dışı sevkiyatların müşteri bazında araç planlaması. Tek noktaya "
            "giden tır ve konteyner; doluluk şirketin hesaplama dosyasındaki yükleme "
            "adetlerinden, ikinci sınır olarak ağırlıktan ölçülür."
        ),
        yol="/ihracat",
        simge="dunya",
        renk="mavi",
    ),
    Modul(
        kod="ARAC_TALEP",
        ad="Araç Talep ve Tedarik",
        aciklama=(
            "Planlanan seferler için araç talebi açma, sözleşmeli nakliyecilerin "
            "araç bildirmesi ve atama."
        ),
        yol="/arac-talep",
        simge="liste",
        renk="sari",
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
        simge="grafik",
        renk="mor",
    ),
    Modul(
        kod="MASTERDATA",
        ad="Master Data",
        aciklama=(
            "Modüllerin ortak verisi tek yerde: ürün ölçüleri, iç piyasa ve ihracat "
            "müşterileri, depo tanımları ve planlama sayıları. Listeler sütundan "
            "süzülür, süzülen liste indirilip doldurulup geri yüklenir."
        ),
        yol="/masterdata",
        simge="katman",
        renk="bej",
    ),
    Modul(
        kod="YONETIM",
        ad="Sistem Yönetimi",
        aciklama="Kullanıcılar, yetkiler ve veri yönetimi.",
        yol="/yonetim/kullanicilar",
        simge="ayar",
        renk="gri",
    ),
)

MODUL_HARITASI = {modul.kod: modul for modul in MODULLER}


def modul(kod: str) -> Modul:
    return MODUL_HARITASI[kod]
