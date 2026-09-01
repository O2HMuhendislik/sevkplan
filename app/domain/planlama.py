"""Sevkiyat planlama motoru.

Saf iş mantığı: veritabanı, Excel veya web katmanını tanımaz. Girdi olarak teslimat
listesi alır, çıktı olarak taslak planları ve planlanamayan (bekleyen) teslimatları
döner. Bu sayede kurallar tek başına test edilebilir.

Hedef sırası:
  1. Aracı doldurmak — kapasite ölçüsü (anahtar değer) üst limite yaklaşmalı.
  2. **Tam palet** yüklemek — kırık palet israfı en aza inmeli, depoda elleçleme azalsın.
  3. Planı mümkün olduğunca tek ürün kodunda tutmak; dolmuyorsa aynı ürün grubu
     içinde karışık plana izin vermek.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.domain.kapasite import KapasiteProfili


@dataclass(frozen=True)
class Teslimat:
    """Planlamanın atomik birimi. Asla bölünmez."""

    teslimat_no: str
    depo_kodu: str
    planlama_anahtari: str
    """Faz 1'de planın saf kalacağı anahtar; genelde ürün kodu."""
    urun_kodu: str
    urun_adi: str
    miktar: Decimal
    birim: Decimal
    """Teslimatın tek başına kapasite büyüklüğü."""
    oncelik_tarihi: date
    satir_idleri: tuple[int, ...] = ()
    sku_kodlari: tuple[str, ...] = ()
    sku_miktarlari: dict[str, Decimal] = field(default_factory=dict)
    """SKU -> miktar kırılımı. Palet ve israf hesabı bunun üzerinden yapılır."""
    urun_grubu: str = ""
    """Faz 2'de karışık plana izin verilen kapsam."""
    palet: Decimal = Decimal(0)
    anahtar: Decimal = Decimal(0)
    agirlik: Decimal = Decimal(0)
    """Raporlama için; planlama yalnızca `birim` alanını kullanır."""

    @property
    def kodlar(self) -> tuple[str, ...]:
        return self.sku_kodlari or (self.urun_kodu,)

    def __post_init__(self) -> None:
        if self.birim <= 0:
            raise ValueError(
                f"{self.teslimat_no}: kapasite büyüklüğü sıfır veya negatif olamaz"
            )


def palet_hesapla(miktar: Decimal, palet_ici_adet: int) -> Decimal:
    """Kırık palet bir tam palet sayılır: yarım palet de bir palet gözü kaplar."""
    if palet_ici_adet <= 0:
        raise ValueError("palet içi adet sıfır veya negatif olamaz")
    return Decimal(math.ceil(Decimal(miktar) / Decimal(palet_ici_adet)))


def _sku_toplamlari(teslimatlar: Sequence[Teslimat]) -> dict[str, Decimal]:
    toplamlar: dict[str, Decimal] = defaultdict(Decimal)
    for teslimat in teslimatlar:
        for sku, miktar in teslimat.sku_miktarlari.items():
            toplamlar[sku] += miktar
    return toplamlar


class BirimHesaplayici(Protocol):
    """Bir plandaki teslimatların toplam kapasite büyüklüğünü hesaplar."""

    def __call__(self, teslimatlar: Sequence[Teslimat]) -> Decimal: ...


def toplam_birim(teslimatlar: Sequence[Teslimat]) -> Decimal:
    """Toplanabilir ölçüler (anahtar değer) için: teslimat büyüklüklerinin toplamı."""
    return sum((t.birim for t in teslimatlar), Decimal(0))


@dataclass(frozen=True)
class PaletBirimi:
    """Palet sayısını **plan bazında** hesaplar.

    Aynı SKU'nun farklı teslimatlardaki miktarları önce toplanır, sonra palete
    yuvarlanır: palet içi adedi 16 olan bir üründen 13 + 3 adet, iki kırık palet yerine
    tek dolu palet kaplar.
    """

    palet_ici: Mapping[str, int]

    def __call__(self, teslimatlar: Sequence[Teslimat]) -> Decimal:
        palet = Decimal(0)
        for sku, miktar in _sku_toplamlari(teslimatlar).items():
            adet = self.palet_ici.get(sku)
            if adet:
                palet += palet_hesapla(miktar, adet)
        return palet


