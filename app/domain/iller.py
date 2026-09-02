"""İl mesafe ve bölge tablosu.

"Son uğrak en az %15 hacim" kuralının uygulanabilmesi için bir plandaki durakların
sıralanması gerekir: en uzak il son uğraktır. Yüklemeler **Eskişehir** (depo 64 ve
bayi ortak deposu -1) ile **Bozüyük** (34, 44, 74 ve varyantları) çıkışlıdır; iki
tesis birbirine yaklaşık 80 km uzaklıkta olduğu için tek bir mesafe tablosu yeterlidir.

**Mesafeler yaklaşıktır** (karayolu, km). Amaç kesin navlun hesabı değil, illerin
birbirine göre sıralanmasıdır; sıralama ±50 km hatadan etkilenmez. Yine de master data
ekranından düzenlenebilir olacak — sahadaki gerçek rota mesafeleri girildiğinde tablo
güncellenmelidir.
"""
from __future__ import annotations

_TR_ASCII = str.maketrans("ıİşŞğĞüÜöÖçÇâÂîÎûÛ", "iIsSgGuUoOcCaAiIuU")

IL_ESANLAMLILARI = {
    "AFYON": "AFYONKARAHISAR",
    "K.MARAS": "KAHRAMANMARAS",
    "KMARAS": "KAHRAMANMARAS",
    "URFA": "SANLIURFA",
    "ICEL": "MERSIN",
}
"""Kaynak dosyalarda kullanılan kısaltmaların resmî il adı karşılığı."""


def yer_adi(deger: object) -> str:
    """İl/ilçe adını tek biçime indirger.

    Kaynak veride aynı il hem 'ISTANBUL' hem 'İSTANBUL' geçiyor; Türkçe karakterler
    ASCII karşılığına çevrilip büyük harfe alınmazsa aynı il iki ayrı il gibi sayılıyor
    ve bölge/rota hesapları bölünüyor.
    """
    if deger is None:
        return ""
    ad = str(deger).strip().translate(_TR_ASCII).upper()
    return IL_ESANLAMLILARI.get(ad, ad)


ESKISEHIR_MESAFELERI: dict[str, int] = {
    "ESKISEHIR": 0, "BILECIK": 80, "KUTAHYA": 80, "AFYONKARAHISAR": 145,
    "BURSA": 155, "USAK": 220, "SAKARYA": 220, "ANKARA": 235, "YALOVA": 250,
    "KOCAELI": 250, "BALIKESIR": 260, "DUZCE": 260, "KIRIKKALE": 290,
    "BOLU": 300, "ISTANBUL": 320, "DENIZLI": 340, "BURDUR": 340,
    "KONYA": 350, "MANISA": 350, "KIRSEHIR": 350, "ISPARTA": 360,
    "CANKIRI": 360, "AYDIN": 400, "IZMIR": 400, "CANAKKALE": 400,
    "AKSARAY": 400, "TEKIRDAG": 400, "KARABUK": 400, "ZONGULDAK": 400,
    "ANTALYA": 420, "YOZGAT": 430, "CORUM": 440, "KASTAMONU": 440,
    "KIRKLARELI": 450, "MUGLA": 450, "NEVSEHIR": 450, "BARTIN": 450,
    "KARAMAN": 480, "NIGDE": 480, "AMASYA": 490, "EDIRNE": 500,
    "KAYSERI": 550, "TOKAT": 570, "SINOP": 570, "ADANA": 610,
    "MERSIN": 620, "SAMSUN": 620, "OSMANIYE": 680, "SIVAS": 700,
    "ORDU": 720, "HATAY": 760, "KAHRAMANMARAS": 750, "GIRESUN": 780,
    "GAZIANTEP": 830, "TRABZON": 850, "KILIS": 880, "ERZINCAN": 890,
    "MALATYA": 900, "RIZE": 900, "GUMUSHANE": 940, "ADIYAMAN": 950,
    "BAYBURT": 990, "SANLIURFA": 990, "ELAZIG": 1000, "TUNCELI": 1050,
    "ERZURUM": 1080, "DIYARBAKIR": 1100, "ARTVIN": 1140, "BINGOL": 1150,
    "BATMAN": 1180, "MARDIN": 1180, "MUS": 1230, "SIIRT": 1260,
    "BITLIS": 1290, "AGRI": 1310, "KARS": 1330, "ARDAHAN": 1370,
    "SIRNAK": 1300, "IGDIR": 1420, "VAN": 1420, "HAKKARI": 1520,
}

BOZUYUK_FARKI = 80
"""Bozüyük tesisi Eskişehir'e yaklaşık bu kadar uzaktır (km); sıralamayı değiştirmez."""

ESKISEHIR_DEPOLARI = {"64", "64-D", "64-V", "64-P", "-1"}
"""Eskişehir'den yüklenen depolar. Diğerleri (34, 44, 74 ...) Bozüyük'ten yüklenir."""

MARKA_SONEKLERI = ("V", "P", "D")
"""Depo kodunun sonundaki marka harfleri: 64-V, 64-P, 64-D hepsi 64 deposundadır."""


def ana_depo(depo_kodu: str) -> str:
    """Marka sonekini atarak ana depo kodunu döner: '64-V' -> '64', '-1' -> '-1'.

    Sonek malın hangi markaya ait olduğunu söyler (bkz. app/domain/marka.py), ayrı bir
    fiziki depo anlamına gelmez. Ortak yüklemede aktarma notu ana depoya göre yazılır:
    64-V'deki mal 64'e "gönderilmez", zaten oradadır.
    """
    kod = (depo_kodu or "").strip().upper()
    govde, ayirac, sonek = kod.rpartition("-")
    if ayirac and govde and sonek in MARKA_SONEKLERI:
        return govde
    return kod


def mesafe(il: str) -> int | None:
    """İlin Eskişehir'e yaklaşık karayolu mesafesi. Tanımsız il için None."""
    return ESKISEHIR_MESAFELERI.get(yer_adi(il))


def yukleme_tesisi(depo_kodu: str) -> str:
    return "ESKİŞEHİR" if (depo_kodu or "").strip().upper() in ESKISEHIR_DEPOLARI else "BOZÜYÜK"


def duraklari_sirala(iller: list[str]) -> list[str]:
    """Durakları yakından uzağa sıralar; sonuncusu 'son uğrak' olur.

    Mesafesi tanımsız iller en sona alınır ki gözden kaçmasınlar.
    """
    return sorted(iller, key=lambda il: (mesafe(il) is None, mesafe(il) or 0, il))


def son_ugrak(iller: list[str]) -> str | None:
    sirali = duraklari_sirala(iller)
    return sirali[-1] if sirali else None
