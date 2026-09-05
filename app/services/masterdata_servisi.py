"""Master Data modülünün servis katmanı.

Üç iş yapar:

1. **Filtreleme.** Ürün ve müşteri listeleri sütun bazında daraltılır (grup, depo,
   il, eksik alan ...). Ekranda görülen liste ile indirilen dosya **aynı filtreden**
   geçer; kullanıcı ekranda 40 kayıt görüp 2.585 satırlık dosya indirmez.
2. **Dışa aktarma.** Dosya, içe aktarımın beklediği başlıklarla yazılır. Böylece
   indirilen dosya doldurulup **doğrudan geri yüklenebilir**; ayrı bir şablon
   doldurmak gerekmez.
3. **Sistem ve depo tanımları.** Sahadan gelen ve değişebilen sayılar (kargo desi
   sınırı, rutin palet sınırı ...) ile depo tanımları veritabanında tutulur; kayıt
   yoksa koddaki varsayılan geçerlidir.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Ayar, Depo, IhracatMusterisi, IhracatUrunu, Musteri, Urun
from app.services import excel
from app.services.veri_formatlari import (
    IHRACAT_MUSTERI_ALANLARI,
    IHRACAT_URUN_ALANLARI,
    MUSTERI_ALANLARI,
    URUN_ALANLARI,
    Alan,
)

# --------------------------------------------------------------------- ürünler


@dataclass(frozen=True)
class UrunFiltresi:
    arama: str = ""
    urun_grubu: str = ""
    durum: str = ""
    """'AKTIF' / 'PASIF' / boş."""
    eksik: str = ""
    """Belirli bir ölçüsü boş olanlar: 'PALET', 'TIR', 'KAMYON', 'OLCU', 'AGIRLIK',
    'DESI', 'HERHANGI'. Eksik master data planlamayı durdurduğu için ayrı filtre."""


EKSIK_KOSULLARI: dict[str, tuple[str, Callable[[Any], bool]]] = {
    "PALET": ("Palet içi adet boş", lambda u: not u.palet_ici_adet),
    "TIR": ("Tır yükleme adeti boş", lambda u: not u.tir_yukleme_adeti),
    "KAMYON": ("Kamyon yükleme adeti boş", lambda u: not u.kamyon_yukleme_adeti),
    "OLCU": ("Palet ölçüsü (en/boy) boş", lambda u: not (u.palet_en and u.palet_boy)),
    "AGIRLIK": ("Ağırlık boş", lambda u: not u.agirlik),
    "DESI": ("Desi boş", lambda u: not u.desi),
    "GRUP": ("Ürün grubu boş", lambda u: not u.urun_grubu),
}
"""Eksik alan filtreleri. Etiketler ekranda açılır listede görünür."""

EKSIK_HERHANGI = "HERHANGI"


def _eksik_mi(urun: Urun) -> bool:
    return any(kosul(urun) for _, kosul in EKSIK_KOSULLARI.values())


def urun_gruplari(db: Session) -> list[str]:
    return [
        g
        for (g,) in db.execute(
            select(Urun.urun_grubu).where(Urun.urun_grubu.is_not(None)).distinct()
        ).all()
        if g
    ]


def urunleri_getir(db: Session, filtre: UrunFiltresi, limit: int = 5000) -> list[Urun]:
    sorgu = select(Urun)
    if filtre.arama:
        desen = f"%{filtre.arama.strip()}%"
        sorgu = sorgu.where(
            or_(
                Urun.urun_kodu.ilike(desen),
                Urun.urun_adi.ilike(desen),
                Urun.header_kod.ilike(desen),
            )
        )
    if filtre.urun_grubu:
        sorgu = sorgu.where(Urun.urun_grubu == filtre.urun_grubu)
    if filtre.durum == "AKTIF":
        sorgu = sorgu.where(Urun.aktif.is_(True))
    elif filtre.durum == "PASIF":
        sorgu = sorgu.where(Urun.aktif.is_(False))
    sorgu = sorgu.order_by(Urun.urun_grubu, Urun.urun_kodu)
    urunler = list(db.scalars(sorgu).all())

    # Eksik alan filtresi Python tarafında: koşullar `EKSIK_KOSULLARI` içinde tek
    # yerde tanımlı, ekrandaki etiketle sorgu böylece ayrışmaz.
    if filtre.eksik == EKSIK_HERHANGI:
        urunler = [u for u in urunler if _eksik_mi(u)]
    elif filtre.eksik in EKSIK_KOSULLARI:
        kosul = EKSIK_KOSULLARI[filtre.eksik][1]
        urunler = [u for u in urunler if kosul(u)]
    return urunler[:limit]


def urun_eksik_ozeti(db: Session) -> list[dict]:
    """Hangi alanın kaç üründe boş olduğu. Master Data ana ekranındaki uyarı listesi."""
    urunler = list(db.scalars(select(Urun)).all())
    toplam = len(urunler)
    ozet = []
    for kod, (etiket, kosul) in EKSIK_KOSULLARI.items():
        sayi = sum(1 for u in urunler if kosul(u))
        if sayi:
            ozet.append(
                {
                    "kod": kod,
                    "etiket": etiket,
                    "sayi": sayi,
                    "oran": (sayi / toplam) if toplam else 0,
                }
            )
    return sorted(ozet, key=lambda o: -o["sayi"])


URUN_DEGERLERI: dict[str, Callable[[Urun], Any]] = {
    "urun_kodu": lambda u: u.urun_kodu,
    "urun_adi": lambda u: u.urun_adi,
    "urun_grubu": lambda u: u.urun_grubu,
    "palet_ici_adet": lambda u: u.palet_ici_adet,
    "kamyon_yukleme_adeti": lambda u: u.kamyon_yukleme_adeti,
    "kamyon_palet": lambda u: u.kamyon_palet,
    "tir_yukleme_adeti": lambda u: u.tir_yukleme_adeti,
    "tir_palet": lambda u: u.tir_palet,
    "agirlik": lambda u: u.agirlik,
    "desi": lambda u: u.desi,
    "m3": lambda u: u.m3,
    "palet_en": lambda u: u.palet_en,
    "palet_boy": lambda u: u.palet_boy,
    "palet_yukseklik": lambda u: u.palet_yukseklik,
    "header_kod": lambda u: u.header_kod,
    "aktif": lambda u: "E" if u.aktif else "H",
}

MUSTERI_DEGERLERI: dict[str, Callable[[Musteri], Any]] = {
    "bayi_adi": lambda m: m.bayi_adi,
    "bayi_kodu": lambda m: m.bayi_kodu,
    "alici_firma": lambda m: m.alici_firma,
    "il": lambda m: m.il,
    "ilce": lambda m: m.ilce,
    "sevk_adresi": lambda m: m.sevk_adresi,
    "telefon": lambda m: m.telefon,
    "incoterms": lambda m: m.incoterms,
    "tir_girisi": lambda m: m.tir_girisi,
    "bolge_kodu": lambda m: m.bolge_kodu,
    "eposta": lambda m: m.eposta,
    "sevk_tipi": lambda m: m.sevk_tipi,
    "cumartesi_teslimat": lambda m: "E" if m.cumartesi_teslimat else "H",
    "e_irsaliye": lambda m: "E" if m.e_irsaliye else "H",
    "ozel_durum": lambda m: m.ozel_durum,
    "notlar": lambda m: m.notlar,
    "aktif": lambda m: "E" if m.aktif else "H",
}

IHRACAT_MUSTERI_DEGERLERI: dict[str, Callable[[IhracatMusterisi], Any]] = {
    "musteri_adi": lambda m: m.musteri_adi,
    "ulke": lambda m: m.ulke,
    "ulke_kodu": lambda m: m.ulke_kodu,
    "sevk_adresi": lambda m: m.sevk_adresi,
    "arac_tipi": lambda m: m.arac_tipi.value if m.arac_tipi else None,
    "sefer_kodu": lambda m: m.sefer_kodu,
    "yukleme_tipi": lambda m: m.yukleme_tipi,
    "azami_agirlik": lambda m: m.azami_agirlik,
    "aciklama": lambda m: m.aciklama,
    "incoterms": lambda m: m.incoterms,
    "tedarikci": lambda m: m.tedarikci,
    "satis_destek": lambda m: m.satis_destek,
    "aktif": lambda m: "E" if m.aktif else "H",
}

IHRACAT_URUN_DEGERLERI: dict[str, Callable[[IhracatUrunu], Any]] = {
    "urun_kodu": lambda u: u.urun_kodu,
    "urun_adi": lambda u: u.urun_adi,
    "palet_ici_adet": lambda u: u.palet_ici_adet,
    "tir_yukleme_adeti": lambda u: u.tir_yukleme_adeti,
    "konteyner_yukleme_adeti": lambda u: u.konteyner_yukleme_adeti,
    "desi": lambda u: u.desi,
    "agirlik": lambda u: u.agirlik,
    "en": lambda u: u.en,
    "boy": lambda u: u.boy,
    "yukseklik": lambda u: u.yukseklik,
    "urun_grubu": lambda u: u.urun_grubu,
    "tir_yukleme_adeti_eski": lambda u: u.tir_yukleme_adeti_eski,
    "konteyner_yukleme_adeti_eski": lambda u: u.konteyner_yukleme_adeti_eski,
    "palet_ici_adet_eski": lambda u: u.palet_ici_adet_eski,
    "dokme_adeti": lambda u: u.dokme_adeti,
    "aktif": lambda u: "E" if u.aktif else "H",
}


def disari_aktar(
    kayitlar: list,
    alanlar: tuple[Alan, ...],
    degerler: dict[str, Callable[[Any], Any]],
    hedef: Path,
    sayfa_adi: str,
) -> Path:
    """Kayıtları içe aktarımın tanıdığı başlıklarla Excel'e yazar.

    Başlıklar `veri_formatlari` içindeki alan tanımlarından gelir; indirilen dosya
    doldurulup doğrudan geri yüklenebilir. Şablon ile veri dosyası arasında başlık
    farkı oluşamaz — ikisi de aynı kaynaktan besleniyor.
    """
    basliklar = [alan.baslik for alan in alanlar]
    satirlar = [
        [
            _excel_degeri(degerler[alan.ad](kayit)) if alan.ad in degerler else None
            for alan in alanlar
        ]
        for kayit in kayitlar
    ]
    kitap = excel.yeni_kitap()
    sayfa = kitap.create_sheet(sayfa_adi[:31])
    excel.sayfa_yaz(sayfa, basliklar, satirlar)
    # Otomatik filtre: dosyayı Excel'de açan kişi sütundan da süzebilsin.
    sayfa.auto_filter.ref = sayfa.dimensions
    hedef.parent.mkdir(parents=True, exist_ok=True)
    kitap.save(hedef)
    return hedef


def _excel_degeri(deger: Any) -> Any:
    if isinstance(deger, Decimal):
        return float(deger)
    return deger


# ------------------------------------------------------------- tekil güncelleme

URUN_SAYISAL_ALANLAR = (
    "palet_ici_adet", "kamyon_yukleme_adeti", "kamyon_palet", "tir_yukleme_adeti",
    "tir_palet", "palet_en", "palet_boy", "palet_yukseklik",
)
URUN_ONDALIK_ALANLAR = ("agirlik", "desi", "m3")


class MasterDataHatasi(Exception):
    pass


def _tam_sayi(deger: str) -> int | None:
    metin = (deger or "").strip().replace(".", "")
    if not metin:
        return None
    try:
        sayi = int(float(metin.replace(",", ".")))
    except ValueError as hata:
        raise MasterDataHatasi(f"'{deger}' sayı değil.") from hata
    return sayi or None


def _ondalik(deger: str) -> Decimal | None:
    metin = (deger or "").strip().replace(",", ".")
    if not metin:
        return None
    try:
        return Decimal(metin)
    except InvalidOperation as hata:
        raise MasterDataHatasi(f"'{deger}' sayı değil.") from hata


def urunu_guncelle(db: Session, urun_kodu: str, alanlar: dict[str, str]) -> Urun:
    """Tek bir ürünün master bilgilerini günceller; yoksa oluşturur.

    Boş bırakılan alan **silinir** (None olur): kullanıcı ekranda gördüğü formu
    olduğu gibi kaydediyor, boş bıraktığı yeri kasten boşaltmış sayılır. Toplu
    Excel yüklemesinde kural bunun tersidir (orada boş sütun mevcut veriyi silmez),
    çünkü orada boşluk çoğu zaman "o sütun dosyada yok" demektir.
    """
    kod = (urun_kodu or "").strip()
    if not kod:
        raise MasterDataHatasi("Ürün kodu boş olamaz.")
    urun = db.scalar(select(Urun).where(Urun.urun_kodu == kod))
    if urun is None:
        urun = Urun(urun_kodu=kod)
        db.add(urun)

    urun.urun_adi = (alanlar.get("urun_adi") or "").strip() or urun.urun_adi or kod
    urun.urun_grubu = (alanlar.get("urun_grubu") or "").strip().upper() or None
    for ad in URUN_SAYISAL_ALANLAR:
        if ad in alanlar:
            setattr(urun, ad, _tam_sayi(alanlar[ad]))
    for ad in URUN_ONDALIK_ALANLAR:
        if ad in alanlar:
            setattr(urun, ad, _ondalik(alanlar[ad]))
    if "header_kod" in alanlar:
        urun.header_kod = (alanlar["header_kod"] or "").strip() or None
    if "aktif" in alanlar:
        urun.aktif = str(alanlar["aktif"]).strip().upper() in {"E", "1", "TRUE", "ON"}

    if not (urun.palet_ici_adet or urun.tir_yukleme_adeti or urun.kamyon_yukleme_adeti):
        raise MasterDataHatasi(
            "Palet içi adet, tır yükleme adeti ve kamyon yükleme adetinden en az biri "
            "girilmelidir; yoksa ürün planlamaya giremez."
        )
    db.flush()
    return urun


# --------------------------------------------------------------- depo tanımları

VARSAYILAN_DEPOLAR: tuple[dict, ...] = (
    {"kod": "64", "ad": "Eskişehir ana depo", "tesis": "ESKİŞEHİR",
     "form_etiketi": "64-D DEPO", "sira": 30, "axata_var": True,
     "parsiyel_yapilir": True},
    {"kod": "64-V", "ad": "Eskişehir Vaillant deposu", "tesis": "ESKİŞEHİR",
     "form_etiketi": "64-V DEPO", "sira": 40, "axata_var": True,
     "parsiyel_yapilir": True},
    {"kod": "64-P", "ad": "Eskişehir Protherm deposu", "tesis": "ESKİŞEHİR",
     "form_etiketi": None, "sira": 45, "axata_var": True, "parsiyel_yapilir": True},
    {"kod": "-1", "ad": "Bayi ortak deposu", "tesis": "ESKİŞEHİR",
     "form_etiketi": "-1-DEPO", "sira": 60, "axata_var": False,
     "parsiyel_yapilir": True,
     "aciklama": "Ayrı bir ERP'de tutulur; Axata iş emri açılmaz, teslimatı bölünebilir."},
    {"kod": "74", "ad": "Bozüyük ana depo", "tesis": "BOZÜYÜK",
     "form_etiketi": "74-DEPO", "sira": 50, "axata_var": True,
     "parsiyel_yapilir": True},
    {"kod": "34", "ad": "Bozüyük 34 deposu", "tesis": "BOZÜYÜK",
     "form_etiketi": "34-DEPO", "sira": 10, "axata_var": True,
     "parsiyel_yapilir": False},
    {"kod": "44", "ad": "Bozüyük 44 deposu", "tesis": "BOZÜYÜK",
     "form_etiketi": "44-DEPO", "sira": 20, "axata_var": True,
     "parsiyel_yapilir": False},
)
"""Programla gelen depo tanımları; boş veritabanı ilk açılışta bunlarla dolar.

