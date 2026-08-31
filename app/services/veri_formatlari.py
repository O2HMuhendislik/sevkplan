"""Excel alan tanımları — içe aktarım ve şablon üretimi tek kaynaktan beslenir.

Yeni bir kolon eklemek gerektiğinde sadece burası güncellenir; hem okuyucu hem de
kullanıcıya verilen şablon otomatik olarak uyumlu kalır.
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
    Alan("urun_kodu", "Ürün Kodu", True, "SKU. Sistemdeki benzersiz anahtar.", "KMB-24-ERP",
         ("SKU", "Malzeme Kodu", "Stok Kodu", "Material")),
    Alan("urun_adi", "Ürün Adı", True, "Yükleme formunda görünecek isim.",
         "Kombi 24 kW ErP", ("Malzeme Adı", "Stok Adı", "Tanım")),
    Alan("urun_grubu", "Ürün Grubu", True,
         "Kombi, Radyatör, Termosifon, Klima, Şofben, Isı Pompası ...", "Kombi",
         ("Grup", "Mal Grubu")),
    Alan("palet_ici_adet", "Palet İçi Adet", True,
         "Bir palete kaç adet sığdığı. Palet hesabının tek girdisi. Tam sayı, > 0.",
         30, ("Paletteki Adet", "Palet Adedi", "Palet Kapasitesi")),
    Alan("header_kod", "Header Kod", False,
         "Ana ürün ve aksesuarını bağlayan üst kod. Aynı header kodlu ürünler "
         "her zaman aynı plana girer. Header sistemi kullanılmıyorsa boş bırakın.",
         "HDR-KMB-24", ("Header Code", "Üst Kod", "Ana Kod")),
    Alan("aksesuar_mi", "Aksesuar mı", False,
         "E / H. Header kod altındaki aksesuar kalemleri için E.", "H",
         ("Aksesuar", "Aksesuar mi")),
    Alan("aktif", "Aktif", False, "E / H. Boş bırakılırsa E kabul edilir.", "E", ()),
)

SIPARIS_ALANLARI: tuple[Alan, ...] = (
    Alan("siparis_no", "Sipariş No", True, "Sipariş başlık numarası.", "SIP-2026-000145",
         ("Siparis No", "Order No", "Belge No")),
    Alan("siparis_satir_no", "Sipariş Satır No", True,
         "Sipariş içindeki satır sırası. Sipariş no ile birlikte benzersiz olmalı; "
         "aynı dosya iki kez yüklenirse mükerrer kayıt oluşmaz.", "10",
         ("Satır No", "Kalem No", "Pozisyon")),
    Alan("teslimat_no", "Teslimat No", True,
         "Planlamanın bölünemez birimi. Aynı teslimat tek plandadır.", "TSL-8800123",
         ("Teslimat", "Delivery", "Sevkiyat No")),
    Alan("musteri_kodu", "Müşteri Kodu", False, "Raporlama için.", "M-10045",
         ("Cari Kodu", "Müşteri No")),
    Alan("musteri_adi", "Müşteri Adı", False, "Yükleme formunda görünür.",
         "Örnek Isıtma Ltd. Şti.", ("Cari Adı", "Müşteri Ünvanı")),
    Alan("urun_kodu", "Ürün Kodu", True,
         "Master datada tanımlı olmalı; tanımsız ürün planlamaya girmez.", "KMB-24-ERP",
         ("SKU", "Malzeme Kodu", "Stok Kodu")),
    Alan("urun_adi", "Ürün Adı", False, "Bilgi amaçlı; master data önceliklidir.",
         "Kombi 24 kW ErP", ("Malzeme Adı", "Stok Adı")),
    Alan("miktar", "Miktar", True, "Sipariş adedi. Palet hesabı bundan yapılır.", 300,
         ("Adet", "Sipariş Miktarı", "Kalan Miktar")),
    Alan("birim_kodu", "Birim", False, "Varsayılan ADET.", "ADET", ("Birim Kodu", "UOM")),
    Alan("depo_kodu", "Depo Kodu", True,
         "Satır bazlıdır. 64 ise Ring planlaması, değilse Faz 2 (tır) kapsamındadır.",
         "64", ("Depo", "Ambar Kodu", "Depo No")),
    Alan("siparis_tarihi", "Sipariş Tarihi", False, "GG.AA.YYYY", "20.08.2026",
         ("Belge Tarihi",)),
    Alan("termin_tarihi", "Termin Tarihi", False,
         "GG.AA.YYYY. Planlama önceliğini belirler: eski termin önce planlanır.",
         "05.09.2026", ("Teslim Tarihi", "Sevk Tarihi", "İstenen Tarih")),
)


def alias_haritasi(alanlar: tuple[Alan, ...]) -> dict[str, tuple[str, ...]]:
    return {alan.ad: alan.kabul_edilen_basliklar for alan in alanlar}


def zorunlu_alanlar(alanlar: tuple[Alan, ...]) -> tuple[str, ...]:
    return tuple(alan.ad for alan in alanlar if alan.zorunlu)


URUN_ALIAS = alias_haritasi(URUN_ALANLARI)
SIPARIS_ALIAS = alias_haritasi(SIPARIS_ALANLARI)
