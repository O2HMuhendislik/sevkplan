"""Nakliye maliyetinin hesabı, kırılımı ve bütçe karşılaştırması.

**Kapsam: iç piyasa (ROTA).** Ring planlarında maliyet yoktur — ring kendi
deposundan çıkan bir iç sevkiyattır, nakliyeciye sefer bedeli ödenmez. İhracat
sonraki adım.

**Hesap satır bazında yapılır, sonra yukarı toplanır.** Böylece araç (plan),
sipariş, ürün ve müşteri kırılımları tek kaynaktan çıkar ve birbiriyle
çelişemez — dört ayrı hesap yazsaydık toplamları tutmazdı.

Tarife iki biçimde:

* **FTL** — il ve araç tipi (tır/kamyon) başına sabit **sefer fiyatı**. Bir araç
  birden çok ile uğrayabildiği için hangi ilin fiyatının geçerli olduğu bir
  karardır; `ftl_maliyet_ili` ayarı bunu belirler, varsayılan **en uzak il**
  (nakliyeci rotanın en uzak noktasına göre fiyat verir). Sefer bedeli satırlara
  **desi payına göre** dağıtılır.
* **RUTIN / KARGO** — il başına **birim desi fiyatı**. Burada dağıtım gerekmez:
  her müşterinin kendi ili ve kendi desisi vardır, satır maliyeti doğrudan çıkar.

**Gerçekleşen iki katmanlı.** Tarifeden hesaplanan tutar *beklenen* maliyettir.
Plana `fiili_maliyet` (nakliyeci faturası) girilmişse gerçekleşen odur ve aradaki
fark ayrıca raporlanır: bekleme, ek durak ve yakıt farkı buradan görünür.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.iller import istanbul_yakasi, yer_adi
from app.domain.marka import marka as depo_markasi
from app.models import (
    Ayar,
    ButceKalemi,
    ButceSenaryosu,
    Depo,
    EkUcretTuru,
    MaliyetBirimi,
    NakliyeEkUcreti,
    NakliyeTarifesi,
    PlanDurumu,
    SevkiyatPlani,
    SiparisSatiri,
    Urun,
)

SIFIR = Decimal("0.00")
MALIYET_MODULU = "ROTA"
"""Maliyet şimdilik yalnızca iç piyasada. Ring'de nakliye bedeli yok."""

SEFER_TIPLERI = {"FTL"}
"""Sefer fiyatıyla (araç başına) fiyatlanan sevkiyat tipleri."""

DESI_TIPLERI = {"RUTIN", "KARGO"}
"""Birim desi ile fiyatlanan sevkiyat tipleri."""

TUM_MARKALAR = ""
"""Marka süzgecinde 'Tümü' seçeneğinin değeri."""


# ------------------------------------------------------------------------ ayarlar
FTL_IL_SECENEKLERI = {
    "EN_UZAK": "En uzak il (rotanın son ili)",
    "SON_UGRAK": "Son uğrak (planın son durağı)",
    "BASKIN": "Baskın il (en çok desinin gittiği il)",
}
FTL_IL_ANAHTARI = "ftl_maliyet_ili"
FTL_IL_VARSAYILAN = "EN_UZAK"


def ftl_il_kurali(db: Session) -> str:
    kayit = db.scalar(select(Ayar).where(Ayar.anahtar == FTL_IL_ANAHTARI))
    deger = (kayit.deger if kayit else "") or FTL_IL_VARSAYILAN
    return deger if deger in FTL_IL_SECENEKLERI else FTL_IL_VARSAYILAN


def ftl_il_kurali_kaydet(db: Session, deger: str) -> None:
    if deger not in FTL_IL_SECENEKLERI:
        raise MaliyetHatasi(f"Bilinmeyen FTL il kuralı: {deger}")
    kayit = db.scalar(select(Ayar).where(Ayar.anahtar == FTL_IL_ANAHTARI))
    if kayit is None:
        db.add(Ayar(anahtar=FTL_IL_ANAHTARI, deger=deger))
    else:
        kayit.deger = deger
    db.flush()


class MaliyetHatasi(Exception):
    """Ekranda gösterilecek, kullanıcının düzeltebileceği hata."""


def _ondalik_ya_da(deger, alan: str) -> Decimal | None:
    if deger in (None, ""):
        return None
    try:
        return Decimal(str(deger).replace(",", "."))
    except Exception:
        raise MaliyetHatasi(f"{alan} sayı olmalı: {deger!r}") from None


# ------------------------------------------------------------------------ tarife
def ek_ucretleri_getir(db: Session) -> list[NakliyeEkUcreti]:
    return list(
        db.scalars(
            select(NakliyeEkUcreti)
            .where(NakliyeEkUcreti.aktif.is_(True))
            .order_by(NakliyeEkUcreti.tur, NakliyeEkUcreti.gecerlilik_baslangic.desc())
        ).all()
    )


def depo_tesisleri(db: Session) -> dict[str, str]:
    """Depo kodu -> tesis (ESKİŞEHİR / BOZÜYÜK).

    Fiyat çıkış tesisine göre değişiyor. Eşleme koda gömülmedi: depo tanımları
    Master Data'dan düzenlenebiliyor, yeni bir depo açıldığında tesisi orada
    yazılıyor.
    """
    return {
        kod: yer_adi(tesis)
        for kod, tesis in db.execute(select(Depo.kod, Depo.tesis)).all()
        if tesis
    }


def tarifeleri_getir(db: Session) -> list[NakliyeTarifesi]:
    return list(
        db.scalars(
            select(NakliyeTarifesi)
            .where(NakliyeTarifesi.aktif.is_(True))
            .order_by(
                NakliyeTarifesi.sevkiyat_tipi,
                NakliyeTarifesi.il,
                NakliyeTarifesi.gecerlilik_baslangic.desc(),
            )
        ).all()
    )


class TarifeDefteri:
    """Tarifeleri bir kez okuyup hızlı arama için indeksler.

    Plan başına sorgu atmak yüzlerce planda ekranı kilitliyordu; bütün tarifeler
    tek seferde okunur ve bellekte aranır.
    """

    def __init__(
        self,
        tarifeler: list[NakliyeTarifesi],
        ek_ucretler: list[NakliyeEkUcreti] | None = None,
    ):
        self._indeks: dict[tuple, list[NakliyeTarifesi]] = defaultdict(list)
        for tarife in tarifeler:
            self._indeks[self._anahtar(
                tarife.sevkiyat_tipi, tarife.il, tarife.ilce, tarife.cikis_noktasi,
                tarife.arac_tipi,
            )].append(tarife)
        self._ek: list[NakliyeEkUcreti] = list(ek_ucretler or [])

    @staticmethod
    def _anahtar(sevkiyat_tipi, il, ilce, cikis, arac) -> tuple:
        return (
            sevkiyat_tipi,
            yer_adi(il),
            yer_adi(ilce) or None,
            yer_adi(cikis) or None,
            (arac or "").upper() or None,
        )

    def bul(
        self,
        sevkiyat_tipi: str,
        il: str,
        gun: date,
        arac_tipi: str | None = None,
        nakliyeci: str | None = None,
        ilce: str | None = None,
        cikis_noktasi: str | None = None,
        desi: Decimal | None = None,
    ) -> NakliyeTarifesi | None:
        """Plan tarihinde geçerli tarife.

        Arama **özelden genele** iner: önce ilçe ve çıkış noktası birebir eşleşen
        satır aranır, bulunamazsa ilçesi boş olan (ilin geneli) ve çıkışı boş olan
        (bütün tesisler) satırlara düşülür. Sözleşmede İstanbul'un iki yakası ayrı
        fiyatlı ama her il için ilçe satırı yok; bu sıralama ikisini de karşılıyor.

        Nakliyeciye özel tarife genelden önce gelir. Aynı gün birden çok tarife
        geçerliyse **en geç başlayan** seçilir: fiyat güncellemesi eskisini
        kapatmadan girilmiş olabilir.
        """
        adaylar_ilce = self._ilce_adaylari(il, ilce)
        for ilce_adayi in adaylar_ilce:
            for cikis_adayi in (cikis_noktasi, None) if cikis_noktasi else (None,):
                adaylar = self._indeks.get(
                    self._anahtar(sevkiyat_tipi, il, ilce_adayi, cikis_adayi, arac_tipi),
                    [],
                )
                secilen = self._sec(adaylar, gun, nakliyeci, desi)
                if secilen is not None:
                    return secilen
        return None

    @staticmethod
    def _ilce_adaylari(il: str, ilce: str | None) -> tuple:
        """Aranacak ilçe anahtarları, özelden genele.

        İstanbul'da sözleşme yakaya göre fiyatlıyor ama siparişte ilçe adı geliyor:
        `KADIKOY` önce kendi adıyla, sonra `ANADOLU` yakasıyla, en sonda ilin
        geneliyle aranır. Böylece yakası bilinen sevkiyat doğru fiyatı bulur.
        """
        adaylar: list[str | None] = []
        if ilce:
            adaylar.append(yer_adi(ilce))
        if yer_adi(il) == "ISTANBUL":
            yaka = istanbul_yakasi(ilce or "")
            if yaka and yaka not in adaylar:
                adaylar.append(yaka)
        adaylar.append(None)
        return tuple(adaylar)

    @staticmethod
    def _sec(
        adaylar: list[NakliyeTarifesi],
        gun: date,
        nakliyeci: str | None,
        desi: Decimal | None,
    ) -> NakliyeTarifesi | None:
        gecerliler = [t for t in adaylar if t.kapsiyor_mu(gun)]
        if desi is not None:
            # Kademe **gönderi** desisine göre seçilir; kademesi olmayan tarife
            # (FTL sefer fiyatı gibi) her desiye uyar.
            gecerliler = [
                t for t in gecerliler
                if (t.desi_alt is None or desi >= t.desi_alt)
                and (t.desi_ust is None or desi <= t.desi_ust)
            ]
        if not gecerliler:
            return None
        ad = (nakliyeci or "").strip().upper()
        ozel = [t for t in gecerliler if (t.nakliyeci or "").strip().upper() == ad and ad]
        genel = [t for t in gecerliler if not t.nakliyeci]
        # Nakliyecinin kendi listesi de genel liste de yoksa eldeki tarife vekil
        # olarak kullanılır; sıfır maliyet yazmaktan iyidir ama çağıran tarafın
        # bunu bilmesi gerekir (bkz. PlanMaliyeti.notlar).
        secilenler = ozel or genel or gecerliler
        return max(secilenler, key=lambda t: t.gecerlilik_baslangic)

    def ek_ucret(
        self,
        tur: EkUcretTuru,
        gun: date,
        sevkiyat_tipi: str | None = None,
        arac_tipi: str | None = None,
        cikis_noktasi: str | None = None,
        nakliyeci: str | None = None,
    ) -> NakliyeEkUcreti | None:
        arac = (arac_tipi or "").upper()
        cikis = yer_adi(cikis_noktasi)
        adaylar = [
            u for u in self._ek
            if u.tur is tur and u.kapsiyor_mu(gun)
            and (not u.sevkiyat_tipi or u.sevkiyat_tipi == sevkiyat_tipi)
            and (not u.arac_tipi or u.arac_tipi.upper() == arac)
            and (not u.cikis_noktasi or yer_adi(u.cikis_noktasi) == cikis)
        ]
        if not adaylar:
            return None
        ad = (nakliyeci or "").strip().upper()
        ozel = [u for u in adaylar if (u.nakliyeci or "").strip().upper() == ad and ad]
        secilenler = ozel or [u for u in adaylar if not u.nakliyeci] or adaylar
        return max(secilenler, key=lambda u: u.gecerlilik_baslangic)


