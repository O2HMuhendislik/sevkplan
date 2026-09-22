"""İstanbul'un iki yakası: Avrupa ve Anadolu.

FTL araçlarda araç durak sırasıyla kapı kapı dolaşır; bir aracın Boğaz'ı geçip
tekrar geçmesi hem köprü/tünel ücretini hem trafik süresini katlıyor. Sahanın
kuralı: **bir FTL aracında İstanbul'un yalnızca tek bir yakasından müşteri olur.**
İstanbul dışındaki iller bu kuraldan etkilenmez — yalnızca `il` İstanbul olan
müşteriye bir yaka atanır, geri kalan her şey `None` (yakasız) kalır ve hiçbir
şeyle çakışmaz.

İlçe adı kaynak dosyalarda dağınık geliyor: bazen mahalle eklenmiş
("ÜMRANİYE-YUKARI DUDULLU"), bazen il tekrar edilmiş ("KARTAL / İSTANBUL"), bazen
yalnızca mahalle yazılmış ("4.LEVENT"), bazen eski/hatalı yazım kullanılmış
("EYÜP", "BEYLUKDÜZÜ"). `yaka()` önce 39 ilçenin tam adını arar, sonra "-" ve "/"
ile ayrılmış parçaları tek tek dener, son olarak sık görülen birkaç mahalle/eski ad
takma adına bakar. Hiçbiri tutmazsa yaka **bilinmez** sayılır — kural yalnızca iki
yaka da kesin biliniyorsa araca engel çıkarır, tanımsız ilçe hiçbir aracı bloklamaz.
"""
from __future__ import annotations

from app.domain.iller import yer_adi

ISTANBUL_ILI = "ISTANBUL"

AVRUPA = "AVRUPA"
ANADOLU = "ANADOLU"

YAKA_ADLARI = {AVRUPA: "Avrupa Yakası", ANADOLU: "Anadolu Yakası"}

_AVRUPA_ILCELERI = (
    "ARNAVUTKOY", "AVCILAR", "BAGCILAR", "BAHCELIEVLER", "BAKIRKOY",
    "BASAKSEHIR", "BAYRAMPASA", "BESIKTAS", "BEYLIKDUZU", "BEYOGLU",
    "BUYUKCEKMECE", "CATALCA", "ESENLER", "ESENYURT", "EYUPSULTAN", "FATIH",
    "GAZIOSMANPASA", "GUNGOREN", "KAGITHANE", "KUCUKCEKMECE", "SARIYER",
    "SILIVRI", "SULTANGAZI", "SISLI", "ZEYTINBURNU",
)
"""25 ilçe — resmî liste. `yer_adi` ile ASCII'ye çevrilmiş, büyük harf hâli."""

_ANADOLU_ILCELERI = (
    "ADALAR", "ATASEHIR", "BEYKOZ", "CEKMEKOY", "KADIKOY", "KARTAL",
    "MALTEPE", "PENDIK", "SANCAKTEPE", "SULTANBEYLI", "SILE", "TUZLA",
    "UMRANIYE", "USKUDAR",
)
"""14 ilçe. Adalar vapurla Kadıköy/Bostancı'ya bağlanır, idari olarak Anadolu'dadır."""

_ILCE_YAKASI: dict[str, str] = {
    **{ilce: AVRUPA for ilce in _AVRUPA_ILCELERI},
    **{ilce: ANADOLU for ilce in _ANADOLU_ILCELERI},
}

_TAKMA_ADLAR: dict[str, str] = {
    # Eski/hatalı yazımlar — kaynak dosyada iki farklı yazım aynı ilçeyi gösteriyor.
    "EYUP": "EYUPSULTAN",
    "BEYLUKDUZU": "BEYLIKDUZU",
    # Yalnızca mahalle yazılan, ilçesi kaynak veride hiç geçmeyen sık örnekler.
    "LEVENT": "BESIKTAS",
    "4.LEVENT": "BESIKTAS",
    "GUNESLI": "BAGCILAR",
    "SIRINEVLER": "BAHCELIEVLER",
    "KASIMPASA": "BEYOGLU",
    "HADIMKOY": "ARNAVUTKOY",
}


def _ilceyi_coz(ham_ilce: str) -> str | None:
    """Dağınık ilçe metninden bilinen ilçe adını çıkarır; bulamazsa None döner."""
    ilce = yer_adi(ham_ilce).strip(" ./-")
    if not ilce:
        return None
    if ilce in _ILCE_YAKASI:
        return ilce
    if ilce in _TAKMA_ADLAR:
        return _TAKMA_ADLAR[ilce]
    # "ÜMRANİYE-YUKARI DUDULLU", "KARTAL / İSTANBUL", "İÇERENKÖY / ATAŞEHİR" gibi
    # değerler: mahalle ya da il adıyla birleşmiş. Her parçayı sırayla dene; ilk
    # eşleşen ilçe kazanır. Parça sırası kaynağa göre değiştiği için ikisi de denenir.
    for ayrac in ("-", "/"):
        if ayrac not in ilce:
            continue
        for parca in ilce.split(ayrac):
            parca = parca.strip()
            if parca in _ILCE_YAKASI:
                return parca
            if parca in _TAKMA_ADLAR:
                return _TAKMA_ADLAR[parca]
    return None


def yaka(il: str, ilce: str) -> str | None:
    """Müşterinin İstanbul yakası; İstanbul dışındaki iller için her zaman None.

    Dönen değer bilinmiyorsa (`ilce` boş, tanınmayan bir yazım) None döner —
    bu, kuralın o müşteriye **uygulanamadığı**, hiçbir aracı bloklamadığı anlamına
    gelir. Kural yalnızca iki yaka da kesin biliniyorsa devreye girer.
    """
    if yer_adi(il) != ISTANBUL_ILI:
        return None
    cozulen = _ilceyi_coz(ilce or "")
    return _ILCE_YAKASI.get(cozulen) if cozulen else None