Değerler bugüne kadar koda gömülü olan sabitlerin aynısıdır (bkz. app/domain/iller.py
ESKISEHIR_DEPOLARI, app/services/yukleme_formu.py DEPO_SATIRLARI,
app/domain/ic_piyasa.py PARSIYEL_DEPO_GRUPLARI).
"""


def depolari_yukle(db: Session) -> int:
    """Tanımsızsa varsayılan depoları ekler; mevcutlara dokunmaz."""
    mevcut = {d.kod for d in db.scalars(select(Depo)).all()}
    eklenen = 0
    for kayit in VARSAYILAN_DEPOLAR:
        if kayit["kod"] in mevcut:
            continue
        db.add(Depo(**kayit))
        eklenen += 1
    if eklenen:
        db.flush()
    return eklenen


def depolari_getir(db: Session, yalnizca_aktif: bool = False) -> list[Depo]:
    sorgu = select(Depo).order_by(Depo.sira, Depo.kod)
    if yalnizca_aktif:
        sorgu = sorgu.where(Depo.aktif.is_(True))
    return list(db.scalars(sorgu).all())


def form_depo_satirlari(db: Session) -> list[str]:
    """Yükleme formunun depo/AXATA kutusundaki satırlar, tanım sırasına göre."""
    return [
        depo.form_etiketi
        for depo in depolari_getir(db, yalnizca_aktif=True)
        if depo.form_etiketi
    ]


def depoyu_kaydet(db: Session, kod: str, alanlar: dict[str, str]) -> Depo:
    temiz = (kod or "").strip().upper()
    if not temiz:
        raise MasterDataHatasi("Depo kodu boş olamaz.")
    depo = db.scalar(select(Depo).where(Depo.kod == temiz))
    if depo is None:
        depo = Depo(kod=temiz, ad=temiz)
        db.add(depo)
    depo.ad = (alanlar.get("ad") or "").strip() or depo.ad or temiz
    depo.tesis = (alanlar.get("tesis") or "").strip().upper() or None
    depo.form_etiketi = (alanlar.get("form_etiketi") or "").strip().upper() or None
    depo.sira = _tam_sayi(alanlar.get("sira", "")) or 100
    depo.aciklama = (alanlar.get("aciklama") or "").strip() or None
    depo.axata_var = str(alanlar.get("axata_var", "")).strip().upper() in {"E", "1", "TRUE", "ON"}
    depo.parsiyel_yapilir = str(alanlar.get("parsiyel_yapilir", "")).strip().upper() in {"E", "1", "TRUE", "ON"}
    depo.aktif = str(alanlar.get("aktif", "")).strip().upper() in {"E", "1", "TRUE", "ON"}
    db.flush()
    return depo


# ------------------------------------------------------------- sistem ayarları


@dataclass(frozen=True)
class AyarTanimi:
    anahtar: str
    etiket: str
    aciklama: str
    tip: str
    """'sayi' (tam sayı), 'ondalik' ya da 'evet_hayir'."""
    varsayilan: str
    birim: str = ""


AYAR_TANIMLARI: tuple[AyarTanimi, ...] = (
    AyarTanimi("rutin_palet_siniri", "Rutin palet sınırı",
               "Müşterinin toplam siparişi bu paleti aşmıyorsa rutin (parsiyel) ile gider.",
               "ondalik", "3", "palet"),
    AyarTanimi("kargo_desi_siniri", "Kargo desi sınırı",
               "Müşteri toplamı bu desinin altındaysa kargoya yönlendirilir.",
               "ondalik", "10", "desi"),
    AyarTanimi("exw_kargoya", "EXW siparişler kargoya",
               "Incoterms EXW ise taşımayı müşteri üstlenir; kargo sayılır.",
               "evet_hayir", "E"),
    AyarTanimi("azami_durak", "FTL azami durak",
               "Tam araçta en fazla kaç uğrama noktası olabilir.", "sayi", "5", "durak"),
    AyarTanimi("son_ugrak_asgari_oran", "Son uğrak asgari oranı",
               "En uzak durak aracın en az bu kadarını kaplamalı (0,15 = %15).",
               "ondalik", "0.15"),
    AyarTanimi("azami_sapma_km", "Azami rota sapması",
               "Rota, tesisten son noktaya doğrudan gidişten en fazla bu kadar uzun "
               "olabilir. Doğudaki zikzak rotaları bu kural engelliyor.",
               "sayi", "100", "km"),
    AyarTanimi("gunluk_ftl_siniri", "Günlük FTL sınırı",
               "Bir günde açılabilecek en fazla tam araç sayısı.", "sayi", "35", "araç"),
    AyarTanimi("gunluk_rutin_siniri", "Günlük rutin sınırı",
               "Bir günde açılabilecek en fazla rutin/parsiyel aracı.", "sayi", "4", "araç"),
)
"""Ekrandan değiştirilebilen planlama sayıları.