@dataclass(frozen=True)
class AnahtarBirimi:
    """Anahtar değeri **işgal edilen palet** üzerinden hesaplar.

    Ham miktar / yükleme adeti oranı yanıltıcıdır: kırık bir palet araçta yarım yer
    kaplamaz, tam bir palet gözü kaplar. Bu yüzden her SKU'nun plandaki toplam miktarı
    önce palete yuvarlanır, sonra anahtar değere çevrilir.

        birim = Σ  yukarı_yuvarla(miktar / palet içi) x palet içi / tır yükleme adeti

    Örnek: palet içi 15, tır yükleme adeti 360 (= 24 tam palet) olan bir üründen
    305 adet, ham oranla 0,847 görünür ama 21 palet gözü kaplar ve gerçek karşılığı
    0,875'tir. Böylece motor 305 yerine 300 adetlik (20 tam palet) bileşimi seçer.

    Palet içi adedi tanımsız ürünlerde ham oran kullanılır.
    """

    palet_ici: Mapping[str, int]
    yukleme_adeti: Mapping[str, int]

    def __call__(self, teslimatlar: Sequence[Teslimat]) -> Decimal:
        toplam = Decimal(0)
        for sku, miktar in _sku_toplamlari(teslimatlar).items():
            adet = self.yukleme_adeti.get(sku)
            if not adet:
                continue
            palet_ici = self.palet_ici.get(sku)
            islenen = (
                palet_hesapla(miktar, palet_ici) * palet_ici if palet_ici else miktar
            )
            toplam += Decimal(islenen) / Decimal(adet)
        return toplam


@dataclass(frozen=True)
class PaletIsrafi:
    """Plandaki kırık palet israfını ölçer: boşa giden palet payı.

    Bir SKU'dan 13 adet varsa ve palete 16 giriyorsa israf 3/16 = 0,1875 palettir.
    Sıfır israf, o üründen tam palet yüklendiği anlamına gelir. Yerleştirme kararı
    önce bu değeri düşürmeye bakar; amaç depoda kırık palet elleçlememektir.
    """

    palet_ici: Mapping[str, int]

    def __call__(self, teslimatlar: Sequence[Teslimat]) -> Decimal:
        israf = Decimal(0)
        for sku, miktar in _sku_toplamlari(teslimatlar).items():
            adet = self.palet_ici.get(sku)
            if adet:
                israf += palet_hesapla(miktar, adet) - miktar / Decimal(adet)
        return israf


def israf_yok(teslimatlar: Sequence[Teslimat]) -> Decimal:
    """Palet verisi olmayan durumlar için nötr israf ölçüsü."""
    return Decimal(0)


@dataclass
class TaslakPlan:
    depo_kodu: str
    planlama_anahtari: str
    profil: KapasiteProfili
    teslimatlar: list[Teslimat] = field(default_factory=list)
    hesaplayici: BirimHesaplayici = toplam_birim
    israf_hesaplayici: BirimHesaplayici = israf_yok
    istisna_asim: bool = False
    """Tek teslimat üst limiti aştığı için açılan istisna planı."""
    alt_limit_esnetildi: bool = False
    """Alt limit dolmadığı halde kullanıcı isteğiyle açılan plan."""
    grup_ici_mix: bool = False
    """Aynı ürün grubunda birden fazla ürün kodu barındıran plan."""

    @property
    def toplam_birim(self) -> Decimal:
        return self.hesaplayici(self.teslimatlar)

    @property
    def israf(self) -> Decimal:
        return self.israf_hesaplayici(self.teslimatlar)

    def eklenince_birim(self, teslimat: Teslimat) -> Decimal:
        return self.hesaplayici([*self.teslimatlar, teslimat])

    def israf_artisi(self, teslimat: Teslimat) -> Decimal:
        """Teslimat eklenirse kırık palet israfı ne kadar artar (ya da azalır)?"""
        return self.israf_hesaplayici([*self.teslimatlar, teslimat]) - self.israf

    @property
    def toplam_palet(self) -> Decimal:
        return Decimal(0)

    @property
    def toplam_adet(self) -> Decimal:
        return sum((t.miktar for t in self.teslimatlar), Decimal(0))

    @property
    def toplam_agirlik(self) -> Decimal:
        return sum((t.agirlik for t in self.teslimatlar), Decimal(0))

    @property
    def toplam_anahtar(self) -> Decimal:
        return sum((t.anahtar for t in self.teslimatlar), Decimal(0))

    @property
    def bos_alan(self) -> Decimal:
        return self.profil.ust_limit - self.toplam_birim

    @property
    def urun_kodlari(self) -> list[str]:
        return sorted({kod for t in self.teslimatlar for kod in t.kodlar})

    @property
    def doluluk_yuzdesi(self) -> Decimal:
        return self.profil.doluluk_yuzdesi(self.toplam_birim)

    @property
    def gecerli(self) -> bool:
        return (
            self.istisna_asim
            or self.alt_limit_esnetildi
            or self.profil.gecerli_dolu(self.toplam_birim)
        )

    def ekle(self, teslimat: Teslimat) -> None:
        self.teslimatlar.append(teslimat)

    def sigar_mi(self, teslimat: Teslimat) -> bool:
        return (
            not self.istisna_asim
            and self.eklenince_birim(teslimat) <= self.profil.ust_limit
        )