# ------------------------------------------------------------------- hesaplama
@dataclass
class SatirMaliyeti:
    """Bir sipariş satırının payına düşen nakliye maliyeti."""

    satir_id: int
    teslimat_no: str
    siparis_no: str
    musteri: str
    il: str
    marka: str
    """Malın yüklendiği depo kodundan okunur; navlun faturası marka bazında kesiliyor."""
    urun_kodu: str
    urun_adi: str
    miktar: Decimal
    desi: Decimal
    tutar: Decimal


@dataclass
class PlanMaliyeti:
    """Bir aracın (planın) maliyeti ve satırlara dağılımı."""

    plan: SevkiyatPlani
    tarife_maliyeti: Decimal = SIFIR
    fiili_maliyet: Decimal | None = None
    birim: MaliyetBirimi | None = None
    fiyat_ili: str = ""
    """FTL'de sefer fiyatının okunduğu il."""
    cikis_noktasi: str = ""
    """Aracın çıktığı tesis (ESKİŞEHİR / BOZÜYÜK); fiyat buna göre değişiyor."""
    kalemler: list[dict] = field(default_factory=list)
    """Maliyetin parçaları: sefer bedeli, ek uğrama, gönderi bedeli, asgari bedel."""
    satirlar: list[SatirMaliyeti] = field(default_factory=list)
    eksikler: list[str] = field(default_factory=list)
    """Tarifesi bulunamayan iller; maliyet bu kadarıyla eksik hesaplandı."""
    notlar: list[str] = field(default_factory=list)
    """Maliyet hesaplandı ama bir varsayımla: örneğin nakliyecinin kendi tarifesi
    yok, başka nakliyecinin listesi vekil olarak kullanıldı. Eksikten farkıdır:
    burada bir tutar var, ama kesin değil."""

    @property
    def gerceklesen(self) -> Decimal:
        """Fatura girilmişse o, girilmemişse tarife maliyeti."""
        return self.fiili_maliyet if self.fiili_maliyet is not None else self.tarife_maliyeti

    @property
    def fark(self) -> Decimal:
        """Fatura ile tarife arasındaki sapma. Fatura yoksa sıfır."""
        if self.fiili_maliyet is None:
            return SIFIR
        return self.fiili_maliyet - self.tarife_maliyeti

    @property
    def eksik_mi(self) -> bool:
        return bool(self.eksikler)

    @property
    def desi_basi(self) -> Decimal:
        toplam = sum((s.desi for s in self.satirlar), Decimal(0))
        if toplam <= 0:
            return SIFIR
        return (self.gerceklesen / toplam).quantize(Decimal("0.0001"))


def _kurus(deger: Decimal) -> Decimal:
    return Decimal(deger).quantize(Decimal("0.01"))


def _plan_illeri(plan: SevkiyatPlani) -> list[str]:
    """Planın uğradığı iller, **yakından uzağa** (kayıttaki sıra budur)."""
    return [
        yer_adi(parca) for parca in (plan.iller_metni or "").split(",") if parca.strip()
    ]


def _musteri_anahtari(satir: SiparisSatiri) -> str:
    for aday in (satir.bayi_adi, satir.alici_firma, satir.sevk_adresi):
        metin = (aday or "").strip()
        if metin:
            return metin
    return f"TESLİMAT {satir.teslimat_no}"


def _ftl_fiyat_ili(plan: SevkiyatPlani, kural: str, iller: list[str],
                   il_desileri: dict[str, Decimal]) -> str:
    if kural == "SON_UGRAK" and plan.son_ugrak:
        return yer_adi(plan.son_ugrak)
    if kural == "BASKIN" and il_desileri:
        return max(il_desileri.items(), key=lambda ikili: (ikili[1], ikili[0]))[0]
    # EN_UZAK (varsayılan): iller yakından uzağa yazılıyor, sonuncusu en uzak.
    return iller[-1] if iller else ""


def plan_maliyeti(
    plan: SevkiyatPlani, defter: TarifeDefteri, urun_desileri: dict[str, Decimal],
    ftl_kurali: str = FTL_IL_VARSAYILAN, tesisler: dict[str, str] | None = None,
) -> PlanMaliyeti:
    """Bir planın maliyetini hesaplar ve sipariş satırlarına dağıtır."""
    sonuc = PlanMaliyeti(plan=plan, fiili_maliyet=plan.fiili_maliyet)
    tip = (plan.sevkiyat_tipi or "").upper()
    if plan.modul != MALIYET_MODULU or plan.durum is PlanDurumu.IPTAL:
        return sonuc

    tesisler = tesisler or {}
    ham: list[tuple[SiparisSatiri, str, Decimal]] = []
    il_desileri: dict[str, Decimal] = defaultdict(Decimal)
    tesis_desileri: dict[str, Decimal] = defaultdict(Decimal)
    for satir in plan.satirlar:
        il = yer_adi(satir.sehir)
        desi = urun_desileri.get(satir.urun_kodu, Decimal(0)) * Decimal(satir.miktar)
        ham.append((satir, il, desi))
        il_desileri[il] += desi
        tesis = tesisler.get(satir.depo_kodu or "")
        if tesis:
            tesis_desileri[tesis] += desi

    # Karma yüklemede araç tek tesisten çıkar: en çok malın geldiği tesis.
    sonuc.cikis_noktasi = (
        max(tesis_desileri.items(), key=lambda i: (i[1], i[0]))[0]
        if tesis_desileri else ""
    )
    gun = plan.plan_tarihi or date.today()

    if tip in SEFER_TIPLERI:
        return _ftl_maliyeti(sonuc, plan, defter, ham, il_desileri, gun, ftl_kurali)
    if tip in DESI_TIPLERI:
        return _parsiyel_maliyeti(sonuc, plan, defter, ham, gun, tip)
    return sonuc


def _ilce_secimi(ham, il: str) -> str | None:
    """O ildeki en çok desinin gittiği ilçe; tarife ilçe kırılımlıysa kullanılır."""
    desiler: dict[str, Decimal] = defaultdict(Decimal)
    for _satir, satir_il, desi in ham:
        if satir_il == il:
            ilce = yer_adi(_satir.ilce)
            if ilce:
                desiler[ilce] += desi
    if not desiler:
        return None
    return max(desiler.items(), key=lambda i: (i[1], i[0]))[0]


