"""İhracat sevkiyat planlama motoru.

İç piyasadan iki temel farkı var:

* **Araç tek noktaya gider.** 2025 verisinde planların %98,3'ü tek müşterilidir; rota,
  durak sırası ve son uğrak kuralı yoktur. Plan = bir müşteri + bir araç.
* **Kapasite iki boyutludur:** hacim (desi) ve ağırlık (kg). Hangisi önce dolarsa araç
  dolmuş sayılır. Ağırlık sınırı müşteriye göre değişir (marka kılavuzundaki "azami
  tonaj"); verilmemişse araç tipinin varsayılanı kullanılır.

Taşıma modu müşteriden gelir: konteyner yüklenen müşteri **deniz**, tır yüklenen
**kara** yoludur. Sefer numarasının belge kodu da müşteriye bağlıdır — `N` (NSC) ya da
`E` (Export); geçmiş veride ikisi birebir bu alana göre ayrışıyor.
"""
from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass, field, replace
from decimal import Decimal

from app.domain.kapasite import IHRACAT_KONTEYNER, IHRACAT_TIR, KapasiteProfili
from app.domain.planlama import Teslimat


class AracTipi(str, enum.Enum):
    TIR = "TIR"
    KONTEYNER = "KONTEYNER"
    PARSIYEL = "PARSİYEL"
    KARGO = "KARGO"

    @property
    def deniz_mi(self) -> bool:
        return self is AracTipi.KONTEYNER

    @property
    def tasima_modu(self) -> str:
        return "DENİZ" if self.deniz_mi else "KARA"

    @property
    def ad(self) -> str:
        return {
            "TIR": "Tır (karayolu)",
            "KONTEYNER": "Konteyner (deniz yolu)",
            "PARSİYEL": "Parsiyel",
            "KARGO": "Kargo",
        }[self.value]


PROFILLER: dict[AracTipi, KapasiteProfili] = {
    AracTipi.TIR: IHRACAT_TIR,
    AracTipi.KONTEYNER: IHRACAT_KONTEYNER,
    AracTipi.PARSIYEL: IHRACAT_TIR,
    AracTipi.KARGO: IHRACAT_TIR,
}

AGIRLIK_KAPASITELERI: dict[AracTipi, Decimal] = {
    AracTipi.TIR: Decimal(22000),
    AracTipi.KONTEYNER: Decimal(19500),
    AracTipi.PARSIYEL: Decimal(22000),
    AracTipi.KARGO: Decimal(22000),
}
"""Araç tipinin varsayılan ağırlık sınırı (kg).

2025 sevklerinin yüzdeliklerinden: tır kg p90 ≈ 21.300, konteyner ≈ 19.250. Müşteri
master datasında "azami tonaj" doluysa o değer bunun önüne geçer.
"""

SEFER_KODLARI = ("N", "E")
"""Sefer numarasının belge kodu: N = NSC, E = Export. Müşteri bazında belirlenir."""


def arac_tipi_coz(ham: str) -> AracTipi:
    """Kaynak dosyalardaki serbest metni araç tipine indirger.

    Sahada '1X40 DC', '1X40 HC', 'Konteyner' hepsi konteyner demek; 'PARSİYEL' ve
    'DHL' ayrı tiplerdir.
    """
    buyuk = (ham or "").strip().upper()
    if any(isaret in buyuk for isaret in ("KONTEYNER", "40", "20", "HC", "DC")):
        return AracTipi.KONTEYNER
    if "PARS" in buyuk:
        return AracTipi.PARSIYEL
    if buyuk in {"DHL", "KARGO", "UPS"}:
        return AracTipi.KARGO
    return AracTipi.TIR


@dataclass(frozen=True)
class Kurallar:
    """İhracat planlama sınırları."""

    gunluk_arac_siniri: int | None = None
    """Günlük araç sınırı yok; alan ileride gerekirse diye duruyor."""
    asgari_doluluk: Decimal = Decimal("0.75")
    """Alt limitin altındaki araç açılmaz; kalan hacim sonraki güne kalır."""


VARSAYILAN_KURALLAR = Kurallar()