@dataclass(frozen=True)
class EsnetmeKurali:
    """Alt limitin ne zaman esneyeceğini tanımlar.

    Alt limiti dolduramayan kalıntılar normalde beklemede kalır; kullanıcı
    "Kalanları da planla" dediğinde (`zorla=True`) alt limit aranmadan plana dönerler.
    `asgari_oran` altındaki kalıntılar bu durumda da beklemede bırakılır.
    """

    zorla: bool = False
    asgari_oran: Decimal = Decimal(0)

    def uygulanir_mi(self, plan: TaslakPlan) -> bool:
        if not self.zorla:
            return False
        return plan.toplam_birim >= plan.profil.ust_limit * self.asgari_oran


@dataclass
class BekleyenTeslimat:
    teslimat: Teslimat
    sebep: str


@dataclass
class PlanlamaSonucu:
    planlar: list[TaslakPlan] = field(default_factory=list)
    bekleyenler: list[BekleyenTeslimat] = field(default_factory=list)

    @property
    def planlanan_teslimat_sayisi(self) -> int:
        return sum(len(plan.teslimatlar) for plan in self.planlar)


def planla(
    teslimatlar: list[Teslimat],
    profil: KapasiteProfili,
    esnetme: EsnetmeKurali | None = None,
    hesaplayici: BirimHesaplayici | None = None,
    israf_hesaplayici: BirimHesaplayici | None = None,
    grup_ici_mix: bool = True,
) -> PlanlamaSonucu:
    """Teslimatları kapasite profiline göre planlara yerleştirir.

    İki fazlı çalışır:
      * **Faz 1 — SKU saf:** her ürün kodu kendi içinde paketlenir. Amaç planların
        mümkün olduğunca tek ürünlü kalması.
      * **Faz 2 — grup içi karışık:** faz 1'den artan teslimatlar, aynı depo ve aynı
        ürün grubu içinde birleştirilerek yeniden paketlenir. `grup_ici_mix=False`
        verilirse bu faz atlanır ve artıklar beklemede kalır.

    Her iki fazda da yerleştirme kararı önce **kırık palet israfını** düşürür, sonra
    aracı en çok dolduran plana yönelir.
    """
    hesaplayici = hesaplayici or toplam_birim
    israf_hesaplayici = israf_hesaplayici or israf_yok
    sonuc = PlanlamaSonucu()

    artiklar: list[Teslimat] = []
    for _, grup in _grupla(teslimatlar, lambda t: (t.depo_kodu, t.planlama_anahtari)):
        planlar, kalan = _paketle(grup, profil, hesaplayici, israf_hesaplayici)
        sonuc.planlar.extend(planlar)
        artiklar.extend(kalan)

    if grup_ici_mix and artiklar:
        yeni_artiklar: list[Teslimat] = []
        for _, grup in _grupla(artiklar, lambda t: (t.depo_kodu, t.urun_grubu)):
            planlar, kalan = _paketle(grup, profil, hesaplayici, israf_hesaplayici)
            for plan in planlar:
                plan.planlama_anahtari = grup[0].urun_grubu or plan.planlama_anahtari
                plan.grup_ici_mix = len(plan.urun_kodlari) > 1
            sonuc.planlar.extend(planlar)
            yeni_artiklar.extend(kalan)
        artiklar = yeni_artiklar

    if esnetme is not None and esnetme.zorla and artiklar:
        kalanlar: list[Teslimat] = []
        for _, grup in _grupla(artiklar, lambda t: (t.depo_kodu, t.urun_grubu)):
            planlar, kalan = _paketle(
                grup, profil, hesaplayici, israf_hesaplayici, alt_limit_ara=False
            )
            for plan in planlar:
                plan.planlama_anahtari = grup[0].urun_grubu or plan.planlama_anahtari
                plan.grup_ici_mix = len(plan.urun_kodlari) > 1
                if not profil.gecerli_dolu(plan.toplam_birim):
                    if not esnetme.uygulanir_mi(plan):
                        kalan.extend(plan.teslimatlar)
                        continue
                    plan.alt_limit_esnetildi = True
                sonuc.planlar.append(plan)
            kalanlar.extend(kalan)
        artiklar = kalanlar

    for teslimat in sorted(artiklar, key=lambda t: t.teslimat_no):
        sonuc.bekleyenler.append(
            BekleyenTeslimat(
                teslimat=teslimat,
                sebep=(
                    "Yeterli hacim yok: kalan teslimatlar "
                    f"{profil.alt_limit} {profil.olcu_adi} alt limitini doldurmuyor"
                ),
            )
        )
    sonuc.planlar.sort(key=lambda p: (p.depo_kodu, p.planlama_anahtari))
    return sonuc


