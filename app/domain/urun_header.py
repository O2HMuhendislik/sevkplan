"""SAP header kodu -> gerçek ürün kodu eşleştirmesi.

Vaillant'ın SAP sisteminde bazı ürünlerin **iki** stok kodu vardır: biri sipariş
girişinde/fiyatlamada kullanılan "header" kod, diğeri depodan fiilen çıkan ürünün
kendi kodu. Master datada header kod da bir ürün satırı olarak durur ama ismi
"... (Header)" / "..._header" gibi bitmesi dışında **ölçüsü yoktur** — palet içi
adet, kamyon/tır yükleme adeti, ağırlık, desi hepsi boş. Bir sipariş satırı header
koduyla gelirse ürün master datada bulunur ama yükleme adeti tanımsız olduğu için
teslimat HATALI'ya düşer ve hiç planlanamaz; sebep ekranda görünmediği sürece bu bir
veri hatası gibi değil, sistemin çalışmadığı gibi görünür.

Bu liste sahadan gelen header -> gerçek ürün eşleştirmesidir (kullanıcının verdiği
tablo) ve ayrıca gerçek master datadaki "(Header)" / "header" ekli ürün adlarının,
eki attıktan sonra **tek ve ayrımsız** eşleştiği başka ürünlerle otomatik doğrulanan
eşleştirmedir. Yalnızca şu iki koşuldan biri sağlanan çiftler buradadır:

  1. Kullanıcı tarafından doğrudan verildi (Nitromix Ioni, vintomiX/ademiX yeni nesil,
     isomiX, Atromix, MAXI PREMIX, Maxi Condense).
  2. Header ekini attıktan sonra master datada **birebir aynı isimde tek bir** ürün
     bulundu (ör. "Atromix P24 Header" -> "Atromix P24"); adı aynı iki ürün fiziken
     aynı üründür, risk taşımaz.

**Buraya girmeyenler:** climaVAIR / aroTHERM / A6 Inverter / A7 Inverter / Kion /
MaxiAir+ gibi header kodların çoğu **split ürün** (iç + dış ünite iki ayrı parça).
Header kod tek başına hangi tarafın ölçüsünü alacağını söylemez — biri seçilirse
fiziksel hacim yanlış hesaplanır. Bu kodlar bilerek dışarıda bırakıldı; gerçek
eşleştirme sahadan gelmeden eklenmemeli.

Yeni bir eşleşme geldiğinde (yeni ürün, yeni header kod) buraya bir satır eklemek
yeterlidir — `header_olculerini_tamamla` her ürün master data içe aktarımında
otomatik çalışır.
"""
from __future__ import annotations

