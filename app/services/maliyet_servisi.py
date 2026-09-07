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
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.iller import yer_adi
from app.models import (
    Ayar,
    ButceKalemi,
    ButceSenaryosu,
    MaliyetBirimi,
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


# ------------------------------------------------------------------------ tarife
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

    def __init__(self, tarifeler: list[NakliyeTarifesi]):
        self._indeks: dict[tuple[str, str, str | None], list[NakliyeTarifesi]] = (
            defaultdict(list)
        )
        for tarife in tarifeler:
            anahtar = (
                tarife.sevkiyat_tipi,
                yer_adi(tarife.il),
                (tarife.arac_tipi or "").upper() or None,
            )
            self._indeks[anahtar].append(tarife)

    def bul(
        self,
        sevkiyat_tipi: str,
        il: str,
        gun: date,
        arac_tipi: str | None = None,
        nakliyeci: str | None = None,
    ) -> NakliyeTarifesi | None:
        """Plan tarihinde geçerli tarife.

        Nakliyeciye özel tarife varsa o kazanır; yoksa genel tarife kullanılır.
        Aynı gün birden çok tarife geçerliyse **en geç başlayan** seçilir: fiyat
        güncellemesi eskisini kapatmadan girilmiş olabilir.
        """
        adaylar = self._indeks.get(
            (sevkiyat_tipi, yer_adi(il), (arac_tipi or "").upper() or None), []
        )
        gecerliler = [t for t in adaylar if t.kapsiyor_mu(gun)]
        if not gecerliler:
            return None
        ad = (nakliyeci or "").strip().upper()
        ozel = [t for t in gecerliler if (t.nakliyeci or "").strip().upper() == ad and ad]
        secilenler = ozel or [t for t in gecerliler if not t.nakliyeci]
        if not secilenler:
            return None
        return max(secilenler, key=lambda t: t.gecerlilik_baslangic)


# ------------------------------------------------------------------- hesaplama
@dataclass
class SatirMaliyeti:
    """Bir sipariş satırının payına düşen nakliye maliyeti."""

    satir_id: int
    teslimat_no: str
    siparis_no: str
    musteri: str
    il: str
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
    satirlar: list[SatirMaliyeti] = field(default_factory=list)
    eksikler: list[str] = field(default_factory=list)
    """Tarifesi bulunamayan iller; maliyet bu kadarıyla eksik hesaplandı."""

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
    ftl_kurali: str = FTL_IL_VARSAYILAN,
) -> PlanMaliyeti:
    """Bir planın maliyetini hesaplar ve sipariş satırlarına dağıtır."""
    sonuc = PlanMaliyeti(plan=plan, fiili_maliyet=plan.fiili_maliyet)
    tip = (plan.sevkiyat_tipi or "").upper()
    if plan.modul != MALIYET_MODULU or plan.durum is PlanDurumu.IPTAL:
        return sonuc

    ham: list[tuple[SiparisSatiri, str, Decimal]] = []
    il_desileri: dict[str, Decimal] = defaultdict(Decimal)
    for satir in plan.satirlar:
        il = yer_adi(satir.sehir)
        desi = urun_desileri.get(satir.urun_kodu, Decimal(0)) * Decimal(satir.miktar)
        ham.append((satir, il, desi))
        il_desileri[il] += desi

    gun = plan.plan_tarihi or date.today()

    if tip in SEFER_TIPLERI:
        sonuc.birim = MaliyetBirimi.SEFER
        iller = _plan_illeri(plan) or sorted(il_desileri)
        fiyat_ili = _ftl_fiyat_ili(plan, ftl_kurali, iller, dict(il_desileri))
        sonuc.fiyat_ili = fiyat_ili
        tarife = defter.bul(
            tip, fiyat_ili, gun,
            arac_tipi=plan.arac_tipi, nakliyeci=plan.nakliyeci,
        )
        if tarife is None:
            sonuc.eksikler.append(
                f"{fiyat_ili or '—'} · {(plan.arac_tipi or '—').upper()} sefer tarifesi yok"
            )
            return sonuc
        sonuc.tarife_maliyeti = _kurus(tarife.birim_fiyat)
        # Sefer bedeli tek parça; satırlara desi payına göre dağıtılır. Desi hiç
        # yoksa (master datada ölçü eksik) adet payı kullanılır — dağıtımsız
        # bırakmak kırılım ekranlarını boş gösterirdi.
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
            tutar = _kurus(sonuc.tarife_maliyeti * pay)
            # Son satır yuvarlama artığını üstlenir: parçaların toplamı her zaman
            # sefer bedeline eşit olmalı, yoksa kırılım toplamı planı tutmaz.
            if sira == len(ham) - 1:
                tutar = sonuc.tarife_maliyeti - dagitilan
            dagitilan += tutar
            sonuc.satirlar.append(_satir_maliyeti(satir, il, desi, tutar))
        return sonuc

    if tip in DESI_TIPLERI:
        sonuc.birim = MaliyetBirimi.DESI
        eksik_iller: set[str] = set()
        toplam = SIFIR
        for satir, il, desi in ham:
            tarife = defter.bul(tip, il, gun, nakliyeci=plan.nakliyeci)
            if tarife is None:
                eksik_iller.add(il or "—")
                tutar = SIFIR
            else:
                tutar = _kurus(tarife.birim_fiyat * desi)
            toplam += tutar
            sonuc.satirlar.append(_satir_maliyeti(satir, il, desi, tutar))
        sonuc.tarife_maliyeti = toplam
        sonuc.eksikler.extend(
            f"{il} · {tip} desi tarifesi yok" for il in sorted(eksik_iller)
        )
        return sonuc

    return sonuc


