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


class Rol(str, enum.Enum):
    """Kullanıcı rolleri. Modül yetkileri ayrıca kullanıcı bazında verilir."""

    YONETICI = "YONETICI"
    """Her modüle ve kullanıcı yönetimine erişir."""
    PLANLAMACI = "PLANLAMACI"
    """Yetkili olduğu modüllerde plan üretir, düzenler."""
    DEPO = "DEPO"
    """Yükleme formunu görür, Axata numarası girer, planı tamamlar."""
    NAKLIYECI = "NAKLIYECI"
    """Dış kullanıcı. Yalnızca kendisine açılan araç talebi ekranlarını görür."""
    IZLEYICI = "IZLEYICI"
    """Yalnızca görüntüler, değişiklik yapamaz."""


class YetkiSeviyesi(str, enum.Enum):
    GORUNTULE = "GORUNTULE"
    DUZENLE = "DUZENLE"


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


class Kullanici(Temel):
    """Sisteme giriş yapan kişi. Parola `app/guvenlik.py` ile scrypt olarak saklanır."""

    __tablename__ = "kullanicilar"

    id: Mapped[int] = mapped_column(primary_key=True)
    kullanici_adi: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    ad_soyad: Mapped[str] = mapped_column(String(150))
    eposta: Mapped[str | None] = mapped_column(String(200), default=None)
    firma: Mapped[str | None] = mapped_column(String(150), default=None)
    """Dış kullanıcılar için nakliyeci firma adı."""
    parola_ozeti: Mapped[str] = mapped_column(String(255))
    rol: Mapped[Rol] = mapped_column(Enum(Rol, native_enum=False, length=20), default=Rol.IZLEYICI, index=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    parola_degistirmeli: Mapped[bool] = mapped_column(Boolean, default=True)
    """İlk giriş ve parola sıfırlamadan sonra değiştirme zorunluluğu."""
    basarisiz_deneme: Mapped[int] = mapped_column(Integer, default=0)
    kilitli_mi: Mapped[bool] = mapped_column(Boolean, default=False)
    son_giris: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    yetkiler: Mapped[list[ModulYetkisi]] = relationship(
        back_populates="kullanici", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def yonetici_mi(self) -> bool:
        return self.rol is Rol.YONETICI

    def yetki_seviyesi(self, modul_kodu: str) -> YetkiSeviyesi | None:
        if self.yonetici_mi:
            return YetkiSeviyesi.DUZENLE
        for yetki in self.yetkiler:
            if yetki.modul_kodu == modul_kodu:
                return yetki.seviye
        return None

    def gorebilir_mi(self, modul_kodu: str) -> bool:
        return self.yetki_seviyesi(modul_kodu) is not None

    def duzenleyebilir_mi(self, modul_kodu: str) -> bool:
        return self.yetki_seviyesi(modul_kodu) is YetkiSeviyesi.DUZENLE


class ModulYetkisi(Temel):
    """Bir kullanıcının bir modüldeki yetki seviyesi."""

    __tablename__ = "modul_yetkileri"
    __table_args__ = (
        UniqueConstraint("kullanici_id", "modul_kodu", name="uq_modul_yetkisi"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kullanici_id: Mapped[int] = mapped_column(
        ForeignKey("kullanicilar.id"), index=True
    )
    modul_kodu: Mapped[str] = mapped_column(String(30), index=True)
    seviye: Mapped[YetkiSeviyesi] = mapped_column(
        Enum(YetkiSeviyesi, native_enum=False, length=20), default=YetkiSeviyesi.GORUNTULE
    )

    kullanici: Mapped[Kullanici] = relationship(back_populates="yetkiler")


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


class Musteri(Temel):
    """İç piyasa müşteri master datası.

    Anahtar **bayi adıdır**: kaynak dosyalarda bayi kodu gelmiyor, eşleştirme ad
    üzerinden yapılıyor (bkz. docs/IC-PIYASA-ANALIZ.md §4). Bayi kodlarına ulaşılınca
    `bayi_kodu` alanı doldurulup anahtar oraya taşınacak.

    Kayıtların çoğu geçmiş sevk verisinden üretildi; `tir_girisi` gibi alanlar ekrandan
    elle düzeltilir.
    """

    __tablename__ = "musteriler"

    id: Mapped[int] = mapped_column(primary_key=True)
    anahtar: Mapped[str] = mapped_column(String(250), unique=True, index=True)
    """Bayi adının normalize hâli (Türkçe karakterler ASCII, büyük harf)."""
    bayi_adi: Mapped[str] = mapped_column(String(250), index=True)
    bayi_kodu: Mapped[str | None] = mapped_column(String(50), index=True, default=None)
    alici_firma: Mapped[str | None] = mapped_column(String(250), default=None)
    il: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    ilce: Mapped[str | None] = mapped_column(String(80), default=None)
    sevk_adresi: Mapped[str | None] = mapped_column(String(400), default=None)
    telefon: Mapped[str | None] = mapped_column(String(60), default=None)
    incoterms: Mapped[str | None] = mapped_column(String(10), default=None)
    tir_girisi: Mapped[str] = mapped_column(String(1), default="?")
    """E = tır girebilir, H = fiziki adres tır almıyor, ? = geçmişten karar verilemedi."""
    bolge_kodu: Mapped[str | None] = mapped_column(String(20), index=True, default=None)
    """Boşsa ilin varsayılan bölgesi kullanılır (app/domain/bolgeler.py)."""
    plan_sayisi: Mapped[int] = mapped_column(Integer, default=0)
    son_sevk: Mapped[date | None] = mapped_column(Date, default=None)
    notlar: Mapped[str | None] = mapped_column(Text, default=None)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    @property
    def tir_girisi_metni(self) -> str:
        return {
            "E": "Tır girebilir",
            "H": "Tır giremiyor",
        }.get(self.tir_girisi, "Belirsiz")

    @property
    def etkin_bolge_kodu(self) -> str:
        from app.domain.bolgeler import il_bolgesi

        return self.bolge_kodu or il_bolgesi(self.il or "")

    @property
    def bolge_adi(self) -> str:
        from app.domain.bolgeler import bolge_adi

        return bolge_adi(self.etkin_bolge_kodu)


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
    alt_limit_esnetildi: Mapped[bool] = mapped_column(Boolean, default=False)
    kirik_palet_israfi: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0)
    """Boşa giden palet payı; 0 ise plandaki her üründen tam palet yükleniyor."""
    marka_paylari_metni: Mapped[str | None] = mapped_column(String(200), default=None)
    """Navlun faturasının markalar arasında dağıtımı: 'DEMİRDÖKÜM:0.25|VAİLLANT:0.75'."""
    mix_mi: Mapped[bool] = mapped_column(Boolean, default=False)

    # ---------------------------------------------------------------- iç piyasa
    modul: Mapped[str] = mapped_column(String(20), index=True, default="RING")
    """Planı üreten modül: RING ya da ROTA (iç piyasa). Ekranlar buna göre filtreler."""
    sevkiyat_tipi: Mapped[str | None] = mapped_column(String(10), default=None)
    """FTL / RUTIN / KARGO. Ring planlarında boştur."""
    bolge_kodu: Mapped[str | None] = mapped_column(String(20), index=True, default=None)
    durak_sayisi: Mapped[int] = mapped_column(Integer, default=0)
    """Yükleme formundaki "Yer Miktarı" ile aynı değer."""
    musteri_sayisi: Mapped[int] = mapped_column(Integer, default=0)
    iller_metni: Mapped[str | None] = mapped_column(String(400), default=None)
    """Uğranan iller, yakından uzağa: 'IZMIR, MANISA'."""
    ilceler_metni: Mapped[str | None] = mapped_column(String(600), default=None)
    """Yükleme formunda '+' ile birleşik yazılan ilçeler."""
    son_ugrak: Mapped[str | None] = mapped_column(String(80), default=None)
    son_ugrak_orani: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    toplam_desi: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    yukleme_deposu: Mapped[str | None] = mapped_column(String(10), default=None)
    """Ortak yüklemede aracın yükleneceği depo; diğer depoların malı buraya getirilir."""
    nakliyeci: Mapped[str | None] = mapped_column(String(150), default=None)
    plaka: Mapped[str | None] = mapped_column(String(30), default=None)
    surucu: Mapped[str | None] = mapped_column(String(150), default=None)
    surucu_telefon: Mapped[str | None] = mapped_column(String(40), default=None)

    durum: Mapped[PlanDurumu] = mapped_column(
        Enum(PlanDurumu, native_enum=False, length=20), default=PlanDurumu.TASLAK, index=True
    )
    axata_no: Mapped[str | None] = mapped_column(String(200), index=True, default=None)
    """Girilen Axata numaralarının birleşik hâli; arama ve dışa aktarım için tutulur."""
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
    axata_numaralari: Mapped[list[AxataNumarasi]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AxataNumarasi.id",
    )

    @property
    def marka_paylari(self) -> dict[str, Decimal]:
        """Marka -> oran. Navlun faturasının dağıtımında kullanılır."""
        from app.domain.marka import paylari_coz

        return paylari_coz(self.marka_paylari_metni)

    @property
    def marka_ozeti(self) -> str:
        """Ekranda ve formda gösterilecek biçim: 'DEMİRDÖKÜM %25 · VAİLLANT %75'."""
        return " · ".join(
            f"{ad} %{(oran * 100).quantize(Decimal('0.01')).normalize():f}"
            for ad, oran in self.marka_paylari.items()
        )

    @property
    def axata_ozeti(self) -> str:
        return ", ".join(a.numara for a in self.axata_numaralari)

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

    @property
    def ic_piyasa_mi(self) -> bool:
        return self.modul == "ROTA"

    @property
    def sevkiyat_tipi_adi(self) -> str:
        from app.domain.ic_piyasa import SevkiyatTipi

        if not self.sevkiyat_tipi:
            return "Ring"
        try:
            return SevkiyatTipi(self.sevkiyat_tipi).ad
        except ValueError:
            return self.sevkiyat_tipi

    @property
    def bolge_adi(self) -> str:
        from app.domain.bolgeler import bolge_adi

        return bolge_adi(self.bolge_kodu) if self.bolge_kodu else ""

    @property
    def il_yeri_metni(self) -> str:
        """Yükleme formunun 'İl' satırı.

        Sahadaki biçim: iller '+' ile birleşir, sonuna toplam durak sayısı eklenir —
        tek illi araçta `İZMİR2YER`, çok illi araçta `ISPARTA+ANTALYA2YER`. Araçtaki
        her il ayrı yazılır; yalnızca ilkini yazmak rotayı yanlış gösterir.
        """
        iller = [
            parca.strip() for parca in (self.iller_metni or "").split(",") if parca.strip()
        ]
        if not iller:
            return ""
        birlesik = "+".join(iller)
        return f"{birlesik}{self.durak_sayisi}YER" if self.durak_sayisi else birlesik

    @property
    def ilce_metni(self) -> str:
        """Formda ilçeler '+' ile birleşik yazılır: 'KARABAĞLAR+BERGAMA'."""
        return "+".join(
            parca.strip() for parca in (self.ilceler_metni or "").split(",") if parca.strip()
        )

    def aktarma_notu(self, satir: SiparisSatiri) -> str:
        """Ortak yüklemede malı başka depoda olan satırın notu."""
        from app.domain.ic_piyasa import aktarma_notu

        return aktarma_notu(satir.depo_kodu, self.yukleme_deposu or "")


class AxataNumarasi(Temel):
    """Bir plana ait WMS iş emri numarası.

    Depo operasyonu toplama işini kolaylaştırmak için ürünleri gruplayıp aynı plana
    birden fazla Axata numarası verebiliyor; bu yüzden numara plan başına tek değildir.
    """

    __tablename__ = "axata_numaralari"
    __table_args__ = (
        UniqueConstraint("plan_id", "numara", name="uq_plan_axata"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("sevkiyat_planlari.id"), index=True)
    numara: Mapped[str] = mapped_column(String(50), index=True)
    aciklama: Mapped[str | None] = mapped_column(String(200), default=None)
    """Numaranın hangi ürün grubunu kapsadığı (depo operasyonunun notu)."""
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    kullanici: Mapped[str] = mapped_column(String(100), default="sistem")

    plan: Mapped[SevkiyatPlani] = relationship(back_populates="axata_numaralari")


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
    """Kaynak dosyanın `Not` sütunu, ham hâliyle."""
    incoterms: Mapped[str | None] = mapped_column(String(10), index=True, default=None)
    """`Not` sütunundan ayrıştırılan teslim şekli: CIF / EXW ... EXW olanlar kargoya gider."""
    ilce: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    """İlçe. Kaynak dosyada bazen `SevkAdresi`, bazen `Not` sütununun içinde gelir."""
    siparis_tarihi: Mapped[date | None] = mapped_column(Date, default=None)
    termin_tarihi: Mapped[date | None] = mapped_column(Date, index=True, default=None)
    durum: Mapped[SiparisDurumu] = mapped_column(
        Enum(SiparisDurumu, native_enum=False, length=20), default=SiparisDurumu.BEKLEMEDE, index=True
    )
    hata_aciklamasi: Mapped[str | None] = mapped_column(Text, default=None)
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("sevkiyat_planlari.id"), index=True, default=None
    )
    ice_aktarim_id: Mapped[int | None] = mapped_column(
        ForeignKey("ice_aktarimlar.id"), default=None
    )
    modul: Mapped[str] = mapped_column(String(20), index=True, default="RING")
    """Siparişi yükleyen modül: RING / ROTA (iç piyasa) / IHRACAT.

    Her modül yalnızca kendi siparişlerini görür ve planlar; havuzlar ayrıdır.
    Bütün siparişler yalnızca Raporlama modülünde bir arada görünür.
    """
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    """Siparişin sisteme girdiği an. Plana alınma süresi KPI'ı bundan hesaplanır."""

    plan: Mapped[SevkiyatPlani | None] = relationship(back_populates="satirlar")
    urun: Mapped[Urun | None] = relationship(
        primaryjoin="foreign(SiparisSatiri.urun_kodu) == Urun.urun_kodu",
        viewonly=True,
        lazy="selectin",
    )
    """Master datadaki ürün kaydı. Sipariş dosyasında ürün adı gelmediğinde kullanılır."""

    @property
    def gosterilecek_urun_adi(self) -> str:
        """Ekranlarda gösterilecek ürün adı: dosyadaki ad, yoksa master datadaki."""
        return self.urun_adi or (self.urun.urun_adi if self.urun else "") or "—"

    @property
    def urun_grubu(self) -> str | None:
        return self.urun.urun_grubu if self.urun else None

    @property
    def oncelik_tarihi(self) -> date:
        return self.termin_tarihi or self.siparis_tarihi or date.today()

    @property
    def plana_alinma_gunu(self) -> int | None:
        """Sipariş sisteme girdikten kaç gün sonra plana alındı?

        Planlanmamış satırda None döner. KPI ekranı bu değerin ortalamasını ve
        dağılımını gösterir.
        """
        if self.plan is None or self.plan.olusturma_tarihi is None:
            return None
        return (self.plan.olusturma_tarihi.date() - self.olusturma_tarihi.date()).days

    @property
    def termine_gore_gun(self) -> int | None:
        """Plan, terminden kaç gün önce (+) ya da sonra (-) yapıldı?"""
        if self.plan is None or self.termin_tarihi is None:
            return None
        return (self.termin_tarihi - self.plan.plan_tarihi).days


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