HEADER_ESLESTIRME: dict[str, str] = {
    "10024055": "10019471",  # DEMIRDOKUM NITROMIX P 24 (DG) (HEP)
    "10024056": "10019472",  # DEMIRDOKUM NITROMIX P 28 (DG) (HEP)
    "10024057": "10019473",  # DEMIRDOKUM NITROMIX P 35 (DG) (HEP)
    "10025244": "10022843",  # Atromix P20
    "10025245": "10022844",  # Atromix P24
    "10025246": "10022845",  # Atromix P28
    "10035779": "10023826",  # L 275 F (H-TR)
    "10035780": "10023827",  # L 275 F (P-TR)
    "10035781": "10023828",  # L 350 F (H-TR)
    "10036738": "10027036",  # Atron Condense P 24-FC/3 (H-TR)
    "10036739": "10028063",  # Atron Condense P 20-FC/3 (H-TR)
    "10037216": "10025337",  # Maxi Premix 150
    "10037217": "10025338",  # Maxi Premix 100
    "10039646": "10025234",  # isomiX P 35-CS/1 (N-TR)
    "10039647": "10038407",  # ventomiX P 18/24 -AS/1 (H-TR)
    "10039648": "10038408",  # ventomiX P24/28 - AS/1 (H-TR)
    "10039649": "10038553",  # vintomiX P 18/24 –AS/1 (H-TR)
    "10039650": "10038554",  # vintomiX P 24/28 –AS/1 (H-TR)
    "10039651": "10038555",  # ademiX P 18/24 –AS/1 (H-TR)
    "10039652": "10038556",  # ademiX P 24/28 –AS/1 (H-TR)
    "10043996": "10021784",  # Maxi Condense 48 kW
    "10043997": "10021785",  # Maxi Condense 65 kW
    "10043998": "10024966",  # Maxi Condense 110 B
    "10043999": "10024968",  # Maxi Condense 150 B
    "8000015133": "10047150",  # Nitromix Ioni P24/26-CS/1 (N-TR)
    "8000015134": "10047151",  # Nitromix Ioni P28/36-CS/1 (N-TR)
    "8000015135": "10047152",  # Nitromix Ioni P34/36-CS/1 (N-TR)
    "8000044988": "8000013411",  # vintomiX P 28/28 –AS/2 (H-TR)
    "8000044996": "8000013403",  # ademiX P 24/24 –AS/2 (H-TR)
    "8000044997": "8000013390",  # ademiX P 28/28 –AS/2 (H-TR)
    "8000044998": "8000013402",  # vintomiX P 24/24 –AS/2 (H-TR)
}

OLCU_ALANLARI: tuple[str, ...] = (
    "urun_grubu",
    "palet_ici_adet",
    "kamyon_yukleme_adeti",
    "kamyon_palet",
    "tir_yukleme_adeti",
    "tir_palet",
    "agirlik",
    "desi",
    "m3",
    "palet_en",
    "palet_boy",
    "palet_yukseklik",
)
"""Header ürününe gerçek üründen kopyalanan alanlar. Ad ve kod kopyalanmaz — header
kendi adıyla ve kendi koduyla kalır, yalnızca planlama ölçüsünü ödünç alır."""


def _normalize(kod: str | None) -> str:
    return (kod or "").strip().lstrip("0") or "0"


def header_olculerini_tamamla(urunler: dict[str, "Urun"]) -> list[tuple[str, str]]:  # noqa: F821
    """Ölçüsüz header ürünlerine, eşleştiği gerçek üründen ölçü kopyalar.

    `urunler` urun_kodu -> Urun sözlüğüdür (ice_aktarim.urunleri_aktar'daki
    `mevcutlar`); DB'deki bütün ürünleri kapsar, yalnızca o an içe aktarılan dosyadaki
    satırları değil — böylece gerçek ürün başka bir yükleme ile daha önce girmiş
    olsa bile eşleştirme çalışır.

    Header ürününün **kendi** ölçüsü varsa (kullanıcı elle doldurduysa) dokunulmaz;
    `_doluyu_yaz`'ın izlediği "boş olan mevcut veriyi silmez" ilkesiyle tutarlıdır.
    Gerçek ürünün kendisi de ölçüsüzse (ikisi de eksikse) hiçbir şey yapılmaz —
    kopyalanacak bir ölçü yok.

    Döner: tamamlanan (header_kodu, gerçek_kodu) çiftleri.
    """
    kodlarla = {_normalize(kod): urun for kod, urun in urunler.items()}
    tamamlananlar: list[tuple[str, str]] = []
    for header_kodu, gercek_kodu in HEADER_ESLESTIRME.items():
        header = kodlarla.get(_normalize(header_kodu))
        gercek = kodlarla.get(_normalize(gercek_kodu))
        if header is None or gercek is None:
            continue
        if header.planlanabilir_mi or not gercek.planlanabilir_mi:
            continue
        for alan in OLCU_ALANLARI:
            deger = getattr(gercek, alan)
            if deger is not None:
                setattr(header, alan, deger)
        tamamlananlar.append((header.urun_kodu, gercek.urun_kodu))
    return tamamlananlar