def _satir_maliyeti(
    satir: SiparisSatiri, il: str, desi: Decimal, tutar: Decimal
) -> SatirMaliyeti:
    return SatirMaliyeti(
        satir_id=satir.id,
        teslimat_no=satir.teslimat_no,
        siparis_no=satir.siparis_no,
        musteri=_musteri_anahtari(satir),
        il=il,
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

    defter = TarifeDefteri(tarifeleri_getir(db))
    desiler = urun_desileri(db)
    kural = ftl_il_kurali(db)

    sonuclar = []
    for plan in db.scalars(sorgu.limit(limit)).all():
        maliyet = plan_maliyeti(plan, defter, desiler, kural)
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


def _senaryo_aylari(
    db: Session, yil: int, senaryo: ButceSenaryosu, surum: str | None = None
) -> dict[int, Decimal]:
    """Ay -> tutar.

    `sevkiyat_tipi` boş olan satır ayın toplamıdır ve varsa kırılım satırları yok
    sayılır; ikisini toplamak maliyeti iki kez sayardı.
    """
    sorgu = select(ButceKalemi).where(
        ButceKalemi.yil == yil, ButceKalemi.senaryo == senaryo
    )
    if surum is not None:
        sorgu = sorgu.where(ButceKalemi.surum == surum)
    kalemler = list(db.scalars(sorgu).all())

    toplamlar: dict[int, Decimal] = {}
    kirilimlar: dict[int, Decimal] = defaultdict(Decimal)
    for kalem in kalemler:
        if kalem.sevkiyat_tipi:
            kirilimlar[kalem.ay] += Decimal(kalem.tutar)
        else:
            toplamlar[kalem.ay] = toplamlar.get(kalem.ay, SIFIR) + Decimal(kalem.tutar)
    for ay, tutar in kirilimlar.items():
        toplamlar.setdefault(ay, tutar)
    return toplamlar


def butce_karsilastirmasi(
    db: Session, yil: int, fc_surum: str = "", bugun: date | None = None
) -> dict:
    """Aylık ve YTD bütçe / FC / gerçekleşen karşılaştırması.

    YTD **yılbaşından bugüne** kümülatiftir; gelecek aylar YTD'ye girmez, yoksa
    henüz gerçekleşmemiş aylar sapmayı olduğundan kötü gösterirdi.
    """
    bugun = bugun or date.today()
    son_ay = 12 if yil < bugun.year else (bugun.month if yil == bugun.year else 0)

    butce = _senaryo_aylari(db, yil, ButceSenaryosu.BUTCE)
    fc = _senaryo_aylari(db, yil, ButceSenaryosu.FC, fc_surum or None)

    maliyetler = plan_maliyetleri(
        db, baslangic=date(yil, 1, 1), bitis=date(yil, 12, 31)
    )
    gerceklesen: dict[int, Decimal] = defaultdict(Decimal)
    for maliyet in maliyetler:
        if maliyet.plan.plan_tarihi:
            gerceklesen[maliyet.plan.plan_tarihi.month] += maliyet.gerceklesen

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
        }
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

    return {
        "yil": yil,
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
                for alan in ("il", "arac_tipi", "nakliyeci", "aciklama")
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

    # Aynı anahtar ve aynı başlangıç tarihi = fiyat düzeltmesi, yeni satır değil.
    mevcut = db.scalar(
        select(NakliyeTarifesi).where(
            NakliyeTarifesi.sevkiyat_tipi == tip,
            NakliyeTarifesi.il == il_adi,
            NakliyeTarifesi.arac_tipi.is_(None) if arac is None
            else NakliyeTarifesi.arac_tipi == arac,
            NakliyeTarifesi.gecerlilik_baslangic == gecerlilik_baslangic,
            NakliyeTarifesi.nakliyeci.is_(None) if not nakliyeci.strip()
            else NakliyeTarifesi.nakliyeci == nakliyeci.strip(),
        )
    )
    tarife = mevcut or NakliyeTarifesi(
        sevkiyat_tipi=tip, il=il_adi, arac_tipi=arac,
        gecerlilik_baslangic=gecerlilik_baslangic,
    )
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

    mevcut = db.scalar(
        select(ButceKalemi).where(
            ButceKalemi.yil == yil_i, ButceKalemi.ay == ay_i,
            ButceKalemi.senaryo == senaryo_e, ButceKalemi.surum == surum_m,
            ButceKalemi.sevkiyat_tipi.is_(None) if tip is None
            else ButceKalemi.sevkiyat_tipi == tip,
        )
    )
    kalem = mevcut or ButceKalemi(
        yil=yil_i, ay=ay_i, senaryo=senaryo_e, surum=surum_m, sevkiyat_tipi=tip
    )
    kalem.tutar = tutar_d
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
            "sevkiyat_tipi": k.sevkiyat_tipi or "",
            "tutar": k.tutar, "para_birimi": k.para_birimi,
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