def _grupla(teslimatlar, anahtar_islevi):
    gruplar: dict[tuple, list[Teslimat]] = defaultdict(list)
    for teslimat in teslimatlar:
        gruplar[anahtar_islevi(teslimat)].append(teslimat)
    return sorted(gruplar.items())


def _paketle(
    grup: list[Teslimat],
    profil: KapasiteProfili,
    hesaplayici: BirimHesaplayici,
    israf_hesaplayici: BirimHesaplayici,
    alt_limit_ara: bool = True,
) -> tuple[list[TaslakPlan], list[Teslimat]]:
    """Bir teslimat kümesini planlara böler; alt limiti tutmayanları geri döner."""
    depo_kodu = grup[0].depo_kodu
    planlama_anahtari = grup[0].planlama_anahtari

    def yeni_plan(**ekstra) -> TaslakPlan:
        return TaslakPlan(
            depo_kodu=depo_kodu,
            planlama_anahtari=planlama_anahtari,
            profil=profil,
            hesaplayici=hesaplayici,
            israf_hesaplayici=israf_hesaplayici,
            **ekstra,
        )

    planlar: list[TaslakPlan] = []
    normal: list[Teslimat] = []
    for teslimat in grup:
        if hesaplayici([teslimat]) > profil.ust_limit:
            # Bölünemeyen teslimat üst limiti aşıyorsa tek başına planlanır.
            planlar.append(yeni_plan(teslimatlar=[teslimat], istisna_asim=True))
        else:
            normal.append(teslimat)

    # Büyükten küçüğe yerleştirme; eşitlikte teslimat numarası ile kararlı sıralama.
    sirali = sorted(normal, key=lambda t: (-t.birim, t.teslimat_no))
    kutular: list[TaslakPlan] = []
    for teslimat in sirali:
        adaylar = [k for k in kutular if k.sigar_mi(teslimat)]
        if adaylar:
            # Önce kırık palet israfını en az artıran plan, sonra en dolu plan.
            hedef = min(
                adaylar,
                key=lambda k: (
                    k.israf_artisi(teslimat),
                    k.bos_alan,
                    k.teslimatlar[0].teslimat_no,
                ),
            )
        else:
            hedef = yeni_plan()
            kutular.append(hedef)
        hedef.ekle(teslimat)

    if not alt_limit_ara:
        planlar.extend(kutular)
        return planlar, []

    kalanlar: list[Teslimat] = []
    for kutu in kutular:
        if profil.gecerli_dolu(kutu.toplam_birim):
            planlar.append(kutu)
        else:
            kalanlar.extend(kutu.teslimatlar)

    for plan in planlar:
        plan.teslimatlar.sort(key=lambda t: t.teslimat_no)
    return planlar, kalanlar