@dataclass(frozen=True)
class MusteriYuku:
    """Bir ihracat müşterisinin o günkü siparişi.

    Araç tek noktaya gittiği için planlamanın birimi doğrudan müşteridir; iç piyasadaki
    gibi bölge ve durak hesabı yoktur.
    """

    anahtar: str
    musteri_adi: str
    ulke: str
    ulke_kodu: str
    sevk_adresi: str
    teslimatlar: tuple[Teslimat, ...]
    desi: Decimal
    agirlik: Decimal
    adet: Decimal
    arac_tipi: AracTipi = AracTipi.TIR
    sefer_kodu: str = "E"
    yukleme_tipi: str = ""
    """STANDART / PALET YÜKSELTME / DÖKME / KÖŞEBENT ... yükleme formuna yazılır."""
    aciklama: str = ""
    """Müşteriye özel not: hava yastığı, silika jel, paletsiz dökme ..."""
    azami_agirlik: Decimal | None = None
    incoterms: str = ""

    @property
    def profil(self) -> KapasiteProfili:
        return PROFILLER[self.arac_tipi]

    @property
    def agirlik_kapasitesi(self) -> Decimal:
        return self.azami_agirlik or AGIRLIK_KAPASITELERI[self.arac_tipi]

    @property
    def satir_idleri(self) -> tuple[int, ...]:
        return tuple(sid for t in self.teslimatlar for sid in t.satir_idleri)

    @property
    def depolar(self) -> set[str]:
        return {t.depo_kodu for t in self.teslimatlar}

    @property
    def depo_katkilari(self) -> dict[str, Decimal]:
        """Depo -> desi. Marka payı (navlun dağıtımı) buradan hesaplanır."""
        toplamlar: dict[str, Decimal] = defaultdict(Decimal)
        for teslimat in self.teslimatlar:
            pay = teslimat.anahtar or Decimal(1)
            for depo_kodu in {teslimat.depo_kodu}:
                toplamlar[depo_kodu] += pay
        return dict(toplamlar)

    def alt_kume(self, teslimatlar: list[Teslimat]) -> "MusteriYuku":
        """Müşterinin bir kısım teslimatından oluşan yeni yük."""
        toplam = sum((t.anahtar for t in self.teslimatlar), Decimal(0)) or Decimal(1)
        pay = sum((t.anahtar for t in teslimatlar), Decimal(0)) / toplam
        return replace(
            self,
            teslimatlar=tuple(teslimatlar),
            desi=(self.desi * pay).quantize(Decimal("0.001")),
            agirlik=(self.agirlik * pay).quantize(Decimal("0.001")),
            adet=sum((t.miktar for t in teslimatlar), Decimal(0)),
        )


@dataclass
class IhracatPlani:
    """Bir ihracat aracı: tek müşteri, tek varış noktası."""

    musteri: MusteriYuku
    teslimatlar: list[Teslimat] = field(default_factory=list)
    desi: Decimal = Decimal(0)
    agirlik: Decimal = Decimal(0)
    adet: Decimal = Decimal(0)
    alt_limit_esnetildi: bool = False
    istisna_asim: bool = False

    @property
    def profil(self) -> KapasiteProfili:
        return self.musteri.profil

    @property
    def arac_tipi(self) -> AracTipi:
        return self.musteri.arac_tipi

    @property
    def hacim_doluluk(self) -> Decimal:
        ust = self.profil.ust_limit
        return (self.desi / ust) if ust else Decimal(0)

    @property
    def agirlik_doluluk(self) -> Decimal:
        ust = self.musteri.agirlik_kapasitesi
        return (self.agirlik / ust) if ust else Decimal(0)

    @property
    def doluluk(self) -> Decimal:
        """Hangi sınır önce dolduysa araç o kadar doludur."""
        return max(self.hacim_doluluk, self.agirlik_doluluk)

    @property
    def doluluk_yuzdesi(self) -> Decimal:
        return (self.doluluk * 100).quantize(Decimal("0.01"))

    @property
    def kisitlayan(self) -> str:
        """Aracı dolduran sınır — planlamacının hangi ölçüye baktığını bilmesi için."""
        return "AĞIRLIK" if self.agirlik_doluluk > self.hacim_doluluk else "HACİM"

    @property
    def depolar(self) -> list[str]:
        return sorted({t.depo_kodu for t in self.teslimatlar})

    @property
    def depo_katkilari(self) -> dict[str, Decimal]:
        toplamlar: dict[str, Decimal] = defaultdict(Decimal)
        for teslimat in self.teslimatlar:
            for depo_kodu, deger in (
                teslimat.depo_katkilari or {teslimat.depo_kodu: Decimal(1)}
            ).items():
                toplamlar[depo_kodu] += deger
        return dict(toplamlar)

    def ekle(self, teslimat: Teslimat, desi: Decimal, agirlik: Decimal) -> None:
        self.teslimatlar.append(teslimat)
        self.desi += desi
        self.agirlik += agirlik
        self.adet += teslimat.miktar

    def sigar_mi(self, desi: Decimal, agirlik: Decimal) -> bool:
        return (
            self.desi + desi <= self.profil.ust_limit
            and self.agirlik + agirlik <= self.musteri.agirlik_kapasitesi
        )