Hepsi `app/domain/ic_piyasa.py` içindeki `Kurallar` alanlarının karşılığıdır;
varsayılanlar oradaki değerlerle birebir aynıdır.
"""

AYAR_HARITASI = {tanim.anahtar: tanim for tanim in AYAR_TANIMLARI}


def ayarlari_getir(db: Session) -> dict[str, str]:
    """Kayıtlı ayarlar; eksik olanlar varsayılanla tamamlanır."""
    kayitli = {a.anahtar: a.deger for a in db.scalars(select(Ayar)).all()}
    return {
        tanim.anahtar: kayitli.get(tanim.anahtar, tanim.varsayilan)
        for tanim in AYAR_TANIMLARI
    }


def ayar_satirlari(db: Session) -> list[dict]:
    """Ekranın gösterdiği liste: tanım + geçerli değer + varsayılandan farklı mı."""
    degerler = ayarlari_getir(db)
    return [
        {
            "tanim": tanim,
            "deger": degerler[tanim.anahtar],
            "degistirilmis": degerler[tanim.anahtar] != tanim.varsayilan,
        }
        for tanim in AYAR_TANIMLARI
    ]


def ayarlari_kaydet(db: Session, degerler: dict[str, str], kullanici: str) -> list[str]:
    """Değişen ayarları yazar; değişenlerin etiketlerini döner."""
    mevcut = {a.anahtar: a for a in db.scalars(select(Ayar)).all()}
    onceki = ayarlari_getir(db)
    degisenler: list[str] = []
    for anahtar, ham in degerler.items():
        tanim = AYAR_HARITASI.get(anahtar)
        if tanim is None:
            continue
        yeni = _ayar_dogrula(tanim, ham)
        if yeni == onceki[anahtar]:
            continue
        kayit = mevcut.get(anahtar)
        if kayit is None:
            kayit = Ayar(anahtar=anahtar)
            db.add(kayit)
        kayit.deger = yeni
        kayit.kullanici = kullanici
        degisenler.append(f"{tanim.etiket}: {onceki[anahtar]} → {yeni}")
    db.flush()
    return degisenler


def _ayar_dogrula(tanim: AyarTanimi, ham: str) -> str:
    metin = str(ham or "").strip().replace(",", ".")
    if tanim.tip == "evet_hayir":
        return "E" if metin.upper() in {"E", "1", "TRUE", "ON"} else "H"
    if not metin:
        return tanim.varsayilan
    try:
        sayi = Decimal(metin)
    except InvalidOperation as hata:
        raise MasterDataHatasi(f"{tanim.etiket}: '{ham}' sayı değil.") from hata
    if sayi <= 0:
        raise MasterDataHatasi(f"{tanim.etiket} sıfırdan büyük olmalı.")
    if tanim.tip == "sayi":
        return str(int(sayi))
    return format(sayi.normalize(), "f")


def kurallari_kur(db: Session):
    """Kayıtlı ayarlardan planlama kurallarını üretir.

    Ayar tablosu boşsa `Kurallar()` varsayılanları döner; iki taraf da aynı sayıları
    taşıdığı için davranış değişmez.
    """
    from app.domain.ic_piyasa import Kurallar

    d = ayarlari_getir(db)
    return Kurallar(
        rutin_palet_siniri=Decimal(d["rutin_palet_siniri"]),
        kargo_desi_siniri=Decimal(d["kargo_desi_siniri"]),
        exw_kargoya=d["exw_kargoya"] == "E",
        azami_durak=int(d["azami_durak"]),
        son_ugrak_asgari_oran=Decimal(d["son_ugrak_asgari_oran"]),
        gunluk_ftl_siniri=int(d["gunluk_ftl_siniri"]),
        gunluk_rutin_siniri=int(d["gunluk_rutin_siniri"]),
        azami_sapma_km=int(d["azami_sapma_km"]),
    )