def _ftl_maliyeti(sonuc, plan, defter, ham, il_desileri, gun, ftl_kurali):
    """Tam araç: tek sefer bedeli + eşiği aşan uğramalar; satırlara desi payıyla dağıtılır."""
    sonuc.birim = MaliyetBirimi.SEFER
    iller = _plan_illeri(plan) or sorted(il_desileri)
    fiyat_ili = _ftl_fiyat_ili(plan, ftl_kurali, iller, dict(il_desileri))
    sonuc.fiyat_ili = fiyat_ili
    tarife = defter.bul(
        "FTL", fiyat_ili, gun,
        arac_tipi=plan.arac_tipi, nakliyeci=plan.nakliyeci,
        ilce=_ilce_secimi(ham, fiyat_ili), cikis_noktasi=sonuc.cikis_noktasi,
    )
    if tarife is None:
        sonuc.eksikler.append(
            f"{fiyat_ili or '—'} · {(plan.arac_tipi or '—').upper()} · "
            f"{sonuc.cikis_noktasi or 'tesis?'} sefer tarifesi yok"
        )
        sonuc.satirlar.extend(
            _satir_maliyeti(satir, il, desi, SIFIR) for satir, il, desi in ham
        )
        return sonuc

    _vekil_notu(sonuc, tarife, plan.nakliyeci)
    sefer = _kurus(tarife.birim_fiyat)
    sonuc.kalemler.append({"ad": "Sefer bedeli", "tutar": sefer,
                           "aciklama": f"{fiyat_ili} · {(plan.arac_tipi or '').upper()}"})

    # Uğrama: sözleşmede ilk iki durak sefer fiyatına dahil, sonrakiler ödenir.
    ugrama = defter.ek_ucret(
        EkUcretTuru.UGRAMA, gun, sevkiyat_tipi="FTL",
        arac_tipi=plan.arac_tipi, cikis_noktasi=sonuc.cikis_noktasi,
        nakliyeci=plan.nakliyeci,
    )
    if ugrama is not None:
        ucretsiz = int(ugrama.esik or 0)
        fazla = max(0, (plan.durak_sayisi or 0) - ucretsiz)
        if fazla:
            tutar = _kurus(Decimal(fazla) * ugrama.tutar)
            sefer += tutar
            sonuc.kalemler.append({
                "ad": "Ek uğrama",
                "tutar": tutar,
                "aciklama": f"{plan.durak_sayisi} durak; ilk {ucretsiz} dahil, "
                            f"{fazla} uğrama ödenir",
            })
    sonuc.tarife_maliyeti = sefer

    # Sefer bedeli tek parça; satırlara desi payına göre dağıtılır. Desi hiç
    # yoksa (master datada ölçü eksik) adet payı kullanılır.
    toplam_desi = sum(desi for _, _, desi in ham)
    toplam_adet = sum(Decimal(s.miktar) for s, _, _ in ham)
    dagitilan = SIFIR
    for sira, (satir, il, desi) in enumerate(ham):
        if toplam_desi > 0:
            pay = desi / toplam_desi
        elif toplam_adet > 0:
            pay = Decimal(satir.miktar) / toplam_adet
        else:
            pay = Decimal(1) / Decimal(len(ham))
        tutar = _kurus(sefer * pay)
        # Son satır yuvarlama artığını üstlenir: parçaların toplamı her zaman
        # sefer bedeline eşit olmalı, yoksa kırılım toplamı planı tutmaz.
        if sira == len(ham) - 1:
            tutar = sefer - dagitilan
        dagitilan += tutar
        sonuc.satirlar.append(_satir_maliyeti(satir, il, desi, tutar))
    return sonuc


def _parsiyel_maliyeti(sonuc, plan, defter, ham, gun, tip):
    """Parsiyel / kargo: her **gönderi** kendi kademesinden fiyatlanır.

    Gönderi = bir müşterinin o plandaki toplam malı. Kademe (0-2000, 2001-4000,
    4001+) ve asgari gönderi bedeli satır bazında değil gönderi bazında işler;
    satır bazında hesaplasaydık her satır ayrı gönderi sayılıp asgari bedel
    defalarca uygulanırdı.
    """
    sonuc.birim = MaliyetBirimi.DESI
    gonderiler: dict[str, list[tuple]] = defaultdict(list)
    for satir, il, desi in ham:
        gonderiler[_musteri_anahtari(satir)].append((satir, il, desi))

    asgari = defter.ek_ucret(
        EkUcretTuru.ASGARI_GONDERI, gun, sevkiyat_tipi=tip,
        cikis_noktasi=sonuc.cikis_noktasi, nakliyeci=plan.nakliyeci,
    )
    eksik_iller: set[str] = set()
    toplam = SIFIR
    asgari_uygulanan = 0
    for _musteri, grup in sorted(gonderiler.items()):
        gonderi_desi = sum(desi for _, _, desi in grup)
        il = grup[0][1]
        tarife = defter.bul(
            tip, il, gun, nakliyeci=plan.nakliyeci,
            ilce=yer_adi(grup[0][0].ilce) or None,
            cikis_noktasi=sonuc.cikis_noktasi, desi=gonderi_desi,
        )
        if tarife is None:
            eksik_iller.add(il or "—")
            for satir, satir_il, desi in grup:
                sonuc.satirlar.append(_satir_maliyeti(satir, satir_il, desi, SIFIR))
            continue

        _vekil_notu(sonuc, tarife, plan.nakliyeci)
        bedel = _kurus(tarife.birim_fiyat * gonderi_desi)
        if asgari is not None and asgari.esik and gonderi_desi <= asgari.esik:
            if _kurus(asgari.tutar) > bedel:
                bedel = _kurus(asgari.tutar)
                asgari_uygulanan += 1
        toplam += bedel

        # Gönderi bedelini satırlara desi payıyla dağıt; artığı son satır üstlenir.
        dagitilan = SIFIR
        for sira, (satir, satir_il, desi) in enumerate(grup):
            pay = desi / gonderi_desi if gonderi_desi > 0 else Decimal(1) / len(grup)
            tutar = _kurus(bedel * pay)
            if sira == len(grup) - 1:
                tutar = bedel - dagitilan
            dagitilan += tutar
            sonuc.satirlar.append(_satir_maliyeti(satir, satir_il, desi, tutar))

    sonuc.tarife_maliyeti = toplam
    sonuc.kalemler.append({
        "ad": "Gönderi bedeli", "tutar": toplam,
        "aciklama": f"{len(gonderiler)} gönderi, kademeli desi fiyatı",
    })
    if asgari_uygulanan:
        sonuc.kalemler.append({
            "ad": "Asgari gönderi bedeli",
            "tutar": SIFIR,
            "aciklama": f"{asgari_uygulanan} gönderi eşiğin altında kaldı, "
                        "asgari bedelden ücretlendirildi",
        })
    sonuc.eksikler.extend(
        f"{il} · {tip} desi tarifesi yok" for il in sorted(eksik_iller)
    )
    return sonuc


def _vekil_notu(sonuc: PlanMaliyeti, tarife, nakliyeci: str | None) -> None:
    """Başka nakliyecinin tarifesi kullanıldıysa not düşer."""
    ad = (nakliyeci or "").strip().upper()
    tarife_sahibi = (tarife.nakliyeci or "").strip().upper()
    if not ad or not tarife_sahibi or ad == tarife_sahibi:
        return
    not_metni = f"{ad} tarifesi yok; {tarife_sahibi} fiyatı vekil kullanıldı"
    if not_metni not in sonuc.notlar:
        sonuc.notlar.append(not_metni)


def _satir_maliyeti(
    satir: SiparisSatiri, il: str, desi: Decimal, tutar: Decimal
) -> SatirMaliyeti:
    return SatirMaliyeti(
        satir_id=satir.id,
        teslimat_no=satir.teslimat_no,
        siparis_no=satir.siparis_no,
        musteri=_musteri_anahtari(satir),
        il=il,
        marka=depo_markasi(satir.depo_kodu),
        urun_kodu=satir.urun_kodu,
        urun_adi=satir.urun_adi or "",
        miktar=Decimal(satir.miktar),
        desi=desi.quantize(Decimal("0.001")),
        tutar=tutar,
    )


def urun_desileri(db: Session) -> dict[str, Decimal]:
    return {
        kod: Decimal(desi)
        for kod, desi in db.execute(
            select(Urun.urun_kodu, Urun.desi).where(Urun.desi.isnot(None))
        ).all()
    }


def plan_maliyetleri(
    db: Session,
    baslangic: date | None = None,
    bitis: date | None = None,
    sevkiyat_tipi: str = "",
    il: str = "",
    limit: int = 5000,
) -> list[PlanMaliyeti]:
    """Süzülen iç piyasa planlarının maliyeti."""
    sorgu = (
        select(SevkiyatPlani)
        .where(
            SevkiyatPlani.modul == MALIYET_MODULU,
            SevkiyatPlani.durum != PlanDurumu.IPTAL,
        )
        .order_by(SevkiyatPlani.plan_tarihi.desc(), SevkiyatPlani.sefer_no.desc())
    )
    if baslangic:
        sorgu = sorgu.where(SevkiyatPlani.plan_tarihi >= baslangic)
    if bitis:
        sorgu = sorgu.where(SevkiyatPlani.plan_tarihi <= bitis)
    if sevkiyat_tipi:
        sorgu = sorgu.where(SevkiyatPlani.sevkiyat_tipi == sevkiyat_tipi)

    defter = TarifeDefteri(tarifeleri_getir(db), ek_ucretleri_getir(db))
    desiler = urun_desileri(db)
    kural = ftl_il_kurali(db)
    tesisler = depo_tesisleri(db)

    sonuclar = []
    for plan in db.scalars(sorgu.limit(limit)).all():
        maliyet = plan_maliyeti(plan, defter, desiler, kural, tesisler)
        if il and yer_adi(il) not in {s.il for s in maliyet.satirlar}:
            continue
        sonuclar.append(maliyet)
    return sonuclar


# -------------------------------------------------------------------- kırılım
BOYUTLAR = {
    "MUSTERI": ("Müşteri", lambda s: s.musteri),
    "URUN": ("Ürün", lambda s: s.urun_kodu),
    "SIPARIS": ("Sipariş", lambda s: s.siparis_no),
    "TESLIMAT": ("Teslimat", lambda s: s.teslimat_no),
    "IL": ("İl", lambda s: s.il or "—"),
    "MARKA": ("Marka", lambda s: s.marka),
}
"""Maliyetin hangi boyutta toplanacağı. Hepsi aynı satır maliyetlerinden çıkar,
bu yüzden toplamları birbirini tutar."""


