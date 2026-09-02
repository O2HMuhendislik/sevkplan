"""İç piyasa sevkiyat planlama motoru.

Ring planlamasından farkı: orada plan **ürün** etrafında kurulur (aynı SKU, tek depo,
coğrafya yok), burada plan **müşteri ve coğrafya** etrafında kurulur. Bu yüzden ayrı
bir motor; ortak olan tek şey `Teslimat` ve kapasite profilidir.

Üç sevkiyat tipi vardır (`SevkiyatTipi`):

* **FTL (`S`)** — bölgeye tam araç çıkacak hacim varsa. En fazla 5 durak, son uğrak
  aracın en az %15'ini kaplamalı, günde en fazla 35 araç.
* **Rutin / parsiyel (`R`)** — müşterinin *toplam* siparişi 3 paleti aşmıyorsa. Araç
  %50-60 dolulukta bırakılır, günde en fazla 3-4 araç.
* **Kargo (`K`)** — Incoterms EXW olanlar (müşteri ödemeli) ve müşteri toplamı 10
  desinin altında kalanlar. Araç kapasitesi aranmaz.

**Kırık palet neden burada toplanmıyor:** Ring'de aynı SKU farklı teslimatlardan
birleşip tek palet olabilir, çünkü hepsi aynı yere gider. İç piyasada her müşterinin
malı ayrı adrese indiği için kırık paletler birleşemez; müşteri bazında hesaplanan
anahtar değerler doğrudan toplanır.
"""
from __future__ import annotations

import enum
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from app.domain.bolgeler import il_bolgesi
from app.domain.iller import BOLUNEBILIR_DEPOLAR, ana_depo, mesafe, yer_adi
from app.domain.kapasite import KapasiteProfili
from app.domain.planlama import Teslimat, palet_hesapla


class SevkiyatTipi(str, enum.Enum):
    FTL = "FTL"
    RUTIN = "RUTIN"
    KARGO = "KARGO"

    @property
    def belge_kodu(self) -> str:
        return {"FTL": "S", "RUTIN": "R", "KARGO": "K"}[self.value]

    @property
    def ad(self) -> str:
        return {"FTL": "FTL (tam araç)", "RUTIN": "Rutin / parsiyel", "KARGO": "Kargo"}[
            self.value
        ]


@dataclass(frozen=True)
class Kurallar:
    """İç piyasa planlama sınırları. Hepsi sahadan alınan kurallardır."""

    rutin_palet_siniri: Decimal = Decimal(3)
    """Müşterinin toplam siparişi bu paleti aşmıyorsa rutin ile gidebilir."""
    kargo_desi_siniri: Decimal = Decimal(10)
    """Müşteri toplamı bu desinin altındaysa kargo."""
    exw_kargoya: bool = True
    """Incoterms EXW ise müşteri kendi taşır; kargo sayılır."""
    azami_durak: int = 5
    """FTL araçta en fazla kaç uğrama noktası olabilir."""
    son_ugrak_asgari_oran: Decimal = Decimal("0.15")
    """Son uğrak (en uzak il) aracın en az bu kadarını kaplamalı."""
    gunluk_ftl_siniri: int = 35
    gunluk_rutin_siniri: int = 4
    """Günlük araç sınırları; aşan hacim sonraki güne kalır."""


VARSAYILAN_KURALLAR = Kurallar()


