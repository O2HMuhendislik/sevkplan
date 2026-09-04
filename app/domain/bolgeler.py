"""Sevkiyat bölgeleri.

İç piyasa FTL planlaması **bölge bazlıdır**: bir araca yalnızca aynı bölgedeki
müşteriler yüklenir. Aşağıdaki bölgeler uydurma değil, geçmiş FTL planlarından
çıkarıldı: iki il "aynı rotada" sayıldı ancak en az 8 planda birlikte **ve** küçük
olanın planlarının en az %20'sinde birlikte gittiyse (bkz.
`scripts/ic_piyasa_analiz.py`, `docs/IC-PIYASA-ANALIZ.md`).

Bu tablo başlangıç değeridir; bölgeler master data ekranından düzenlenebilir ve
veritabanındaki kayıt bu tablonun önüne geçer.

**Bilinen eksik:** 5 numaralı bölge 29 il içeriyor. Doğu, Güneydoğu, Akdeniz ve İç
Anadolu rotaları zincirleme birbirine bağlandığı için otomatik ayrılamadı; bölge
ekrandan elle bölünecek. Planlama bu arada da çalışır — bir bölgenin içinde araçlar
Eskişehir'e uzaklığa göre kurulduğu için birbirine yakın iller yine aynı araca düşer.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.iller import yer_adi


@dataclass(frozen=True)
class Bolge:
    kod: str
    ad: str
    iller: tuple[str, ...]


VARSAYILAN_BOLGELER: tuple[Bolge, ...] = (
    Bolge("B01", "Marmara / Batı Karadeniz", (
        "ISTANBUL", "KOCAELI", "SAKARYA", "TEKIRDAG", "EDIRNE", "KIRKLARELI",
        "DUZCE", "BOLU", "ZONGULDAK", "BARTIN", "KARABUK", "KASTAMONU",
    )),
    Bolge("B02", "Ankara ve çevresi", ("ANKARA", "CANKIRI")),
    Bolge("B03", "Ege", ("IZMIR", "MANISA")),
    Bolge("B04", "Güney Marmara", ("BALIKESIR", "BURSA", "CANAKKALE")),
    Bolge("B05", "Doğu / Güneydoğu / Akdeniz", (
        "ADANA", "ADIYAMAN", "AGRI", "AKSARAY", "BATMAN", "BINGOL", "DIYARBAKIR",
        "ELAZIG", "ERZINCAN", "ERZURUM", "GAZIANTEP", "HATAY", "IGDIR",
        "KAHRAMANMARAS", "KAYSERI", "KILIS", "KIRSEHIR", "KONYA", "MALATYA",
        "MARDIN", "MERSIN", "MUS", "NEVSEHIR", "NIGDE", "OSMANIYE", "SANLIURFA",
        "SIRNAK", "SIVAS", "VAN",
    )),
    Bolge("B06", "İç Ege", ("AFYONKARAHISAR", "AYDIN", "DENIZLI", "MUGLA", "USAK")),
    Bolge("B07", "Akdeniz Batı", ("ANTALYA", "BURDUR", "ISPARTA")),
    Bolge("B08", "Karadeniz", (
        "SAMSUN", "ORDU", "GIRESUN", "TRABZON", "RIZE", "SINOP", "CORUM",
    )),
    Bolge("B09", "Bilecik", ("BILECIK",)),
    Bolge("B10", "Eskişehir", ("ESKISEHIR",)),
    Bolge("B11", "Yozgat", ("YOZGAT",)),
    Bolge("B12", "Kütahya", ("KUTAHYA",)),
    Bolge("B13", "Tokat", ("TOKAT",)),
    Bolge("B14", "Hakkâri", ("HAKKARI",)),
    Bolge("B15", "Amasya", ("AMASYA",)),
    Bolge("B16", "Yalova", ("YALOVA",)),
    Bolge("B17", "Bayburt", ("BAYBURT",)),
    Bolge("B18", "Bitlis", ("BITLIS",)),
    Bolge("B19", "Kırıkkale", ("KIRIKKALE",)),
    Bolge("B20", "Siirt", ("SIIRT",)),
    Bolge("B21", "Tunceli", ("TUNCELI",)),
    Bolge("B22", "Artvin", ("ARTVIN",)),
    Bolge("B23", "Gümüşhane", ("GUMUSHANE",)),
    Bolge("B24", "Karaman", ("KARAMAN",)),
    Bolge("B25", "Kars / Ardahan", ("KARS", "ARDAHAN")),
)

BOLGE_HARITASI = {bolge.kod: bolge for bolge in VARSAYILAN_BOLGELER}

IL_BOLGELERI: dict[str, str] = {
    il: bolge.kod for bolge in VARSAYILAN_BOLGELER for il in bolge.iller
}

TANIMSIZ_BOLGE = "B00"
"""Bölgesi belirlenemeyen iller. Planlamada kendi aralarında birleşmezler."""


def il_bolgesi(il: str) -> str:
    """İlin bölge kodu. Tanımsız il kendi adıyla tek başına bölge olur.

    Tanımsız ili başka illerle aynı torbaya atmak yanlış rota kurar; bu yüzden il
    adının kendisi bölge kodu olarak kullanılır ve yalnız kalır.
    """
    ad = yer_adi(il)
    if not ad:
        return TANIMSIZ_BOLGE
    return IL_BOLGELERI.get(ad, f"IL:{ad}")


def bolge_adi(kod: str) -> str:
    """Bölge kodunun ekranda görünen adı.

    Parsiyel planların kodu bölge değil aktarma merkezidir: `AKT:ANKARA|64`
    ("Ankara aktarma · 64/-1 deposu").
    """
    bolge = BOLGE_HARITASI.get(kod)
    if bolge is not None:
        return bolge.ad
    if kod.startswith("AKT:"):
        from app.domain.aktarma import merkez_adi

        merkez, _, depo_grubu = kod[4:].partition("|")
        ad = f"{merkez_adi(merkez)} aktarma"
        depolar = {"64": "64/-1 deposu", "74": "74 deposu"}
        return f"{ad} · {depolar.get(depo_grubu, depo_grubu)}" if depo_grubu else ad
    if kod.startswith("IL:"):
        return kod[3:].title()
    return "Bölgesiz"
