"""Veri temizleme servisleri.

Test ve deneme sırasında biriken kayıtları seçerek silmek için. Silme işlemleri geri
alınamaz; her biri neyi sildiğini rapor eder ve bağımlılıkları kendisi çözer
(bir plan silinirken içindeki sipariş satırları önce plandan koparılır).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    IceAktarim,
    PlanDurumu,
    PlanHareketi,
    SeferSayaci,
    SevkiyatPlani,
    SiparisDurumu,
    SiparisSatiri,
    Urun,
)


@dataclass
class SilmeSonucu:
    siparis: int = 0
    plan: int = 0
    urun: int = 0
    ice_aktarim: int = 0
    sayac: int = 0

    def ozet(self) -> str:
        parcalar = []
        if self.plan:
            parcalar.append(f"{self.plan} plan")
        if self.siparis:
            parcalar.append(f"{self.siparis} sipariş satırı")
        if self.urun:
            parcalar.append(f"{self.urun} ürün")
        if self.ice_aktarim:
            parcalar.append(f"{self.ice_aktarim} aktarım kaydı")
        if self.sayac:
            parcalar.append("sefer sayacı sıfırlandı")
        return ", ".join(parcalar) + " silindi." if parcalar else "Silinecek kayıt yok."


def sayimlar(db: Session) -> dict[str, int]:
    """Ekranda gösterilecek mevcut kayıt sayıları."""
    return {
        "urun": db.scalar(select(func.count(Urun.id))) or 0,
        "siparis": db.scalar(select(func.count(SiparisSatiri.id))) or 0,
        "bekleyen": db.scalar(
            select(func.count(SiparisSatiri.id)).where(
                SiparisSatiri.durum.in_([SiparisDurumu.BEKLEMEDE, SiparisDurumu.HATALI])
            )
        ) or 0,
        "plan": db.scalar(select(func.count(SevkiyatPlani.id))) or 0,
        "tamamlanan_plan": db.scalar(
            select(func.count(SevkiyatPlani.id)).where(
                SevkiyatPlani.durum == PlanDurumu.TAMAMLANDI
            )
        ) or 0,
        "aktarim": db.scalar(select(func.count(IceAktarim.id))) or 0,
    }


def _planlari_sil(db: Session, planlar: list[SevkiyatPlani]) -> int:
    """Planları ve hareketlerini siler; sipariş satırlarını beklemeye döndürür."""
    if not planlar:
        return 0
    plan_idleri = [plan.id for plan in planlar]
    for satir in db.scalars(
        select(SiparisSatiri).where(SiparisSatiri.plan_id.in_(plan_idleri))
    ).all():
        satir.plan_id = None
        satir.durum = SiparisDurumu.BEKLEMEDE
    db.flush()
    db.execute(delete(PlanHareketi).where(PlanHareketi.plan_id.in_(plan_idleri)))
    db.execute(delete(SevkiyatPlani).where(SevkiyatPlani.id.in_(plan_idleri)))
    db.flush()
    return len(plan_idleri)


def bekleyen_siparisleri_sil(db: Session) -> SilmeSonucu:
    """Planlanmamış (beklemede ve hatalı) sipariş satırlarını siler.

    Planlara dokunmaz; planlanmış ve tamamlanmış satırlar korunur.
    """
    satirlar = db.scalars(
        select(SiparisSatiri).where(
            SiparisSatiri.durum.in_([SiparisDurumu.BEKLEMEDE, SiparisDurumu.HATALI]),
            SiparisSatiri.plan_id.is_(None),
        )
    ).all()
    for satir in satirlar:
        db.delete(satir)
    db.flush()
    return SilmeSonucu(siparis=len(satirlar))


def planlari_sil(
    db: Session,
    baslangic: date | None = None,
    bitis: date | None = None,
    tamamlananlar_dahil: bool = False,
    siparisleri_de_sil: bool = False,
) -> SilmeSonucu:
    """Verilen tarih aralığındaki planları siler.

    Varsayılan olarak tamamlanmış planlara dokunulmaz — onlar sevk edilmiş işin
    kaydıdır. `siparisleri_de_sil` verilmezse plandaki siparişler beklemeye döner.
    """
    sorgu = select(SevkiyatPlani)
    if baslangic:
        sorgu = sorgu.where(SevkiyatPlani.plan_tarihi >= baslangic)
    if bitis:
        sorgu = sorgu.where(SevkiyatPlani.plan_tarihi <= bitis)
    if not tamamlananlar_dahil:
        sorgu = sorgu.where(SevkiyatPlani.durum != PlanDurumu.TAMAMLANDI)
    planlar = list(db.scalars(sorgu).all())

    silinen_siparis = 0
    if siparisleri_de_sil and planlar:
        plan_idleri = [plan.id for plan in planlar]
        satirlar = db.scalars(
            select(SiparisSatiri).where(SiparisSatiri.plan_id.in_(plan_idleri))
        ).all()
        silinen_siparis = len(satirlar)
        for satir in satirlar:
            db.delete(satir)
        db.flush()

    return SilmeSonucu(plan=_planlari_sil(db, planlar), siparis=silinen_siparis)


def siparis_ve_planlari_sil(db: Session, sayaci_sifirla: bool = False) -> SilmeSonucu:
    """Bütün sipariş ve planları siler; ürün master datası korunur."""
    planlar = list(db.scalars(select(SevkiyatPlani)).all())
    sonuc = SilmeSonucu(plan=_planlari_sil(db, planlar))
    sonuc.siparis = db.scalar(select(func.count(SiparisSatiri.id))) or 0
    db.execute(delete(SiparisSatiri))
    sonuc.ice_aktarim = db.scalar(
        select(func.count(IceAktarim.id)).where(IceAktarim.tur == "SIPARIS")
    ) or 0
    db.execute(delete(IceAktarim).where(IceAktarim.tur == "SIPARIS"))
    if sayaci_sifirla:
        sonuc.sayac = db.scalar(select(func.count(SeferSayaci.id))) or 0
        db.execute(delete(SeferSayaci))
    db.flush()
    return sonuc


def her_seyi_sil(db: Session) -> SilmeSonucu:
    """Ürün master datası dahil bütün verileri siler. Boş sistemle başlamak için."""
    sonuc = siparis_ve_planlari_sil(db, sayaci_sifirla=True)
    sonuc.urun = db.scalar(select(func.count(Urun.id))) or 0
    db.execute(delete(Urun))
    kalan_aktarim = db.scalar(select(func.count(IceAktarim.id))) or 0
    sonuc.ice_aktarim += kalan_aktarim
    db.execute(delete(IceAktarim))
    db.flush()
    return sonuc
