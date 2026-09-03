"""İhracat sevkiyat planlama motoru.

İç piyasadan iki temel farkı var:

* **Araç tek noktaya gider.** 2025 verisinde planların %98,3'ü tek müşterilidir; rota,
  durak sırası ve son uğrak kuralı yoktur. Plan = bir müşteri + bir araç.
* **Kapasite iki boyutludur:** hacim ve ağırlık (kg). Hangisi önce dolarsa araç
  dolmuş sayılır. Ağırlık sınırı müşteriye göre değişir (marka kılavuzundaki "azami
  tonaj"); verilmemişse araç tipinin varsayılanı kullanılır.

Hacim, şirketin `Hesaplama.xlsx` dosyasındaki formülle ölçülür::

    DOLULUK = Σ ( miktar / yükleme adeti )      1,00 = araç %100 dolu

Yükleme adeti araç tipine göre ayrıdır (tır / konteyner) ve müşterinin hesap sürümüne
göre iki set hâlinde tutulur (yeni / eski). Palet yükseltmeli yüklemede sonuç 1,2'ye
bölünür. Hesabın kendisi `app/domain/ihracat_hesap.py` içindedir.

Taşıma modu müşteriden gelir: konteyner yüklenen müşteri **deniz**, tır yüklenen
**kara** yoludur. Sefer numarasının belge kodu da müşteriye bağlıdır — `N` (NSC) ya da
`E` (Export); geçmiş veride ikisi birebir bu alana göre ayrışıyor.
"""
from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass, field, replace
from decimal import Decimal

from app.domain.ihracat_hesap import VARSAYILAN_KURAL, YuklemeKurali
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
master datasında "maksimum tonaj" doluysa o değer bunun önüne geçer — notu "TONAJ
ÖNEMLİ" olan müşterilerde aracı dolduran sınır zaten ağırlıktır.
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
    doluluk: Decimal
    """Planlamanın ölçüsü: Σ(miktar / yükleme adeti). 1,00 = bir araç dolusu."""
    desi: Decimal
    agirlik: Decimal
    adet: Decimal
    palet: Decimal = Decimal(0)
    """Σ(miktar / palet içi adet) — yükleme formunda gösterilir, kapasiteyi belirlemez."""
    kural: YuklemeKurali = VARSAYILAN_KURAL
    """Hangi hesap sürümü ve istif biçimi; doluluk buna göre hesaplandı."""
    olcusuz_kodlar: tuple[str, ...] = ()
    """Yükleme adeti master datada olmayan SKU'lar; desiden yaklaşık hesaplandı."""
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
            doluluk=(self.doluluk * pay).quantize(Decimal("0.000001")),
            desi=(self.desi * pay).quantize(Decimal("0.001")),
            agirlik=(self.agirlik * pay).quantize(Decimal("0.001")),
            palet=(self.palet * pay).quantize(Decimal("0.001")),
            adet=sum((t.miktar for t in teslimatlar), Decimal(0)),
        )


@dataclass
class IhracatPlani:
    """Bir ihracat aracı: tek müşteri, tek varış noktası."""

    musteri: MusteriYuku
    teslimatlar: list[Teslimat] = field(default_factory=list)
    hacim: Decimal = Decimal(0)
    """Aracın doluluk değeri: Σ(miktar / yükleme adeti)."""
    desi: Decimal = Decimal(0)
    agirlik: Decimal = Decimal(0)
    adet: Decimal = Decimal(0)
    palet: Decimal = Decimal(0)
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
        return (self.hacim / ust) if ust else Decimal(0)

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

    def ekle(self, teslimat: Teslimat) -> None:
        self.teslimatlar.append(teslimat)
        self.hacim += teslimat.anahtar
        self.desi += teslimat.desi
        self.agirlik += teslimat.agirlik
        self.palet += teslimat.palet
        self.adet += teslimat.miktar

    def sigar_mi(self, teslimat: Teslimat) -> bool:
        return (
            self.hacim + teslimat.anahtar <= self.profil.ust_limit
            and self.agirlik + teslimat.agirlik <= self.musteri.agirlik_kapasitesi
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
            musteri.doluluk >= profil.alt_limit
            or musteri.agirlik >= musteri.agirlik_kapasitesi * profil.alt_limit
        )
        if not yeterli and not kalanlari_zorla:
            sonuc.bekleyenler.append(
                BekleyenYuk(
                    musteri=musteri,
                    sebep=(
                        "Yeterli hacim yok: müşteri toplamı "
                        f"%{musteri.doluluk * 100:.1f} araç, alt limit "
                        f"%{profil.alt_limit * 100:.0f}"
                    ),
                )
            )
            continue
        for plan in _musteriyi_paketle(musteri):
            plan.alt_limit_esnetildi = not yeterli
            sonuc.planlar.append(plan)
    return sonuc


def _musteriyi_paketle(musteri: MusteriYuku) -> list[IhracatPlani]:
    """Müşterinin teslimatlarını araçlara yerleştirir (büyükten küçüğe).

    Teslimatın doluluk payı (`anahtar`), desisi ve ağırlığı satır bazında zaten
    hesaplanmıştır; burada yalnızca araçlara dağıtılırlar.
    """
    ust_limit = PROFILLER[musteri.arac_tipi].ust_limit
    planlar: list[IhracatPlani] = []
    sirali = sorted(musteri.teslimatlar, key=lambda t: (-t.anahtar, t.teslimat_no))
    for teslimat in sirali:
        asiyor = (
            teslimat.anahtar > ust_limit
            or teslimat.agirlik > musteri.agirlik_kapasitesi
        )
        if asiyor:
            # Tek teslimat aracı aşıyor: bölünemez, istisna aracıyla gider.
            plan = IhracatPlani(musteri=musteri, istisna_asim=True)
            plan.ekle(teslimat)
            planlar.append(plan)
            continue
        hedef = next(
            (p for p in planlar if not p.istisna_asim and p.sigar_mi(teslimat)), None
        )
        if hedef is None:
            hedef = IhracatPlani(musteri=musteri)
            planlar.append(hedef)
        hedef.ekle(teslimat)
    return planlar