@dataclass(frozen=True)
class MusteriSiparisi:
    """Bir müşterinin o günkü **tüm** siparişi.

    Sevkiyat tipi kararı (kargo / rutin / FTL) müşteri toplamı üzerinden verildiği için
    planlamanın atomik birimi teslimat değil, müşteridir. Bir müşterinin teslimatları
    birbirinden ayrılmaz: aynı adrese iki araç gitmez.
    """

    anahtar: str
    """Müşteriyi tekilleştiren değer; bayi adının normalize hâli."""
    bayi_adi: str
    il: str
    ilce: str
    teslimatlar: tuple[Teslimat, ...]
    palet: Decimal
    birim: Decimal
    """Tam palet ölçüsüyle anahtar değer: kırık palet bir palet gözü kaplar (FTL)."""
    desi: Decimal
    adet: Decimal
    agirlik: Decimal
    ham_birim: Decimal = Decimal(0)
    """Yuvarlamasız anahtar değer: parsiyel araçta paletler karışık istiflenir (rutin/kargo)."""
    incoterms: str = ""
    tir_girisi: str = "?"
    """E = tır girer, H = giremez, ? = geçmişten karar verilemedi."""

    def olcu(self, tip: "SevkiyatTipi") -> Decimal:
        """Aracı doldurma ölçüsü, sevkiyat tipine göre.

        FTL'de her müşterinin malı tam palet olarak yüklenir; kırık palet de bir palet
        gözü kaplar. Rutinde ve kargoda paletler karışık istiflendiği için yuvarlama
        yapılmaz — yoksa 3 parçalık bir sipariş tam palet sayılır ve araç 5 durakta
        dolmuş görünür (gerçekte rutin araçlar 25-30 durak yapıyor).
        """
        if tip is SevkiyatTipi.FTL:
            return self.birim
        return self.ham_birim or self.birim

    @property
    def bolge_kodu(self) -> str:
        return il_bolgesi(self.il)

    @property
    def uzaklik(self) -> int:
        """Eskişehir'e yaklaşık mesafe; tanımsız il en uzağa konur ki gözden kaçmasın."""
        return mesafe(self.il) if mesafe(self.il) is not None else 9999

    @property
    def satir_idleri(self) -> tuple[int, ...]:
        return tuple(sid for t in self.teslimatlar for sid in t.satir_idleri)

    @property
    def depolar(self) -> set[str]:
        return {t.depo_kodu for t in self.teslimatlar}

    @property
    def depo_katkilari(self) -> dict[str, Decimal]:
        toplamlar: dict[str, Decimal] = defaultdict(Decimal)
        for teslimat in self.teslimatlar:
            for depo_kodu, deger in teslimat.depo_katkilari.items():
                toplamlar[depo_kodu] += deger
        return dict(toplamlar)

    def alt_kume(self, teslimatlar: Sequence[Teslimat]) -> "MusteriSiparisi":
        """Aynı durağın bir kısım teslimatından oluşan yeni bir müşteri siparişi.

        Bir müşterinin toplamı tek aracı aştığında kullanılır: teslimatlar bölünmez ama
        müşteri birden çok araca dağıtılabilir. Desi, teslimat başına ölçülmediği için
        hacim payına göre dağıtılır — zaten kargo kararı bölmeden önce verilmiştir.
        """
        toplam = sum((t.birim for t in self.teslimatlar), Decimal(0)) or Decimal(1)
        pay = sum((t.birim for t in teslimatlar), Decimal(0)) / toplam
        return replace(
            self,
            teslimatlar=tuple(teslimatlar),
            palet=sum((t.palet for t in teslimatlar), Decimal(0)),
            birim=sum((t.birim for t in teslimatlar), Decimal(0)),
            ham_birim=sum((t.ham_anahtar for t in teslimatlar), Decimal(0)),
            adet=sum((t.miktar for t in teslimatlar), Decimal(0)),
            agirlik=sum((t.agirlik for t in teslimatlar), Decimal(0)),
            desi=(self.desi * pay).quantize(Decimal("0.001")),
        )


def _teslimat_olcusu(teslimat: Teslimat, tip: SevkiyatTipi) -> Decimal:
    return (
        teslimat.birim
        if tip is SevkiyatTipi.FTL
        else (teslimat.ham_anahtar or teslimat.birim)
    )


