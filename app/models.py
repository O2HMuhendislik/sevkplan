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

from app.domain.kapasite import AracTipi


AKSESUAR_GRUPLARI = {"AKSESUAR", "BACA", "DİRSEK", "DIRSEK"}


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
    """Ürün master datası — kaynak sistemdeki `masterdata` sayfasının karşılığı.

    Planlama iki ölçüden birini kullanır:
      * palet  = yukarı yuvarla(miktar / palet_ici_adet)
      * anahtar = miktar / (kamyon|tır) yükleme adeti   (1.0 = araç %100 dolu)
    """

    __tablename__ = "urunler"

    id: Mapped[int] = mapped_column(primary_key=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    urun_adi: Mapped[str] = mapped_column(String(250))
    urun_grubu: Mapped[str | None] = mapped_column(String(50), index=True, default=None)

    palet_ici_adet: Mapped[int | None] = mapped_column(Integer, default=None)
    kamyon_yukleme_adeti: Mapped[int | None] = mapped_column(Integer, default=None)
    kamyon_palet: Mapped[int | None] = mapped_column(Integer, default=None)
    tir_yukleme_adeti: Mapped[int | None] = mapped_column(Integer, default=None)
    tir_palet: Mapped[int | None] = mapped_column(Integer, default=None)

    agirlik: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    desi: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)
    m3: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
    palet_en: Mapped[int | None] = mapped_column(Integer, default=None)
    palet_boy: Mapped[int | None] = mapped_column(Integer, default=None)
    palet_yukseklik: Mapped[int | None] = mapped_column(Integer, default=None)

    header_kod: Mapped[str | None] = mapped_column(String(50), index=True, default=None)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    @property
    def planlanabilir_mi(self) -> bool:
        """Kapasite ölçülerinden en az biri hesaplanabiliyor mu?"""
        return bool(
            self.palet_ici_adet or self.kamyon_yukleme_adeti or self.tir_yukleme_adeti
        )

    def yukleme_adeti(self, arac_tipi: AracTipi) -> int | None:
        return (
            self.kamyon_yukleme_adeti
            if arac_tipi is AracTipi.KAMYON
            else self.tir_yukleme_adeti
        )

    def anahtar_degeri(self, arac_tipi: AracTipi) -> Decimal | None:
        """Bir adet ürünün araçta kapladığı oran."""
        adet = self.yukleme_adeti(arac_tipi)
        if not adet:
            return None
        return Decimal(1) / Decimal(adet)

    @property
    def aksesuar_mi(self) -> bool:
        return (self.urun_grubu or "").strip().upper() in AKSESUAR_GRUPLARI

    def planlama_anahtari(self, seviye: str) -> str:
        """Planın içinde neyin aynı kalacağını belirleyen anahtar.

        Header kod tanımlıysa her zaman o kazanır: ana ürün ile aksesuarı aynı
        planda tutmanın yolu budur.
        """
        if self.header_kod:
            return self.header_kod
        if seviye == "URUN_GRUBU" and self.urun_grubu:
            return self.urun_grubu.strip().upper()
        return self.urun_kodu


class SevkiyatPlani(Temel):
    __tablename__ = "sevkiyat_planlari"

    id: Mapped[int] = mapped_column(primary_key=True)
    sefer_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    donem: Mapped[str] = mapped_column(String(4), index=True)
    plan_tipi: Mapped[str] = mapped_column(String(10), default="RING")
    depo_kodu: Mapped[str] = mapped_column(String(10), index=True)
    planlama_anahtari: Mapped[str] = mapped_column(String(50), index=True)
    urun_kodlari: Mapped[str] = mapped_column(String(500))
    olcu: Mapped[str] = mapped_column(String(10), default="PALET")
    toplam_birim: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    toplam_palet: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    toplam_anahtar: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    toplam_adet: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    toplam_agirlik: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
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
    def profil(self):
        from app.domain.kapasite import profil_getir

        return profil_getir(self.plan_tipi)

    @property
    def birim_metni(self) -> str:
        """Planın büyüklüğünü kendi ölçüsüyle gösterir: '20 palet' / '0,984 anahtar'."""
        if self.olcu == "PALET":
            return f"{Decimal(self.toplam_birim).quantize(Decimal(1))} palet"
        return f"{Decimal(self.toplam_birim).quantize(Decimal('0.001'))} anahtar"

    @property
    def teslimat_nolar(self) -> list[str]:
        return sorted({satir.teslimat_no for satir in self.satirlar})


class SiparisSatiri(Temel):
    __tablename__ = "siparis_satirlari"
    __table_args__ = (
        UniqueConstraint(
            "siparis_no", "teslimat_no", "siparis_satir_no", name="uq_siparis_satiri"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    siparis_no: Mapped[str] = mapped_column(String(50), index=True)
    siparis_satir_no: Mapped[str] = mapped_column(String(20))
    teslimat_no: Mapped[str] = mapped_column(String(50), index=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), index=True)
    urun_adi: Mapped[str | None] = mapped_column(String(250), default=None)
    miktar: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    depo_kodu: Mapped[str] = mapped_column(String(10), index=True)
    sehir: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    bayi_adi: Mapped[str | None] = mapped_column(String(250), default=None)
    alici_firma: Mapped[str | None] = mapped_column(String(250), default=None)
    """Kaynak dosyada sevk adresi bu sütunda gelir (yükleme formunda adres satırı)."""
    sevk_adresi: Mapped[str | None] = mapped_column(String(250), default=None)
    """Kaynak dosyada ilçe bu sütunda gelir."""
    teslim_sekli: Mapped[str | None] = mapped_column(String(30), default=None)
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
