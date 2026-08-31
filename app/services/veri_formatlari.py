"""Excel alan tanımları — içe aktarım ve şablon üretimi tek kaynaktan beslenir.

Başlıklar, sahadaki gerçek dosyalara göre belirlendi:
  * ürün master datası → "Ring Planları" çalışma kitabının `masterdata` sayfası
  * siparişler         → sevk planı / havuz sipariş sayfaları ve Bekleyen Talep Listesi
Alternatif başlıklar `aliaslar` alanında listelenir; hepsi otomatik tanınır.
"""
from __future__ import annotations

from dataclasses import dataclass


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
         "Planlamanın bölünemez birimi. Aynı teslimat tek plandadır.", 2013624900,
         ("Teslimat", "Delivery")),
    Alan("urun_kodu", "StokKodu", True,
         "Master datada tanımlı olmalı; tanımsız ürün planlamaya girmez.", 8000013403,
         ("Stok Kodu", "Stok No", "Ürün Kodu", "SKU")),
    Alan("urun_adi", "StokAdi", False, "Bilgi amaçlı; master data önceliklidir.",
         "ademiX P 24/24 –AS/2 (H-TR)", ("Stok Adı", "Ürün Adı")),
    Alan("miktar", "Adet", True, "Sipariş adedi. Palet ve anahtar hesabı bundan yapılır.",
         72, ("Miktar", "Sipariş Miktarı")),
    Alan("depo_kodu", "Depo  Kodu", True,
         "Satır bazlıdır. 64 → palet ölçüsüyle, 74 → anahtar değerle planlanır.",
         64, ("Depo Kodu", "Depo", "Ambar Kodu")),
    Alan("sehir", "SehirAdi", False, "Yükleme formunun 'İl Adı' sütunu.", "ESKİŞEHİR",
         ("Şehir Adı", "Sehir Adi", "İl", "İl Adi")),
    Alan("bayi_adi", "BayiAdi", False, "Yükleme formunun 'Bayii Adı' sütunu.",
         "MOVUS DEPO-EREMİZ ISITMA SOĞUTMA", ("Bayi Adı", "Bayii Adı")),
    Alan("alici_firma", "AliciFirma", False,
         "Kaynak dosyada sevk adresi bu sütunda gelir; yükleme formunda adres olarak yazılır.",
         "OSB 20. CADDE NO:36", ("Alıcı Firma", "Alici Firma")),
    Alan("sevk_adresi", "SevkAdresi", False,
         "Kaynak dosyada ilçe bu sütunda gelir; yükleme formunun son adres sütunudur.",
         "ODUNPAZARI", ("Sevk Adresi", "İlçe")),
    Alan("teslim_sekli", "Not", False, "Teslim şekli (CIF vb.).", "CIF", ("Teslim Şekli",)),
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


def alias_haritasi(alanlar: tuple[Alan, ...]) -> dict[str, tuple[str, ...]]:
    return {alan.ad: alan.kabul_edilen_basliklar for alan in alanlar}


def zorunlu_alanlar(alanlar: tuple[Alan, ...]) -> tuple[str, ...]:
    return tuple(alan.ad for alan in alanlar if alan.zorunlu)


URUN_ALIAS = alias_haritasi(URUN_ALANLARI)
SIPARIS_ALIAS = alias_haritasi(SIPARIS_ALANLARI)
