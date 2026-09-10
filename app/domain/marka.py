"""Marka çıkarımı ve plan bazında marka payı.

Navlun faturalarının markalar arasında dağıtılabilmesi için her planın hangi markadan
ne kadar taşıdığı bilinmelidir. Marka üç kaynaktan, bu sırayla okunur:

1. **Depo kodunun soneki** — `64-V` Vaillant, `64-P` Protherm. En kesin bilgi.
2. **Teslimat numarası** (normal depolar) — 006/6 ile başlayan teslimatlar Vaillant,
   2013 ile başlayanlar DemirDöküm ürünüdür. Sahanın kuralı; 2025 verisinin 123.000
   satırında doğrulandı: 006/6 teslimatlarda ürün adı Vaillant'a işaret eden 18.254
   satıra karşılık DemirDöküm'e işaret eden 79 satır var, 2013'lerde 25.565'e karşılık
   16.
3. **Bayi adı** (bayi ortak deposu, -1) — orada teslimat numarası marka taşımıyor;
   adı `P-` ile başlayan bayiler (P-Süha gibi) **Vaillant** bayisidir ve faturada
   Vaillant olarak görünmelidir. Aynı veride P- bayilerinde 2.415 Vaillant satırına
   karşılık 10 DemirDöküm satırı çıktı.

Pay, adet üzerinden değil **anahtar değer** (araçta kapladığı yer) üzerinden hesaplanır;
navlun da yer üzerinden oluştuğu için doğru dağıtım ölçüsü budur.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

VARSAYILAN_MARKA = "DEMİRDÖKÜM"

DEPO_SONEK_MARKALARI: dict[str, str] = {
    "V": "VAİLLANT",
    "P": "PROTHERM",
}
"""Depo kodunun son eki -> marka.

Sonu `-V` olan depolar Vaillant, `-P` olanlar Protherm, diğerleri DemirDöküm.
Navlun faturası her üçü için ayrı kesildiğinden fatura satırında da ayrı görünürler.
"""


BAYI_ORTAK_DEPOSU = "-1"

VAILLANT_BAYI_ONEKI = "P-"
"""Bayi ortak deposunda Vaillant bayisini gösteren ad öneki (P-Süha gibi).

Protherm'i **göstermez**: buradaki P bayi kodundan gelir, depo sonekindeki `-P` ile
karıştırılmamalı."""

VAILLANT_TESLIMAT_ONEKI = "6"
"""Baştaki sıfırlar atıldığında 6 ile başlayan teslimat numarası (006…, 6…)."""

DEMIRDOKUM_TESLIMAT_ONEKI = "2013"


def _teslimat_markasi(teslimat_no: str) -> str | None:
    """Teslimat numarasının işaret ettiği marka; belirsizse None."""
    numara = (teslimat_no or "").strip().lstrip("0")
    if numara.startswith(VAILLANT_TESLIMAT_ONEKI):
        return "VAİLLANT"
    if numara.startswith(DEMIRDOKUM_TESLIMAT_ONEKI):
        return VARSAYILAN_MARKA
    return None


def marka(
    depo_kodu: str, teslimat_no: str = "", bayi_adi: str = ""
) -> str:
    """Bir sipariş satırının markası.

    Sıra önemlidir: depo soneki en kesin bilgidir (mal zaten o markanın deposundan
    çıkıyor), sonra bayi ortak deposunun bayi öneki, sonra teslimat numarası.
    """
    kod = (depo_kodu or "").strip().upper()
    if "-" in kod:
        sonek = kod.rsplit("-", 1)[1]
        if sonek in DEPO_SONEK_MARKALARI:
            return DEPO_SONEK_MARKALARI[sonek]
    if kod == BAYI_ORTAK_DEPOSU:
        # Bayi ortak deposunda teslimat numarası marka taşımıyor; bayi adı taşıyor.
        if (bayi_adi or "").strip().upper().startswith(VAILLANT_BAYI_ONEKI):
            return "VAİLLANT"
        return VARSAYILAN_MARKA
    return _teslimat_markasi(teslimat_no) or VARSAYILAN_MARKA


def paylari_hesapla(katkilar: dict[str, Decimal]) -> dict[str, Decimal]:
    """{depo kodu: anahtar değer} -> {marka: oran}. Oranlar toplamı 1,00'dir.

    Yalnızca depo kodu bilinen yerlerde (ihracat) kullanılır; iç piyasa ve Ring
    planları marka katkılarını satır bazında taşır, bkz. `marka_paylari`.
    """
    marka_toplamlari: dict[str, Decimal] = {}
    for depo_kodu, deger in katkilar.items():
        ad = marka(depo_kodu)
        marka_toplamlari[ad] = marka_toplamlari.get(ad, Decimal(0)) + Decimal(deger)
    return _oranla(marka_toplamlari)


def marka_paylari(katkilar: dict[str, Decimal]) -> dict[str, Decimal]:
    """{marka: anahtar değer} -> {marka: oran}. Katkılar satır bazında toplanmıştır."""
    return _oranla({ad: Decimal(deger) for ad, deger in katkilar.items()})


def _oranla(marka_toplamlari: dict[str, Decimal]) -> dict[str, Decimal]:
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