def kirilim(maliyetler: list[PlanMaliyeti], boyut: str, limit: int = 500) -> list[dict]:
    """Satır maliyetlerini seçilen boyutta toplar.

    Fatura girilmiş planlarda satırlara dağıtılan tutar tarifeye göredir; toplam
    gerçekleşene eşit olsun diye satır payları fatura oranıyla ölçeklenir.
    """
    if boyut not in BOYUTLAR:
        raise MaliyetHatasi(f"Bilinmeyen kırılım boyutu: {boyut}")
    _, anahtar_fn = BOYUTLAR[boyut]

    gruplar: dict[str, dict] = {}
    for maliyet in maliyetler:
        olcek = Decimal(1)
        if maliyet.fiili_maliyet is not None and maliyet.tarife_maliyeti > 0:
            olcek = maliyet.fiili_maliyet / maliyet.tarife_maliyeti
        for satir in maliyet.satirlar:
            anahtar = anahtar_fn(satir) or "—"
            grup = gruplar.setdefault(anahtar, {
                "anahtar": anahtar,
                "ad": satir.urun_adi if boyut == "URUN" else "",
                "tutar": SIFIR,
                "desi": Decimal(0),
                "adet": Decimal(0),
                "plan": set(),
                "musteri": set(),
                "il": set(),
            })
            grup["tutar"] += _kurus(satir.tutar * olcek)
            grup["desi"] += satir.desi
            grup["adet"] += satir.miktar
            grup["plan"].add(maliyet.plan.sefer_no)
            grup["musteri"].add(satir.musteri)
            if satir.il:
                grup["il"].add(satir.il)

    satirlar = []
    for grup in gruplar.values():
        desi = grup["desi"]
        satirlar.append({
            **grup,
            "plan_sayisi": len(grup["plan"]),
            "musteri_sayisi": len(grup["musteri"]),
            "iller": ", ".join(sorted(grup["il"])[:4]),
            "desi": desi.quantize(Decimal("0.001")),
            "desi_basi": (grup["tutar"] / desi).quantize(Decimal("0.0001"))
            if desi > 0 else SIFIR,
        })
    satirlar.sort(key=lambda s: s["tutar"], reverse=True)
    return satirlar[:limit]


def ozet(maliyetler: list[PlanMaliyeti]) -> dict:
    gerceklesen = sum((m.gerceklesen for m in maliyetler), SIFIR)
    desi = sum((s.desi for m in maliyetler for s in m.satirlar), Decimal(0))
    faturali = [m for m in maliyetler if m.fiili_maliyet is not None]
    return {
        "plan": len(maliyetler),
        "gerceklesen": gerceklesen,
        "tarife": sum((m.tarife_maliyeti for m in maliyetler), SIFIR),
        "fark": sum((m.fark for m in maliyetler), SIFIR),
        "faturali": len(faturali),
        "desi": desi.quantize(Decimal("0.001")),
        "desi_basi": (gerceklesen / desi).quantize(Decimal("0.0001")) if desi > 0 else SIFIR,
        "eksik": sum(1 for m in maliyetler if m.eksik_mi),
        "arac_basi": (gerceklesen / len(maliyetler)).quantize(Decimal("0.01"))
        if maliyetler else SIFIR,
    }


def tip_ozeti(maliyetler: list[PlanMaliyeti]) -> list[dict]:
    gruplar: dict[str, dict] = {}
    for maliyet in maliyetler:
        tip = (maliyet.plan.sevkiyat_tipi or "—").upper()
        grup = gruplar.setdefault(
            tip, {"tip": tip, "plan": 0, "tutar": SIFIR, "desi": Decimal(0)}
        )
        grup["plan"] += 1
        grup["tutar"] += maliyet.gerceklesen
        grup["desi"] += sum((s.desi for s in maliyet.satirlar), Decimal(0))
    for grup in gruplar.values():
        grup["desi_basi"] = (
            (grup["tutar"] / grup["desi"]).quantize(Decimal("0.0001"))
            if grup["desi"] > 0 else SIFIR
        )
        grup["desi"] = grup["desi"].quantize(Decimal("0.001"))
    return sorted(gruplar.values(), key=lambda g: g["tutar"], reverse=True)


# ------------------------------------------------------------- bütçe ve FC
AY_ADLARI = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)


def fc_surumleri(db: Session, yil: int) -> list[str]:
    """O yıl için girilmiş FC sürümleri, en yenisi başta."""
    en_son = func.max(ButceKalemi.olusturma_tarihi)
    satirlar = db.execute(
        select(ButceKalemi.surum, en_son)
        .where(ButceKalemi.yil == yil, ButceKalemi.senaryo == ButceSenaryosu.FC)
        .group_by(ButceKalemi.surum)
        .order_by(en_son.desc())
    ).all()
    return [surum for surum, _ in satirlar if surum]


def _tip_kurali(kalemler: list[ButceKalemi], alan: str = "tutar") -> dict[int, Decimal]:
    """Ay -> değer; sevkiyat tipi boş olan satır (ay toplamı) kırılımı ezer.

    İkisini toplamak maliyeti iki kez sayardı.
    """
    toplamlar: dict[int, Decimal] = {}
    kirilimlar: dict[int, Decimal] = defaultdict(Decimal)
    for kalem in kalemler:
        deger = getattr(kalem, alan)
        if deger is None:
            continue
        if kalem.sevkiyat_tipi:
            kirilimlar[kalem.ay] += Decimal(deger)
        else:
            toplamlar[kalem.ay] = toplamlar.get(kalem.ay, SIFIR) + Decimal(deger)
    for ay, deger in kirilimlar.items():
        toplamlar.setdefault(ay, deger)
    return toplamlar


def _senaryo_aylari(
    db: Session,
    yil: int,
    senaryo: ButceSenaryosu,
    surum: str | None = None,
    marka: str = TUM_MARKALAR,
    alan: str = "tutar",
) -> dict[int, Decimal]:
    """Ay -> bütçe tutarı (ya da bütçelenen desi).

    İki kırılım boyutu var ve ikisinde de aynı kural işler: **boş bırakılan satır
    toplamdır ve kırılımı ezer.**

    * Bir marka seçilmişse yalnızca o markanın satırları okunur.
    * "Tümü" seçiliyse önce markası boş olan satır (bütün markaların toplamı)
      aranır; o ay için yoksa markaların satırları toplanır. Böylece bütçe ister
      tek satır ister marka marka girilsin doğru okunur.
    """
    sorgu = select(ButceKalemi).where(
        ButceKalemi.yil == yil, ButceKalemi.senaryo == senaryo
    )
    if surum is not None:
        sorgu = sorgu.where(ButceKalemi.surum == surum)
    kalemler = list(db.scalars(sorgu).all())

    if marka:
        return _tip_kurali([k for k in kalemler if k.marka == marka], alan)

    genel = _tip_kurali([k for k in kalemler if not k.marka], alan)
    markalilar: dict[int, Decimal] = defaultdict(Decimal)
    for ad in {k.marka for k in kalemler if k.marka}:
        for ay, deger in _tip_kurali([k for k in kalemler if k.marka == ad], alan).items():
            markalilar[ay] += deger
    for ay, deger in markalilar.items():
        genel.setdefault(ay, deger)
    return genel


def butce_karsilastirmasi(
    db: Session,
    yil: int,
    fc_surum: str = "",
    bugun: date | None = None,
    marka: str = TUM_MARKALAR,
) -> dict:
    """Aylık ve YTD bütçe / FC / gerçekleşen karşılaştırması.

    YTD **yılbaşından bugüne** kümülatiftir; gelecek aylar YTD'ye girmez, yoksa
    henüz gerçekleşmemiş aylar sapmayı olduğundan kötü gösterirdi.
    """
    bugun = bugun or date.today()
    son_ay = 12 if yil < bugun.year else (bugun.month if yil == bugun.year else 0)

    butce = _senaryo_aylari(db, yil, ButceSenaryosu.BUTCE, marka=marka)
    butce_desi = _senaryo_aylari(
        db, yil, ButceSenaryosu.BUTCE, marka=marka, alan="desi"
    )
    fc = _senaryo_aylari(db, yil, ButceSenaryosu.FC, fc_surum or None, marka=marka)

    maliyetler = markaya_indirge(
        plan_maliyetleri(db, baslangic=date(yil, 1, 1), bitis=date(yil, 12, 31)),
        marka,
    )
    aylik: dict[int, list[PlanMaliyeti]] = defaultdict(list)
    for maliyet in maliyetler:
        if maliyet.plan.plan_tarihi:
            aylik[maliyet.plan.plan_tarihi.month].append(maliyet)
    gerceklesen = {
        ay: sum((m.gerceklesen for m in grup), SIFIR) for ay, grup in aylik.items()
    }

    satirlar = []
    ytd = {"butce": SIFIR, "fc": SIFIR, "gerceklesen": SIFIR}
    for ay in range(1, 13):
        satir = {
            "ay": ay,
            "ay_adi": AY_ADLARI[ay - 1],
            "butce": butce.get(ay, SIFIR),
            "fc": fc.get(ay, SIFIR),
            "gerceklesen": gerceklesen.get(ay, SIFIR),
            "gecmis_mi": ay <= son_ay,
            "butce_desi": butce_desi.get(ay),
        }
        satir["aciklama"] = sapma_aciklamasi(
            aylik.get(ay, []), satir["butce"], butce_desi.get(ay)
        )
        satir["butce_farki"] = satir["gerceklesen"] - satir["butce"]
        satir["fc_farki"] = satir["gerceklesen"] - satir["fc"]
        satir["butce_orani"] = _oran(satir["gerceklesen"], satir["butce"])
        satir["fc_orani"] = _oran(satir["gerceklesen"], satir["fc"])
        if satir["gecmis_mi"]:
            ytd["butce"] += satir["butce"]
            ytd["fc"] += satir["fc"]
            ytd["gerceklesen"] += satir["gerceklesen"]
            satir["ytd_butce"] = ytd["butce"]
            satir["ytd_fc"] = ytd["fc"]
            satir["ytd_gerceklesen"] = ytd["gerceklesen"]
        satirlar.append(satir)

    ytd["butce_farki"] = ytd["gerceklesen"] - ytd["butce"]
    ytd["fc_farki"] = ytd["gerceklesen"] - ytd["fc"]
    ytd["butce_orani"] = _oran(ytd["gerceklesen"], ytd["butce"])
    ytd["fc_orani"] = _oran(ytd["gerceklesen"], ytd["fc"])
    ytd["son_ay"] = son_ay
    ytd["son_ay_adi"] = AY_ADLARI[son_ay - 1] if son_ay else ""

    ytd_maliyetleri = [m for ay in range(1, son_ay + 1) for m in aylik.get(ay, [])]
    ytd["aciklama"] = sapma_aciklamasi(
        ytd_maliyetleri,
        ytd["butce"],
        sum(
            (butce_desi[ay] for ay in range(1, son_ay + 1) if butce_desi.get(ay)),
            Decimal(0),
        ) or None,
    )

    return {
        "yil": yil,
        "marka": marka,
        "fc_surum": fc_surum,
        "satirlar": satirlar,
        "ytd": ytd,
        "yillik": {
            "butce": sum(butce.values(), SIFIR),
            "fc": sum(fc.values(), SIFIR),
            "gerceklesen": sum(gerceklesen.values(), SIFIR),
        },
    }


