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
    select,
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
    eposta: Mapped[str | None] = mapped_column(String(200), default=None)
    """Sevk bilgilendirmesinin gideceği adres."""
    sevk_tipi: Mapped[str | None] = mapped_column(String(80), default=None)
    """Sahanın kendi yazdığı teslimat tipi metni ("TIR-C.TESİ YOK-EİRSALİYE" gibi).

    `tir_girisi` bundan türetilir ama ham metin de saklanır: içinde araç tipinin
    yanında cumartesi ve e-irsaliye bilgisi de var ve ileride başka kural çıkabilir.
    """
    cumartesi_teslimat: Mapped[bool] = mapped_column(Boolean, default=True)
    """Cumartesi mal kabul ediyor mu? Sevk tipinde "C.TESİ YOK" geçenlerde hayır."""
    e_irsaliye: Mapped[bool] = mapped_column(Boolean, default=False)
    """Teslimatta e-irsaliye isteniyor mu?"""
    ozel_durum: Mapped[str | None] = mapped_column(Text, default=None)
    """Sahanın serbest notu: "saat 10:00'a kadar teslim", "tam araç olana kadar
    bekletilmesi" gibi. `notlar` kullanıcının kendi notu; bu alan kaynak dosyadan
    gelir ve yeniden yüklemede güncellenir."""
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


