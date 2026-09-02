"""Excel alan tanımları — içe aktarım ve şablon üretimi tek kaynaktan beslenir.

Başlıklar, sahadaki gerçek dosyalara göre belirlendi:
  * ürün master datası → "Ring Planları" çalışma kitabının `masterdata` sayfası
  * siparişler         → sevk planı / havuz sipariş sayfaları ve Bekleyen Talep Listesi
Alternatif başlıklar `aliaslar` alanında listelenir; hepsi otomatik tanınır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.iller import yer_adi

INCOTERMS = {"CIF", "EXW", "FOB", "DAP", "FCA", "DDP", "CPT", "ZKL"}
"""Sipariş dosyasının `Not` sütununda geçebilen teslim şekilleri.

`ZKL` de bir teslim şeklidir (geçmiş veride 19.425 satır). İlçe sanılırsa müşteri
master datasında "ZKL" diye olmayan bir ilçe oluşuyor; o satırlarda gerçek ilçe
`SevkAdresi` sütununda duruyor.
"""


def not_alanini_coz(deger: object) -> tuple[str, str]:
    """`Not` sütununu (incoterms, ilçe) olarak ayırır.

    Sahadaki dosyalarda bu sütun üç ayrı şeyi taşıyor: yalnız teslim şekli (`CIF`),
    yalnız ilçe (` - MERKEZ`) ya da ikisi birden (`CIF - MERKEZ`). EXW olan siparişler
    kargoya yönlendirildiği için ayrıştırma planlamayı doğrudan etkiliyor.
    """
    ham = str(deger).strip() if deger is not None else ""
    if not ham:
        return "", ""
    if " - " in ham or ham.startswith("-") or ham.endswith("-"):
        sol, _, sag = ham.partition("-")
        sol = sol.strip().upper()
        return (sol if sol in INCOTERMS else ""), _ilce_ya_da_bos(sag)
    buyuk = ham.upper()
    if buyuk in INCOTERMS:
        return buyuk, ""
    return "", _ilce_ya_da_bos(ham)


def _ilce_ya_da_bos(deger: object) -> str:
    """İlçe adı en az bir harf içermeli.

    `Not` sütununda ilçe yerine zaman zaman `45796` gibi kodlar geliyor; bunlar ilçe
    olarak yazılırsa yükleme formunda ve rota bilgisinde sayı görünüyor.
    """
    ad = yer_adi(deger)
    return ad if any(karakter.isalpha() for karakter in ad) else ""


ADRES_ISARETLERI = (
    "MAH", "CAD", " CD", "SOK", " SK", "NO:", "NO :", "BULV", "APT", "OSB",
    "SANAYI", "SANAYİ", "SİTE", "BLOK", "PLAZA", "ÇARŞI", "KÜME", "KÖY",
)


def adres_gibi_mi(deger: object) -> bool:
    """Metin açık adres mi, yoksa firma/ilçe adı mı?"""
    ham = (str(deger).strip() if deger is not None else "").upper()
    if not ham:
        return False
    if any(isaret in ham for isaret in ADRES_ISARETLERI):
        return True
    # Uzun ve içinde numara geçen metinler adrestir; firma adları böyle olmaz.
    return len(ham) > 25 and any(karakter.isdigit() for karakter in ham)


def yer_alanlarini_coz(
    alici_firma: object, sevk_adresi: object, not_alani: object
) -> tuple[str, str, str, str]:
    """(alıcı firma, açık adres, ilçe, incoterms) döndürür.

    Kaynak dosyalarda bu üç sütunun anlamı satır tipine göre kayıyor:

    * Bayi siparişleri: `AliciFirma` **adres**, `SevkAdresi` **ilçe**, `Not` incoterms.
    * Bayi ortak deposu (-1) siparişleri: `AliciFirma` firma, `SevkAdresi` **adres**,
      `Not` ` - İLÇE`.

    Ayrım sütun adından değil içerikten yapılır: hangi alan adres kalıbı taşıyorsa
    (MAH/CAD/SOK/NO: gibi) o adrestir. Karıştırılırsa yükleme formunda ilçe yerine
    sokak adı yazılır ve rota bilgisi bozulur.
    """
    incoterms, not_ilcesi = not_alanini_coz(not_alani)
    firma = str(alici_firma).strip() if alici_firma is not None else ""
    adres = str(sevk_adresi).strip() if sevk_adresi is not None else ""
    if adres_gibi_mi(firma) and not adres_gibi_mi(adres):
        # Bu düzende ilçe kendi sütununda geliyor; `Not` alanı yalnızca yedektir
        # (orada zaman zaman 'ZKL' gibi ilçe olmayan kodlar da görülüyor).
        return "", firma, (_ilce_ya_da_bos(adres) or not_ilcesi), incoterms
    return firma, adres, not_ilcesi, incoterms


BAYI_KODU_DESENI = re.compile(r"^\s*(\d{3,6})\s*-\s*(.+)$")


def bayi_adini_coz(bayi_adi: object) -> tuple[str, str]:
    """'1001 - KARTAL YAPI MARKET' -> ('1001', 'KARTAL YAPI MARKET').

    Bayi kodu ayrı sütunda gelmiyor ama bir kısım bayi adının başında duruyor;
    ayrıştırılınca müşteri master datasında gerçek kodla eşleşme kurulabiliyor.
    """
    ham = str(bayi_adi).strip() if bayi_adi is not None else ""
    eslesme = BAYI_KODU_DESENI.match(ham)
    if eslesme:
        return eslesme.group(1), eslesme.group(2).strip()
    return "", ham


@dataclass(frozen=True)
class Alan:
    ad: str
    baslik: str
    zorunlu: bool
    aciklama: str
    ornek: object
    aliaslar: tuple[str, ...] = ()

    @property
    def kabul_edilen_basliklar(self) -> tuple[str, ...]:
        return (self.baslik, *self.aliaslar)


URUN_ALANLARI: tuple[Alan, ...] = (
    Alan("urun_kodu", "StokKodu", True, "SKU. Sistemdeki benzersiz anahtar.", 8000013403,
         ("Stok Kodu", "Ürün Kodu", "SKU", "Malzeme Kodu", "Stok No")),
    Alan("urun_adi", "StokAdi", True, "Yükleme formunda görünen ürün adı.",
         "ademiX P 24/24 –AS/2 (H-TR)", ("Stok Adı", "Ürün Adı", "Malzeme Adı")),
    Alan("urun_grubu", "Ürün Grubu", True,
         "PANEL, KOMBİ, KLİMA, TERMOSİFON, AKSESUAR, BACA, ŞOFBEN, ISI POMPASI ... "
         "Planlama bu alana göre gruplanır.", "KOMBİ", ("Grup", "Mal Grubu")),
    Alan("palet_ici_adet", "Palet içi adet", True,
         "Bir palete kaç adet sığdığı. Palet ölçüsüyle planlanan depolarda (64) "
         "kullanılan tek girdi.", 18, ("Palet İçi Adet", "Paletteki Adet")),
    Alan("kamyon_yukleme_adeti", "Kamyon yükleme adeti", False,
         "Bir kamyonu dolduran adet. Kamyon anahtar değeri = 1 / bu sayı.", 234,
         ("Kamyon Yükleme Adeti", "Kamyon adet")),
    Alan("kamyon_palet", "Kamyon palet", False,
         "Bu üründen bir kamyona sığan palet sayısı (bilgi amaçlı).", 13, ()),
    Alan("tir_yukleme_adeti", "Tır yükleme adeti", False,
         "Bir tırı dolduran adet. Tır anahtar değeri = 1 / bu sayı. Anahtar ölçüsüyle "
         "planlanan depolarda (74) kullanılır.", 468, ("Tir yükleme adeti", "Tır adet")),
    Alan("tir_palet", "Tır palet", False,
         "Bu üründen bir tıra sığan palet sayısı (bilgi amaçlı).", 26, ("Tir palet",)),
    Alan("agirlik", "Ağırlık", False, "Birim ağırlık (kg).", 29, ("Agirlik", "Kg")),
    Alan("desi", "Ürün Desi", False, "Birim desi.", 1.28, ("Desi",)),
    Alan("m3", "M3", False, "Birim hacim (m³).", 0.00384, ("Hacim",)),
    Alan("palet_en", "Palet En", False, "Palet eni (cm).", 80, ()),
    Alan("palet_boy", "Palet Boy", False, "Palet boyu (cm).", 120, ()),
    Alan("palet_yukseklik", "Palet Yükseklik", False, "Palet yüksekliği (cm).", 162, ()),
    Alan("header_kod", "Header Kod", False,
         "Ana ürün ile aksesuarını bağlayan üst kod. Doluysa planlama anahtarı "
         "olarak ürün grubunun önüne geçer.", None, ("Header Code", "Üst Kod")),
    Alan("aktif", "Aktif", False, "E / H. Boş bırakılırsa E kabul edilir.", "E", ()),
)

SIPARIS_ALANLARI: tuple[Alan, ...] = (
    Alan("siparis_no", "Sipariş No", True, "Sipariş başlık numarası.", 2010421633,
         ("Siparis No", "Talep Numarası", "Belge No", "Order No")),
    Alan("teslimat_no", "Teslimat No", True,
         "Planlamanın bölünemez birimi. Aynı teslimat tek plandadır. Bayi ortak "
         "deposu (-1) satırlarında bu sütun 'BAYİ DEPO' gibi bir etiket taşır; "
         "o durumda sipariş numarası teslimat anahtarı olarak kullanılır.",
         2013624900, ("Teslimat", "Delivery")),
    Alan("urun_kodu", "StokKodu", True,
         "Master datada tanımlı olmalı; tanımsız ürün planlamaya girmez.", 8000013403,
         ("Stok Kodu", "Stok No", "Ürün Kodu", "SKU")),
    Alan("urun_adi", "StokAdi", False, "Bilgi amaçlı; master data önceliklidir.",
         "ademiX P 24/24 –AS/2 (H-TR)", ("Stok Adı", "Ürün Adı")),
    Alan("miktar", "Adet", True, "Sipariş adedi. Palet ve anahtar hesabı bundan yapılır.",
         72, ("Miktar", "Sipariş Miktarı")),
    Alan("depo_kodu", "Depo  Kodu", True,
         "Satır bazlıdır. Bütün depolar anahtar değerle planlanır; -1 bayi ortak "
         "deposudur (Eskişehir).", 64, ("Depo Kodu", "Depo", "Ambar Kodu")),
    Alan("sehir", "SehirAdi", False, "Yükleme formunun 'İl Adı' sütunu.", "ESKİŞEHİR",
         ("Şehir Adı", "Sehir Adi", "İl", "İl Adi")),
    Alan("bayi_adi", "BayiAdi", False, "Yükleme formunun 'Bayii Adı' sütunu.",
         "MOVUS DEPO-EREMİZ ISITMA SOĞUTMA", ("Bayi Adı", "Bayii Adı")),
    Alan("alici_firma", "AliciFirma", False,
         "Sevkiyatın teslim edileceği firma; yükleme formunda bayi adının yanına yazılır.",
         "ANKA CORP İNŞAAT LİMİTED ŞİRKETİ", ("Alıcı Firma", "Alici Firma")),
    Alan("sevk_adresi", "SevkAdresi", False,
         "Açık sevk adresi. Yükleme formunun son adres sütunudur.",
         "GÜMÜŞÇEŞME MAH. 184 SOK. NO:13/B", ("Sevk Adresi", "Adres")),
    Alan("teslim_sekli", "Not", False,
         "Teslim şekli ve/veya ilçe: 'CIF', ' - MERKEZ' ya da 'CIF - MERKEZ'. "
         "EXW olanlar kargoya yönlendirilir.", "CIF - MERKEZ", ("Teslim Şekli",)),
    Alan("siparis_tarihi", "Tarih", False, "GG.AA.YYYY", "31.08.2026",
         ("Sipariş Tarihi", "Talep Tarihi", "Belge Tarihi")),
    Alan("termin_tarihi", "Termin Tarihi", False,
         "GG.AA.YYYY. Planlama önceliğini belirler: eski termin önce planlanır. "
         "Boşsa sipariş tarihi kullanılır.", None,
         ("Teslim Tarihi", "Sevk Tarihi", "Planlama Tarihi", "PLANLAMA TARİHİ")),
    Alan("siparis_satir_no", "Sipariş Satır No", False,
         "Verilmezse ürün kodu satır anahtarı olarak kullanılır.", None,
         ("Satır No", "Kalem No")),
)


MUSTERI_ALANLARI: tuple[Alan, ...] = (
    Alan("bayi_adi", "Bayi Adı", True,
         "Müşterinin anahtarı. Bayi kodlarına ulaşılana kadar eşleştirme bu adla yapılır.",
         "MOVUS DEPO-EREMİZ ISITMA SOĞUTMA", ("BayiAdi", "Bayii Adı", "Müşteri Adı")),
    Alan("bayi_kodu", "Bayi Kodu", False, "Varsa bayi kodu; ileride anahtar olacak.",
         None, ("Müşteri Kodu", "Cari Kod")),
    Alan("alici_firma", "Alıcı Firma", False, "Sevkiyatın teslim edileceği firma adı.",
         "ALTEK TEKNİK TESİSAT", ("AliciFirma",)),
    Alan("il", "İl", True, "Rota ve bölge hesabı bu alandan yapılır.", "İZMİR",
         ("SehirAdi", "Şehir", "İl Adı")),
    Alan("ilce", "İlçe", False, "Yükleme formunda '+' ile birleşik yazılır.", "KARABAĞLAR",
         ("Ilce", "İlçe Adı")),
    Alan("sevk_adresi", "Sevk Adresi", False, "Açık adres.", "OSB 20. CADDE NO:36",
         ("SevkAdresi", "Adres")),
    Alan("telefon", "Telefon", False, "İrtibat telefonu.", None, ("Tel",)),
    Alan("incoterms", "Incoterms", False,
         "CIF / EXW ... EXW olan müşteriler kargoya yönlendirilir.", "CIF",
         ("Teslim Şekli", "Incoterm")),
    Alan("tir_girisi", "Tır Girişi (E/H/?)", False,
         "E = tır girebilir, H = fiziki adres tır almıyor, ? = belirsiz. "
         "Boş bırakılırsa ? kabul edilir.", "E",
         ("Tır Girişi", "Tir Girisi", "Tır Girer mi")),
    Alan("bolge_kodu", "Bölge", False,
         "Boş bırakılırsa ilin varsayılan bölgesi kullanılır.", None, ("Bolge", "Bölge Kodu")),
    Alan("notlar", "Notlar", False, "Serbest not.", None, ("Not", "Açıklama")),
    Alan("aktif", "Aktif", False, "E / H. Boş bırakılırsa E kabul edilir.", "E", ()),
)


IHRACAT_SIPARIS_ALANLARI: tuple[Alan, ...] = (
    Alan("siparis_no", "SİPARİŞ NO", True, "Sipariş numarası.", 9002842146,
         ("Sipariş No", "SIPARIS NO")),
    Alan("teslimat_no", "TESLİMAT NO", True,
         "Planlamanın bölünmez birimi.", 9106800933, ("Teslimat No", "TESLIMAT NO")),
    Alan("urun_kodu", "ÜRÜN KODU", True, "SKU.", 916041211, ("Ürün Kodu", "StokKodu")),
    Alan("urun_adi", "ÜRÜN TANIMI", False, "Yükleme formunda görünen ürün adı.",
         "25 VAI S 22 600 0400 V0 A1", ("Ürün Tanımı", "StokAdi")),
    Alan("miktar", "ADET", True, "Sipariş adedi.", 10, ("Adet", "Miktar")),
    Alan("depo_kodu", "DEPO", True, "Yükleme deposu (34, 74 ...).", 34, ("Depo",)),
    Alan("bayi_adi", "MÜŞTERİ ADI", True,
         "İhracat müşterisi. Araç tek noktaya gittiği için planın müşterisi budur.",
         "VAILLANT D.O.O.", ("Müşteri Adı", "MUSTERI ADI")),
    Alan("sehir", "ÜLKE", False, "Varış ülkesi.", "HIRVATİSTAN", ("Ülke",)),
    Alan("ulke_kodu", "ÜLKE KODU", False, "İki harfli ülke kodu.", "HR",
         ("Ulke Kodu", "Ülke kodu")),
    Alan("sevk_adresi", "SEVK ADRESİ", False, "Varış şehri / adresi.", "OSIJEK",
         ("Sevk Adresi",)),
    Alan("desi", "Desi", True,
         "Satırın desisi. İhracatta araç kapasitesi desi ile ölçülür; ürün master "
         "datasında ihracat SKU'ları bulunmadığı için doğrudan dosyadan alınır.",
         93.2, ("DESİ", "Desi ")),
    Alan("agirlik", "KG", False, "Satırın ağırlığı (kg). Ağırlık ikinci kapasite sınırıdır.",
         138.8, ("Ağırlık", "AGIRLIK")),
    Alan("teslim_sekli", "INCOTERMS", False, "DAP / CIF / EXW ...", "DAP",
         ("Incoterms",)),
    Alan("siparis_tarihi", "Tarih", False, "GG.AA.YYYY", None, ("Sipariş Tarihi",)),
    Alan("termin_tarihi", "Termin Tarihi", False, "GG.AA.YYYY", None,
         ("Teslim Tarihi", "Sevk Tarihi")),
)


IHRACAT_MUSTERI_ALANLARI: tuple[Alan, ...] = (
    Alan("musteri_adi", "Müşteri Adı", True, "Eşleştirme anahtarı.",
         "VAILLANT D.O.O.", ("MÜŞTERİ", "Musteri Adi")),
    Alan("ulke", "Ülke", False, "Varış ülkesi.", "HIRVATİSTAN", ("ÜLKE",)),
    Alan("ulke_kodu", "Ülke Kodu", False, "İki harfli kod.", "HR", ("ÜLKE KODU",)),
    Alan("sevk_adresi", "Sevk Adresi", False, "Varış şehri.", "OSIJEK", ("SEVK ADRESİ",)),
    Alan("arac_tipi", "Araç Tipi", False,
         "TIR / KONTEYNER / PARSİYEL / KARGO. Taşıma modunu belirler: konteyner deniz, "
         "diğerleri kara yoludur.", "TIR", ("ARAÇ TİPİ",)),
    Alan("sefer_kodu", "Sefer Kodu", False,
         "Sefer numarasının belge kodu: N (NSC) ya da E (Export). Boşsa E kabul edilir.",
         "E", ("NSC&Core", "NSC&Export")),
    Alan("yukleme_tipi", "Yükleme Tipi", False,
         "STANDART / PALET YÜKSELTME / DÖKME / KÖŞEBENT ... forma yazılır.",
         "PALET YÜKSELTME", ("YÜKLEME TİPİ",)),
    Alan("azami_agirlik", "Azami Tonaj", False,
         "kg. '22.000 KG' gibi metin de kabul edilir; boşsa araç tipinin varsayılanı "
         "kullanılır.", "22.000 KG", ("MAKSİMUM TONAJ", "Maksimum Tonaj")),
    Alan("aciklama", "Açıklama", False,
         "Müşteriye özel yükleme notu: hava yastığı, silika jel, paletsiz dökme ...",
         None, ("Not", "Notlar")),
    Alan("incoterms", "Incoterms", False, "DAP / CIF / EXW ...", "DAP", ("INCOTERMS",)),
    Alan("tedarikci", "Tedarikçi", False, "Araç tedarikçisi.", "OKTAY ALAGÖZ",
         ("TEDARİKÇİ",)),
    Alan("satis_destek", "Satış Destek", False, "Satış destek sorumlusu.",
         "SEÇİL KARACA", ("SATIŞ DESTEK",)),
    Alan("aktif", "Aktif", False, "E / H.", "E", ()),
)


def alias_haritasi(alanlar: tuple[Alan, ...]) -> dict[str, tuple[str, ...]]:
    return {alan.ad: alan.kabul_edilen_basliklar for alan in alanlar}


def zorunlu_alanlar(alanlar: tuple[Alan, ...]) -> tuple[str, ...]:
    return tuple(alan.ad for alan in alanlar if alan.zorunlu)


URUN_ALIAS = alias_haritasi(URUN_ALANLARI)
SIPARIS_ALIAS = alias_haritasi(SIPARIS_ALANLARI)
MUSTERI_ALIAS = alias_haritasi(MUSTERI_ALANLARI)
IHRACAT_SIPARIS_ALIAS = alias_haritasi(IHRACAT_SIPARIS_ALANLARI)
IHRACAT_MUSTERI_ALIAS = alias_haritasi(IHRACAT_MUSTERI_ALANLARI)