@dataclass
class BekleyenYuk:
    musteri: MusteriYuku
    sebep: str


@dataclass
class IhracatSonucu:
    planlar: list[IhracatPlani] = field(default_factory=list)
    bekleyenler: list[BekleyenYuk] = field(default_factory=list)


def planla(
    musteriler: list[MusteriYuku],
    kurallar: Kurallar = VARSAYILAN_KURALLAR,
    kalanlari_zorla: bool = False,
) -> IhracatSonucu:
    """Her müşteriyi kendi araçlarına böler.

    Müşterinin yükü bir aracı aşıyorsa teslimatlar birden çok araca dağıtılır —
    teslimat bölünmez, araç sayısı artar. Tek başına aracı aşan bir teslimat kendi
    aracında kalır ve plan istisna olarak işaretlenir.

    Alt limit **araç başına değil müşteri toplamına** uygulanır. Sorulan soru şu:
    "bu müşteriye bugün araç kaldırmaya değer mi?" Cevap evetse araç sayısını
    teslimatların bölünmezliği belirler — üç teslimatı ikişer ikişer birleştiremiyorsak
    üç araç çıkar ve bunların yarım kalması kaçınılmazdır, kuralın ihlali değildir.
    Müşterinin toplamı alt limitin altındaysa hepsi beklemede kalır ve hacim birikince
    planlanır; `kalanlari_zorla` bu sınırı atlar.
    """
    sonuc = IhracatSonucu()
    for musteri in sorted(musteriler, key=lambda m: (m.ulke, m.musteri_adi)):
        profil = musteri.profil
        yeterli = (
            musteri.desi >= profil.alt_limit
            or musteri.agirlik >= musteri.agirlik_kapasitesi * Decimal("0.75")
        )
        if not yeterli and not kalanlari_zorla:
            sonuc.bekleyenler.append(
                BekleyenYuk(
                    musteri=musteri,
                    sebep=(
                        f"Yeterli hacim yok: müşteri toplamı {musteri.desi:.0f} desi, "
                        f"alt limit {profil.alt_limit} desi"
                    ),
                )
            )
            continue
        for plan in _musteriyi_paketle(musteri):
            plan.alt_limit_esnetildi = not yeterli
            sonuc.planlar.append(plan)
    return sonuc


def _musteriyi_paketle(musteri: MusteriYuku) -> list[IhracatPlani]:
    """Müşterinin teslimatlarını araçlara yerleştirir (büyükten küçüğe)."""
    toplam_anahtar = (
        sum((t.anahtar for t in musteri.teslimatlar), Decimal(0)) or Decimal(1)
    )

    def olculer(teslimat: Teslimat) -> tuple[Decimal, Decimal]:
        """Teslimatın desi ve ağırlık payı."""
        pay = (teslimat.anahtar or Decimal(0)) / toplam_anahtar
        return musteri.desi * pay, musteri.agirlik * pay

    planlar: list[IhracatPlani] = []
    sirali = sorted(
        musteri.teslimatlar, key=lambda t: (-olculer(t)[0], t.teslimat_no)
    )
    for teslimat in sirali:
        desi, agirlik = olculer(teslimat)
        if desi > PROFILLER[musteri.arac_tipi].ust_limit or agirlik > musteri.agirlik_kapasitesi:
            # Tek teslimat aracı aşıyor: bölünemez, istisna aracıyla gider.
            plan = IhracatPlani(musteri=musteri, istisna_asim=True)
            plan.ekle(teslimat, desi, agirlik)
            planlar.append(plan)
            continue
        hedef = next((p for p in planlar if not p.istisna_asim and p.sigar_mi(desi, agirlik)), None)
        if hedef is None:
            hedef = IhracatPlani(musteri=musteri)
            planlar.append(hedef)
        hedef.ekle(teslimat, desi, agirlik)
    return planlar
