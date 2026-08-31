"""Veritabanı modelleri."""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Temel(DeclarativeBase):
    pass


class SiparisDurumu(str, enum.Enum):
    BEKLEMEDE = "BEKLEMEDE"
    PLANLANDI = "PLANLANDI"
    TAMAMLANDI = "TAMAMLANDI"
    HATALI = "HATALI"
    IPTAL = "IPTAL"


class PlanDurumu(str, enum.Enum):
    TASLAK = "TASLAK"
    AXATA_BEKLIYOR = "AXATA_BEKLIYOR"
    MAIL_GONDERILDI = "MAIL_GONDERILDI"
    TAMAMLANDI = "TAMAMLANDI"
    IPTAL = "IPTAL"


class Urun(Temel):
    """Ürün master datası. Palet içi adet planlamanın temel girdisidir."""

    __tablename__ = "urunler"

    id: Mapped[int] = mapped_column(primary_key=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    urun_adi: Mapped[str] = mapped_column(String(200))
    urun_grubu: Mapped[str] = mapped_column(String(50), index=True)
    palet_ici_adet: Mapped[int] = mapped_column(Integer)
    header_kod: Mapped[str | None] = mapped_column(String(50), index=True, default=None)
    aksesuar_mi: Mapped[bool] = mapped_column(Boolean, default=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    @property
    def planlama_anahtari(self) -> str:
        """Header code'lu ürünler ana ürünle aynı planda kalmak zorundadır."""
        return self.header_kod or self.urun_kodu


class SevkiyatPlani(Temel):
    __tablename__ = "sevkiyat_planlari"

    id: Mapped[int] = mapped_column(primary_key=True)
    sefer_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    donem: Mapped[str] = mapped_column(String(4), index=True)
    plan_tipi: Mapped[str] = mapped_column(String(10), default="RING")
    depo_kodu: Mapped[str] = mapped_column(String(10), index=True)
    planlama_anahtari: Mapped[str] = mapped_column(String(50), index=True)
    urun_kodlari: Mapped[str] = mapped_column(String(500))
    toplam_palet: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    doluluk_yuzdesi: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    teslimat_sayisi: Mapped[int] = mapped_column(Integer, default=0)
    istisna_asim: Mapped[bool] = mapped_column(Boolean, default=False)
    mix_mi: Mapped[bool] = mapped_column(Boolean, default=False)
    durum: Mapped[PlanDurumu] = mapped_column(
        Enum(PlanDurumu), default=PlanDurumu.TASLAK, index=True
    )
    axata_no: Mapped[str | None] = mapped_column(String(50), index=True, default=None)
    plan_tarihi: Mapped[date] = mapped_column(Date, index=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    mail_gonderim_tarihi: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    tamamlanma_tarihi: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    iptal_aciklamasi: Mapped[str | None] = mapped_column(Text, default=None)
    olusturan: Mapped[str] = mapped_column(String(100), default="sistem")

    satirlar: Mapped[list[SiparisSatiri]] = relationship(back_populates="plan")
    hareketler: Mapped[list[PlanHareketi]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )

    @property
    def teslimat_nolar(self) -> list[str]:
        return sorted({satir.teslimat_no for satir in self.satirlar})


class SiparisSatiri(Temel):
    __tablename__ = "siparis_satirlari"
    __table_args__ = (
        UniqueConstraint("siparis_no", "siparis_satir_no", name="uq_siparis_satiri"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    siparis_no: Mapped[str] = mapped_column(String(50), index=True)
    siparis_satir_no: Mapped[str] = mapped_column(String(20))
    teslimat_no: Mapped[str] = mapped_column(String(50), index=True)
    musteri_kodu: Mapped[str | None] = mapped_column(String(50), default=None)
    musteri_adi: Mapped[str | None] = mapped_column(String(200), default=None)
    urun_kodu: Mapped[str] = mapped_column(String(50), index=True)
    urun_adi: Mapped[str | None] = mapped_column(String(200), default=None)
    miktar: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    birim_kodu: Mapped[str] = mapped_column(String(10), default="ADET")
    depo_kodu: Mapped[str] = mapped_column(String(10), index=True)
    siparis_tarihi: Mapped[date | None] = mapped_column(Date, default=None)
    termin_tarihi: Mapped[date | None] = mapped_column(Date, index=True, default=None)
    durum: Mapped[SiparisDurumu] = mapped_column(
        Enum(SiparisDurumu), default=SiparisDurumu.BEKLEMEDE, index=True
    )
    hata_aciklamasi: Mapped[str | None] = mapped_column(Text, default=None)
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("sevkiyat_planlari.id"), index=True, default=None
    )
    ice_aktarim_id: Mapped[int | None] = mapped_column(
        ForeignKey("ice_aktarimlar.id"), default=None
    )
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    plan: Mapped[SevkiyatPlani | None] = relationship(back_populates="satirlar")

    @property
    def oncelik_tarihi(self) -> date:
        return self.termin_tarihi or self.siparis_tarihi or date.today()


class SeferSayaci(Temel):
    """Dönem (YYAA) + belge kodu bazında sayaç. Her ay 1001'den başlar."""

    __tablename__ = "sefer_sayaclari"
    __table_args__ = (UniqueConstraint("donem", "belge_kodu", name="uq_sefer_sayaci"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    donem: Mapped[str] = mapped_column(String(4), index=True)
    belge_kodu: Mapped[str] = mapped_column(String(1))
    son_sayac: Mapped[int] = mapped_column(Integer)


class IceAktarim(Temel):
    __tablename__ = "ice_aktarimlar"

    id: Mapped[int] = mapped_column(primary_key=True)
    dosya_adi: Mapped[str] = mapped_column(String(300))
    tur: Mapped[str] = mapped_column(String(20))
    toplam_satir: Mapped[int] = mapped_column(Integer, default=0)
    basarili_satir: Mapped[int] = mapped_column(Integer, default=0)
    hatali_satir: Mapped[int] = mapped_column(Integer, default=0)
    hata_ozeti: Mapped[str | None] = mapped_column(Text, default=None)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    kullanici: Mapped[str] = mapped_column(String(100), default="sistem")


class PlanHareketi(Temel):
    """Plan üzerindeki her statü değişikliğinin izi. Geçmişe dönük sorgulama için."""

    __tablename__ = "plan_hareketleri"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("sevkiyat_planlari.id"), index=True)
    onceki_durum: Mapped[str | None] = mapped_column(String(20), default=None)
    yeni_durum: Mapped[str] = mapped_column(String(20))
    aciklama: Mapped[str | None] = mapped_column(Text, default=None)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    kullanici: Mapped[str] = mapped_column(String(100), default="sistem")

    plan: Mapped[SevkiyatPlani] = relationship(back_populates="hareketler")
