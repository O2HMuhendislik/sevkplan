"""Depo kodundan marka çıkarımı ve plan bazında marka payı.

Navlun faturalarının markalar arasında dağıtılabilmesi için her planın hangi markadan
ne kadar taşıdığı bilinmelidir. Marka, ürünün yüklendiği **depo kodundan** okunur:
kodun sonundaki harf markayı verir.

Pay, adet üzerinden değil **anahtar değer** (araçta kapladığı yer) üzerinden hesaplanır;
navlun da yer üzerinden oluştuğu için doğru dağıtım ölçüsü budur.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

VARSAYILAN_MARKA = "DEMİRDÖKÜM"

DEPO_SONEK_MARKALARI: dict[str, str] = {
    "V": "VAİLLANT",
    "P": "VAİLLANT",
}
"""Depo kodunun son eki -> marka.

Sahadaki kural: sonu `-V` ya da `-P` olan depolar Vaillant, diğerleri DemirDöküm.
Yükleme formunda PROTHERM ayrı bir satır olarak da görünüyor; ayrı izlenmesi
istenirse `"P": "PROTHERM"` yapmak yeterli.
"""


def marka(depo_kodu: str) -> str:
    kod = (depo_kodu or "").strip().upper()
    if "-" in kod:
        sonek = kod.rsplit("-", 1)[1]
        if sonek in DEPO_SONEK_MARKALARI:
            return DEPO_SONEK_MARKALARI[sonek]
    return VARSAYILAN_MARKA


def paylari_hesapla(katkilar: dict[str, Decimal]) -> dict[str, Decimal]:
    """{depo kodu: anahtar değer} -> {marka: oran}. Oranlar toplamı 1,00'dir."""
    marka_toplamlari: dict[str, Decimal] = {}
    for depo_kodu, deger in katkilar.items():
        ad = marka(depo_kodu)
        marka_toplamlari[ad] = marka_toplamlari.get(ad, Decimal(0)) + Decimal(deger)
    toplam = sum(marka_toplamlari.values(), Decimal(0))
    if toplam <= 0:
        return {}
    return {
        ad: (deger / toplam).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        for ad, deger in sorted(marka_toplamlari.items())
    }


def paylari_metne_cevir(paylar: dict[str, Decimal]) -> str:
    """Veritabanında saklanan biçim: 'DEMİRDÖKÜM:0.2500|VAİLLANT:0.7500'."""
    return "|".join(f"{ad}:{oran}" for ad, oran in sorted(paylar.items()))


def paylari_coz(metin: str | None) -> dict[str, Decimal]:
    if not metin:
        return {}
    paylar: dict[str, Decimal] = {}
    for parca in metin.split("|"):
        ad, _, oran = parca.partition(":")
        if ad and oran:
            paylar[ad] = Decimal(oran)
    return paylar