def _oran(gerceklesen: Decimal, hedef: Decimal) -> Decimal | None:
    """Gerçekleşenin hedefe oranı (%). Hedef yoksa oran da yoktur — sıfıra bölmek
    yerine boş dönülür, ekran '—' yazar."""
    if not hedef:
        return None
    return (gerceklesen / hedef * 100).quantize(Decimal("0.1"))


def butce_yillari(db: Session) -> list[int]:
    return sorted(
        {yil for (yil,) in db.execute(select(ButceKalemi.yil).distinct()).all()},
        reverse=True,
    )


# ------------------------------------------------------------- tarife yönetimi
def tarife_satirlari(db: Session, sevkiyat_tipi: str = "", il: str = "",
                     arama: str = "") -> list[dict]:
    """Ekran listesi."""
    satirlar = []
    for tarife in tarifeleri_getir(db):
        if sevkiyat_tipi and tarife.sevkiyat_tipi != sevkiyat_tipi:
            continue
        if il and yer_adi(tarife.il) != yer_adi(il):
            continue
        satir = {
            "id": tarife.id,
            "sevkiyat_tipi": tarife.sevkiyat_tipi,
            "il": tarife.il,
            "ilce": tarife.ilce or "",
            "cikis_noktasi": tarife.cikis_noktasi or "",
            "desi_alt": tarife.desi_alt,
            "desi_ust": tarife.desi_ust,
            "motorin_fiyati": tarife.motorin_fiyati,
            "arac_tipi": tarife.arac_tipi or "",
            "birim": tarife.birim.value,
            "birim_fiyat": tarife.birim_fiyat,
            "para_birimi": tarife.para_birimi,
            "gecerlilik_baslangic": tarife.gecerlilik_baslangic,
            "gecerlilik_bitis": tarife.gecerlilik_bitis,
            "nakliyeci": tarife.nakliyeci or "",
            "aciklama": tarife.aciklama or "",
            "yururlukte": tarife.kapsiyor_mu(date.today()),
        }
        if arama:
            desen = arama.strip().lower()
            havuz = " ".join(
                str(satir[alan]).lower()
                for alan in ("il", "ilce", "cikis_noktasi", "arac_tipi",
                             "nakliyeci", "aciklama")
            )
            if desen not in havuz:
                continue
        satirlar.append(satir)
    return satirlar


def tarife_kaydet(
    db: Session,
    sevkiyat_tipi: str,
    il: str,
    birim_fiyat,
    gecerlilik_baslangic: date,
    arac_tipi: str = "",
    gecerlilik_bitis: date | None = None,
    nakliyeci: str = "",
    para_birimi: str = "TRY",
    aciklama: str = "",
    ilce: str = "",
    cikis_noktasi: str = "",
    desi_alt=None,
    desi_ust=None,
    motorin_fiyati=None,
) -> NakliyeTarifesi:
    tip = (sevkiyat_tipi or "").strip().upper()
    if tip not in SEFER_TIPLERI | DESI_TIPLERI:
        raise MaliyetHatasi(
            f"Sevkiyat tipi FTL, RUTIN veya KARGO olmalı: {sevkiyat_tipi!r}"
        )
    il_adi = yer_adi(il)
    if not il_adi:
        raise MaliyetHatasi("İl boş olamaz.")
    try:
        fiyat = Decimal(str(birim_fiyat).replace(",", "."))
    except Exception:
        raise MaliyetHatasi(f"Birim fiyat sayı olmalı: {birim_fiyat!r}") from None
    if fiyat <= 0:
        raise MaliyetHatasi("Birim fiyat sıfırdan büyük olmalı.")
    if not gecerlilik_baslangic:
        raise MaliyetHatasi("Geçerlilik başlangıcı gerekli.")
    if gecerlilik_bitis and gecerlilik_bitis < gecerlilik_baslangic:
        raise MaliyetHatasi("Geçerlilik bitişi başlangıçtan önce olamaz.")

    sefer_mi = tip in SEFER_TIPLERI
    arac = (arac_tipi or "").strip().upper() or None
    if sefer_mi and arac not in {"TIR", "KAMYON"}:
        raise MaliyetHatasi("FTL tarifesinde araç tipi TIR ya da KAMYON olmalı.")
    if not sefer_mi:
        # Parsiyel ve kargoda fiyat araca değil desiye bağlı; araç tipi taşımak
        # tarifeyi bulunamaz hâle getirirdi.
        arac = None

    ilce_adi = yer_adi(ilce) or None
    cikis_adi = yer_adi(cikis_noktasi) or None
    alt = _ondalik_ya_da(desi_alt, "Desi alt")
    ust = _ondalik_ya_da(desi_ust, "Desi üst")
    if alt is not None and ust is not None and ust < alt:
        raise MaliyetHatasi("Desi üst sınırı alt sınırdan küçük olamaz.")
    if sefer_mi and (alt is not None or ust is not None):
        # Sefer fiyatı araç başına; desi kademesi taşımak tarifeyi bulunamaz yapardı.
        alt = ust = None
    motorin = _ondalik_ya_da(motorin_fiyati, "Motorin")

    # Aynı anahtar ve aynı başlangıç tarihi = fiyat düzeltmesi, yeni satır değil.
    mevcut = db.scalar(
        select(NakliyeTarifesi).where(
            NakliyeTarifesi.sevkiyat_tipi == tip,
            NakliyeTarifesi.il == il_adi,
            NakliyeTarifesi.ilce.is_(None) if ilce_adi is None
            else NakliyeTarifesi.ilce == ilce_adi,
            NakliyeTarifesi.cikis_noktasi.is_(None) if cikis_adi is None
            else NakliyeTarifesi.cikis_noktasi == cikis_adi,
            NakliyeTarifesi.arac_tipi.is_(None) if arac is None
            else NakliyeTarifesi.arac_tipi == arac,
            NakliyeTarifesi.desi_alt.is_(None) if alt is None
            else NakliyeTarifesi.desi_alt == alt,
            NakliyeTarifesi.gecerlilik_baslangic == gecerlilik_baslangic,
            NakliyeTarifesi.nakliyeci.is_(None) if not nakliyeci.strip()
            else NakliyeTarifesi.nakliyeci == nakliyeci.strip(),
        )
    )
    tarife = mevcut or NakliyeTarifesi(
        sevkiyat_tipi=tip, il=il_adi, arac_tipi=arac,
        gecerlilik_baslangic=gecerlilik_baslangic,
    )
    tarife.ilce = ilce_adi
    tarife.cikis_noktasi = cikis_adi
    tarife.desi_alt = alt
    tarife.desi_ust = ust
    tarife.motorin_fiyati = motorin
    tarife.birim = MaliyetBirimi.SEFER if sefer_mi else MaliyetBirimi.DESI
    tarife.birim_fiyat = fiyat
    tarife.gecerlilik_bitis = gecerlilik_bitis
    tarife.nakliyeci = nakliyeci.strip() or None
    tarife.para_birimi = (para_birimi or "TRY").strip().upper()[:3] or "TRY"
    tarife.aciklama = (aciklama or "").strip() or None
    tarife.aktif = True
    if mevcut is None:
        db.add(tarife)
    db.flush()
    return tarife


def tarifeyi_sil(db: Session, tarife_id: int) -> None:
    tarife = db.get(NakliyeTarifesi, tarife_id)
    if tarife is None:
        raise MaliyetHatasi("Tarife bulunamadı.")
    db.delete(tarife)
    db.flush()


