"""Saha dosyalarındaki bayi adlarını sistemdeki müşteri kaydına bağlar.

Sahadan gelen listelerde (cari kod listesi, teslimat tipi listesi) bayi **adla**
geliyor; sistemdeki müşteri kaydının anahtarı da ad. İki liste aynı bayiyi farklı
yazabildiği için eşleştirme kademeli yapılır.

**Bulanık (benzerlik) eşleştirme bilerek yapılmaz.** Türkçe bayi adları ISI, DEPO,
MÜHENDİSLİK gibi ortak kelimeleri paylaşıyor ve benzerlik oranı yanıltıyor:
"AKKAŞ ISI DEPO" ile "ARSE ISI DEPO" %81 benziyor ama farklı bayiler. Yanlış
eşleşme yanlış cari kod ya da yanlış "tır giremez" işareti demek — biri faturaya,
diğeri araç seçimine dokunur. Eşleşmeyenler bu yüzden otomatik atanmaz;
gerekçesiyle listelenir ve kullanıcı eşler.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.iller import yer_adi
from app.models import Musteri

FIRMA_TAKILARI = frozenset(
    {
        "LTD", "STI", "SIRKETI", "SIRKET", "AS", "ANONIM", "LIMITED", "KOLL",
        "SAN", "SANAYI", "TIC", "TICARET", "VE", "INS", "INSAAT",
        "MUH", "MUHENDISLIK",
    }
)
"""Şirket unvanı ekleri. Ayırt edici değiller: "X MÜH. LTD. ŞTİ." ile "X" aynı bayi."""


def sikistir(ad: str) -> str:
    """Noktalama ve boşluk farklarını yok sayar: 'A.B.C' ile 'ABC' aynı olur."""
    return re.sub(r"[^A-Z0-9]", "", yer_adi(ad))


def jetonlar(ad: str) -> frozenset[str]:
    """Ayırt edici kelimeler kümesi; unvan ekleri ve tek harfler atılır."""
    parcalar = re.split(r"[^A-Z0-9]+", yer_adi(ad))
    return frozenset(p for p in parcalar if len(p) > 1 and p not in FIRMA_TAKILARI)


@dataclass
class EslestirmeSonucu:
    eslesen: int = 0
    belirsiz: list[tuple[str, list[str]]] = field(default_factory=list)
    """Birden fazla müşteriye uyan adlar: (dosyadaki ad, aday müşteri adları)."""
    eslesmeyen: list[str] = field(default_factory=list)

    @property
    def toplam(self) -> int:
        return self.eslesen + len(self.belirsiz) + len(self.eslesmeyen)

    def ozet(self) -> str:
        return (
            f"{self.toplam} ad okundu · {self.eslesen} eşleşti · "
            f"{len(self.belirsiz)} belirsiz · {len(self.eslesmeyen)} eşleşmedi"
        )


class MusteriEslestirici:
    """Müşteri adlarını üç kademede eşler; hepsi **kesin** eşleşmedir.

    1. Ad birebir aynı (normalize edilmiş hâliyle).
    2. Yalnızca noktalama/boşluk farkı var.
    3. Ayırt edici kelime kümesi aynı (unvan ekleri sayılmaz).

    Bir kademede birden fazla müşteri çıkarsa eşleşme yapılmaz; hangisi olduğu
    belirsizdir ve tahmin etmek yanlış kayıt güncellemekten kötüdür.
    """

    def __init__(self, db: Session) -> None:
        self._kademeler: list[tuple[callable, dict]] = [
            (yer_adi, defaultdict(set)),
            (sikistir, defaultdict(set)),
            (jetonlar, defaultdict(set)),
        ]
        for musteri in db.scalars(select(Musteri)).all():
            # Alıcı firma da aday sayılır: aynı bayi kaynak dosyalarda bazen bu adla
            # geçiyor.
            for ad in {musteri.bayi_adi, musteri.alici_firma}:
                if not ad or not ad.strip():
                    continue
                for fn, harita in self._kademeler:
                    harita[fn(ad)].add(musteri.id)
        self._kayitlar = {m.id: m for m in db.scalars(select(Musteri)).all()}

    def esle(self, ad: str) -> tuple[Musteri | None, list[Musteri]]:
        """(eşleşen müşteri, belirsizse adaylar) döner. İkisi de boşsa eşleşme yok."""
        if not (ad or "").strip():
            return None, []
        for fn, harita in self._kademeler:
            idler = harita.get(fn(ad)) or set()
            if len(idler) == 1:
                return self._kayitlar[next(iter(idler))], []
            if len(idler) > 1:
                return None, [self._kayitlar[i] for i in sorted(idler)]
        return None, []
