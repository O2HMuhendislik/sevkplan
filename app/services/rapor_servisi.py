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
) -> list[SiparisSatiri]:
    sorgu = select(SiparisSatiri).options(selectinload(SiparisSatiri.plan))
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
    """Ana ekran özet metrikleri. `modul` verilirse yalnızca o modülün planları sayılır."""
    siparis_durumlari = dict(
        db.execute(
            select(SiparisSatiri.durum, func.count(SiparisSatiri.id)).group_by(
                SiparisSatiri.durum
            )
        ).all()
    )
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


def urun_bazli_ozet(db: Session) -> list[dict]:
    """Ürün bazında plan / palet / doluluk özeti."""
    satirlar = db.execute(
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
    ).all()
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


def aylik_ozet(db: Session) -> list[dict]:
    satirlar = db.execute(
        select(
            SevkiyatPlani.donem,
            func.count(SevkiyatPlani.id),
            func.sum(SevkiyatPlani.toplam_palet),
            func.avg(SevkiyatPlani.doluluk_yuzdesi),
        )
        .where(SevkiyatPlani.durum != PlanDurumu.IPTAL)
        .group_by(SevkiyatPlani.donem)
        .order_by(SevkiyatPlani.donem.desc())
    ).all()
    return [
        {
            "donem": f"20{donem[:2]}-{donem[2:]}",
            "plan_sayisi": adet,
            "toplam_palet": palet or 0,
            "ortalama_doluluk": Decimal(doluluk or 0).quantize(Decimal("0.1")),
        }
        for donem, adet, palet, doluluk in satirlar
    ]


def sevk_durumu(db: Session, limit: int = 200) -> list[SevkiyatPlani]:
    """Axata ve gönderim takibi için plan listesi.

    Henüz tamamlanmamış planlar önce gelir; böylece Axata numarası girilmeyi bekleyen
    planlar listenin başında görünür.
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
    return list(db.scalars(sorgu.limit(limit)).all())


def bekleyen_ozeti(db: Session) -> list[dict]:
    """Neden planlanamadığını gösteren bekleyen sipariş özeti (ürün bazında)."""
    satirlar = db.execute(
        select(
            SiparisSatiri.urun_kodu,
            func.count(func.distinct(SiparisSatiri.teslimat_no)),
            func.sum(SiparisSatiri.miktar),
            func.min(SiparisSatiri.termin_tarihi),
        )
        .where(SiparisSatiri.durum == SiparisDurumu.BEKLEMEDE)
        .group_by(SiparisSatiri.urun_kodu)
        .order_by(func.min(SiparisSatiri.termin_tarihi))
    ).all()
    return [
        {
            "urun_kodu": urun_kodu,
            "teslimat_sayisi": teslimat,
            "toplam_miktar": miktar or 0,
            "en_eski_termin": termin,
        }
        for urun_kodu, teslimat, miktar, termin in satirlar
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
