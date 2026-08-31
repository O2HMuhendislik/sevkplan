"""Sevkiyat planlama motoru.

Saf iş mantığı: veritabanı, Excel veya web katmanını tanımaz. Girdi olarak
teslimat listesi alır, çıktı olarak taslak planları ve planlanamayan (bekleyen)
teslimatları döner. Bu sayede kurallar tek başına test edilebilir.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.domain.kapasite import KapasiteProfili


@dataclass(frozen=True)
class Teslimat:
    """Planlamanın atomik birimi. Asla bölünmez."""

    teslimat_no: str
    depo_kodu: str
    planlama_anahtari: str
    """header_kod varsa o, yoksa urun_kodu."""
    urun_kodu: str
    """Teslimatı temsil eden ana ürün kodu."""
    urun_adi: str
    miktar: Decimal
    birim: Decimal
    """Kapasite ölçüsündeki büyüklük (Ring için palet adedi)."""
    oncelik_tarihi: date
    satir_idleri: tuple[int, ...] = ()
    sku_kodlari: tuple[str, ...] = ()
    """Teslimattaki tüm SKU'lar. Header code'lu teslimatta ana ürün + aksesuarları."""
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
                f"{self.teslimat_no}: birim (palet) sıfır veya negatif olamaz"
            )


@dataclass
class TaslakPlan:
    depo_kodu: str
    planlama_anahtari: str
    profil: KapasiteProfili
    teslimatlar: list[Teslimat] = field(default_factory=list)
    istisna_asim: bool = False
    """Tek teslimat üst limiti aştığı için açılan istisna planı."""
    alt_limit_esnetildi: bool = False
    """Alt limit dolmadığı halde esnetme kuralıyla açılan plan."""

    @property
    def toplam_birim(self) -> Decimal:
        return sum((t.birim for t in self.teslimatlar), Decimal(0))

    @property
    def toplam_palet(self) -> Decimal:
        return sum((t.palet for t in self.teslimatlar), Decimal(0))

    @property
    def toplam_anahtar(self) -> Decimal:
        return sum((t.anahtar for t in self.teslimatlar), Decimal(0))

    @property
    def toplam_adet(self) -> Decimal:
        return sum((t.miktar for t in self.teslimatlar), Decimal(0))

    @property
    def toplam_agirlik(self) -> Decimal:
        return sum((t.agirlik for t in self.teslimatlar), Decimal(0))

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
        return not self.istisna_asim and teslimat.birim <= self.bos_alan


@dataclass(frozen=True)
class EsnetmeKurali:
    """Alt limitin ne zaman esneyeceğini tanımlar.

    Alt limiti dolduramayan teslimatlar normalde beklemede kalır. İki durumda plana
    dönüşürler:
      * `zorla=True`  — kullanıcı "kalanları planla" dediğinde alt limit hiç aranmaz.
      * aciliyet      — kalanlar arasında termin tarihine `gun_esigi` gün veya daha az
                        kalmış (ya da termini geçmiş) bir teslimat varsa.
    Her iki durumda da `asgari_oran` altındaki kalıntılar yine beklemede bırakılır.
    """

    bugun: date
    zorla: bool = False
    gun_esigi: int | None = None
    asgari_oran: Decimal = Decimal(0)

    def uygulanir_mi(self, plan: TaslakPlan) -> bool:
        if plan.toplam_birim < plan.profil.ust_limit * self.asgari_oran:
            return False
        if self.zorla:
            return True
        if self.gun_esigi is None:
            return False
        son_tarih = self.bugun + timedelta(days=self.gun_esigi)
        return any(t.oncelik_tarihi <= son_tarih for t in plan.teslimatlar)


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


def palet_hesapla(miktar: Decimal, palet_ici_adet: int) -> Decimal:
    """Kırık palet bir tam palet sayılır: yarım palet de bir palet gözü kaplar."""
    if palet_ici_adet <= 0:
        raise ValueError("palet içi adet sıfır veya negatif olamaz")
    return Decimal(math.ceil(Decimal(miktar) / Decimal(palet_ici_adet)))


def planla(
    teslimatlar: list[Teslimat],
    profil: KapasiteProfili,
    esnetme: EsnetmeKurali | None = None,
) -> PlanlamaSonucu:
    """Teslimatları kapasite profiline göre planlara yerleştirir.

    Kurallar (bkz. docs/ANALIZ.md):
      * Gruplama: (depo kodu, planlama anahtarı). Farklı SKU'lar karışmaz.
      * Üst limiti tek başına aşan teslimat kendi istisna planına gider.
      * Yerleştirme: Best-Fit Decreasing.
      * Alt limitin altında kalan planlar dağıtılır, teslimatları beklemede kalır —
        `esnetme` kuralı devreye girmediği sürece.
    """
    sonuc = PlanlamaSonucu()
    for anahtar in sorted({(t.depo_kodu, t.planlama_anahtari) for t in teslimatlar}):
        grup = [
            t for t in teslimatlar
            if (t.depo_kodu, t.planlama_anahtari) == anahtar
        ]
        _grubu_planla(grup, profil, sonuc, esnetme)
    sonuc.planlar.sort(key=lambda p: (p.depo_kodu, p.planlama_anahtari))
    return sonuc


def _grubu_planla(
    grup: list[Teslimat],
    profil: KapasiteProfili,
    sonuc: PlanlamaSonucu,
    esnetme: EsnetmeKurali | None = None,
) -> None:
    depo_kodu = grup[0].depo_kodu
    planlama_anahtari = grup[0].planlama_anahtari

    normal: list[Teslimat] = []
    for teslimat in grup:
        if teslimat.birim > profil.ust_limit:
            # Kural 5: bölünemeyen teslimat üst limiti aşıyorsa tek başına planlanır.
            sonuc.planlar.append(
                TaslakPlan(
                    depo_kodu=depo_kodu,
                    planlama_anahtari=planlama_anahtari,
                    profil=profil,
                    teslimatlar=[teslimat],
                    istisna_asim=True,
                )
            )
        else:
            normal.append(teslimat)

    # Best-Fit Decreasing. Eşit büyüklükte teslimatlarda eski termin öne alınır.
    sirali = sorted(normal, key=lambda t: (-t.birim, t.oncelik_tarihi, t.teslimat_no))
    kutular: list[TaslakPlan] = []
    for teslimat in sirali:
        adaylar = [k for k in kutular if k.sigar_mi(teslimat)]
        if adaylar:
            hedef = min(adaylar, key=lambda k: (k.bos_alan, k.teslimatlar[0].teslimat_no))
        else:
            hedef = TaslakPlan(
                depo_kodu=depo_kodu,
                planlama_anahtari=planlama_anahtari,
                profil=profil,
            )
            kutular.append(hedef)
        hedef.ekle(teslimat)

    gecerliler = [k for k in kutular if k.gecerli]
    eksik_kalanlar = [k for k in kutular if not k.gecerli]

    if esnetme is not None:
        for kutu in eksik_kalanlar:
            if esnetme.uygulanir_mi(kutu):
                kutu.alt_limit_esnetildi = True
        gecerliler = [k for k in kutular if k.gecerli]
        eksik_kalanlar = [k for k in kutular if not k.gecerli]

    dagitilanlar = [t for k in eksik_kalanlar for t in k.teslimatlar]

    _yaslandirma_takasi(gecerliler, dagitilanlar)

    for plan in gecerliler:
        plan.teslimatlar.sort(key=lambda t: t.teslimat_no)
    sonuc.planlar.extend(gecerliler)
    for teslimat in sorted(dagitilanlar, key=lambda t: t.teslimat_no):
        sonuc.bekleyenler.append(
            BekleyenTeslimat(
                teslimat=teslimat,
                sebep=(
                    f"Yeterli hacim yok: kalan teslimatlar "
                    f"{profil.alt_limit} {profil.olcu_adi} alt limitini doldurmuyor"
                ),
            )
        )


def _yaslandirma_takasi(
    planlar: list[TaslakPlan], bekleyenler: list[Teslimat]
) -> None:
    """Eski siparişlerin sürekli beklemesini önler.

    Beklemede kalan bir teslimat, geçerli bir plandaki *aynı büyüklükte* ama daha yeni
    tarihli bir teslimatla yer değiştirir. Büyüklük eşit olduğu için planın doluluğu
    ve geçerliliği bozulmaz.
    """
    for _ in range(len(bekleyenler)):
        takas_yapildi = False
        for bekleyen_idx, bekleyen in enumerate(bekleyenler):
            en_iyi: tuple[TaslakPlan, int] | None = None
            en_yeni_tarih = bekleyen.oncelik_tarihi
            for plan in planlar:
                if plan.istisna_asim:
                    continue
                for idx, mevcut in enumerate(plan.teslimatlar):
                    if (
                        mevcut.birim == bekleyen.birim
                        and mevcut.oncelik_tarihi > en_yeni_tarih
                    ):
                        en_iyi = (plan, idx)
                        en_yeni_tarih = mevcut.oncelik_tarihi
            if en_iyi is not None:
                plan, idx = en_iyi
                bekleyenler[bekleyen_idx] = plan.teslimatlar[idx]
                plan.teslimatlar[idx] = bekleyen
                takas_yapildi = True
        if not takas_yapildi:
            break
