"""Excel içe aktarım servisleri: ürün master datası ve siparişler."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IceAktarim, SiparisDurumu, SiparisSatiri, Urun
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
    hatalar: list[SatirHatasi] = field(default_factory=list)

    @property
    def basarili(self) -> int:
        return self.eklenen + self.guncellenen

    @property
    def hatali(self) -> int:
        return len(self.hatalar)

    def ozet(self) -> str:
        return (
            f"{self.toplam} satır okundu · {self.eklenen} yeni · "
            f"{self.guncellenen} güncellendi · {self.atlanan} atlandı · "
            f"{self.hatali} hatalı"
        )


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
    kayitlar = excel.satirlari_oku(dosya, URUN_ALIAS)
    sonuc = IceAktarimSonucu(toplam=len(kayitlar))

    for kayit in kayitlar:
        satir_no = kayit["_satir_no"]
        urun_kodu = excel.metin(kayit.get("urun_kodu"))
        try:
            if not urun_kodu:
                raise ExcelHatasi("Ürün Kodu boş olamaz")
            palet_ici = excel.tam_sayi(kayit.get("palet_ici_adet"), "Palet İçi Adet")
            if palet_ici <= 0:
                raise ExcelHatasi("Palet İçi Adet sıfırdan büyük olmalı")
            urun_adi = excel.metin(kayit.get("urun_adi"))
            urun_grubu = excel.metin(kayit.get("urun_grubu"))
            if not urun_adi or not urun_grubu:
                raise ExcelHatasi("Ürün Adı ve Ürün Grubu zorunludur")
        except ExcelHatasi as hata:
            sonuc.hatalar.append(SatirHatasi(satir_no, urun_kodu or "-", str(hata)))
            continue

        mevcut = db.scalar(select(Urun).where(Urun.urun_kodu == urun_kodu))
        if mevcut is None:
            mevcut = Urun(urun_kodu=urun_kodu)
            db.add(mevcut)
            sonuc.eklenen += 1
        else:
            sonuc.guncellenen += 1
        mevcut.urun_adi = urun_adi
        mevcut.urun_grubu = urun_grubu
        mevcut.palet_ici_adet = palet_ici
        mevcut.header_kod = excel.metin(kayit.get("header_kod"))
        mevcut.aksesuar_mi = excel.evet_hayir(kayit.get("aksesuar_mi"), False)
        mevcut.aktif = excel.evet_hayir(kayit.get("aktif"), True)

    _aktarim_kaydet(db, dosya_adi, "URUN", sonuc, kullanici)
    db.flush()
    return sonuc


def siparisleri_aktar(
    db: Session, dosya: Path | Any, dosya_adi: str, kullanici: str = "sistem"
) -> IceAktarimSonucu:
    _kontrol_et(dosya, SIPARIS_ALANLARI, SIPARIS_ALIAS)
    kayitlar = excel.satirlari_oku(dosya, SIPARIS_ALIAS)
    sonuc = IceAktarimSonucu(toplam=len(kayitlar))
    aktarim = _aktarim_kaydet(db, dosya_adi, "SIPARIS", sonuc, kullanici)
    db.flush()

    etkilenen_teslimatlar: set[str] = set()

    for kayit in kayitlar:
        satir_no = kayit["_satir_no"]
        siparis_no = excel.metin(kayit.get("siparis_no"))
        siparis_satir_no = excel.metin(kayit.get("siparis_satir_no"))
        anahtar = f"{siparis_no or '-'}/{siparis_satir_no or '-'}"
        try:
            if not siparis_no or not siparis_satir_no:
                raise ExcelHatasi("Sipariş No ve Sipariş Satır No zorunludur")
            teslimat_no = excel.metin(kayit.get("teslimat_no"))
            if not teslimat_no:
                raise ExcelHatasi("Teslimat No boş olamaz")
            urun_kodu = excel.metin(kayit.get("urun_kodu"))
            if not urun_kodu:
                raise ExcelHatasi("Ürün Kodu boş olamaz")
            depo_kodu = excel.metin(kayit.get("depo_kodu"))
            if not depo_kodu:
                raise ExcelHatasi("Depo Kodu boş olamaz")
            miktar = excel.sayi(kayit.get("miktar"), "Miktar")
            if miktar <= 0:
                raise ExcelHatasi("Miktar sıfırdan büyük olmalı")
            siparis_tarihi = excel.tarih(kayit.get("siparis_tarihi"))
            termin_tarihi = excel.tarih(kayit.get("termin_tarihi"))
        except ExcelHatasi as hata:
            sonuc.hatalar.append(SatirHatasi(satir_no, anahtar, str(hata)))
            continue

        mevcut = db.scalar(
            select(SiparisSatiri).where(
                SiparisSatiri.siparis_no == siparis_no,
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
                siparis_no=siparis_no, siparis_satir_no=siparis_satir_no
            )
            db.add(mevcut)
            sonuc.eklenen += 1
        else:
            sonuc.guncellenen += 1

        mevcut.teslimat_no = teslimat_no
        mevcut.musteri_kodu = excel.metin(kayit.get("musteri_kodu"))
        mevcut.musteri_adi = excel.metin(kayit.get("musteri_adi"))
        mevcut.urun_kodu = urun_kodu
        mevcut.urun_adi = excel.metin(kayit.get("urun_adi"))
        mevcut.miktar = miktar
        mevcut.birim_kodu = excel.metin(kayit.get("birim_kodu")) or "ADET"
        mevcut.depo_kodu = depo_kodu
        mevcut.siparis_tarihi = siparis_tarihi
        mevcut.termin_tarihi = termin_tarihi
        mevcut.durum = SiparisDurumu.BEKLEMEDE
        mevcut.hata_aciklamasi = None
        mevcut.ice_aktarim_id = aktarim.id
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
    """Kural 8: bir teslimat tek ürün ve tek depo içermek zorunda.

    Header code'lu ürünler (ana ürün + aksesuar) istisnadır; planlama anahtarları
    aynı olduğu için tek kalem sayılırlar.
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
        anahtarlar = set()
        for satir in grup:
            urun = urun_haritasi.get(satir.urun_kodu)
            anahtarlar.add(urun.planlama_anahtari if urun else satir.urun_kodu)
        depolar = {satir.depo_kodu for satir in grup}

        mesaj = None
        if len(anahtarlar) > 1:
            mesaj = (
                "Teslimat birden fazla ürün içeriyor "
                f"({', '.join(sorted(anahtarlar))}). Sisteme yalnızca tek ürünlü "
                "teslimatlar yüklenebilir."
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