# -------------------------------------------------------------- bütçe yönetimi
def butce_kaydet(
    db: Session, yil, ay, senaryo: str, tutar, surum: str = "",
    sevkiyat_tipi: str = "", para_birimi: str = "TRY", aciklama: str = "",
    marka: str = "", desi=None,
) -> ButceKalemi:
    try:
        yil_i, ay_i = int(yil), int(ay)
    except (TypeError, ValueError):
        raise MaliyetHatasi("Yıl ve ay sayı olmalı.") from None
    if not 1 <= ay_i <= 12:
        raise MaliyetHatasi(f"Ay 1-12 arasında olmalı: {ay}")
    try:
        senaryo_e = ButceSenaryosu((senaryo or "").strip().upper())
    except ValueError:
        raise MaliyetHatasi(f"Senaryo BUTCE ya da FC olmalı: {senaryo!r}") from None
    try:
        tutar_d = Decimal(str(tutar).replace(",", "."))
    except Exception:
        raise MaliyetHatasi(f"Tutar sayı olmalı: {tutar!r}") from None

    tip = (sevkiyat_tipi or "").strip().upper() or None
    if tip and tip not in SEFER_TIPLERI | DESI_TIPLERI:
        raise MaliyetHatasi(f"Sevkiyat tipi FTL, RUTIN veya KARGO olmalı: {tip}")
    surum_m = (surum or "").strip()
    if senaryo_e is ButceSenaryosu.FC and not surum_m:
        raise MaliyetHatasi("FC satırlarında sürüm gerekli (FC1, FC2 ...).")
    if senaryo_e is ButceSenaryosu.BUTCE:
        surum_m = ""

    marka_m = (marka or "").strip().upper() or None
    desi_d = None
    if desi not in (None, ""):
        try:
            desi_d = Decimal(str(desi).replace(",", "."))
        except Exception:
            raise MaliyetHatasi(f"Bütçelenen desi sayı olmalı: {desi!r}") from None

    mevcut = db.scalar(
        select(ButceKalemi).where(
            ButceKalemi.yil == yil_i, ButceKalemi.ay == ay_i,
            ButceKalemi.senaryo == senaryo_e, ButceKalemi.surum == surum_m,
            ButceKalemi.marka.is_(None) if marka_m is None
            else ButceKalemi.marka == marka_m,
            ButceKalemi.sevkiyat_tipi.is_(None) if tip is None
            else ButceKalemi.sevkiyat_tipi == tip,
        )
    )
    kalem = mevcut or ButceKalemi(
        yil=yil_i, ay=ay_i, senaryo=senaryo_e, surum=surum_m,
        marka=marka_m, sevkiyat_tipi=tip,
    )
    kalem.tutar = tutar_d
    kalem.desi = desi_d
    kalem.para_birimi = (para_birimi or "TRY").strip().upper()[:3] or "TRY"
    kalem.aciklama = (aciklama or "").strip() or None
    if mevcut is None:
        db.add(kalem)
    db.flush()
    return kalem


def butce_satirlari(db: Session, yil: int | None = None) -> list[dict]:
    sorgu = select(ButceKalemi).order_by(
        ButceKalemi.yil.desc(), ButceKalemi.senaryo, ButceKalemi.surum, ButceKalemi.ay
    )
    if yil:
        sorgu = sorgu.where(ButceKalemi.yil == yil)
    return [
        {
            "id": k.id, "yil": k.yil, "ay": k.ay, "ay_adi": AY_ADLARI[k.ay - 1],
            "senaryo": k.senaryo.value, "surum": k.surum,
            "marka": k.marka or "",
            "sevkiyat_tipi": k.sevkiyat_tipi or "",
            "tutar": k.tutar, "desi": k.desi, "para_birimi": k.para_birimi,
            "aciklama": k.aciklama or "",
        }
        for k in db.scalars(sorgu).all()
    ]


def butceyi_sil(db: Session, kalem_id: int) -> None:
    kalem = db.get(ButceKalemi, kalem_id)
    if kalem is None:
        raise MaliyetHatasi("Bütçe kalemi bulunamadı.")
    db.delete(kalem)
    db.flush()


def fiili_maliyet_kaydet(
    db: Session, plan_id: int, tutar: str, fatura_no: str = "", not_metni: str = ""
) -> SevkiyatPlani:
    """Nakliyeci faturasındaki gerçek tutarı plana yazar. Boş tutar faturayı siler."""
    plan = db.get(SevkiyatPlani, plan_id)
    if plan is None:
        raise MaliyetHatasi("Plan bulunamadı.")
    ham = (tutar or "").strip().replace(".", "").replace(",", ".")
    if not ham:
        plan.fiili_maliyet = None
    else:
        try:
            plan.fiili_maliyet = Decimal(ham)
        except Exception:
            raise MaliyetHatasi(f"Tutar sayı olmalı: {tutar!r}") from None
    plan.fatura_no = (fatura_no or "").strip() or None
    plan.maliyet_notu = (not_metni or "").strip() or None
    db.flush()
    return plan


# --------------------------------------------------------------------- marka
def markalari_getir(db: Session) -> list[str]:
    """Veride geçen markalar. Depo kodlarından türetilir, elle tanımlanmaz."""
    kodlar = db.execute(
        select(SiparisSatiri.depo_kodu)
        .where(SiparisSatiri.modul == MALIYET_MODULU)
        .distinct()
    ).all()
    markalar = {depo_markasi(kod) for (kod,) in kodlar if kod}
    butcedekiler = {
        m for (m,) in db.execute(select(ButceKalemi.marka).distinct()).all() if m
    }
    return sorted(markalar | butcedekiler)


def _marka_paylari(maliyet: PlanMaliyeti) -> dict[str, Decimal]:
    """Planın markalar arası dağılımı.

    Ölçü **desidir**: tarifesi bulunamayan planda tutar sıfırdır ama hacim
    bilinir, dağıtım yine de doğru yapılabilir. Satır hiç yoksa planın kendi
    marka payına düşülür.
    """
    desiler: dict[str, Decimal] = defaultdict(Decimal)
    for satir in maliyet.satirlar:
        desiler[satir.marka] += satir.desi
    toplam = sum(desiler.values(), Decimal(0))
    if toplam > 0:
        return {ad: deger / toplam for ad, deger in desiler.items()}
    if desiler:  # desi yok ama satır var: eşit böl
        pay = Decimal(1) / Decimal(len(desiler))
        return {ad: pay for ad in desiler}
    return maliyet.plan.marka_paylari or {depo_markasi(maliyet.plan.depo_kodu): Decimal(1)}


def markaya_indirge(maliyetler: list[PlanMaliyeti], marka: str) -> list[PlanMaliyeti]:
    """Maliyetleri tek markaya indirger: yalnızca o markanın satırları ve payı.

    Aşağıdaki bütün özet, kırılım ve bütçe hesapları bu indirgenmiş listeyle
    çalışır; böylece marka süzgeci tek yerde uygulanır ve ekranlar arasında
    tutarsızlık çıkamaz.
    """
    if not marka:
        return maliyetler

    indirgenmis: list[PlanMaliyeti] = []
    for maliyet in maliyetler:
        satirlar = [s for s in maliyet.satirlar if s.marka == marka]
        if satirlar:
            # Toplamlar **kalan satırlardan** kurulur, plan tutarı oranlanarak
            # değil: kırılım ekranları da satırlardan hesapladığı için üç ekran
            # kuruşu kuruşuna aynı sayıyı gösterir.
            olcek = Decimal(1)
            if maliyet.fiili_maliyet is not None and maliyet.tarife_maliyeti > 0:
                olcek = maliyet.fiili_maliyet / maliyet.tarife_maliyeti
            tarife = sum((s.tutar for s in satirlar), SIFIR)
            fiili = (
                sum((_kurus(s.tutar * olcek) for s in satirlar), SIFIR)
                if maliyet.fiili_maliyet is not None else None
            )
        else:
            # Satırı olmayan plan: planın kendi marka payına düşülür.
            pay = _marka_paylari(maliyet).get(marka, Decimal(0))
            if pay <= 0:
                continue
            tarife = _kurus(maliyet.tarife_maliyeti * pay)
            fiili = (
                _kurus(maliyet.fiili_maliyet * pay)
                if maliyet.fiili_maliyet is not None else None
            )
        indirgenmis.append(PlanMaliyeti(
            plan=maliyet.plan,
            tarife_maliyeti=tarife,
            fiili_maliyet=fiili,
            birim=maliyet.birim,
            fiyat_ili=maliyet.fiyat_ili,
            satirlar=satirlar,
            eksikler=list(maliyet.eksikler),
            notlar=list(maliyet.notlar),
            cikis_noktasi=maliyet.cikis_noktasi,
            kalemler=list(maliyet.kalemler),
        ))
    return indirgenmis


