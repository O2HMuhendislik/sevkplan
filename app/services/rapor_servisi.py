"""Raporlama ve sorgulama servisleri."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PlanDurumu,
    SevkiyatPlani,
    SiparisDurumu,
    SiparisSatiri,
)


@dataclass
class PlanFiltresi:
    durum: str | None = None
    baslangic: date | None = None
    bitis: date | None = None
    arama: str | None = None
    depo_kodu: str | None = None
    modul: str | None = None
    """RING ya da ROTA. Verilmezse bütün modüllerin planları döner."""
    sevkiyat_tipi: str | None = None
    bolge_kodu: str | None = None
    arac_tipi: str | None = None
    """KAMYON / TIR — iç piyasada araç tipine göre filtre."""


def planlari_getir(db: Session, filtre: PlanFiltresi, limit: int = 500) -> list[SevkiyatPlani]:
    sorgu = select(SevkiyatPlani).options(selectinload(SevkiyatPlani.satirlar))
    if filtre.durum:
        sorgu = sorgu.where(SevkiyatPlani.durum == PlanDurumu(filtre.durum))
    if filtre.baslangic:
        sorgu = sorgu.where(SevkiyatPlani.plan_tarihi >= filtre.baslangic)
    if filtre.bitis:
        sorgu = sorgu.where(SevkiyatPlani.plan_tarihi <= filtre.bitis)
    if filtre.depo_kodu:
        sorgu = sorgu.where(SevkiyatPlani.depo_kodu == filtre.depo_kodu)
    if filtre.modul:
        sorgu = sorgu.where(SevkiyatPlani.modul == filtre.modul)
    if filtre.sevkiyat_tipi:
        sorgu = sorgu.where(SevkiyatPlani.sevkiyat_tipi == filtre.sevkiyat_tipi)
    if filtre.bolge_kodu:
        sorgu = sorgu.where(SevkiyatPlani.bolge_kodu == filtre.bolge_kodu)
    if filtre.arac_tipi:
        sorgu = sorgu.where(SevkiyatPlani.arac_tipi == filtre.arac_tipi)
    if filtre.arama:
        desen = f"%{filtre.arama.strip()}%"
        eslesen_plan_idleri = select(SiparisSatiri.plan_id).where(
            or_(
                SiparisSatiri.teslimat_no.ilike(desen),
                SiparisSatiri.siparis_no.ilike(desen),
            )
        )
        sorgu = sorgu.where(
            or_(
                SevkiyatPlani.sefer_no.ilike(desen),
                SevkiyatPlani.axata_no.ilike(desen),
                SevkiyatPlani.urun_kodlari.ilike(desen),
                SevkiyatPlani.iller_metni.ilike(desen),
                SevkiyatPlani.id.in_(eslesen_plan_idleri),
            )
        )
    sorgu = sorgu.order_by(SevkiyatPlani.plan_tarihi.desc(), SevkiyatPlani.sefer_no.desc())
    return list(db.scalars(sorgu.limit(limit)).all())


def siparisleri_getir(
    db: Session,
    durum: str | None = None,
    arama: str | None = None,
    depo_kodu: str | None = None,
    limit: int = 1000,
    modul: str | None = None,
) -> list[SiparisSatiri]:
    """`modul` verilirse yalnızca o modülün sipariş havuzu döner."""
    sorgu = select(SiparisSatiri).options(selectinload(SiparisSatiri.plan))
    if modul:
        sorgu = sorgu.where(SiparisSatiri.modul == modul)
    if durum:
        sorgu = sorgu.where(SiparisSatiri.durum == SiparisDurumu(durum))
    if depo_kodu:
        sorgu = sorgu.where(SiparisSatiri.depo_kodu == depo_kodu)
    if arama:
        desen = f"%{arama.strip()}%"
        sorgu = sorgu.where(
            or_(
                SiparisSatiri.siparis_no.ilike(desen),
                SiparisSatiri.teslimat_no.ilike(desen),
                SiparisSatiri.urun_kodu.ilike(desen),
                SiparisSatiri.bayi_adi.ilike(desen),
                SiparisSatiri.sehir.ilike(desen),
            )
        )
    sorgu = sorgu.order_by(
        SiparisSatiri.termin_tarihi.asc().nullslast(), SiparisSatiri.siparis_no
    )
    return list(db.scalars(sorgu.limit(limit)).all())


def izleme_sorgusu(db: Session, anahtar: str) -> dict:
    """Sipariş ya da teslimat numarasıyla uçtan uca izleme."""
    desen = f"%{anahtar.strip()}%"
    satirlar = list(
        db.scalars(
            select(SiparisSatiri)
            .options(selectinload(SiparisSatiri.plan).selectinload(SevkiyatPlani.hareketler))
            .where(
                or_(
                    SiparisSatiri.siparis_no.ilike(desen),
                    SiparisSatiri.teslimat_no.ilike(desen),
                )
            )
            .order_by(SiparisSatiri.teslimat_no, SiparisSatiri.siparis_satir_no)
        ).all()
    )
    planlar = {satir.plan.sefer_no: satir.plan for satir in satirlar if satir.plan}
    return {"satirlar": satirlar, "planlar": list(planlar.values())}


def gosterge_paneli(db: Session, modul: str | None = None) -> dict:
    """Ana ekran özet metrikleri.

    `modul` verilirse **hem siparişler hem planlar** yalnızca o modülden sayılır.
    Havuzlar ayrı olduğu için Ring ekranında iç piyasa siparişini "bekleyen" diye
    göstermek yanıltıyordu: kullanıcı planlanmayı bekleyen bir iş var sanıyor, oysa
    o satırı planlayacak modül başka.
    """
    siparis_sorgusu = select(
        SiparisSatiri.durum, func.count(SiparisSatiri.id)
    ).group_by(SiparisSatiri.durum)
    if modul:
        siparis_sorgusu = siparis_sorgusu.where(SiparisSatiri.modul == modul)
    siparis_durumlari = dict(db.execute(siparis_sorgusu).all())
    plan_sorgusu = select(
        SevkiyatPlani.durum, func.count(SevkiyatPlani.id)
    ).group_by(SevkiyatPlani.durum)
    if modul:
        plan_sorgusu = plan_sorgusu.where(SevkiyatPlani.modul == modul)
    plan_durumlari = dict(db.execute(plan_sorgusu).all())
    aktif = [PlanDurumu.TASLAK, PlanDurumu.AXATA_BEKLIYOR, PlanDurumu.MAIL_GONDERILDI,
             PlanDurumu.TAMAMLANDI]
    doluluk_sorgusu = select(func.avg(SevkiyatPlani.doluluk_yuzdesi)).where(
        SevkiyatPlani.durum.in_(aktif)
    )
    if modul:
        doluluk_sorgusu = doluluk_sorgusu.where(SevkiyatPlani.modul == modul)
    ortalama_doluluk = db.scalar(doluluk_sorgusu)
    return {
        "siparis": {durum.value: adet for durum, adet in siparis_durumlari.items()},
        "plan": {durum.value: adet for durum, adet in plan_durumlari.items()},
        "toplam_plan": sum(plan_durumlari.values()),
        "ortalama_doluluk": (
            Decimal(ortalama_doluluk).quantize(Decimal("0.1")) if ortalama_doluluk else Decimal(0)
        ),
    }


def urun_bazli_ozet(db: Session, modul: str | None = None) -> list[dict]:
    """Ürün bazında plan / palet / doluluk özeti. `modul` verilirse o modülle sınırlı."""
    sorgu = (
        select(
            SevkiyatPlani.planlama_anahtari,
            SevkiyatPlani.urun_kodlari,
            func.count(SevkiyatPlani.id),
            func.sum(SevkiyatPlani.toplam_palet),
            func.avg(SevkiyatPlani.doluluk_yuzdesi),
        )
        .where(SevkiyatPlani.durum != PlanDurumu.IPTAL)
        .group_by(SevkiyatPlani.planlama_anahtari, SevkiyatPlani.urun_kodlari)
        .order_by(func.count(SevkiyatPlani.id).desc())
    )
    if modul:
        sorgu = sorgu.where(SevkiyatPlani.modul == modul)
    satirlar = db.execute(sorgu).all()
    return [
        {
            "anahtar": anahtar,
            "urunler": urunler,
            "plan_sayisi": adet,
            "toplam_palet": palet or 0,
            "ortalama_doluluk": Decimal(doluluk or 0).quantize(Decimal("0.1")),
        }
        for anahtar, urunler, adet, palet, doluluk in satirlar
    ]


def aylik_ozet(db: Session, modul: str | None = None) -> list[dict]:
    """Dönem bazında plan özeti. `modul` verilirse o modülle sınırlı."""
    sorgu = (
        select(
            SevkiyatPlani.donem,
            func.count(SevkiyatPlani.id),
            func.sum(SevkiyatPlani.toplam_palet),
            func.avg(SevkiyatPlani.doluluk_yuzdesi),
        )
        .where(SevkiyatPlani.durum != PlanDurumu.IPTAL)
        .group_by(SevkiyatPlani.donem)
        .order_by(SevkiyatPlani.donem.desc())
    )
    if modul:
        sorgu = sorgu.where(SevkiyatPlani.modul == modul)
    satirlar = db.execute(sorgu).all()
    return [
        {
            "donem": f"20{donem[:2]}-{donem[2:]}",
            "plan_sayisi": adet,
            "toplam_palet": palet or 0,
            "ortalama_doluluk": Decimal(doluluk or 0).quantize(Decimal("0.1")),
        }
        for donem, adet, palet, doluluk in satirlar
    ]


def sevk_durumu(
    db: Session, limit: int = 200, modul: str | None = None
) -> list[SevkiyatPlani]:
    """Axata ve gönderim takibi için plan listesi.

    Henüz tamamlanmamış planlar önce gelir; böylece Axata numarası girilmeyi bekleyen
    planlar listenin başında görünür. `modul` verilirse o modülle sınırlı.
    """
    sorgu = (
        select(SevkiyatPlani)
        .where(SevkiyatPlani.durum != PlanDurumu.IPTAL)
        .order_by(
            SevkiyatPlani.durum == PlanDurumu.TAMAMLANDI,
            SevkiyatPlani.axata_no.isnot(None),
            SevkiyatPlani.plan_tarihi.desc(),
            SevkiyatPlani.sefer_no.desc(),
        )
    )
    if modul:
        sorgu = sorgu.where(SevkiyatPlani.modul == modul)
    return list(db.scalars(sorgu.limit(limit)).all())


def bekleyen_ozeti(db: Session, modul: str | None = None) -> list[dict]:
    """Planlanmayı bekleyen siparişlerin ürün bazında özeti.

    **Modüle göre daraltılır.** Havuzlar ayrı olduğu için Ring ekranında iç piyasa
    ya da ihracat siparişi göstermek yanıltıcıydı: kullanıcı "kalanları da planla"
    dediğinde o satırlar yerinde kalıyor, çünkü onları planlayacak modül başka.
    """
    sorgu = (
        select(
            SiparisSatiri.urun_kodu,
            func.count(func.distinct(SiparisSatiri.teslimat_no)),
            func.sum(SiparisSatiri.miktar),
            func.min(SiparisSatiri.termin_tarihi),
        )
        .where(SiparisSatiri.durum == SiparisDurumu.BEKLEMEDE)
        .group_by(SiparisSatiri.urun_kodu)
        .order_by(func.min(SiparisSatiri.termin_tarihi))
    )
    if modul:
        sorgu = sorgu.where(SiparisSatiri.modul == modul)
    return [
        {
            "urun_kodu": urun_kodu,
            "teslimat_sayisi": teslimat,
            "toplam_miktar": miktar or 0,
            "en_eski_termin": termin,
        }
        for urun_kodu, teslimat, miktar, termin in db.execute(sorgu).all()
    ]


def bekleyen_detaylari(
    db: Session, modul: str | None = None, limit: int = 2000
) -> list[SiparisSatiri]:
    """Plana giremeyen sipariş satırlarının tamamı — beklemede **ve** hatalı.

    Özet tablo "hangi üründen kaç teslimat" diyor ama planlamacının görmesi gereken
    şey satırın kendisi: hangi bayi, hangi il, hangi depo, ne zamandır bekliyor.
    """
    sorgu = (
        select(SiparisSatiri)
        .where(
            SiparisSatiri.durum.in_([SiparisDurumu.BEKLEMEDE, SiparisDurumu.HATALI]),
            SiparisSatiri.plan_id.is_(None),
        )
        .order_by(
            SiparisSatiri.durum,
            SiparisSatiri.termin_tarihi.asc().nullslast(),
            SiparisSatiri.teslimat_no,
        )
    )
    if modul:
        sorgu = sorgu.where(SiparisSatiri.modul == modul)
    return list(db.scalars(sorgu.limit(limit)).all())


def hatali_ozeti(db: Session, modul: str | None = None) -> list[dict]:
    """Planlamaya hiç giremeyen (HATALI) siparişler ve gerekçeleri.

    Bunlar hacim bekleyen satırlar değildir: master datası eksik olduğu için
    planlanamazlar ve "kalanları da planla" da onları kurtarmaz. Ekranda ayrı
    gösterilmezse kullanıcı planlamanın çalışmadığını sanıyor.
    """
    sorgu = (
        select(
            SiparisSatiri.urun_kodu,
            SiparisSatiri.hata_aciklamasi,
            func.count(func.distinct(SiparisSatiri.teslimat_no)),
            func.sum(SiparisSatiri.miktar),
        )
        .where(SiparisSatiri.durum == SiparisDurumu.HATALI)
        .group_by(SiparisSatiri.urun_kodu, SiparisSatiri.hata_aciklamasi)
        .order_by(func.sum(SiparisSatiri.miktar).desc())
    )
    if modul:
        sorgu = sorgu.where(SiparisSatiri.modul == modul)
    return [
        {
            "urun_kodu": urun_kodu,
            "sebep": sebep or "Sebep kaydedilmemiş",
            "teslimat_sayisi": teslimat,
            "toplam_miktar": miktar or 0,
        }
        for urun_kodu, sebep, teslimat, miktar in db.execute(sorgu).all()
    ]


def ic_piyasa_ozeti(db: Session) -> dict:
    """İç piyasa gösterge paneli: sevkiyat tipi bazında plan ve durak sayıları."""
    satirlar = db.execute(
        select(
            SevkiyatPlani.sevkiyat_tipi,
            func.count(SevkiyatPlani.id),
            func.sum(SevkiyatPlani.durak_sayisi),
            func.avg(SevkiyatPlani.doluluk_yuzdesi),
            func.sum(SevkiyatPlani.toplam_adet),
        )
        .where(
            SevkiyatPlani.modul == "ROTA",
            SevkiyatPlani.durum != PlanDurumu.IPTAL,
        )
        .group_by(SevkiyatPlani.sevkiyat_tipi)
    ).all()
    return {
        (tip or "?"): {
            "plan": adet,
            "durak": int(durak or 0),
            "doluluk": (
                Decimal(doluluk).quantize(Decimal("0.1")) if doluluk else Decimal(0)
            ),
            "adet": Decimal(toplam_adet or 0),
        }
        for tip, adet, durak, doluluk, toplam_adet in satirlar
    }


def ic_arac_ozeti(db: Session) -> list[dict]:
    """İç piyasa planlarının araç (kamyon / tır) dağılımı.

    Aynı yük hem kamyona hem tıra yüklenebildiği için planlamanın verdiği asıl karar
    budur; "kaç kamyon, kaç tır" sorusunun cevabı gösterge panelinde durmalı.
    """
    satirlar = db.execute(
        select(
            SevkiyatPlani.arac_tipi,
            SevkiyatPlani.sevkiyat_tipi,
            func.count(SevkiyatPlani.id),
            func.avg(SevkiyatPlani.doluluk_yuzdesi),
            func.sum(SevkiyatPlani.toplam_adet),
        )
        .where(
            SevkiyatPlani.modul == "ROTA",
            SevkiyatPlani.durum != PlanDurumu.IPTAL,
            SevkiyatPlani.sevkiyat_tipi != "KARGO",
        )
        .group_by(SevkiyatPlani.arac_tipi, SevkiyatPlani.sevkiyat_tipi)
        .order_by(func.count(SevkiyatPlani.id).desc())
    ).all()
    adlar = {"KAMYON": "Kamyon", "TIR": "Tır"}
    return [
        {
            "arac": adlar.get((arac or "").upper(), arac or "—"),
            "tip": tip or "—",
            "plan": adet,
            "doluluk": (
                Decimal(doluluk).quantize(Decimal("0.1")) if doluluk else Decimal(0)
            ),
            "adet": Decimal(toplam_adet or 0),
        }
        for arac, tip, adet, doluluk, toplam_adet in satirlar
    ]


def bolge_ozeti(db: Session) -> list[dict]:
    """Bölge bazında iç piyasa plan dağılımı."""
    from app.domain.bolgeler import bolge_adi

    satirlar = db.execute(
        select(
            SevkiyatPlani.bolge_kodu,
            func.count(SevkiyatPlani.id),
            func.sum(SevkiyatPlani.durak_sayisi),
            func.avg(SevkiyatPlani.doluluk_yuzdesi),
        )
        .where(
            SevkiyatPlani.modul == "ROTA",
            SevkiyatPlani.durum != PlanDurumu.IPTAL,
        )
        .group_by(SevkiyatPlani.bolge_kodu)
        .order_by(func.count(SevkiyatPlani.id).desc())
    ).all()
    return [
        {
            "kod": kod or "",
            "ad": bolge_adi(kod or ""),
            "plan": adet,
            "durak": int(durak or 0),
            "doluluk": (
                Decimal(doluluk).quantize(Decimal("0.1")) if doluluk else Decimal(0)
            ),
        }
        for kod, adet, durak, doluluk in satirlar
    ]


def musterileri_getir(
    db: Session,
    arama: str | None = None,
    tir_girisi: str | None = None,
    limit: int = 500,
) -> list:
    from app.models import Musteri

    sorgu = select(Musteri)
    if arama:
        desen = f"%{arama.strip()}%"
        sorgu = sorgu.where(
            or_(
                Musteri.bayi_adi.ilike(desen),
                Musteri.alici_firma.ilike(desen),
                Musteri.il.ilike(desen),
                Musteri.ilce.ilike(desen),
                Musteri.bayi_kodu.ilike(desen),
            )
        )
    if tir_girisi:
        sorgu = sorgu.where(Musteri.tir_girisi == tir_girisi)
    sorgu = sorgu.order_by(Musteri.bayi_adi)
    return list(db.scalars(sorgu.limit(limit)).all())


# ------------------------------------------------------------ modüller arası rapor

MODUL_ADLARI = {
    "RING": "Ring",
    "ROTA": "İç Piyasa",
    "IHRACAT": "İhracat",
}


def modul_ozeti(db: Session) -> list[dict]:
    """Modül bazında sipariş ve plan sayıları — Raporlama ekranının üst tablosu."""
    siparisler = dict(
        db.execute(
            select(SiparisSatiri.modul, func.count(SiparisSatiri.id)).group_by(
                SiparisSatiri.modul
            )
        ).all()
    )
    bekleyenler = dict(
        db.execute(
            select(SiparisSatiri.modul, func.count(SiparisSatiri.id))
            .where(SiparisSatiri.durum == SiparisDurumu.BEKLEMEDE)
            .group_by(SiparisSatiri.modul)
        ).all()
    )
    planlar = dict(
        db.execute(
            select(SevkiyatPlani.modul, func.count(SevkiyatPlani.id))
            .where(SevkiyatPlani.durum != PlanDurumu.IPTAL)
            .group_by(SevkiyatPlani.modul)
        ).all()
    )
    kodlar = sorted(set(siparisler) | set(planlar) | set(MODUL_ADLARI))
    return [
        {
            "kod": kod,
            "ad": MODUL_ADLARI.get(kod, kod),
            "siparis": siparisler.get(kod, 0),
            "bekleyen": bekleyenler.get(kod, 0),
            "plan": planlar.get(kod, 0),
        }
        for kod in kodlar
    ]


@dataclass
class PlanlamaKpi:
    """Siparişin sisteme girmesiyle plana alınması arasındaki süre.

    Sahadaki soru şu: "sipariş elimize geldikten kaç gün sonra araca bindi?"
    Ölçü, sipariş satırının sisteme yüklendiği gün ile planın üretildiği gün
    arasındaki farktır. Termin verilmişse plan tarihinin termine göre kaç gün
    erken/geç olduğu da ayrıca tutulur.
    """

    modul: str
    planlanan: int = 0
    bekleyen: int = 0
    gun_toplami: int = 0
    ayni_gun: int = 0
    bir_gun: int = 0
    iki_uc_gun: int = 0
    dort_yedi_gun: int = 0
    yedi_ustu: int = 0
    termin_gecikmesi: int = 0
    """Termini geçtikten sonra plana alınan satır sayısı."""
    termin_olculen: int = 0

    @property
    def ad(self) -> str:
        return MODUL_ADLARI.get(self.modul, self.modul)

    @property
    def ortalama_gun(self) -> Decimal:
        if not self.planlanan:
            return Decimal(0)
        return (Decimal(self.gun_toplami) / self.planlanan).quantize(Decimal("0.1"))

    @property
    def gununde_orani(self) -> Decimal:
        """Aynı gün ya da ertesi gün plana alınanların payı (%)."""
        if not self.planlanan:
            return Decimal(0)
        hedefte = self.ayni_gun + self.bir_gun
        return (Decimal(hedefte) * 100 / self.planlanan).quantize(Decimal("0.1"))

    @property
    def termin_gecikme_orani(self) -> Decimal:
        if not self.termin_olculen:
            return Decimal(0)
        return (
            Decimal(self.termin_gecikmesi) * 100 / self.termin_olculen
        ).quantize(Decimal("0.1"))


def planlama_kpi(db: Session, modul: str | None = None) -> list[PlanlamaKpi]:
    """Modül bazında plana alınma süresi dağılımı.

    Yalnızca planlanmış satırlar süreye girer; beklemedekiler ayrı sayılır ki
    "hızlı planladık ama yarısı beklemede" durumu gizlenmesin.
    """
    sorgu = select(SiparisSatiri).options(selectinload(SiparisSatiri.plan))
    if modul:
        sorgu = sorgu.where(SiparisSatiri.modul == modul)
    satirlar = list(db.scalars(sorgu).all())

    kpiler: dict[str, PlanlamaKpi] = {}
    for satir in satirlar:
        kpi = kpiler.setdefault(satir.modul, PlanlamaKpi(modul=satir.modul))
        gun = satir.plana_alinma_gunu
        if gun is None:
            kpi.bekleyen += 1
            continue
        kpi.planlanan += 1
        kpi.gun_toplami += gun
        if gun <= 0:
            kpi.ayni_gun += 1
        elif gun == 1:
            kpi.bir_gun += 1
        elif gun <= 3:
            kpi.iki_uc_gun += 1
        elif gun <= 7:
            kpi.dort_yedi_gun += 1
        else:
            kpi.yedi_ustu += 1

        termin_farki = satir.termine_gore_gun
        if termin_farki is not None:
            kpi.termin_olculen += 1
            if termin_farki < 0:
                kpi.termin_gecikmesi += 1
    return sorted(kpiler.values(), key=lambda k: k.ad)


def tum_siparisler(
    db: Session,
    modul: str | None = None,
    durum: str | None = None,
    arama: str | None = None,
    limit: int = 500,
) -> list[SiparisSatiri]:
    """Raporlama ekranının sipariş listesi: bütün modüller, modüle göre filtrelenebilir."""
    return siparisleri_getir(db, durum, arama, limit=limit, modul=modul)


def ihracat_ulke_ozeti(db: Session) -> list[dict]:
    """Ülke bazında ihracat planı dağılımı ve taşıma modu."""
    satirlar = db.execute(
        select(
            SevkiyatPlani.ulke,
            SevkiyatPlani.tasima_modu,
            func.count(SevkiyatPlani.id),
            func.sum(SevkiyatPlani.toplam_desi),
            func.avg(SevkiyatPlani.doluluk_yuzdesi),
        )
        .where(
            SevkiyatPlani.modul == "IHRACAT",
            SevkiyatPlani.durum != PlanDurumu.IPTAL,
        )
        .group_by(SevkiyatPlani.ulke, SevkiyatPlani.tasima_modu)
        .order_by(func.count(SevkiyatPlani.id).desc())
    ).all()
    return [
        {
            "ulke": ulke or "—",
            "tasima_modu": modu or "",
            "plan": adet,
            "desi": Decimal(desi or 0).quantize(Decimal(1)),
            "doluluk": (
                Decimal(doluluk).quantize(Decimal("0.1")) if doluluk else Decimal(0)
            ),
        }
        for ulke, modu, adet, desi, doluluk in satirlar
    ]