class IhracatMusterisi(Temel):
    """İhracat müşteri master datası.

    Araç tipi müşteriye bağlıdır ve taşıma modunu belirler: konteyner yüklenen müşteri
    deniz, tır yüklenen kara yoludur. Sefer numarasının belge kodu da müşteriden gelir
    (`N` = NSC, `E` = Export).
    """

    __tablename__ = "ihracat_musterileri"

    id: Mapped[int] = mapped_column(primary_key=True)
    anahtar: Mapped[str] = mapped_column(String(250), unique=True, index=True)
    """Müşteri adının normalize hâli; eşleştirme bununla yapılır."""
    musteri_adi: Mapped[str] = mapped_column(String(250), index=True)
    ulke: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    ulke_kodu: Mapped[str | None] = mapped_column(String(10), index=True, default=None)
    sevk_adresi: Mapped[str | None] = mapped_column(String(300), default=None)
    arac_tipi: Mapped[str] = mapped_column(String(20), default="TIR")
    """TIR / KONTEYNER / PARSİYEL / KARGO."""
    sefer_kodu: Mapped[str] = mapped_column(String(1), default="E")
    yukleme_tipi: Mapped[str | None] = mapped_column(String(60), default=None)
    """STANDART / PALET YÜKSELTME / DÖKME / KÖŞEBENT ... yükleme formuna yazılır."""
    aciklama: Mapped[str | None] = mapped_column(Text, default=None)
    """Müşteriye özel yükleme notu: hava yastığı, silika jel, paletsiz dökme ..."""
    azami_agirlik: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    """Azami tonaj (kg). Boşsa araç tipinin varsayılanı kullanılır."""
    incoterms: Mapped[str | None] = mapped_column(String(10), default=None)
    tedarikci: Mapped[str | None] = mapped_column(String(150), default=None)
    satis_destek: Mapped[str | None] = mapped_column(String(150), default=None)
    plan_sayisi: Mapped[int] = mapped_column(Integer, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    @property
    def yukleme_kurali(self):
        """Yükleme tipi + notlardan çözülen hesap kuralı (yeni/eski, palet yükseltme)."""
        from app.domain.ihracat_hesap import yukleme_kurali_coz

        return yukleme_kurali_coz(self.yukleme_tipi or "", self.aciklama or "")

    @property
    def hesaplama_adi(self) -> str:
        return self.yukleme_kurali.ad

    @property
    def tasima_modu(self) -> str:
        from app.domain.ihracat import AracTipi

        try:
            return AracTipi(self.arac_tipi).tasima_modu
        except ValueError:
            return "KARA"

    @property
    def arac_tipi_adi(self) -> str:
        from app.domain.ihracat import AracTipi

        try:
            return AracTipi(self.arac_tipi).ad
        except ValueError:
            return self.arac_tipi


class IhracatUrunu(Temel):
    """İhracat ürün master datası — `Hesaplama.xlsx` dosyasının `Ürün` sayfası.

    İç piyasa ürün master datasından ayrı durur: ihracat SKU'larının tır/konteyner
    yükleme adetleri ve iki ayrı hesap sürümü (yeni / eski) burada tutulur.
    Doluluk = Σ(miktar / yükleme adeti); ayrıntısı `app/domain/ihracat_hesap.py`.
    """

    __tablename__ = "ihracat_urunleri"

    id: Mapped[int] = mapped_column(primary_key=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    urun_adi: Mapped[str] = mapped_column(String(250), default="")
    urun_grubu: Mapped[str | None] = mapped_column(String(50), index=True, default=None)

    palet_ici_adet: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    tir_yukleme_adeti: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    konteyner_yukleme_adeti: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), default=None
    )
    """Yeni hesaplama sütunları: PALET İÇİ ADET / TIR / KONTEYNER."""

    palet_ici_adet_eski: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), default=None
    )
    tir_yukleme_adeti_eski: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), default=None
    )
    konteyner_yukleme_adeti_eski: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), default=None
    )
    """Eski hesaplama sütunları: PALET İÇİ ADET-2 / TIR-2 / KONTEYNER-2."""

    desi: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)
    agirlik: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    en: Mapped[int | None] = mapped_column(Integer, default=None)
    boy: Mapped[int | None] = mapped_column(Integer, default=None)
    yukseklik: Mapped[int | None] = mapped_column(Integer, default=None)
    dokme_adeti: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    """Paletsiz (dökme) yüklemede araca giren adet; master datada çok az üründe dolu."""

    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    @property
    def olcu(self) -> "UrunOlcusu":
        from app.domain.ihracat_hesap import UrunOlcusu

        return UrunOlcusu(
            urun_kodu=self.urun_kodu,
            urun_adi=self.urun_adi or "",
            urun_grubu=self.urun_grubu or "",
            palet_ici_adet=self.palet_ici_adet,
            tir_yukleme_adeti=self.tir_yukleme_adeti,
            konteyner_yukleme_adeti=self.konteyner_yukleme_adeti,
            palet_ici_adet_eski=self.palet_ici_adet_eski,
            tir_yukleme_adeti_eski=self.tir_yukleme_adeti_eski,
            konteyner_yukleme_adeti_eski=self.konteyner_yukleme_adeti_eski,
            desi=self.desi,
            agirlik=self.agirlik,
            dokme_adeti=self.dokme_adeti,
        )

    @property
    def olculebilir_mi(self) -> bool:
        return self.olcu.olculebilir_mi


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

    # ------------------------------------------------------------------ ihracat
    musteri_adi: Mapped[str | None] = mapped_column(String(250), index=True, default=None)
    """İhracatta araç tek noktaya gider; planın müşterisi budur."""
    ulke: Mapped[str | None] = mapped_column(String(80), index=True, default=None)
    ulke_kodu: Mapped[str | None] = mapped_column(String(10), default=None)
    arac_tipi: Mapped[str | None] = mapped_column(String(20), default=None)
    tasima_modu: Mapped[str | None] = mapped_column(String(10), default=None)
    """KARA / DENİZ."""
    yukleme_tipi: Mapped[str | None] = mapped_column(String(60), default=None)
    musteri_aciklamasi: Mapped[str | None] = mapped_column(Text, default=None)
    """Yükleme formuna basılan müşteri notu: hava yastığı, silika jel ..."""
    azami_agirlik: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    konteyner_no: Mapped[str | None] = mapped_column(String(40), default=None)
    muhur_no: Mapped[str | None] = mapped_column(String(40), default=None)
    kisitlayan_olcu: Mapped[str | None] = mapped_column(String(10), default=None)
    """Aracı dolduran sınır: HACİM ya da AĞIRLIK."""
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
    yukleme_notu: Mapped[str | None] = mapped_column(Text, default=None)
    """Yükleme formuna basılacak serbest not; planlamacı depoya buradan yazar."""
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
        """Bütün Axata numaraları tek satırda; deposu olan '74: 5321' diye yazılır."""
        return ", ".join(
            f"{a.depo_kodu}: {a.numara}" if a.depo_kodu else a.numara
            for a in self.axata_numaralari
        )

    @property
    def axata_depolari(self) -> list[str]:
        """Plandaki Axata iş emri açılabilecek depolar.

        Bayi ortak deposu (-1) hariç tutulur: orası ayrı bir ERP, Axata açılmıyor.
        Birden fazla depo çıkarsa her depo kendi iş emrini açar ve numara depoya
        bağlanmalıdır.
        """
        from app.domain.iller import ana_depo

        depolar = {
            ana_depo(satir.depo_kodu)
            for satir in self.satirlar
            if satir.depo_kodu and ana_depo(satir.depo_kodu) != "-1"
        }
        return sorted(depolar)

    @property
    def cok_depolu_mu(self) -> bool:
        """Planda birden fazla Axata deposu var mı? Varsa numara depoya bağlanmalı."""
        return len(self.axata_depolari) > 1

    def depo_axatalari(self, depo_kodu: str) -> list["AxataNumarasi"]:
        """Bir depoya yazılacak Axata numaraları.

        Deposu belirtilmemiş numaralar bütün depolar için geçerli sayılır: tek depolu
        planlarda kullanıcı depo seçmek zorunda kalmasın diye. Böylece eski kayıtlar
        da (depo alanı boş) formda görünmeye devam eder.
        """
        from app.domain.iller import ana_depo

        hedef = ana_depo(depo_kodu)
        if hedef == "-1":
            # Bayi ortak deposu ayrı bir ERP'de; orada Axata iş emri açılmıyor.
            return []
        return [
            a
            for a in self.axata_numaralari
            if not a.depo_kodu or ana_depo(a.depo_kodu) == hedef
        ]

    def depo_axata_ozeti(self, depo_kodu: str) -> str:
        return ", ".join(a.numara for a in self.depo_axatalari(depo_kodu))

    @property
    def axatasiz_depolar(self) -> list[str]:
        """Henüz Axata numarası girilmemiş depolar; plan detayında uyarı olarak çıkar."""
        if not self.axata_numaralari:
            return []
        return [d for d in self.axata_depolari if not self.depo_axatalari(d)]

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
    def ihracat_mi(self) -> bool:
        return self.modul == "IHRACAT"

    @property
    def modul_yolu(self) -> str:
        """Plan detay ekranının yolu — raporlama ekranı buradan bağlantı kurar."""
        return {
            "ROTA": "/rota/planlar",
            "IHRACAT": "/ihracat/planlar",
        }.get(self.modul, "/ring/planlar")

    IC_ARAC_ADLARI = {"KAMYON": "Kamyon", "TIR": "Tır"}
    """İç piyasa planında aracın adı; kamyon ile tır ayrı kapasitedir."""

    @property
    def ic_arac_adi(self) -> str:
        """İç piyasa planının aracı: Kamyon ya da Tır. Kargoda araç yoktur."""
        if self.modul != "ROTA" or self.sevkiyat_tipi == "KARGO":
            return ""
        return self.IC_ARAC_ADLARI.get((self.arac_tipi or "").upper(), "")

    @property
    def sevkiyat_tipi_adi(self) -> str:
        """Plan listelerinde görünen tip adı.

        İç piyasada "FTL" tek başına yeterli değil: sahada aracın kamyon mu tır mı
        olduğu bilinmeli. Araç tipi biliniyorsa FTL yerine doğrudan aracın adı yazılır.
        """
        from app.domain.ic_piyasa import SevkiyatTipi

        if not self.sevkiyat_tipi:
            return "Ring"
        arac = self.ic_arac_adi
        if arac and self.sevkiyat_tipi == "FTL":
            return f"{arac} (tam araç)"
        if arac and self.sevkiyat_tipi == "RUTIN":
            return f"Rutin / parsiyel ({arac.lower()})"
        try:
            return SevkiyatTipi(self.sevkiyat_tipi).ad
        except ValueError:
            return self.sevkiyat_tipi

    @property
    def bolge_adi(self) -> str:
        from app.domain.bolgeler import bolge_adi

        return bolge_adi(self.bolge_kodu) if self.bolge_kodu else ""

    @property
    def _ihracat_musterisi(self):
        """Planın müşterisinin güncel master data kaydı (varsa)."""
        from sqlalchemy.orm import object_session

        from app.domain.iller import yer_adi

        oturum = object_session(self)
        if oturum is None or not self.musteri_adi:
            return None
        return oturum.scalar(
            select(IhracatMusterisi).where(
                IhracatMusterisi.anahtar == yer_adi(self.musteri_adi)
            )
        )

    @property
    def musteri_notu(self) -> str:
        """Yükleme formuna basılacak müşteri notu.

        Plan üretilirken master datadaki not plana kopyalanır. Not plandan **sonra**
        yazıldıysa bu kopya boş kalır; o zaman müşteri master datasından okunur, aksi
        hâlde kullanıcının yeni yazdığı açıklama forma hiç gelmez.
        """
        if self.musteri_aciklamasi:
            return self.musteri_aciklamasi
        musteri = self._ihracat_musterisi
        return (musteri.aciklama or "") if musteri is not None else ""

    @property
    def yukleme_tipi_metni(self) -> str:
        """Yükleme tipi; plandaki kopya boşsa müşteri master datasından okunur."""
        if self.yukleme_tipi:
            return self.yukleme_tipi
        musteri = self._ihracat_musterisi
        return (musteri.yukleme_tipi or "") if musteri is not None else ""

    @property
    def yukleme_tesisleri(self) -> list[str]:
        """Aracın hangi tesis(ler)den yüklendiği: ESKİŞEHİR (64, -1) / BOZÜYÜK (74, 34 ...)."""
        from app.domain.iller import yukleme_tesisi

        return sorted({yukleme_tesisi(satir.depo_kodu) for satir in self.satirlar})

    @property
    def rota_ozeti(self) -> dict | None:
        """Rotanın uzunluğu ve doğrudan gidişten sapması (km).

        Duraklar uzaklığa göre sıralandığı için sapma, aracın ne kadar zikzak
        yaptığını gösterir. Planlama sapmayı 100 km ile sınırlar.
        """
        from app.domain.koordinatlar import mesafe_km, rota_km

        iller = [
            parca.strip()
            for parca in (self.iller_metni or "").split(",")
            if parca.strip()
        ]
        if len(iller) < 1 or self.modul != "ROTA" or self.sevkiyat_tipi != "FTL":
            return None
        cikis = "BILECIK" if self.yukleme_tesisleri == ["BOZÜYÜK"] else "ESKISEHIR"
        rota = rota_km(cikis, iller)
        dogrudan = mesafe_km(cikis, iller[-1])
        if rota is None or dogrudan is None:
            return None
        return {"cikis": cikis, "rota": rota, "dogrudan": dogrudan,
                "sapma": rota - dogrudan}

    @property
    def axata_teslimat_numaralari(self) -> list[str]:
        """Axata'ya yapıştırılacak teslimat numaraları.

        Bayi ortak deposu (-1) satırları hariç tutulur: o depo ayrı bir ERP'dedir ve
        Axata iş emri açılmaz. Numaralar tekrarsız ve sıralıdır.
        """
        from app.domain.iller import ana_depo

        numaralar = {
            satir.teslimat_no
            for satir in self.satirlar
            if satir.teslimat_no and ana_depo(satir.depo_kodu) != "-1"
        }
        return sorted(numaralar)

    @property
    def yukleme_depolari(self) -> list[str]:
        """Aracın yüklendiği tesisteki depolar: 64 ile -1 aynı lokasyondadır.

        Yükleme deposu kutusunda tek kod yazmak yanıltıyordu; planda hem 64 hem -1
        varsa ikisi de görünmeli.
        """
        from app.domain.iller import ana_depo, yukleme_tesisi

        if not self.yukleme_deposu:
            return []
        hedef = yukleme_tesisi(self.yukleme_deposu)
        depolar = {
            ana_depo(satir.depo_kodu)
            for satir in self.satirlar
            if yukleme_tesisi(satir.depo_kodu) == hedef
        }
        return sorted(depolar) or [ana_depo(self.yukleme_deposu)]

    @property
    def yukleme_deposu_metni(self) -> str:
        depolar = self.yukleme_depolari
        return " + ".join(depolar) if depolar else (self.yukleme_deposu or self.depo_kodu)

    @property
    def ortak_yukleme_mi(self) -> bool:
        """Araç iki ayrı şehirden yükleniyor mu? Depo bunu formda görmeli."""
        return len(self.yukleme_tesisleri) > 1

    @property
    def aktarma_merkezi_adi(self) -> str:
        """Parsiyel aracın aktarma merkezi (Ankara / İstanbul / Bursa); yoksa boş."""
        if self.sevkiyat_tipi != "RUTIN" or not (self.bolge_kodu or "").startswith("AKT:"):
            return ""
        from app.domain.aktarma import merkez_adi

        return merkez_adi(self.bolge_kodu[4:].partition("|")[0])

    @property
    def urun_grubu_ozeti(self) -> list[dict]:
        """Plandaki ürünlerin grup bazında adedi.

        Depo "bu araca hangi gruptan kaç adet giriyor" diye baktığı için plan
        detayında ve raporlarda bu kırılım gösterilir. Grubu tanımsız ürünler
        "GRUPSUZ" altında toplanır ki toplam her zaman plan adediyle eşleşsin.
        """
        toplamlar: dict[str, dict] = {}
        for satir in self.satirlar:
            ad = (satir.urun_grubu or "GRUPSUZ").upper()
            kayit = toplamlar.setdefault(
                ad, {"grup": ad, "adet": Decimal(0), "satir": 0, "teslimatlar": set()}
            )
            kayit["adet"] += Decimal(satir.miktar or 0)
            kayit["satir"] += 1
            kayit["teslimatlar"].add(satir.teslimat_no)
        for kayit in toplamlar.values():
            kayit["teslimat"] = len(kayit.pop("teslimatlar"))
        return sorted(toplamlar.values(), key=lambda k: -k["adet"])

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
    depo_kodu: Mapped[str | None] = mapped_column(String(20), default=None)
    """Numaranın ait olduğu depo. Boşsa plandaki bütün depolar için geçerlidir.

    Bir planda birden çok depo olabiliyor (ör. 64 + 74) ve her depo kendi Axata iş
    emrini açıyor. Numara depoya bağlanmazsa yükleme formunda hangi satıra
    yazılacağı bilinemiyor; depo yanlış iş emriyle toplama yapıyor.
    """
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
    ulke_kodu: Mapped[str | None] = mapped_column(String(10), index=True, default=None)
    """İhracat siparişlerinde ülke kodu (HR, MD, TR ...). İç piyasada boştur.

    İhracatta `bayi_adi` müşteri adını, `sehir` ülkeyi taşır.
    """
    desi: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), default=None)
    agirlik: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), default=None)
    """İhracat dosyalarında desi ve kg satır bazında geliyor; ürün master datasında
    ihracat SKU'ları bulunmadığı için ölçü doğrudan dosyadan alınır."""
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
    def bayi_gosterimi(self) -> str:
        """Yükleme formunun 'Bayii Adı' sütunu.

        Kaynak dosyalarda bayi adı sütunu bazen boş geliyor; sırayla alıcı firma ve
        açık adres denenir. Sütunun boş kalması depo için formu okunmaz hâle
        getiriyor: sürücü kime gittiğini göremiyor. Sıralama iç piyasa planlamasının
        durak adıyla aynıdır (bkz. ic_piyasa_servisi._durak_adi), böylece plan ekranı
        ile yükleme formu aynı adı yazar.
        """
        for aday in (self.bayi_adi, self.alici_firma, self.sevk_adresi):
            metin = (aday or "").strip()
            if metin:
                return metin
        return "—"

    @property
    def alici_gosterimi(self) -> str:
        """Alıcı firma; bayi adının aynısıysa tekrar yazılmaz."""
        alici = (self.alici_firma or "").strip()
        return "" if not alici or alici == (self.bayi_adi or "").strip() else alici

    @property
    def adres_metni(self) -> str:
        """Açık adres ve ilçe tek metinde; ikisi de forma sığsın diye birleştirilir."""
        parcalar = [
            parca.strip()
            for parca in (self.sevk_adresi, self.ilce)
            if parca and parca.strip()
        ]
        # Adres zaten ilçeyi içeriyorsa iki kez yazılmaz.
        if len(parcalar) == 2 and parcalar[1].upper() in parcalar[0].upper():
            return parcalar[0]
        return " - ".join(parcalar)

    @property
    def oncelik_tarihi(self) -> date:
        return self.termin_tarihi or self.siparis_tarihi or date.today()

    @property
    def bekleme_gunu(self) -> int:
        """Sipariş kaç gündür plana giremeden bekliyor?"""
        return (date.today() - self.olusturma_tarihi.date()).days

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


