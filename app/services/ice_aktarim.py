"""Excel içe aktarım servisleri: ürün master datası ve siparişler."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IceAktarim, SiparisDurumu, SiparisSatiri, Urun
from app.services.planlama_anahtari import teslimat_anahtari
from app.services import excel
from app.services.excel import ExcelHatasi
from app.services.veri_formatlari import (
    SIPARIS_ALANLARI,
    SIPARIS_ALIAS,
    URUN_ALANLARI,
    URUN_ALIAS,
    zorunlu_alanlar,
)


@dataclass
class SatirHatasi:
    satir_no: int
    anahtar: str
    mesaj: str


@dataclass
class IceAktarimSonucu:
    toplam: int = 0
    eklenen: int = 0
    guncellenen: int = 0
    atlanan: int = 0
    birlestirilen: int = 0
    """Aynı sipariş/teslimat/ürün tekrar geldiği için miktarı toplanan satır sayısı."""
    hatalar: list[SatirHatasi] = field(default_factory=list)
    uyarilar: list[SatirHatasi] = field(default_factory=list)
    """Kayıt alındı ama eksik veri var; kullanıcının görmesi gereken durumlar."""

    @property
    def basarili(self) -> int:
        return self.eklenen + self.guncellenen

    @property
    def hatali(self) -> int:
        return len(self.hatalar)

    def ozet(self) -> str:
        metin = (
            f"{self.toplam} satır okundu · {self.eklenen} yeni · "
            f"{self.guncellenen} güncellendi · {self.atlanan} atlandı · "
            f"{self.hatali} hatalı"
        )
        if self.birlestirilen:
            metin += f" · {self.birlestirilen} satır birleştirildi"
        if self.uyarilar:
            metin += f" · {len(self.uyarilar)} eksik veri uyarısı"
        return metin


def _kontrol_et(dosya: Any, alanlar, alias) -> None:
    eksikler = excel.eksik_kolonlar(dosya, alias, zorunlu_alanlar(alanlar))
    if eksikler:
        basliklar = {alan.ad: alan.baslik for alan in alanlar}
        raise ExcelHatasi(
            "Dosyada zorunlu kolonlar bulunamadı: "
            + ", ".join(basliklar[ad] for ad in eksikler)
        )


def urunleri_aktar(
    db: Session, dosya: Path | Any, dosya_adi: str, kullanici: str = "sistem"
) -> IceAktarimSonucu:
    _kontrol_et(dosya, URUN_ALANLARI, URUN_ALIAS)
    kayitlar = excel.satirlari_oku(dosya, URUN_ALIAS, zorunlu_alanlar(URUN_ALANLARI))
    sonuc = IceAktarimSonucu(toplam=len(kayitlar))

    mevcutlar = {
        urun.urun_kodu: urun for urun in db.scalars(select(Urun)).all()
    }
    for kayit in kayitlar:
        satir_no = kayit["_satir_no"]
        urun_kodu = excel.metin(kayit.get("urun_kodu"))
        try:
            if not urun_kodu:
                raise ExcelHatasi("Stok kodu boş olamaz")
            urun_adi = excel.metin(kayit.get("urun_adi"))
            if not urun_adi:
                raise ExcelHatasi("Stok adı boş olamaz")
            palet_ici = excel.tam_sayi_ya_da(kayit.get("palet_ici_adet"))
            kamyon_adet = excel.tam_sayi_ya_da(kayit.get("kamyon_yukleme_adeti"))
            tir_adet = excel.tam_sayi_ya_da(kayit.get("tir_yukleme_adeti"))
        except ExcelHatasi as hata:
            sonuc.hatalar.append(SatirHatasi(satir_no, urun_kodu or "-", str(hata)))
            continue

        urun = mevcutlar.get(urun_kodu)
        if urun is None:
            urun = Urun(urun_kodu=urun_kodu)
            db.add(urun)
            mevcutlar[urun_kodu] = urun
            sonuc.eklenen += 1
        else:
            sonuc.guncellenen += 1

        urun.urun_adi = urun_adi
        urun.urun_grubu = (excel.metin(kayit.get("urun_grubu")) or "").upper() or None
        urun.palet_ici_adet = palet_ici
        urun.kamyon_yukleme_adeti = kamyon_adet
        urun.kamyon_palet = excel.tam_sayi_ya_da(kayit.get("kamyon_palet"))
        urun.tir_yukleme_adeti = tir_adet
        urun.tir_palet = excel.tam_sayi_ya_da(kayit.get("tir_palet"))
        urun.agirlik = excel.sayi_ya_da(kayit.get("agirlik"))
        urun.desi = excel.sayi_ya_da(kayit.get("desi"))
        urun.m3 = excel.sayi_ya_da(kayit.get("m3"))
        urun.palet_en = excel.tam_sayi_ya_da(kayit.get("palet_en"))
        urun.palet_boy = excel.tam_sayi_ya_da(kayit.get("palet_boy"))
        urun.palet_yukseklik = excel.tam_sayi_ya_da(kayit.get("palet_yukseklik"))
        urun.header_kod = excel.metin(kayit.get("header_kod"))
        urun.aktif = excel.evet_hayir(kayit.get("aktif"), True)

        if not urun.planlanabilir_mi:
            # Kayıt yine de alınır; planlamaya girdiğinde gerekçesiyle uyarılır.
            sonuc.uyarilar.append(
                SatirHatasi(
                    satir_no, urun_kodu,
                    "Palet içi adet / kamyon / tır yükleme adeti alanlarının üçü de boş; "
                    "bu ürün planlamaya giremez",
                )
            )

    _aktarim_kaydet(db, dosya_adi, "URUN", sonuc, kullanici)
    db.flush()
    return sonuc


def siparisleri_aktar(
    db: Session, dosya: Path | Any, dosya_adi: str, kullanici: str = "sistem"
) -> IceAktarimSonucu:
    _kontrol_et(dosya, SIPARIS_ALANLARI, SIPARIS_ALIAS)
    kayitlar = excel.satirlari_oku(dosya, SIPARIS_ALIAS, zorunlu_alanlar(SIPARIS_ALANLARI))
    sonuc = IceAktarimSonucu(toplam=len(kayitlar))
    aktarim = _aktarim_kaydet(db, dosya_adi, "SIPARIS", sonuc, kullanici)
    db.flush()

    etkilenen_teslimatlar: set[str] = set()
    parti: dict[tuple[str, str, str], SiparisSatiri] = {}
    """Aynı dosyada tekrar eden (sipariş, teslimat, ürün) satırları birleştirmek için."""

    for kayit in kayitlar:
        satir_no = kayit["_satir_no"]
        siparis_no = excel.metin(kayit.get("siparis_no"))
        urun_kodu = excel.metin(kayit.get("urun_kodu"))
        # Kaynak dosyalarda satır numarası yok; satır anahtarı ürün kodudur.
        siparis_satir_no = excel.metin(kayit.get("siparis_satir_no")) or urun_kodu
        anahtar = f"{siparis_no or '-'}/{siparis_satir_no or '-'}"
        try:
            if not siparis_no:
                raise ExcelHatasi("Sipariş No boş olamaz")
            if not urun_kodu:
                raise ExcelHatasi("Stok kodu boş olamaz")
            teslimat_no = excel.metin(kayit.get("teslimat_no"))
            if not teslimat_no:
                raise ExcelHatasi("Teslimat No boş olamaz")
            if not any(karakter.isdigit() for karakter in str(teslimat_no)):
                # Havuz listelerinde teslimat henüz atanmamış satırlar "BAYİ DEPO"
                # gibi metinlerle gelir; bunlar planlanamaz.
                raise ExcelHatasi(
                    f"Teslimat numarası atanmamış ({teslimat_no}); bu satır planlanamaz"
                )
            depo_kodu = excel.metin(kayit.get("depo_kodu"))
            if not depo_kodu or depo_kodu.strip() in {"-1", "0"}:
                raise ExcelHatasi(
                    f"Depo kodu atanmamış ({depo_kodu or 'boş'}); bu satır planlanamaz"
                )
            miktar = excel.sayi(kayit.get("miktar"), "Miktar")
            if miktar <= 0:
                raise ExcelHatasi("Miktar sıfırdan büyük olmalı")
            siparis_tarihi = excel.tarih(kayit.get("siparis_tarihi"))
            termin_tarihi = excel.tarih(kayit.get("termin_tarihi"))
        except ExcelHatasi as hata:
            sonuc.hatalar.append(SatirHatasi(satir_no, anahtar, str(hata)))
            continue

        satir_anahtari = (siparis_no, teslimat_no, siparis_satir_no)
        if satir_anahtari in parti:
            # Kaynak dosyada aynı sipariş/teslimat/ürün birden çok satırda gelebiliyor;
            # miktarlar toplanır, mükerrer kayıt oluşmaz.
            parti[satir_anahtari].miktar = Decimal(parti[satir_anahtari].miktar) + miktar
            sonuc.birlestirilen += 1
            continue

        mevcut = db.scalar(
            select(SiparisSatiri).where(
                SiparisSatiri.siparis_no == siparis_no,
                SiparisSatiri.teslimat_no == teslimat_no,
                SiparisSatiri.siparis_satir_no == siparis_satir_no,
            )
        )
        if mevcut is not None and mevcut.durum in {
            SiparisDurumu.PLANLANDI,
            SiparisDurumu.TAMAMLANDI,
        }:
            # Planlanmış satır yeniden yüklemeyle bozulmaz.
            sonuc.atlanan += 1
            continue

        if mevcut is None:
            mevcut = SiparisSatiri(
                siparis_no=siparis_no,
                teslimat_no=teslimat_no,
                siparis_satir_no=siparis_satir_no,
            )
            db.add(mevcut)
            sonuc.eklenen += 1
        else:
            sonuc.guncellenen += 1

        mevcut.teslimat_no = teslimat_no
        mevcut.urun_kodu = urun_kodu
        mevcut.urun_adi = excel.metin(kayit.get("urun_adi"))
        mevcut.miktar = miktar
        mevcut.depo_kodu = depo_kodu.strip().upper()
        mevcut.sehir = excel.metin(kayit.get("sehir"))
        mevcut.bayi_adi = excel.metin(kayit.get("bayi_adi"))
        mevcut.alici_firma = excel.metin(kayit.get("alici_firma"))
        mevcut.sevk_adresi = excel.metin(kayit.get("sevk_adresi"))
        mevcut.teslim_sekli = excel.metin(kayit.get("teslim_sekli"))
        mevcut.siparis_tarihi = siparis_tarihi
        mevcut.termin_tarihi = termin_tarihi
        mevcut.durum = SiparisDurumu.BEKLEMEDE
        mevcut.hata_aciklamasi = None
        mevcut.ice_aktarim_id = aktarim.id
        parti[satir_anahtari] = mevcut
        etkilenen_teslimatlar.add(teslimat_no)

    db.flush()
    for hata in _teslimatlari_dogrula(db, etkilenen_teslimatlar):
        sonuc.hatalar.append(hata)

    aktarim.basarili_satir = sonuc.basarili
    aktarim.hatali_satir = sonuc.hatali
    aktarim.hata_ozeti = _hata_ozeti(sonuc)
    db.flush()
    return sonuc


def _teslimatlari_dogrula(db: Session, teslimat_nolar: set[str]) -> list[SatirHatasi]:
    """Bir teslimat tek planlama anahtarına ve tek depoya ait olmak zorunda.

    Planlama anahtarı ürün grubu (ayarlanmışsa SKU) olduğundan, ana ürün ile
    aksesuarının aynı teslimatta gelmesi normaldir: aksesuar grupları ana ürünün
    anahtarına yazılır.
    """
    hatalar: list[SatirHatasi] = []
    if not teslimat_nolar:
        return hatalar

    satirlar = db.scalars(
        select(SiparisSatiri).where(SiparisSatiri.teslimat_no.in_(teslimat_nolar))
    ).all()
    urun_haritasi = {
        urun.urun_kodu: urun
        for urun in db.scalars(
            select(Urun).where(
                Urun.urun_kodu.in_({satir.urun_kodu for satir in satirlar})
            )
        ).all()
    }

    gruplar: dict[str, list[SiparisSatiri]] = {}
    for satir in satirlar:
        gruplar.setdefault(satir.teslimat_no, []).append(satir)

    for teslimat_no, grup in gruplar.items():
        mesaj = None
        depolar = {satir.depo_kodu for satir in grup}
        anahtar = teslimat_anahtari(urun_haritasi.get(s.urun_kodu) for s in grup)

        if anahtar and " + " in anahtar:
            mesaj = (
                f"Teslimat birden fazla ürün grubu içeriyor ({anahtar}). "
                "Bir teslimat tek planlama anahtarına ait olmalıdır."
            )
        elif len(depolar) > 1:
            mesaj = (
                f"Teslimat birden fazla depo kodu içeriyor ({', '.join(sorted(depolar))})."
            )
        if mesaj:
            for satir in grup:
                satir.durum = SiparisDurumu.HATALI
                satir.hata_aciklamasi = mesaj
            hatalar.append(SatirHatasi(0, teslimat_no, mesaj))
    return hatalar


def _hata_ozeti(sonuc: IceAktarimSonucu, azami: int = 50) -> str | None:
    if not sonuc.hatalar:
        return None
    satirlar = [
        f"Satır {hata.satir_no or '-'} ({hata.anahtar}): {hata.mesaj}"
        for hata in sonuc.hatalar[:azami]
    ]
    if len(sonuc.hatalar) > azami:
        satirlar.append(f"... ve {len(sonuc.hatalar) - azami} hata daha")
    return "\n".join(satirlar)


def _aktarim_kaydet(
    db: Session, dosya_adi: str, tur: str, sonuc: IceAktarimSonucu, kullanici: str
) -> IceAktarim:
    aktarim = IceAktarim(
        dosya_adi=dosya_adi,
        tur=tur,
        toplam_satir=sonuc.toplam,
        basarili_satir=sonuc.basarili,
        hatali_satir=sonuc.hatali,
        hata_ozeti=_hata_ozeti(sonuc),
        kullanici=kullanici,
    )
    db.add(aktarim)
    return aktarim