def teslimati_bol(
    teslimat: Teslimat,
    kapasite: Decimal,
    tip: SevkiyatTipi,
    palet_ici: Mapping[str, int] | None = None,
    yukleme_adeti: Mapping[str, int] | None = None,
) -> list[Teslimat]:
    """Araç kapasitesini aşan **bölünebilir** teslimatı araç boyutunda parçalara ayırır.

    Önce satırlar bütün hâlde yerleştirilir; bir satır tek başına sığmıyorsa miktarı
    kesilir. Kesim **tam palet** sınırında yapılır: 1000 adetlik bir siparişten araca
    800 adet (tam palet karşılığı) alınır, kalan 200 adet aynı teslimat numarasıyla
    beklemede kalır.

    Bölünemeyen ya da zaten sığan teslimat olduğu gibi döner.
    """
    if not teslimat.bolunebilir_mi or not teslimat.satir_miktarlari:
        return [teslimat]
    if _teslimat_olcusu(teslimat, tip) <= kapasite:
        return [teslimat]

    palet_ici = palet_ici or {}
    yukleme_adeti = yukleme_adeti or {}

    def satir_olcusu(sku: str, miktar: Decimal) -> Decimal:
        adet = yukleme_adeti.get(sku)
        if not adet:
            return Decimal(0)
        ici = palet_ici.get(sku)
        islenen = (
            palet_hesapla(miktar, ici) * ici
            if ici and tip is SevkiyatTipi.FTL
            else miktar
        )
        return Decimal(islenen) / Decimal(adet)

    def sigan_miktar(sku: str, kalan_kapasite: Decimal) -> Decimal:
        """Kalan boşluğa bu üründen kaç adet sığar? Tam palete yuvarlanır."""
        adet = yukleme_adeti.get(sku)
        if not adet or kalan_kapasite <= 0:
            return Decimal(0)
        ham = int(kalan_kapasite * Decimal(adet))
        ici = palet_ici.get(sku)
        if ici:
            return Decimal((ham // ici) * ici)
        return Decimal(ham)

    # Büyük satır önce: aracın çoğunu dolduran satır kesilmeye aday olsun.
    kalanlar = sorted(
        ((sid, sku, Decimal(miktar)) for sid, (sku, miktar) in teslimat.satir_miktarlari.items()),
        key=lambda k: (-satir_olcusu(k[1], k[2]), k[0]),
    )

    parcalar: list[dict[int, tuple[str, Decimal]]] = []
    while kalanlar:
        kutu: dict[int, tuple[str, Decimal]] = {}
        bos = kapasite
        yeni_kalanlar: list[tuple[int, str, Decimal]] = []
        for sid, sku, miktar in kalanlar:
            deger = satir_olcusu(sku, miktar)
            if deger <= bos:
                kutu[sid] = (sku, miktar)
                bos -= deger
                continue
            alinan = sigan_miktar(sku, bos)
            if alinan > 0:
                kutu[sid] = (sku, alinan)
                bos -= satir_olcusu(sku, alinan)
                yeni_kalanlar.append((sid, sku, miktar - alinan))
            else:
                yeni_kalanlar.append((sid, sku, miktar))
        if not kutu:
            # Tek palet bile sığmıyor: bölmek çözmüyor, teslimat olduğu gibi kalsın.
            return [teslimat]
        parcalar.append(kutu)
        kalanlar = yeni_kalanlar

    return [_teslimat_parcasi(teslimat, kutu, palet_ici, yukleme_adeti) for kutu in parcalar]


def _teslimat_parcasi(
    teslimat: Teslimat,
    satirlar: dict[int, tuple[str, Decimal]],
    palet_ici: Mapping[str, int],
    yukleme_adeti: Mapping[str, int],
) -> Teslimat:
    """Teslimatın bir parçası: ölçüler alınan miktarlara göre yeniden hesaplanır."""
    sku_miktarlari: dict[str, Decimal] = defaultdict(Decimal)
    for sku, miktar in satirlar.values():
        sku_miktarlari[sku] += miktar

    palet = anahtar = ham = Decimal(0)
    for sku, miktar in sku_miktarlari.items():
        ici = palet_ici.get(sku)
        adet = yukleme_adeti.get(sku)
        if ici:
            palet += palet_hesapla(miktar, ici)
        if adet:
            ham += miktar / Decimal(adet)
            islenen = palet_hesapla(miktar, ici) * ici if ici else miktar
            anahtar += Decimal(islenen) / Decimal(adet)

    toplam_miktar = sum(sku_miktarlari.values(), Decimal(0))
    oran = (
        toplam_miktar / Decimal(teslimat.miktar) if teslimat.miktar else Decimal(1)
    )
    return replace(
        teslimat,
        miktar=toplam_miktar,
        birim=anahtar or teslimat.birim * oran,
        palet=palet,
        anahtar=anahtar,
        ham_anahtar=ham,
        agirlik=(Decimal(teslimat.agirlik) * oran).quantize(Decimal("0.001")),
        sku_miktarlari=dict(sku_miktarlari),
        sku_kodlari=tuple(sorted(sku_miktarlari)),
        satir_idleri=tuple(sorted(satirlar)),
        satir_miktarlari=dict(satirlar),
        depo_katkilari={teslimat.depo_kodu: anahtar},
    )


def musteriyi_bol(
    musteri: MusteriSiparisi,
    tip: SevkiyatTipi,
    ust_limit: Decimal,
    palet_ici: Mapping[str, int] | None = None,
    yukleme_adeti: Mapping[str, int] | None = None,
) -> list[MusteriSiparisi]:
    """Tek aracı aşan müşteriyi araç boyutunda parçalara ayırır.

    Kural olarak bölünmez olan **teslimattır**, müşteri değil: 3,6 araçlık sipariş
    veren bir bayiye gerçekte de dört araç gider. Teslimatlar büyükten küçüğe
    yerleştirilir; tek başına aracı aşan bir teslimat kendi parçasında kalır ve o araç
    istisna olarak işaretlenir.

    Bayi ortak deposu (-1) teslimatları bunun istisnasıdır: miktarları araç
    kapasitesine göre kesilir (bkz. `teslimati_bol`).
    """
    if musteri.olcu(tip) <= ust_limit:
        return [musteri]

    def olcu(teslimat: Teslimat) -> Decimal:
        return _teslimat_olcusu(teslimat, tip)

    bolunmus: list[Teslimat] = []
    for teslimat in musteri.teslimatlar:
        bolunmus.extend(
            teslimati_bol(teslimat, ust_limit, tip, palet_ici, yukleme_adeti)
        )

    kutular: list[list[Teslimat]] = []
    toplamlar: list[Decimal] = []
    for teslimat in sorted(bolunmus, key=lambda t: (-olcu(t), t.teslimat_no)):
        deger = olcu(teslimat)
        for sira, toplam in enumerate(toplamlar):
            if toplam + deger <= ust_limit:
                kutular[sira].append(teslimat)
                toplamlar[sira] = toplam + deger
                break
        else:
            kutular.append([teslimat])
            toplamlar.append(deger)
    return [musteri.alt_kume(kutu) for kutu in kutular]


def tip_belirle(
    musteri: MusteriSiparisi, kurallar: Kurallar = VARSAYILAN_KURALLAR
) -> tuple[SevkiyatTipi, str]:
    """Müşterinin toplam siparişine bakarak sevkiyat tipini ve gerekçesini döner.

    Sıra önemlidir: önce kargoya düşenler ayrılır (taşımayı müşteri üstleniyor ya da
    hacim araç planlamayı hak etmiyor), sonra 3 palet kuralıyla rutin, kalan FTL.
    """
    if kurallar.exw_kargoya and musteri.incoterms.upper() == "EXW":
        return SevkiyatTipi.KARGO, "Incoterms EXW — taşımayı müşteri üstleniyor"
    if 0 < musteri.desi < kurallar.kargo_desi_siniri:
        return (
            SevkiyatTipi.KARGO,
            f"Müşteri toplamı {musteri.desi:.1f} desi; "
            f"{kurallar.kargo_desi_siniri} desi altındaki siparişler kargo ile gider",
        )
    if musteri.palet <= kurallar.rutin_palet_siniri:
        return (
            SevkiyatTipi.RUTIN,
            f"Müşteri toplamı {musteri.palet} palet; "
            f"{kurallar.rutin_palet_siniri} palet ve altı rutin ile gönderilebilir",
        )
    return SevkiyatTipi.FTL, f"Müşteri toplamı {musteri.palet} palet — tam araç"


# --------------------------------------------------------------------------- plan


@dataclass
class RotaPlani:
    """Bir araç. Duraklar Eskişehir'e uzaklığa göre sıralanır; en uzak il son uğraktır."""

    bolge_kodu: str
    tip: SevkiyatTipi
    profil: KapasiteProfili
    musteriler: list[MusteriSiparisi] = field(default_factory=list)
    alt_limit_esnetildi: bool = False
    istisna_asim: bool = False

    def musteri_olcusu(self, musteri: MusteriSiparisi) -> Decimal:
        return musteri.olcu(self.tip)

    @property
    def toplam_birim(self) -> Decimal:
        return sum((self.musteri_olcusu(m) for m in self.musteriler), Decimal(0))

    @property
    def toplam_palet(self) -> Decimal:
        return sum((m.palet for m in self.musteriler), Decimal(0))

    @property
    def toplam_adet(self) -> Decimal:
        return sum((m.adet for m in self.musteriler), Decimal(0))

    @property
    def toplam_agirlik(self) -> Decimal:
        return sum((m.agirlik for m in self.musteriler), Decimal(0))

    @property
    def toplam_desi(self) -> Decimal:
        return sum((m.desi for m in self.musteriler), Decimal(0))

    @property
    def bos_alan(self) -> Decimal:
        return self.profil.ust_limit - self.toplam_birim

    @property
    def doluluk_yuzdesi(self) -> Decimal:
        return self.profil.doluluk_yuzdesi(self.toplam_birim)

    @property
    def teslimatlar(self) -> list[Teslimat]:
        return [t for m in self.musteriler for t in m.teslimatlar]

    @property
    def sirali_musteriler(self) -> list[MusteriSiparisi]:
        """Yakından uzağa. Aracın yükleme ve boşaltma sırası budur."""
        return sorted(self.musteriler, key=lambda m: (m.uzaklik, m.il, m.bayi_adi))

    @property
    def duraklar(self) -> list[MusteriSiparisi]:
        return self.sirali_musteriler

    @property
    def durak_sayisi(self) -> int:
        return len(self.musteriler)

    @property
    def iller(self) -> list[str]:
        """Uğranan iller, yakından uzağa ve tekrarsız."""
        gorulen: list[str] = []
        for musteri in self.sirali_musteriler:
            if musteri.il not in gorulen:
                gorulen.append(musteri.il)
        return gorulen

    @property
    def ilceler(self) -> list[str]:
        gorulen: list[str] = []
        for musteri in self.sirali_musteriler:
            if musteri.ilce and musteri.ilce not in gorulen:
                gorulen.append(musteri.ilce)
        return gorulen

    @property
    def son_ugrak(self) -> str | None:
        iller = self.iller
        return iller[-1] if iller else None

    @property
    def son_ugrak_orani(self) -> Decimal:
        """Son uğrak ilindeki müşterilerin araçtaki payı."""
        toplam = self.toplam_birim
        if toplam <= 0 or self.son_ugrak is None:
            return Decimal(0)
        son = sum(
            (self.musteri_olcusu(m) for m in self.musteriler if m.il == self.son_ugrak),
            Decimal(0),
        )
        return son / toplam

    @property
    def depo_katkilari(self) -> dict[str, Decimal]:
        toplamlar: dict[str, Decimal] = defaultdict(Decimal)
        for musteri in self.musteriler:
            for depo_kodu, deger in musteri.depo_katkilari.items():
                toplamlar[depo_kodu] += deger
        return dict(toplamlar)

    @property
    def depolar(self) -> list[str]:
        return sorted({depo for m in self.musteriler for depo in m.depolar})

    @property
    def tir_giremeyen_musteriler(self) -> list[MusteriSiparisi]:
        return [m for m in self.musteriler if m.tir_girisi == "H"]

    def son_ugrak_uygun_mu(self, kurallar: Kurallar) -> bool:
        """Tek duraklı araçta kural aranmaz; son uğrak zaten aracın tamamıdır."""
        if len(self.iller) <= 1:
            return True
        return self.son_ugrak_orani >= kurallar.son_ugrak_asgari_oran

    def ekle(self, musteri: MusteriSiparisi) -> None:
        self.musteriler.append(musteri)

    def sigar_mi(self, musteri: MusteriSiparisi, kurallar: Kurallar) -> bool:
        if self.istisna_asim:
            return False
        if self.tip is SevkiyatTipi.FTL and self.durak_sayisi >= kurallar.azami_durak:
            return False
        return (
            self.toplam_birim + self.musteri_olcusu(musteri) <= self.profil.ust_limit
        )


@dataclass
class BekleyenMusteri:
    musteri: MusteriSiparisi
    tip: SevkiyatTipi
    sebep: str


@dataclass
class IcPiyasaSonucu:
    planlar: list[RotaPlani] = field(default_factory=list)
    bekleyenler: list[BekleyenMusteri] = field(default_factory=list)

    @property
    def musteri_sayisi(self) -> int:
        return sum(plan.durak_sayisi for plan in self.planlar)


def _bolgelere_ayir(
    musteriler: list[MusteriSiparisi],
) -> list[tuple[str, list[MusteriSiparisi]]]:
    gruplar: dict[str, list[MusteriSiparisi]] = defaultdict(list)
    for musteri in musteriler:
        gruplar[musteri.bolge_kodu].append(musteri)
    return sorted(gruplar.items())


def _paketle(
    grup: list[MusteriSiparisi],
    bolge_kodu: str,
    tip: SevkiyatTipi,
    profil: KapasiteProfili,
    kurallar: Kurallar,
    palet_ici: Mapping[str, int] | None = None,
    yukleme_adeti: Mapping[str, int] | None = None,
) -> list[RotaPlani]:
    """Bir bölgedeki müşterileri araçlara yerleştirir.

    Sıra: büyükten küçüğe, eşitlikte yakından uzağa. Böylece bir araç önce hacmi
    tutan müşteriyle kurulur, kalan yer aynı yöndeki küçük müşterilerle doldurulur.
    """
    planlar: list[RotaPlani] = []
    normal: list[MusteriSiparisi] = []
    for ham_musteri in grup:
        # Bir aracı aşan müşteri önce araç boyutunda parçalara ayrılır.
        for musteri in musteriyi_bol(
            ham_musteri, tip, profil.ust_limit, palet_ici, yukleme_adeti
        ):
            if musteri.olcu(tip) > profil.ust_limit:
                # Tek teslimat bile aracı aşıyor: bölünemez, istisna aracıyla gider.
                planlar.append(
                    RotaPlani(
                        bolge_kodu=bolge_kodu,
                        tip=tip,
                        profil=profil,
                        musteriler=[musteri],
                        istisna_asim=True,
                    )
                )
            else:
                normal.append(musteri)

    sirali = sorted(normal, key=lambda m: (-m.olcu(tip), m.uzaklik, m.bayi_adi))
    araclar: list[RotaPlani] = []
    for musteri in sirali:
        adaylar = [a for a in araclar if a.sigar_mi(musteri, kurallar)]
        if adaylar:
            # En dolu araca ekle (best-fit); eşitlikte rotası bu müşteriye en yakın olan.
            hedef = min(
                adaylar,
                key=lambda a: (
                    a.bos_alan,
                    abs(a.musteriler[0].uzaklik - musteri.uzaklik),
                    a.musteriler[0].bayi_adi,
                ),
            )
        else:
            hedef = RotaPlani(bolge_kodu=bolge_kodu, tip=tip, profil=profil)
            araclar.append(hedef)
        hedef.ekle(musteri)

    planlar.extend(araclar)
    return planlar


def _son_ugragi_duzelt(
    planlar: list[RotaPlani], kurallar: Kurallar
) -> tuple[list[RotaPlani], list[MusteriSiparisi]]:
    """Son uğrak %15 kuralını uygular.

    En uzak ildeki pay eşiğin altındaysa o ildeki müşteriler araçtan çıkarılır; navlun
    o mesafeye bu hacim için mantıklı olmaz. Çıkanlar havuza döner ve bir sonraki turda
    başka bir araca girebilir.
    """
    kalanlar: list[MusteriSiparisi] = []
    duzeltilmis: list[RotaPlani] = []
    for plan in planlar:
        while not plan.son_ugrak_uygun_mu(kurallar):
            son_il = plan.son_ugrak
            cikanlar = [m for m in plan.musteriler if m.il == son_il]
            plan.musteriler = [m for m in plan.musteriler if m.il != son_il]
            kalanlar.extend(cikanlar)
            if not plan.musteriler:
                break
        if plan.musteriler:
            duzeltilmis.append(plan)
    return duzeltilmis, kalanlar


def planla(
    musteriler: list[MusteriSiparisi],
    tip: SevkiyatTipi,
    profil: KapasiteProfili,
    kurallar: Kurallar = VARSAYILAN_KURALLAR,
    gunluk_sinir: int | None = None,
    kalanlari_zorla: bool = False,
    palet_ici: Mapping[str, int] | None = None,
    yukleme_adeti: Mapping[str, int] | None = None,
) -> IcPiyasaSonucu:
    """Verilen tipteki müşterileri araçlara böler.

    Kargo bir araç planlaması değildir: kapasite ve durak kuralları aranmaz, aynı
    bölgedeki kargo müşterileri tek bir kargo listesinde toplanır.

    `kalanlari_zorla` verilmezse alt limiti dolduramayan araçlar açılmaz; müşterileri
    beklemede kalır ve ertesi gün planlanır.
    """
    sonuc = IcPiyasaSonucu()
    if not musteriler:
        return sonuc

    if tip is SevkiyatTipi.KARGO:
        for bolge_kodu, grup in _bolgelere_ayir(musteriler):
            sonuc.planlar.append(
                RotaPlani(
                    bolge_kodu=bolge_kodu, tip=tip, profil=profil, musteriler=list(grup)
                )
            )
        return sonuc

    ham_planlar: list[RotaPlani] = []
    for bolge_kodu, grup in _bolgelere_ayir(musteriler):
        ham_planlar.extend(
            _paketle(grup, bolge_kodu, tip, profil, kurallar, palet_ici, yukleme_adeti)
        )

    if tip is SevkiyatTipi.FTL:
        ham_planlar, cikanlar = _son_ugragi_duzelt(ham_planlar, kurallar)
        for musteri in cikanlar:
            sonuc.bekleyenler.append(
                BekleyenMusteri(
                    musteri=musteri,
                    tip=tip,
                    sebep=(
                        "Son uğrak kuralı: bu müşteri aracın son durağı olurdu ve "
                        f"aracın %{kurallar.son_ugrak_asgari_oran * 100:.0f}'inden "
                        "azını kaplıyor"
                    ),
                )
            )

    uygunlar: list[RotaPlani] = []
    for plan in ham_planlar:
        if plan.istisna_asim or profil.gecerli_dolu(plan.toplam_birim):
            uygunlar.append(plan)
        elif kalanlari_zorla:
            plan.alt_limit_esnetildi = True
            uygunlar.append(plan)
        else:
            for musteri in plan.musteriler:
                sonuc.bekleyenler.append(
                    BekleyenMusteri(
                        musteri=musteri,
                        tip=tip,
                        sebep=(
                            "Yeterli hacim yok: kalan müşteriler "
                            f"{profil.alt_limit} {profil.olcu_adi} alt limitini "
                            "doldurmuyor"
                        ),
                    )
                )

    # En dolu araçlar önce planlanır; günlük sınıra takılan hacim ertesi güne kalır.
    uygunlar.sort(key=lambda p: (-p.toplam_birim, p.bolge_kodu))
    if gunluk_sinir is not None and len(uygunlar) > gunluk_sinir:
        for plan in uygunlar[gunluk_sinir:]:
            for musteri in plan.musteriler:
                sonuc.bekleyenler.append(
                    BekleyenMusteri(
                        musteri=musteri,
                        tip=tip,
                        sebep=(
                            f"Günlük {gunluk_sinir} araç sınırına ulaşıldı; "
                            "sonraki güne aktarılacak"
                        ),
                    )
                )
        uygunlar = uygunlar[:gunluk_sinir]

    sonuc.planlar = sorted(uygunlar, key=lambda p: (p.bolge_kodu, -p.toplam_birim))
    return sonuc


# ------------------------------------------------------------------ ortak yükleme

ORTAK_YUKLEME_DEPOLARI = {"64", "74", "-1"}
"""Aynı araca birlikte yüklenebilen depolar (bkz. docs/IC-PIYASA-ANALIZ.md §5)."""


def yukleme_deposu(plan: RotaPlani) -> str:
    """Aracın hangi depodan yükleneceği: anahtar değeri en yüksek olan **ana** depo.

    Ortak yüklemede araçta hangi depodan daha az ürün varsa, o ürünler başka bir
    araçla bu depoya getirilir. Bu aktarma için ayrı plan üretilmez; yükleme formuna
    "... depoya gönderilmelidir" notu düşülür.

    Marka sonekleri (64-V, 64-P) ayrı depo sayılmaz; hepsi 64 deposundadır.
    """
    toplamlar: dict[str, Decimal] = defaultdict(Decimal)
    for depo_kodu, deger in plan.depo_katkilari.items():
        toplamlar[ana_depo(depo_kodu)] += deger
    if not toplamlar:
        return ""
    return max(sorted(toplamlar), key=lambda depo: toplamlar[depo])


def aktarma_notu(satir_depo_kodu: str, yukleme_depo_kodu: str) -> str:
    """Satırın malı başka bir depodaysa yükleme formuna yazılacak not."""
    if not yukleme_depo_kodu or not satir_depo_kodu:
        return ""
    if ana_depo(satir_depo_kodu) == ana_depo(yukleme_depo_kodu):
        return ""
    return f"{ana_depo(yukleme_depo_kodu)} depoya gönderilmelidir"
