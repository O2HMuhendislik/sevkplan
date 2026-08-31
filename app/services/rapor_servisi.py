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
                SiparisSatiri.musteri_adi.ilike(desen),
                SiparisSatiri.musteri_kodu.ilike(desen),
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


def gosterge_paneli(db: Session) -> dict:
    """Ana ekran özet metrikleri."""
    siparis_durumlari = dict(
        db.execute(
            select(SiparisSatiri.durum, func.count(SiparisSatiri.id)).group_by(
                SiparisSatiri.durum
            )
        ).all()
    )
    plan_durumlari = dict(
        db.execute(
            select(SevkiyatPlani.durum, func.count(SevkiyatPlani.id)).group_by(
                SevkiyatPlani.durum
            )
        ).all()
    )
    aktif = [PlanDurumu.TASLAK, PlanDurumu.AXATA_BEKLIYOR, PlanDurumu.MAIL_GONDERILDI,
             PlanDurumu.TAMAMLANDI]
    ortalama_doluluk = db.scalar(
        select(func.avg(SevkiyatPlani.doluluk_yuzdesi)).where(
            SevkiyatPlani.durum.in_(aktif)
        )
    )
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