def marka_ozeti(maliyetler: list[PlanMaliyeti]) -> list[dict]:
    """Markalara göre gerçekleşen maliyet."""
    gruplar: dict[str, dict] = {}
    for maliyet in maliyetler:
        olcek = Decimal(1)
        if maliyet.fiili_maliyet is not None and maliyet.tarife_maliyeti > 0:
            olcek = maliyet.fiili_maliyet / maliyet.tarife_maliyeti
        # Tutar **satır maliyetlerinden** toplanır; kırılım ekranı da aynı yoldan
        # hesapladığı için iki ekran kuruşu kuruşuna aynı sayıyı gösterir.
        for satir in maliyet.satirlar:
            grup = gruplar.setdefault(
                satir.marka,
                {"marka": satir.marka, "tutar": SIFIR, "desi": Decimal(0), "plan": set()},
            )
            grup["tutar"] += _kurus(satir.tutar * olcek)
            grup["desi"] += satir.desi
            grup["plan"].add(maliyet.plan.sefer_no)
        if not maliyet.satirlar:
            # Satırı olmayan plan (sipariş satırı silinmiş): planın kendi payına düş.
            for ad, pay in _marka_paylari(maliyet).items():
                grup = gruplar.setdefault(
                    ad, {"marka": ad, "tutar": SIFIR, "desi": Decimal(0), "plan": set()}
                )
                grup["tutar"] += _kurus(maliyet.gerceklesen * pay)
                grup["plan"].add(maliyet.plan.sefer_no)
    satirlar = []
    for grup in gruplar.values():
        desi = grup["desi"]
        satirlar.append({
            **grup,
            "plan_sayisi": len(grup["plan"]),
            "desi": desi.quantize(Decimal("0.001")),
            "desi_basi": (grup["tutar"] / desi).quantize(Decimal("0.0001"))
            if desi > 0 else SIFIR,
        })
    return sorted(satirlar, key=lambda g: g["tutar"], reverse=True)


# ------------------------------------------------------------ sapma açıklaması
def _yuzde(pay: Decimal, taban: Decimal) -> Decimal | None:
    if not taban:
        return None
    return (pay / taban * 100).quantize(Decimal("0.1"))


def sapma_aciklamasi(
    maliyetler: list[PlanMaliyeti], butce: Decimal, butce_desi: Decimal | None
) -> dict:
    """Gerçekleşen ile bütçe arasındaki farkın **nereden geldiği**.

    Sapmayı üç bileşene ayırır ve üçünün toplamı **tam olarak** farka eşittir —
    eşit olmasaydı açıklama değil tahmin olurdu:

    1. **Hacim etkisi** = (gerçekleşen desi − bütçe desi) × bütçelenen desi başı
       maliyet. Bütçeden farklı hacim taşımanın bedeli.
    2. **Birim maliyet etkisi** = (tarife desi başı − bütçe desi başı) × gerçekleşen
       desi. Aynı hacmi daha pahalıya/ucuza taşımanın bedeli; içinde tarife zammı
       da, uzak illere kayan karma da vardır.
    3. **Fatura farkı** = fatura − tarife. Bekleme, ek durak, yakıt farkı.

    Cebir: (Gd−Bd)·bü + (tü−bü)·Gd + (G−T) = T − B + G − T = G − B ✓

    Bütçelenen desi girilmemişse ilk iki bileşen ayrıştırılamaz; o zaman sapma
    "tarife maliyeti sapması" olarak tek parça verilir ve hangi sevkiyat tipinin,
    ilin ve markanın ne kadar katkı yaptığı listelenir.
    """
    gerceklesen = sum((m.gerceklesen for m in maliyetler), SIFIR)
    tarife = sum((m.tarife_maliyeti for m in maliyetler), SIFIR)
    fatura_farki = sum((m.fark for m in maliyetler), SIFIR)
    desi = sum((s.desi for m in maliyetler for s in m.satirlar), Decimal(0))
    fark = gerceklesen - butce

    bilesenler: list[dict] = []
    if butce_desi and butce_desi > 0 and desi > 0:
        butce_birim = butce / butce_desi
        tarife_birim = tarife / desi
        hacim = _kurus((desi - butce_desi) * butce_birim)
        birim = _kurus(tarife - butce - hacim)  # kalanı birim etkisine yaz: toplam tutsun
        bilesenler.append({
            "ad": "Hacim etkisi",
            "tutar": hacim,
            "aciklama": (
                f"{_sayi(desi)} desi taşındı, bütçe {_sayi(butce_desi)} desiydi "
                f"(%{_yuzde(desi - butce_desi, butce_desi)} sapma)."
            ),
        })
        bilesenler.append({
            "ad": "Birim maliyet etkisi",
            "tutar": birim,
            "aciklama": (
                f"Desi başı tarife maliyeti {_kurus(tarife_birim)}; "
                f"bütçelenen {_kurus(butce_birim)}."
            ),
        })
    elif butce:
        bilesenler.append({
            "ad": "Tarife maliyeti sapması",
            "tutar": _kurus(tarife - butce),
            "aciklama": (
                "Bütçelenen desi girilmediği için hacim ve birim maliyet etkisi "
                "ayrıştırılamıyor. Bütçe satırına desi yazarsanız bu satır ikiye "
                "ayrılır."
            ),
        })

    if fatura_farki:
        faturali = [m for m in maliyetler if m.fiili_maliyet is not None]
        bilesenler.append({
            "ad": "Fatura farkı",
            "tutar": _kurus(fatura_farki),
            "aciklama": (
                f"{len(faturali)} planda nakliyeci faturası tarifeden farklı "
                "(bekleme, ek durak, yakıt farkı)."
            ),
        })

    uyarilar = []
    eksik = [m for m in maliyetler if m.eksik_mi]
    if eksik:
        uyarilar.append(
            f"{len(eksik)} planın tarifesi eksik: gerçekleşen olduğundan **düşük** "
            "görünüyor, sapma bu kadar yanıltıcı."
        )
    if not butce:
        uyarilar.append("Bu ay için bütçe girilmemiş; sapma hesaplanamıyor.")

    return {
        "fark": fark,
        "gerceklesen": gerceklesen,
        "tarife": tarife,
        "desi": desi.quantize(Decimal("0.001")),
        "butce_desi": butce_desi,
        "bilesenler": bilesenler,
        "aciklanan": sum((b["tutar"] for b in bilesenler), SIFIR),
        "katkilar": {
            "Sevkiyat tipi": _katki(maliyetler, lambda s, m: (m.plan.sevkiyat_tipi or "—")),
            "İl": _katki(maliyetler, lambda s, m: s.il or "—"),
            "Marka": _katki(maliyetler, lambda s, m: s.marka),
        },
        "uyarilar": uyarilar,
        "plan_sayisi": len(maliyetler),
    }


def _katki(maliyetler: list[PlanMaliyeti], anahtar_fn, en_fazla: int = 5) -> list[dict]:
    """Gerçekleşen maliyetin bir boyuttaki dağılımı; sapmanın nereye gittiğini gösterir."""
    gruplar: dict[str, dict] = {}
    toplam = SIFIR
    for maliyet in maliyetler:
        olcek = Decimal(1)
        if maliyet.fiili_maliyet is not None and maliyet.tarife_maliyeti > 0:
            olcek = maliyet.fiili_maliyet / maliyet.tarife_maliyeti
        for satir in maliyet.satirlar:
            anahtar = anahtar_fn(satir, maliyet)
            tutar = _kurus(satir.tutar * olcek)
            grup = gruplar.setdefault(
                anahtar, {"ad": anahtar, "tutar": SIFIR, "desi": Decimal(0)}
            )
            grup["tutar"] += tutar
            grup["desi"] += satir.desi
            toplam += tutar
    satirlar = sorted(gruplar.values(), key=lambda g: g["tutar"], reverse=True)
    for grup in satirlar:
        grup["pay"] = _yuzde(grup["tutar"], toplam)
        grup["desi_basi"] = (
            (grup["tutar"] / grup["desi"]).quantize(Decimal("0.0001"))
            if grup["desi"] > 0 else SIFIR
        )
        grup["desi"] = grup["desi"].quantize(Decimal("0.001"))
    return satirlar[:en_fazla]


def _sayi(deger: Decimal) -> str:
    return format(Decimal(deger).quantize(Decimal("0.1")).normalize(), "f").replace(".", ",")


# ----------------------------------------------------------------- ek ücretler
def ek_ucret_satirlari(db: Session) -> list[dict]:
    return [
        {
            "id": u.id, "tur": u.tur.value, "sevkiyat_tipi": u.sevkiyat_tipi or "",
            "arac_tipi": u.arac_tipi or "", "cikis_noktasi": u.cikis_noktasi or "",
            "tutar": u.tutar, "esik": u.esik,
            "gecerlilik_baslangic": u.gecerlilik_baslangic,
            "gecerlilik_bitis": u.gecerlilik_bitis,
            "nakliyeci": u.nakliyeci or "", "motorin_fiyati": u.motorin_fiyati,
            "aciklama": u.aciklama or "",
            "yururlukte": u.kapsiyor_mu(date.today()),
        }
        for u in ek_ucretleri_getir(db)
    ]


