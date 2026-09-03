"""Programla birlikte gelen master datanın ilk kurulumda yüklenmesi.

Kullanıcı hiçbir dosya yüklemeden çalışmaya başlayabilsin diye şirketin kendi
verisi `veri/ornek/` altında programa gömülüdür. İlgili tablo **boşsa** — yani ilk
kurulumda ya da veritabanı sıfırlandıktan sonra — bu dosyalar otomatik yüklenir.

Tablo doluysa hiçbir şey yapılmaz: kullanıcının ekrandan yüklediği güncel master
data hiçbir zaman gömülü dosyayla ezilmez.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import IhracatMusterisi, IhracatUrunu, Musteri
from app.services import ice_aktarim
from app.services.excel import ExcelHatasi

ORNEK_DIZIN = Path("veri/ornek")


@dataclass(frozen=True)
class GomuluDosya:
    ad: str
    dosya: Path
    tablo: type
    yukleyici: Callable[..., ice_aktarim.IceAktarimSonucu]


GOMULU_DOSYALAR: tuple[GomuluDosya, ...] = (
    GomuluDosya(
        "İhracat ürün master datası",
        ORNEK_DIZIN / "ihracat_urun_masterdata.xlsx",
        IhracatUrunu,
        ice_aktarim.ihracat_urunlerini_aktar,
    ),
    GomuluDosya(
        "İhracat müşteri master datası",
        ORNEK_DIZIN / "ihracat_masterdata.xlsx",
        IhracatMusterisi,
        ice_aktarim.ihracat_musterilerini_aktar,
    ),
    GomuluDosya(
        "İç piyasa müşteri master datası",
        ORNEK_DIZIN / "ic_piyasa_masterdata.xlsx",
        Musteri,
        ice_aktarim.musterileri_aktar,
    ),
)


def eksikleri_yukle(db: Session) -> list[str]:
    """Boş tabloları gömülü dosyalardan doldurur; yüklenenlerin özetini döner."""
    mesajlar: list[str] = []
    for gomulu in GOMULU_DOSYALAR:
        if not gomulu.dosya.exists():
            continue
        if (db.scalar(select(func.count()).select_from(gomulu.tablo)) or 0) > 0:
            continue
        try:
            sonuc = gomulu.yukleyici(db, gomulu.dosya, gomulu.dosya.name, "kurulum")
        except (ExcelHatasi, OSError) as hata:
            # Gömülü veri yüklenemezse program yine de açılmalı; ekrandan yüklenebilir.
            mesajlar.append(f"{gomulu.ad}: yüklenemedi ({hata})")
            continue
        mesajlar.append(f"{gomulu.ad}: {sonuc.eklenen} kayıt")
    return mesajlar