class BagTipi(str, enum.Enum):
    """İki ürünün birbirine ne kadar sıkı bağlı olduğu."""

    SET = "SET"
    """Bir bütünün iki parçası; hiçbiri tek başına gitmemeli.

    Klimada iç ünite ile dış ünite budur: biri gidip diğeri kalırsa müşteride
    kurulum yapılamaz.
    """
    AKSESUAR = "AKSESUAR"
    """Ana ürünün yanında gitmesi gereken parça: baca, montaj seti, dirsek.

    Bağ tek yönlüdür. Aksesuar ana ürünü olmadan **gitmemeli**; ana ürün ise
    aksesuarı sipariş edilmemişse tek başına gidebilir.
    """


class UrunBagi(Temel):
    """Birlikte sevk edilmesi gereken iki ürün.

    Şirkette bu bağ için 'header kod' alanı vardı ama Vaillant ürünlerinde hiç
    doldurulmamış (master datadaki 2.585 ürünün tamamında boş). Bağ bilgisi
    olmayınca kombi bir araca, bacası iki gün sonra başka bir araca düşüyor ve
    bu bir müşteri şikâyetine dönüşüyor.

    Bağ **ürün kodu** üzerinden kurulur, teslimat üzerinden değil: stoklar farklı
    zamanlarda geldiği için aynı siparişin parçaları farklı teslimat numaraları
    alabiliyor ve teslimat bazlı bağ bu durumda kopuyor.
    """

    __tablename__ = "urun_baglari"
    __table_args__ = (
        UniqueConstraint("ana_urun_kodu", "bagli_urun_kodu", name="uq_urun_bagi"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ana_urun_kodu: Mapped[str] = mapped_column(String(50), index=True)
    """SET bağında çiftin ilk parçası, AKSESUAR bağında ana ürün."""
    bagli_urun_kodu: Mapped[str] = mapped_column(String(50), index=True)
    """SET bağında çiftin ikinci parçası, AKSESUAR bağında aksesuarın kendisi."""
    tip: Mapped[BagTipi] = mapped_column(
        Enum(BagTipi, native_enum=False, length=20), default=BagTipi.AKSESUAR
    )
    kaynak: Mapped[str] = mapped_column(String(20), default="ELLE")
    """ELLE (ekrandan girildi) ya da GECMIS (sevk geçmişinden önerildi)."""
    aciklama: Mapped[str | None] = mapped_column(Text, default=None)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    @property
    def simetrik_mi(self) -> bool:
        """SET bağı iki yönlüdür: hangi parça planda olursa olsun diğeri aranır."""
        return self.tip is BagTipi.SET


class Depo(Temel):
    """Depo tanımı: kod, ad, bulunduğu tesis ve yükleme formundaki karşılığı.

    Depolar bugüne kadar koda gömülüydü; yeni bir depo açıldığında yükleme formunun
    depo/AXATA kutusuna satır eklemek için kod değiştirmek gerekiyordu. Tanımlar
    artık Master Data'dan yönetilir.

    **Sınır:** planlama kapasitesi (hangi depo hangi ölçüyle planlanır) bu tabloda
    değil, `app/config.py` içindeki DEPO_PROFILLERI'ndedir. O bir iş kuralıdır ve
    gerçek sevk verisiyle doğrulanmıştır; ekrandan değiştirilmesi doğru olmaz.
    """

    __tablename__ = "depolar"

    id: Mapped[int] = mapped_column(primary_key=True)
    kod: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    ad: Mapped[str] = mapped_column(String(120))
    tesis: Mapped[str | None] = mapped_column(String(80), default=None)
    """Deponun fiziken bulunduğu yer (Eskişehir / Bozüyük). Ortak yükleme kararı
    buna bakar: farklı tesisten yükleme aracı iki şehre uğratır."""
    form_etiketi: Mapped[str | None] = mapped_column(String(40), default=None)
    """Yükleme formunun depo/AXATA kutusunda görünecek satır adı (ör. '64-D DEPO')."""
    sira: Mapped[int] = mapped_column(Integer, default=100)
    """Formdaki satır sırası."""
    axata_var: Mapped[bool] = mapped_column(Boolean, default=True)
    """Bu depoda Axata iş emri açılıyor mu? Bayi ortak deposu (-1) için hayır."""
    parsiyel_yapilir: Mapped[bool] = mapped_column(Boolean, default=False)
    """Parsiyel (rutin) sevkiyat bu depodan yapılabiliyor mu?"""
    aciklama: Mapped[str | None] = mapped_column(Text, default=None)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Depo {self.kod}>"


class Ayar(Temel):
    """Ekrandan değiştirilebilen sistem ayarı (anahtar/değer).

    Kargo desi sınırı, rutin palet sınırı, azami durak gibi **sahadan gelen ve
    değişebilen** sayılar burada tutulur. Kayıt yoksa koddaki varsayılan geçerlidir;
    böylece boş bir veritabanı da doğru çalışır.
    """

    __tablename__ = "ayarlar"

    id: Mapped[int] = mapped_column(primary_key=True)
    anahtar: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    deger: Mapped[str] = mapped_column(String(200))
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )
    kullanici: Mapped[str] = mapped_column(String(100), default="sistem")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Ayar {self.anahtar}={self.deger}>"