def ek_ucret_kaydet(
    db: Session, tur: str, tutar, gecerlilik_baslangic: date,
    sevkiyat_tipi: str = "", arac_tipi: str = "", cikis_noktasi: str = "",
    esik=None, gecerlilik_bitis: date | None = None, nakliyeci: str = "",
    motorin_fiyati=None, aciklama: str = "",
) -> NakliyeEkUcreti:
    try:
        tur_e = EkUcretTuru((tur or "").strip().upper())
    except ValueError:
        raise MaliyetHatasi(
            f"Tür ASGARI_GONDERI, UGRAMA ya da EK_KM olmalı: {tur!r}"
        ) from None
    tutar_d = _ondalik_ya_da(tutar, "Tutar")
    if tutar_d is None or tutar_d <= 0:
        raise MaliyetHatasi("Tutar sıfırdan büyük olmalı.")
    if not gecerlilik_baslangic:
        raise MaliyetHatasi("Geçerlilik başlangıcı gerekli.")

    tip = (sevkiyat_tipi or "").strip().upper() or None
    arac = (arac_tipi or "").strip().upper() or None
    cikis = yer_adi(cikis_noktasi) or None
    mevcut = db.scalar(
        select(NakliyeEkUcreti).where(
            NakliyeEkUcreti.tur == tur_e,
            NakliyeEkUcreti.sevkiyat_tipi.is_(None) if tip is None
            else NakliyeEkUcreti.sevkiyat_tipi == tip,
            NakliyeEkUcreti.arac_tipi.is_(None) if arac is None
            else NakliyeEkUcreti.arac_tipi == arac,
            NakliyeEkUcreti.cikis_noktasi.is_(None) if cikis is None
            else NakliyeEkUcreti.cikis_noktasi == cikis,
            NakliyeEkUcreti.gecerlilik_baslangic == gecerlilik_baslangic,
        )
    )
    kayit = mevcut or NakliyeEkUcreti(
        tur=tur_e, sevkiyat_tipi=tip, arac_tipi=arac, cikis_noktasi=cikis,
        gecerlilik_baslangic=gecerlilik_baslangic,
    )
    kayit.tutar = tutar_d
    kayit.esik = _ondalik_ya_da(esik, "Eşik")
    kayit.gecerlilik_bitis = gecerlilik_bitis
    kayit.nakliyeci = nakliyeci.strip() or None
    kayit.motorin_fiyati = _ondalik_ya_da(motorin_fiyati, "Motorin")
    kayit.aciklama = (aciklama or "").strip() or None
    kayit.aktif = True
    if mevcut is None:
        db.add(kayit)
    db.flush()
    return kayit


def ek_ucreti_sil(db: Session, kayit_id: int) -> None:
    kayit = db.get(NakliyeEkUcreti, kayit_id)
    if kayit is None:
        raise MaliyetHatasi("Ek ücret bulunamadı.")
    db.delete(kayit)
    db.flush()


# ------------------------------------------------- motorine endeksli güncelleme
def guncel_motorin(db: Session) -> Decimal | None:
    """Yürürlükteki tarifelerin dayandığı motorin fiyatı."""
    fiyatlar = [
        t.motorin_fiyati
        for t in tarifeleri_getir(db)
        if t.motorin_fiyati and t.kapsiyor_mu(date.today())
    ]
    return max(fiyatlar) if fiyatlar else None


@dataclass
class ZamOnizlemesi:
    """Motorin değişiminin tarifelere etkisi; uygulanmadan önce gösterilir."""

    eski_motorin: Decimal
    yeni_motorin: Decimal
    yakit_payi: Decimal
    """Sözleşmede fiyatın yakıta bağlı olan kısmı (%). 100 = fiyat motorinle
    birebir hareket eder."""
    oran: Decimal
    """Fiyatlara uygulanacak değişim yüzdesi."""
    tarife_sayisi: int
    ek_ucret_sayisi: int
    ornekler: list[dict]

    @property
    def artis_mi(self) -> bool:
        return self.oran > 0


def zam_orani(eski: Decimal, yeni: Decimal, yakit_payi: Decimal) -> Decimal:
    """Motorin değişiminin fiyata yansıyan yüzdesi.

    Sözleşme fiyatının tamamı yakıt değil; yakıt payı kadarı motorinle hareket
    eder. `yakit_payi` 100 verilirse fiyat motorinle birebir değişir.
    """
    if eski <= 0:
        raise MaliyetHatasi("Eski motorin fiyatı sıfırdan büyük olmalı.")
    return ((yeni - eski) / eski * yakit_payi).quantize(Decimal("0.0001"))


def zam_onizle(
    db: Session, yeni_motorin, yakit_payi, gecerlilik: date,
    eski_motorin=None, nakliyeci: str = "",
) -> ZamOnizlemesi:
    yeni = _ondalik_ya_da(yeni_motorin, "Yeni motorin fiyatı")
    pay = _ondalik_ya_da(yakit_payi, "Yakıt payı")
    if yeni is None or yeni <= 0:
        raise MaliyetHatasi("Yeni motorin fiyatı sıfırdan büyük olmalı.")
    if pay is None or pay < 0:
        raise MaliyetHatasi("Yakıt payı sıfır ya da daha büyük olmalı.")
    eski = _ondalik_ya_da(eski_motorin, "Eski motorin fiyatı") or guncel_motorin(db)
    if eski is None:
        raise MaliyetHatasi(
            "Yürürlükteki tarifelerde motorin fiyatı yazılı değil; "
            "eski motorin fiyatını elle girin."
        )

    oran = zam_orani(eski, yeni, pay / Decimal(100))
    tarifeler = _zamlanacak_tarifeler(db, gecerlilik, nakliyeci)
    ek_ucretler = _zamlanacak_ek_ucretler(db, gecerlilik, nakliyeci)
    ornekler = [
        {
            "il": t.il, "ilce": t.ilce or "", "cikis": t.cikis_noktasi or "",
            "arac": t.arac_tipi or "", "tip": t.sevkiyat_tipi,
            "eski": t.birim_fiyat,
            "yeni": _yeni_fiyat(t.birim_fiyat, oran),
        }
        for t in tarifeler[:8]
    ]
    return ZamOnizlemesi(
        eski_motorin=eski, yeni_motorin=yeni, yakit_payi=pay, oran=oran,
        tarife_sayisi=len(tarifeler), ek_ucret_sayisi=len(ek_ucretler),
        ornekler=ornekler,
    )


def _zamlanacak_tarifeler(db, gecerlilik: date, nakliyeci: str = ""):
    ad = (nakliyeci or "").strip().upper()
    return [
        t for t in tarifeleri_getir(db)
        if t.kapsiyor_mu(gecerlilik)
        and (not ad or (t.nakliyeci or "").strip().upper() == ad)
    ]


def _zamlanacak_ek_ucretler(db, gecerlilik: date, nakliyeci: str = ""):
    ad = (nakliyeci or "").strip().upper()
    return [
        u for u in ek_ucretleri_getir(db)
        if u.kapsiyor_mu(gecerlilik)
        and (not ad or (u.nakliyeci or "").strip().upper() == ad)
    ]


def _yeni_fiyat(eski: Decimal, oran: Decimal) -> Decimal:
    return (Decimal(eski) * (Decimal(1) + oran)).quantize(Decimal("0.0001"))


def zam_uygula(
    db: Session, yeni_motorin, yakit_payi, gecerlilik: date,
    eski_motorin=None, nakliyeci: str = "", aciklama: str = "",
) -> ZamOnizlemesi:
    """Yürürlükteki tarifeleri kapatır, güncel fiyatla yenilerini açar.

    **Eski fiyatlar silinmez.** Geçerlilik bitişi yeni tarifenin bir gün öncesine
    çekilir; geçmiş planlar kendi tarihlerinde geçerli olan fiyatla maliyetlenmeye
    devam eder, yoksa geçmişin maliyeti bugünkü fiyatla yeniden yazılırdı.
    """
    onizleme = zam_onizle(
        db, yeni_motorin, yakit_payi, gecerlilik, eski_motorin, nakliyeci
    )
    if onizleme.oran == 0:
        raise MaliyetHatasi("Motorin değişmemiş; güncellenecek fiyat yok.")

    onceki_gun = gecerlilik - timedelta(days=1)
    not_metni = (aciklama or "").strip() or (
        f"Motorin {onizleme.eski_motorin} → {onizleme.yeni_motorin}; "
        f"yakıt payı %{onizleme.yakit_payi}, fiyat değişimi "
        f"%{(onizleme.oran * 100).quantize(Decimal('0.01'))}"
    )

    for tarife in _zamlanacak_tarifeler(db, gecerlilik, nakliyeci):
        yeni = NakliyeTarifesi(
            sevkiyat_tipi=tarife.sevkiyat_tipi, il=tarife.il, ilce=tarife.ilce,
            cikis_noktasi=tarife.cikis_noktasi, arac_tipi=tarife.arac_tipi,
            birim=tarife.birim, desi_alt=tarife.desi_alt, desi_ust=tarife.desi_ust,
            birim_fiyat=_yeni_fiyat(tarife.birim_fiyat, onizleme.oran),
            para_birimi=tarife.para_birimi,
            gecerlilik_baslangic=gecerlilik, gecerlilik_bitis=None,
            nakliyeci=tarife.nakliyeci, motorin_fiyati=onizleme.yeni_motorin,
            aciklama=not_metni,
        )
        # Eski satır kapanır ama durur: geçmiş planlar onunla maliyetlenir.
        if tarife.gecerlilik_bitis is None or tarife.gecerlilik_bitis > onceki_gun:
            tarife.gecerlilik_bitis = onceki_gun
        db.add(yeni)

    for ucret in _zamlanacak_ek_ucretler(db, gecerlilik, nakliyeci):
        yeni_ucret = NakliyeEkUcreti(
            tur=ucret.tur, sevkiyat_tipi=ucret.sevkiyat_tipi,
            arac_tipi=ucret.arac_tipi, cikis_noktasi=ucret.cikis_noktasi,
            tutar=_yeni_fiyat(ucret.tutar, onizleme.oran), esik=ucret.esik,
            gecerlilik_baslangic=gecerlilik, gecerlilik_bitis=None,
            nakliyeci=ucret.nakliyeci, motorin_fiyati=onizleme.yeni_motorin,
            aciklama=not_metni,
        )
        if ucret.gecerlilik_bitis is None or ucret.gecerlilik_bitis > onceki_gun:
            ucret.gecerlilik_bitis = onceki_gun
        db.add(yeni_ucret)

    db.flush()
    return onizleme
