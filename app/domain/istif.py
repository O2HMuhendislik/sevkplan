"""Araç içi yerleşim (istif) planı: hangi palet aracın neresine konulacak.

Deponun formda gördüğü tek şey satır listesiydi; malın araca hangi sırayla ve
nereye konulacağı yükleyicinin kafasındaydı. Bu modül aracın **üstten görünüşünü**
kurar: zemin, duraklara ayrılır ve her palet bir yere oturtulur.

İki kural belirleyicidir:

1. **Ters rota sırası.** En son uğranacak durağın malı en dibe (kabin tarafına),
   ilk durağın malı kapıya konur. Aksi hâlde ilk durakta bütün aracı boşaltmak
   gerekir.
2. **Zemin, anahtar değerin kendisidir.** Bir paletin kapladığı yer
   `araç zemini / o ürünün tır palet sayısı` kadardır. Tır palet sayısı ürün
   master datasından, yani şirketin kendi ölçüsünden gelir; anahtar değer de
   `Σ palet / tır palet` olduğu için çizim ile planın doluluk yüzdesi **hiçbir
   zaman çelişmez**. %100 dolu bir plan zemini tam doldurur.

Palet ölçüleri (en x boy) yalnızca **kaç tanesinin yan yana sığdığını** ve çizimin
oranlarını belirler; kapasiteyi belirlemez.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from app.domain.kapasite import AracTipi


@dataclass(frozen=True)
class AracOlcusu:
    """Aracın iç ölçüleri (cm)."""

    ad: str
    uzunluk: int
    genislik: int
    yukseklik: int

    @property
    def zemin_alani(self) -> Decimal:
        return Decimal(self.uzunluk) * Decimal(self.genislik)


TIR = AracOlcusu("Tır", 1360, 245, 270)
"""Standart tenteli tır dorsesi.

Ölçü tahmin değil, şirketin kendi verisinden türetildi: master datada 80x120
paletli ürünler için "tır palet" 33, 100x120 için 26 yazıyor. 1360 x 245 cm zemin
bu iki sayıyı da birebir veriyor (3 sıra x 11 derinlik = 33; çevrilmiş 2 x 13 = 26).
"""

KAMYON = AracOlcusu("Kamyon", 700, 245, 260)
"""Kamyon kasası. Aynı ürünlerde "kamyon palet" sayısı tırın tam yarısı (17 / 14);
700 x 245 cm zemin bu sayıları da birebir veriyor."""

ASGARI_PALET_YUKSEKLIGI = 15
"""Boş palet tahtasının yüksekliği (cm): kırık palet bundan alçak olamaz."""

KONTEYNER = AracOlcusu("Konteyner", 1200, 235, 239)
"""40' standart konteyner. İhracatta deniz yolu için kullanılır."""

ARAC_OLCULERI = {
    AracTipi.TIR: TIR,
    AracTipi.KAMYON: KAMYON,
}


def arac_olcusu(arac_tipi: str | None) -> AracOlcusu:
    kod = (arac_tipi or "").strip().upper()
    if kod == "KAMYON":
        return KAMYON
    if kod == "KONTEYNER":
        return KONTEYNER
    return TIR


