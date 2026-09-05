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

VARSAYILAN_PALET_EN = 80
VARSAYILAN_PALET_BOY = 120
"""Ölçüsü master datada tanımsız ürün için standart Euro palet."""

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

    @property
    def olculu_mu(self) -> bool:
        return bool(self.en and self.boy)

    def yerlesim_olcusu(self, arac: AracOlcusu) -> tuple[int, int, int]:
        """(yan yana adet, palet eni, palet derinliği) — cm.

        Palet iki yönde de denenir; aracın enine **daha çok** sığan yön seçilir,
        eşitlikte daha az derinlik kaplayan. Depo da paleti çevirerek yerleştiriyor.

        Ölçüsü tanımsız ürün için standart Euro palet (80x120) varsayılır; çizimde
        işaretlenir. Ölçüsüz diye paleti hiç çizmemek depoya daha az bilgi verirdi.
        """
        en = self.en or VARSAYILAN_PALET_EN
        boy = self.boy or VARSAYILAN_PALET_BOY
        adaylar = [
            (int(arac.genislik // genis), genis, derin)
            for genis, derin in ((en, boy), (boy, en))
            if genis <= arac.genislik
        ]
        if not adaylar:
            # Palet araca enine sığmıyor: tek başına, aracın enini kaplar.
            return 1, arac.genislik, min(en, boy)
        return max(adaylar, key=lambda a: (a[0], -a[2]))


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
        """Kullanılan uzunluğun araç boyuna oranı (0-1)."""
        if not self.arac.uzunluk:
            return Decimal(0)
        oran = self.kullanilan_uzunluk / Decimal(self.arac.uzunluk)
        return min(oran, Decimal(1)).quantize(Decimal("0.0001"))

    @property
    def zemin_kaplama(self) -> Decimal:
        """Paletlerin zeminde kapladığı **alan** oranı (0-1).

        Kullanılan uzunluktan farklıdır: sıra eksik kaldıysa o sıranın kalan eni
        boştur. Depoya asıl bilgiyi bu verir — zeminde ne kadar boşluk kaldı.
        """
        toplam = self.arac.zemin_alani
        if not toplam:
            return Decimal(0)
        alan = sum(
            (y.derinlik * y.genislik for y in self.yerlesimler), Decimal(0)
        )
        return min(alan / toplam, Decimal(1)).quantize(Decimal("0.0001"))

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
    """Paletleri araç zeminine **tek tek**, gerçek palet ölçüleriyle oturtur.

    Her palet master datadaki eni ve boyu kadar yer kaplar; araç zemini gerçek bir
    zemin planı gibi çizilir. Yerleştirme sıra sıra ilerler: bir sıra aracın enine
    kaç palet sığıyorsa onu alır, sıra dolunca ya da ürün değişince yeni sıra açılır.
    Sıranın derinliği içindeki en derin paletin derinliğidir.

    Sıra **ters rota** düzenindedir: en son uğranacak durağın paleti dipten
    (kabinden) başlar, ilk durağınki kapıya en yakın sırada kalır. Böylece her
    durakta yalnızca kapıdaki mal indirilir.

    Bir sıraya **aynı durağın** paletleri girer; ürünleri farklı olabilir. Sıralama
    aynı ürünü yan yana tuttuğu için karışma ancak bir ürünün son paletinde olur.
    Durak karıştırılmaz: sıra bir bütün olarak indirilir, dipteki sıraya öndekiler
    boşaltılmadan ulaşılamaz.

    Zemine sığmayan paletler `_istifle` ile mevcut paletlerin üstüne konur.
    """
    plan = IstifPlani(arac=arac)
    sirali = sorted(paletler, key=_sira_anahtari)

    x = Decimal(0)
    sira_no = 0
    indeks = 0
    while indeks < len(sirali):
        palet = sirali[indeks]
        _, palet_eni, palet_derinligi = palet.tip.yerlesim_olcusu(arac)
        if x + palet_derinligi > Decimal(arac.uzunluk):
            # Zemin doldu; kalanlar istiflenmeye çalışılır.
            break

        # Sırayı aracın eni bitene kadar doldur. Sıradaki palet sığmıyorsa aynı
        # durağın **ilerideki** paletlerine bakılır: bir kalemin geniş paleti yüzünden
        # sıranın kalanı boş kalmasın. Durak bloğu dışına çıkılmaz (sıralama duraklara
        # göre olduğu için blok bitişiktir).
        sira: list[tuple[PaletYuku, int]] = [(palet, palet_eni)]
        alinanlar = {indeks}
        kalan_en = arac.genislik - palet_eni
        derinlik = palet_derinligi
        ileri = indeks + 1
        while ileri < len(sirali) and sirali[ileri].durak.sira == palet.durak.sira:
            if kalan_en <= 0:
                break
            aday = sirali[ileri]
            _, aday_eni, aday_derinligi = aday.tip.yerlesim_olcusu(arac)
            yeni_derinlik = max(derinlik, aday_derinligi)
            if (
                aday_eni <= kalan_en
                and x + yeni_derinlik <= Decimal(arac.uzunluk)
            ):
                sira.append((aday, aday_eni))
                alinanlar.add(ileri)
                kalan_en -= aday_eni
                derinlik = yeni_derinlik
            ileri += 1

        sira_no += 1
        y_konum = 0
        for yuk, en in sira:
            plan.yerlesimler.append(
                Yerlesim(
                    yuk=yuk,
                    x=x,
                    y=Decimal(y_konum),
                    genislik=Decimal(en),
                    derinlik=Decimal(derinlik),
                    yukleme_sirasi=sira_no,
                )
            )
            y_konum += en
        x += Decimal(derinlik)
        sirali = [p for i, p in enumerate(sirali) if i not in alinanlar]
        indeks = 0

    if sirali:
        _istifle(plan, sirali)
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
