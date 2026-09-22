"""100 cm ve 120 cm panel radyatörlerin birlikte yüklenince kazandırdığı ek kapasite.

Panel radyatör ürün adı uzunluğu üç haneli kodla taşır: `"22-600 100CMV010_B1A1G1
_13"` 100 cm, `"22-600 120CMV010_B1A1G1 _13"` aynı ailenin (aynı panel tipi/yüksekliği)
120 cm'lik hâlidir. Aynı ailenin 100 ve 120 cm'lik parçaları **birlikte** yüklenince
farklı boyları birbirinin içine geçirerek istiflemek mümkün oluyor; standart
yükleme adeti bunu hesaba katmıyor, çünkü palet bazlı ve karışık yüklemeye göre
kalibre edilmiş.

**Kanıt** (gerçekleşen sevk verisi, 2026): yalnızca aynı aile 100+120 cm panelden
oluşan, başka ürün taşımayan 7 gerçek tır seferi bulundu — hepsi standart anahtar
değer hesabının **üzerinde**: %103,2 – %113,2 (medyan %113,2). Örneklem küçük ve
tamamı "22-600" ailesinden (tek müşteriye toplu sevkiyat); başka panel
ailelerinde (300/400/500/900 mm gibi) aynı etkinin var olduğu doğrulanmadı, ama
mekanizma (aynı yükseklikte farklı boyun içine geçmesi) aileye özgü değil, bu
yüzden kural bütün ailelere uygulanıyor. Bonus, gözlenen en düşük değerin (1,032)
altında kalacak şekilde temkinli seçildi; `Kurallar.panel_bonusu` ayarından
büyütülüp küçültülebilir.

**Kural dar tutuldu:** araçtaki **bütün** SKU'lar aynı ailenin 100 ve 120 cm
parçası olmalı — başka bir panel boyu ya da başka bir ürün grubu karışırsa bonus
uygulanmaz. Yedi örneğin hepsi de tek aileden, saf yüklemeydi; karışık yükte aynı
etkinin geçerli olduğuna dair kanıt yok.
"""
from __future__ import annotations

PANEL_UZUNLUKLARI = ("100", "120")
"""Bonusa giren iki uzunluk. Ailedeki başka bir uzunluk (60, 90, 140 ...) varsa
kural devre dışı kalır — yalnızca bu ikisinin birlikteliği doğrulandı."""


def panel_uzunlugu(urun_adi: str | None) -> str | None:
    """Ürün adından panel uzunluğu (100/120); eşleşmiyorsa None."""
    ad = urun_adi or ""
    for uzunluk in PANEL_UZUNLUKLARI:
        if f"{uzunluk}CMV" in ad:
            return uzunluk
    return None


def panel_ailesi(urun_adi: str | None) -> str | None:
    """Uzunluk hariç geri kalanı aynı olan ürünleri aynı aileye sokan anahtar.

    `"22-600 100CMV..."` ile `"22-600 120CMV..."` aynı aileyi döner; farklı
    yükseklikteki (`"22-500 100CMV..."`) panel ayrı bir ailedir.
    """
    uzunluk = panel_uzunlugu(urun_adi)
    if uzunluk is None:
        return None
    return (urun_adi or "").replace(f"{uzunluk}CMV", "XCMV")


def bonus_haritasi(urunler: dict) -> dict[str, tuple[str, str]]:
    """{urun_kodu: (aile_anahtari, uzunluk)} — yalnızca 100/120 cm panel SKU'ları.

    `urunler` urun_kodu -> Urun sözlüğüdür (ice_aktarim/plan_uret'teki gibi).
    """
    harita: dict[str, tuple[str, str]] = {}
    for kod, urun in urunler.items():
        uzunluk = panel_uzunlugu(getattr(urun, "urun_adi", None))
        if uzunluk is None:
            continue
        aile = panel_ailesi(urun.urun_adi)
        if aile:
            harita[kod] = (aile, uzunluk)
    return harita


def bonus_uygun_mu(sku_kodlari, harita: dict[str, tuple[str, str]]) -> bool:
    """Verilen SKU kümesi tek bir panel ailesinin 100 ve 120 cm parçalarından mı oluşuyor?

    Boş küme ya da haritada olmayan (bonusa girmeyen) tek bir SKU bile varsa False —
    kural yalnızca **saf** 100+120 cm yüklemede işler.
    """
    kodlar = list(sku_kodlari)
    if not kodlar:
        return False
    aileler: set[str] = set()
    uzunluklar: set[str] = set()
    for kod in kodlar:
        eslesme = harita.get(kod)
        if eslesme is None:
            return False
        aile, uzunluk = eslesme
        aileler.add(aile)
        uzunluklar.add(uzunluk)
    return len(aileler) == 1 and uzunluklar == set(PANEL_UZUNLUKLARI)