@dataclass(frozen=True)
class PaletTipi:
    """Bir SKU'nun paleti: ne kadar yer kaplar, kaç tanesi yan yana sığar."""

    urun_kodu: str
    urun_adi: str
    urun_grubu: str
    palet_ici_adet: int
    en: int
    """Palet eni (cm). 0 ise ölçü master datada yok."""
    boy: int
    yukseklik: int
    agirlik: Decimal
    """Tam paletin ağırlığı (kg)."""
    arac_palet_sayisi: int
    """Bu üründen araca kaç palet sığdığı (master datanın 'tır/kamyon palet' alanı)."""

    def sira_adedi(self, arac: AracOlcusu) -> int:
        """Aracın enine kaç tanesi yan yana girer? İki yön de denenir."""
        adaylar = [
            int(arac.genislik // olcu)
            for olcu in (self.en, self.boy)
            if olcu and olcu <= arac.genislik
        ]
        return max(adaylar) if adaylar else 1

    def sira_derinligi(self, arac: AracOlcusu, palet_adedi: int | None = None) -> Decimal:
        """`palet_adedi` paletlik bir sıranın araç boyunca kapladığı derinlik (cm).

        Şirketin palet sayısından türetilir: `arac_palet_sayisi` palet zemini **tam**
        doldurmalı. Derinlik sıradaki gerçek palet sayısıyla orantılıdır; son sıra
        eksik kalırsa daha az yer kaplar. Sabit derinlik varsayılsaydı yan yana
        sığmayan sayılarda (kamyona 17 palet, sıraya 3) zemin tutmuyordu.

        Ölçü yoksa paletin kendi boyuna düşülür.
        """
        yan_yana = self.sira_adedi(arac)
        adet = yan_yana if palet_adedi is None else palet_adedi
        if self.arac_palet_sayisi > 0:
            return (
                Decimal(arac.uzunluk) * Decimal(adet) / Decimal(self.arac_palet_sayisi)
            )
        if self.boy:
            return Decimal(min(self.en, self.boy) if yan_yana > 1 else self.boy)
        return Decimal(120)

    def palet_payi(self, arac: AracOlcusu) -> Decimal:
        """Tek paletin araç zemininden aldığı pay (0-1)."""
        if self.arac_palet_sayisi > 0:
            return Decimal(1) / Decimal(self.arac_palet_sayisi)
        yan_yana = self.sira_adedi(arac) or 1
        return self.sira_derinligi(arac) / Decimal(arac.uzunluk) / Decimal(yan_yana)


@dataclass(frozen=True)
class Durak:
    """Yükleme sırasına giren bir teslimat noktası."""

    sira: int
    """Rota sırası: 1 ilk uğrak. Yüklemede tersi geçerlidir."""
    ad: str
    il: str
    ilce: str = ""


@dataclass(frozen=True)
class PaletYuku:
    """Araca konulacak tek bir palet."""

    tip: PaletTipi
    durak: Durak
    adet: Decimal
    """Paletin üzerindeki ürün adedi; son palet kırık (eksik) olabilir."""

    @property
    def kirik_mi(self) -> bool:
        return bool(self.tip.palet_ici_adet) and self.adet < self.tip.palet_ici_adet

    @property
    def agirlik(self) -> Decimal:
        if not self.tip.palet_ici_adet:
            return self.tip.agirlik
        return (
            self.tip.agirlik * self.adet / Decimal(self.tip.palet_ici_adet)
        ).quantize(Decimal("0.1"))

    @property
    def yukseklik(self) -> int:
        """Paletin gerçek yüksekliği (cm). Kırık palet tam boy değildir.

        Master datadaki yükseklik **dolu** paletin ölçüsüdür. 16'lık bir palette 3
        ürün varsa yığın 3/16'sı kadar yükselir; tam boy sayılırsa hiçbir kırık palet
        istiflenemez ve dolu bir araçta paletlerin beşte biri "yerleştirilemedi"
        görünür. Alt sınır palet tahtasının kendisidir (`ASGARI_PALET_YUKSEKLIGI`).
        """
        if not self.tip.yukseklik:
            return 0
        if not self.tip.palet_ici_adet or self.adet >= self.tip.palet_ici_adet:
            return self.tip.yukseklik
        oran = Decimal(self.adet) / Decimal(self.tip.palet_ici_adet)
        return max(
            ASGARI_PALET_YUKSEKLIGI,
            int((Decimal(self.tip.yukseklik) * oran).to_integral_value(ROUND_CEILING)),
        )


@dataclass
class Yerlesim:
    """Bir paletin araç zemininde oturduğu dikdörtgen (cm, sol üst köşe)."""

    yuk: PaletYuku
    x: Decimal
    """Kabin tarafından (dip) itibaren uzaklık. 0 = en dip."""
    y: Decimal
    """Sol duvardan itibaren uzaklık."""
    genislik: Decimal
    derinlik: Decimal
    yukleme_sirasi: int
    """Kaçıncı sırada yüklenecek. 1 ilk yüklenen (en dipteki)."""
    ustundekiler: list[PaletYuku] = field(default_factory=list)
    """Bu paletin **üstüne** istiflenen paletler; en alttaki başta."""

    @property
    def yigin_yuksekligi(self) -> int:
        return self.yuk.yukseklik + sum(p.yukseklik for p in self.ustundekiler)


@dataclass
class IstifPlani:
    arac: AracOlcusu
    yerlesimler: list[Yerlesim] = field(default_factory=list)
    sigmayanlar: list[PaletYuku] = field(default_factory=list)
    """Ne zemine ne de bir paletin üstüne yerleştirilebilen paletler.

    Boş değilse yük gerçekten araca girmiyor demektir; zemine sığmayıp istiflenenler
    burada değil, tabanlarının `ustundekiler` listesindedir.
    """

    @property
    def zemin_paleti(self) -> int:
        return len(self.yerlesimler)

    @property
    def istiflenen(self) -> int:
        return sum(len(y.ustundekiler) for y in self.yerlesimler)

    @property
    def palet_sayisi(self) -> int:
        return self.zemin_paleti + self.istiflenen

    @property
    def kullanilan_uzunluk(self) -> Decimal:
        if not self.yerlesimler:
            return Decimal(0)
        return max(y.x + y.derinlik for y in self.yerlesimler)

    @property
    def zemin_doluluk(self) -> Decimal:
        """Zeminin ne kadarının kaplandığı (0-1)."""
        if not self.arac.uzunluk:
            return Decimal(0)
        oran = self.kullanilan_uzunluk / Decimal(self.arac.uzunluk)
        return min(oran, Decimal(1)).quantize(Decimal("0.0001"))

    def _yigin_agirligi(self, yerlesim: Yerlesim) -> Decimal:
        return yerlesim.yuk.agirlik + sum(
            (p.agirlik for p in yerlesim.ustundekiler), Decimal(0)
        )

    @property
    def toplam_agirlik(self) -> Decimal:
        return sum((self._yigin_agirligi(y) for y in self.yerlesimler), Decimal(0))

    def agirlik_dagilimi(self) -> tuple[Decimal, Decimal]:
        """(ön yarı, arka yarı) ağırlığı. Dengesizlik dingil yükünü bozar."""
        orta = Decimal(self.arac.uzunluk) / 2
        on = sum(
            (
                self._yigin_agirligi(y)
                for y in self.yerlesimler
                if y.x + y.derinlik / 2 <= orta
            ),
            Decimal(0),
        )
        return on, self.toplam_agirlik - on


def paletleri_kur(
    yukler: list[tuple[PaletTipi, Durak, Decimal]],
) -> list[PaletYuku]:
    """(ürün, durak, miktar) üçlülerini tek tek paletlere böler.

    Kırık palet en sona konur: aynı duraktaki tam paletler önce yüklensin, kırık
    olan kapıya yakın kalsın diye. Palet içi adet tanımsızsa yük tek palet sayılır.
    """
    paletler: list[PaletYuku] = []
    for tip, durak, miktar in yukler:
        kalan = Decimal(miktar)
        if kalan <= 0:
            continue
        if not tip.palet_ici_adet:
            paletler.append(PaletYuku(tip=tip, durak=durak, adet=kalan))
            continue
        ici = Decimal(tip.palet_ici_adet)
        tam = int(kalan // ici)
        for _ in range(tam):
            paletler.append(PaletYuku(tip=tip, durak=durak, adet=ici))
        artik = kalan - ici * tam
        if artik > 0:
            paletler.append(PaletYuku(tip=tip, durak=durak, adet=artik))
    return paletler


def _sira_anahtari(palet: PaletYuku) -> tuple:
    """Yükleme sırası: son durak önce, sonra ürün grubu, sonra kırık palet en sona.

    Aynı ürünün paletleri yan yana kalsın diye ürün kodu da anahtara girer; depo
    tek seferde toplayıp tek seferde yüklüyor.
    """
    return (
        -palet.durak.sira,
        palet.tip.urun_grubu,
        palet.tip.urun_kodu,
        palet.kirik_mi,
    )


def istif_planla(paletler: list[PaletYuku], arac: AracOlcusu) -> IstifPlani:
    """Paletleri araç zeminine sıra sıra oturtur.

    Yerleştirme **ters rota sırasıyla** ilerler: en son uğranacak durağın paleti
    dipten başlar, ilk durağınki kapıya en yakın sırada kalır. Böylece her durakta
    yalnızca kapıdaki mal indirilir.

    Bir sıra aracın enine sığdığı kadar palet alır; sıra dolunca ya da sıradaki
    paletin tipi değişince yeni sıra açılır. Aynı sırada farklı ürün karışmaz —
    depo bir sırayı tek ürün olarak topluyor.
    """
    plan = IstifPlani(arac=arac)
    sirali = sorted(paletler, key=_sira_anahtari)

    # Ondalık bölmeden gelen milimetrenin binde biri kadar taşmalar sıra düşürmesin:
    # 1360 / 26 x 2 gibi hesaplar tam kapanmayabiliyor.
    TOLERANS = Decimal("0.001")

    x = Decimal(0)
    sira_no = 0
    indeks = 0
    while indeks < len(sirali):
        palet = sirali[indeks]
        tip = palet.tip
        yan_yana = tip.sira_adedi(arac)

        # Sıraya yalnızca aynı ürünün ve aynı durağın paletleri girer.
        grup = [palet]
        ileri = indeks + 1
        while (
            len(grup) < yan_yana
            and ileri < len(sirali)
            and sirali[ileri].tip.urun_kodu == tip.urun_kodu
            and sirali[ileri].durak.sira == palet.durak.sira
        ):
            grup.append(sirali[ileri])
            ileri += 1

        derinlik = tip.sira_derinligi(arac, len(grup))
        if x + derinlik > Decimal(arac.uzunluk) + TOLERANS:
            # Zemin doldu; kalanlar aşağıda istiflenmeye çalışılır.
            break

        sira_no += 1
        genislik = Decimal(arac.genislik) / Decimal(yan_yana)
        for sutun, yuk in enumerate(grup):
            plan.yerlesimler.append(
                Yerlesim(
                    yuk=yuk,
                    x=x,
                    y=genislik * sutun,
                    genislik=genislik,
                    derinlik=derinlik,
                    yukleme_sirasi=sira_no,
                )
            )
        x += derinlik
        indeks = ileri

    if indeks < len(sirali):
        _istifle(plan, sirali[indeks:])
    return plan


def _istifle(plan: IstifPlani, kalanlar: list[PaletYuku]) -> None:
    """Zemine sığmayan paletleri mevcut paletlerin **üstüne** koyar.

    Anahtar değeri 1,00 olan bir araçta palet gözü sayısı çoğu zaman zeminden
    fazladır: 3 adetlik bir kalem de bir palet yapar ama depo onu yere ayrı bir göz
    olarak koymaz, başka bir paletin üstüne alır. 30.09.2025'in gerçek verisinde 30
    FTL aracın 30'unda bu durum var — "araca sığmıyor" demek yanlış olurdu.

    İki kural:

    * **Yükseklik.** Taban ile üstündekilerin toplam yüksekliği aracın iç
      yüksekliğini aşamaz. Yüksekliği tanımsız ürün istiflenmez; bilinmeyen ölçüyle
      istif önerilmez.
    * **Boşaltma sırası.** Üstteki palet, tabanından **önce ya da onunla aynı**
      durakta inmelidir (`sıra <= tabanın sırası`). Aksi hâlde alttaki malı almak
      için üstündekini indirip tekrar yüklemek gerekir.

    Uygun taban bulunamayan palet `sigmayanlar` listesine düşer; yük gerçekten
    araca girmiyordur.
    """
    for palet in kalanlar:
        if not palet.yukseklik:
            plan.sigmayanlar.append(palet)
            continue
        adaylar = [
            yerlesim
            for yerlesim in plan.yerlesimler
            if yerlesim.yuk.yukseklik
            and palet.durak.sira <= yerlesim.yuk.durak.sira
            and yerlesim.yigin_yuksekligi + palet.yukseklik <= plan.arac.yukseklik
        ]
        if not adaylar:
            plan.sigmayanlar.append(palet)
            continue
        # En boş yığın seçilir: ağırlık tek noktada toplanmasın, istif dengeli olsun.
        hedef = min(adaylar, key=lambda y: (y.yigin_yuksekligi, y.x))
        hedef.ustundekiler.append(palet)


def palet_sayisi_tahmini(tip: PaletTipi, miktar: Decimal) -> int:
    if not tip.palet_ici_adet:
        return 1
    return math.ceil(Decimal(miktar) / Decimal(tip.palet_ici_adet))
